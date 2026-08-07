"""Audit broad-QA reporting products and refresh water/inland ratios."""

from __future__ import annotations

import argparse
import csv
import gc
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from scipy import ndimage

from nocturne.disaggregate.broad_reporting import BROAD_REPORTING_VERSION
from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.export import sha256_file
from nocturne.disaggregate.full_city import FULL_CITY_VERSION
from nocturne.disaggregate.shoreline import _matched_low_proxy_mask
from nocturne.disaggregate.validate import allocated_direct_region_metrics
from nocturne.preview.paths import resolve_project_path

VERSION = "v1_coverage_and_water_inland"
DIRECT = "direct_upsample__broad_qa"
UNIFORM = "uniform_normalized_convolution__broad_qa"
PRIMARY = "built_form_primary__no_water_prior__circular_mean_reference__broad_qa"
S2_ABLATION = "s2_only_ablation__no_water_prior__circular_mean_reference__broad_qa"


def audit_broad_reporting(config_path: str | Path) -> Path:
    """Validate broad products and recompute radiance-dependent regional ratios."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    config_hash = disaggregation_config_sha256(config_path)
    raster_base = resolve_project_path(config["outputs"]["rasters"]) / "full_city"
    broad_root = raster_base / BROAD_REPORTING_VERSION
    broad_manifest_path = broad_root / "artifact_manifest.json"
    broad_manifest = json.loads(broad_manifest_path.read_text(encoding="utf-8"))
    if broad_manifest.get("complete") is not True:
        raise ValueError("Broad reporting manifest is incomplete")
    if broad_manifest.get("config_sha256") != config_hash:
        raise ValueError("Broad reporting manifest belongs to another configuration")

    product_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    regional_rows: list[dict[str, Any]] = []
    for city in broad_manifest["cities"]:
        city_id = city["city_id"]
        records = {record["configuration"]["name"]: record for record in city["configurations"]}
        audited_names = [DIRECT, UNIFORM, PRIMARY]
        if S2_ABLATION in records:
            audited_names.append(S2_ABLATION)
        for name in audited_names:
            record = records[name]
            path = Path(record["path"])
            with rasterio.open(path) as dataset:
                allocation = dataset.read(1)
                valid = np.isfinite(allocation)
                product_rows.append(
                    {
                        "city_id": city_id,
                        "configuration": name,
                        "path": str(path),
                        "sha256_matches_manifest": sha256_file(path) == record["sha256"],
                        "cog_layout": dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT"),
                        "pixel_count": allocation.size,
                        "valid_pixel_count": int(valid.sum()),
                        "valid_fraction": float(valid.mean()),
                    }
                )
            del allocation

        broad_direct_path = Path(records[DIRECT]["path"])
        strict_direct_path = (
            raster_base / FULL_CITY_VERSION / city_id / "direct_upsample" / "products.tif"
        )
        broad_direct = _read_band_one(broad_direct_path)
        strict_direct = _read_band_one(strict_direct_path)
        common = np.isfinite(broad_direct) & np.isfinite(strict_direct)
        newly_filled = np.isfinite(broad_direct) & ~np.isfinite(strict_direct)
        left = broad_direct[common].astype(np.float64)
        right = strict_direct[common].astype(np.float64)
        comparison_rows.append(
            {
                "city_id": city_id,
                "common_pixel_count": int(common.sum()),
                "newly_filled_pixel_count": int(newly_filled.sum()),
                "strict_valid_fraction": float(np.isfinite(strict_direct).mean()),
                "broad_valid_fraction": float(np.isfinite(broad_direct).mean()),
                "pearson_on_common_support": float(np.corrcoef(left, right)[0, 1]),
                "mean_broad_minus_strict": float(np.mean(left - right)),
                "mean_absolute_broad_minus_strict": float(np.mean(np.abs(left - right))),
            }
        )
        del strict_direct, common, newly_filled, left, right

        broad_allocation = _read_band_one(Path(records[PRIMARY]["path"]))
        water_path = (
            resolve_project_path(config["outputs"]["root"])
            / "inputs"
            / "gate2_water_reference"
            / city_id
            / "water_reference.tif"
        )
        water = _read_band_one(water_path).astype(bool)
        distance = ndimage.distance_transform_edt(~water, sampling=10.0)
        inland = _matched_low_proxy_mask(
            config,
            city_id=city_id,
            proxy="built_form_primary",
            water=water,
            distance=distance,
        )
        metrics = {}
        for region_name, mask in (
            ("mapped_water", water),
            ("matched_inland_low_proxy", inland),
        ):
            result = allocated_direct_region_metrics(
                broad_allocation,
                direct_radiance=broad_direct,
                region_mask=mask,
            )
            metrics[region_name] = result
            regional_rows.append(
                {
                    "city_id": city_id,
                    "region": region_name,
                    **result,
                }
            )
        regional_rows.append(
            {
                "city_id": city_id,
                "region": "water_minus_inland_reduction",
                "region_pixel_count": None,
                "common_support_pixel_count": None,
                "allocated_radiance_sum": None,
                "positive_direct_radiance_sum": None,
                "allocated_to_direct_ratio": None,
                "reduction_fraction_vs_direct": (
                    metrics["mapped_water"]["reduction_fraction_vs_direct"]
                    - metrics["matched_inland_low_proxy"]["reduction_fraction_vs_direct"]
                ),
            }
        )
        del broad_direct, broad_allocation, water, distance, inland
        gc.collect()

    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "broad_reporting"
        / VERSION
    )
    output_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "product_audit": output_root / "product_audit.csv",
        "strict_broad_comparison": output_root / "strict_broad_comparison.csv",
        "water_inland_ratio": output_root / "water_inland_ratio.csv",
    }
    _write_csv(paths["product_audit"], product_rows)
    _write_csv(paths["strict_broad_comparison"], comparison_rows)
    _write_csv(paths["water_inland_ratio"], regional_rows)
    selection_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "primary_selection"
        / "v2_broad_qa_reporting"
    )
    selection_root.mkdir(parents=True, exist_ok=True)
    selection_path = selection_root / "selection.json"
    selected_artifacts = []
    for city in broad_manifest["cities"]:
        records = {record["configuration"]["name"]: record for record in city["configurations"]}
        selected = {
            "city_id": city["city_id"],
            "direct": {
                "path": records[DIRECT]["path"],
                "sha256": records[DIRECT]["sha256"],
            },
            "uniform": {
                "path": records[UNIFORM]["path"],
                "sha256": records[UNIFORM]["sha256"],
            },
            "built_form_primary": {
                "path": records[PRIMARY]["path"],
                "sha256": records[PRIMARY]["sha256"],
            },
            "trust_indicators": city["radiance_blind_gain"],
        }
        if S2_ABLATION in records:
            selected["s2_only_ablation"] = {
                "path": records[S2_ABLATION]["path"],
                "sha256": records[S2_ABLATION]["sha256"],
            }
            selected["s2_ablation_trust_indicators"] = city["s2_ablation_radiance_blind_gain"]
        selected_artifacts.append(selected)
    selection = {
        "schema_version": 1,
        "decision_id": "VNP-COVERAGE-002",
        "decision_date": "2026-08-03",
        "status": "accepted_for_demonstration_reporting",
        "radiance_variant": "broad_sensitivity",
        "minimum_valid_observations": 5,
        "proxy": "built_form_primary",
        "water_variant": "no_water_prior",
        "kernel": "circular_mean_reference",
        "rationale": (
            "complete two-city spatial coverage avoids dilation of a small strict "
            "retrieval-support mask; selection is coverage-driven, not performance-tuned"
        ),
        "strict_v1_role": (
            "immutable conservative quality sensitivity and authority for the "
            "frozen Gate 0 cohort and strict daily-condition audit"
        ),
        "s2_spatial_scope": (
            "New York S2-only was regenerated under broad QA; Delhi S2-only remains "
            "strict-v1, so the city maps are not a matched radiance-contract pair"
        ),
        "gap_filled_role": "explicit sensitivity only; not selected",
        "interpretation_limit": (
            "broad QA admits MQF 1 and lower cloud-mask quality; coverage completeness "
            "does not imply equivalently high quality at every pixel"
        ),
        "selected_artifacts": selected_artifacts,
    }
    selection_path.write_text(
        json.dumps(selection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "artifact_version": VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config_sha256": config_hash,
        "broad_reporting_manifest": {
            "path": str(broad_manifest_path),
            "sha256": sha256_file(broad_manifest_path),
        },
        "artifacts": {
            name: {"path": str(path), "sha256": sha256_file(path)} for name, path in paths.items()
        },
        "reporting_selection": {
            "path": str(selection_path),
            "sha256": sha256_file(selection_path),
        },
        "all_primary_and_baseline_products_complete_coverage": all(
            row["valid_fraction"] == 1.0
            for row in product_rows
            if row["configuration"] in {DIRECT, UNIFORM, PRIMARY}
        ),
        "s2_ablation_support_interpretation": (
            "New York broad QA removes every radiance-neighborhood gap; remaining "
            "invalid output is unchanged S2 proxy-neighborhood support, not VNP coverage"
        ),
        "observation_condition_policy": (
            "retain the completed strict daily propagation audit as a conservative "
            "sensitivity; the reporting-median change does not alter its radiance-blind "
            "non-amplification comparison and no broad daily stack is fabricated"
        ),
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _read_band_one(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return dataset.read(1)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    print(audit_broad_reporting(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
