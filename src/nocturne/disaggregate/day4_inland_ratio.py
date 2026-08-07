"""Day 4 mapped-water versus matched inland allocated/direct comparison."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from scipy import ndimage

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.shoreline import _matched_low_proxy_mask
from nocturne.disaggregate.validate import allocated_direct_region_metrics
from nocturne.preview.paths import resolve_project_path

VERSION = "v1_existing_matched_inland_control"


def run_day4_inland_ratio(config_path: str | Path) -> Path:
    """Compare reporting allocations with direct radiance over two regions."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    config_hash = disaggregation_config_sha256(config_path)
    raster_root = (
        resolve_project_path(config["outputs"]["rasters"])
        / "full_city"
        / "v1_resumable_tiled"
    )
    source_manifest_path = raster_root / "artifact_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("complete") is not True:
        raise ValueError("Full-city artifact manifest is incomplete")
    if source_manifest.get("config_sha256") != config_hash:
        raise ValueError("Full-city artifact manifest belongs to another configuration")

    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "day4_allocated_direct_ratio"
        / VERSION
    )
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    sources: dict[str, Any] = {"full_city_manifest": _file_record(source_manifest_path)}

    for city_id in ("usa_new_york", "india_delhi"):
        city_root = raster_root / city_id
        direct_path = city_root / "direct_upsample" / "products.tif"
        water_path = (
            resolve_project_path(config["outputs"]["root"])
            / "inputs"
            / "gate2_water_reference"
            / city_id
            / "water_reference.tif"
        )
        direct = _read_band_one(direct_path)
        water = _read_band_one(water_path).astype(bool)
        distance = ndimage.distance_transform_edt(~water, sampling=10.0)
        sources[city_id] = {
            "direct": _file_record(direct_path),
            "water_reference": _file_record(water_path),
        }

        for proxy in ("built_form_primary", "s2_only_ablation"):
            allocation_path = (
                city_root
                / f"{proxy}__no_water_prior__circular_mean_reference"
                / "products.tif"
            )
            allocation = _read_band_one(allocation_path)
            inland = _matched_low_proxy_mask(
                config,
                city_id=city_id,
                proxy=proxy,
                water=water,
                distance=distance,
            )
            sources[city_id][proxy] = _file_record(allocation_path)
            region_metrics: dict[str, dict[str, Any]] = {}
            for region_name, mask in (
                ("mapped_water", water),
                ("matched_inland_low_proxy", inland),
            ):
                metrics = allocated_direct_region_metrics(
                    allocation,
                    direct_radiance=direct,
                    region_mask=mask,
                )
                region_metrics[region_name] = metrics
                rows.append(
                    {
                        "city_id": city_id,
                        "proxy": proxy,
                        "water_variant": "no_water_prior",
                        "kernel": "circular_mean_reference",
                        "region": region_name,
                        **metrics,
                    }
                )
            water_reduction = region_metrics["mapped_water"][
                "reduction_fraction_vs_direct"
            ]
            inland_reduction = region_metrics["matched_inland_low_proxy"][
                "reduction_fraction_vs_direct"
            ]
            difference = water_reduction - inland_reduction
            comparisons.append(
                {
                    "city_id": city_id,
                    "proxy": proxy,
                    "water_reduction_fraction": water_reduction,
                    "matched_inland_reduction_fraction": inland_reduction,
                    "water_minus_inland_reduction_fraction": difference,
                    "direction": (
                        "water_larger_reduction"
                        if difference > 0
                        else "inland_larger_reduction"
                        if difference < 0
                        else "equal_reduction"
                    ),
                }
            )

    metrics_path = output_root / "region_metrics.csv"
    comparison_path = output_root / "water_vs_inland_comparison.csv"
    _write_csv(metrics_path, rows)
    _write_csv(comparison_path, comparisons)
    interpretation_path = output_root / "interpretation.json"
    interpretation = {
        "classification": "general_low_proxy_reallocation_not_water_specific",
        "headline": (
            "Mapped water does not show a larger allocated-versus-direct reduction "
            "than the existing matched inland low-proxy control in either city or proxy."
        ),
        "scope": (
            "Descriptive aggregate-sum ratios over common valid support; this is not "
            "independent fine-resolution accuracy validation."
        ),
        "control_caveat": (
            "The existing radiance-blind control targets the lowest proxy-valued inland "
            "pixels more than 1500 m from mapped water. Its target count equals mapped-water "
            "area but is capped at 10% of eligible inland support; it does not distribution-"
            "match proxy values or urban context to mapped water."
        ),
        "comparisons": comparisons,
    }
    interpretation_path.write_text(
        json.dumps(interpretation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    artifacts = {
        "region_metrics": _file_record(metrics_path),
        "water_vs_inland_comparison": _file_record(comparison_path),
        "interpretation": _file_record(interpretation_path),
    }
    manifest = {
        "schema_version": 1,
        "artifact_version": VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config_sha256": config_hash,
        "metric_contract": (
            "ratio of allocated-radiance sum to nonnegative direct-radiance sum on "
            "common finite regional support; reduction is one minus that ratio"
        ),
        "control_contract": (
            "reuse the frozen v1 shoreline radiance-blind matched-low-proxy mask exactly"
        ),
        "sources": sources,
        "artifacts": artifacts,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _read_band_one(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return dataset.read(1)


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    print(run_day4_inland_ratio(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
