"""Gate 2 input-readiness audit for Day 3 validation."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import rasterio
from affine import Affine

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.export import sha256_file
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.preview.paths import resolve_project_path

GATE2_VERSION = "v1_input_readiness"


def audit_gate2_inputs(config_path: str | Path) -> Path:
    """Audit independent-reference and retained-stack inputs without fetching them."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    config_hash = disaggregation_config_sha256(config_path)
    output_root = resolve_project_path(config["outputs"]["validation"]) / "gate2"
    reference_root = (
        resolve_project_path(config["outputs"]["root"]) / "inputs" / "gate2_water_reference"
    )
    daily_root = resolve_project_path(config["outputs"]["root"]) / "inputs" / "gate2_daily_vnp"
    full_city_manifest = (
        resolve_project_path(config["outputs"]["rasters"])
        / "full_city"
        / "v1_resumable_tiled"
        / "artifact_manifest.json"
    )
    full_city = _audit_full_city_manifest(full_city_manifest, config_hash=config_hash)
    cities = []
    for grid in build_city_grid_specs(config_path):
        daily_resolution_m = 500
        daily_transform = Affine(
            daily_resolution_m,
            0,
            grid.transform[2],
            0,
            -daily_resolution_m,
            grid.transform[5],
        )
        daily_shape = (
            grid.height * grid.resolution_m // daily_resolution_m,
            grid.width * grid.resolution_m // daily_resolution_m,
        )
        cities.append(
            {
                "city_id": grid.city_id,
                "water_reference": _audit_water_reference(
                    reference_root / grid.city_id / "water_reference.tif",
                    reference_root / grid.city_id / "metadata.json",
                    expected_crs=grid.crs,
                    expected_transform=Affine(*grid.transform),
                    expected_shape=(grid.height, grid.width),
                ),
                "daily_vnp": _audit_daily_stack(
                    daily_root / grid.city_id / "daily_vnp_stack.tif",
                    daily_root / grid.city_id / "metadata.json",
                    expected_crs=grid.crs,
                    expected_transform=daily_transform,
                    expected_shape=daily_shape,
                ),
            }
        )
    water_ready = full_city["ready"] and all(city["water_reference"]["ready"] for city in cities)
    daily_ready = all(city["daily_vnp"]["ready"] for city in cities)
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifact_version": GATE2_VERSION,
        "config_sha256": config_hash,
        "full_city": full_city,
        "cities": cities,
        "readiness": {
            "shoreline_external_reference": water_ready,
            "heldout_coarse_cell": full_city["ready"],
            "observation_condition_propagation": daily_ready,
            "sdgsat_optional_independent_benchmark": False,
        },
        "prohibitions": [
            "do not relabel the internal JRC prior as independent shoreline validation",
            "do not substitute 2021 preview granules for the declared 2024 daily stack",
            "do not fabricate missing reference metadata or calibration",
        ],
    }
    output_path = output_root / GATE2_VERSION / "input_readiness.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _audit_full_city_manifest(path: Path, *, config_hash: str) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "ready": False}
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts = {
        city["city_id"]: len(city.get("configurations", [])) for city in payload.get("cities", [])
    }
    ready = (
        payload.get("complete") is True
        and payload.get("config_sha256") == config_hash
        and counts == {"usa_new_york": 23, "india_delhi": 22}
    )
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "configuration_counts": counts,
        "ready": ready,
    }


def _audit_water_reference(
    raster_path: Path,
    metadata_path: Path,
    *,
    expected_crs: str,
    expected_transform: Affine,
    expected_shape: tuple[int, int],
) -> dict[str, Any]:
    record = _audit_aligned_raster(
        raster_path,
        expected_crs=expected_crs,
        expected_transform=expected_transform,
        expected_shape=expected_shape,
        expected_band_name="water_reference_mask",
    )
    metadata = _audit_metadata(
        metadata_path,
        required={
            "source_name",
            "source_version",
            "acquisition_or_coverage_dates",
            "water_class_definition",
            "license",
            "source_url_or_identifier",
        },
    )
    record["metadata"] = metadata
    record["ready"] = record["raster_ready"] and metadata["ready"]
    return record


def _audit_daily_stack(
    raster_path: Path,
    metadata_path: Path,
    *,
    expected_crs: str,
    expected_transform: Affine,
    expected_shape: tuple[int, int],
) -> dict[str, Any]:
    expected_dates = [
        (date(2024, 1, 11) + timedelta(days=offset)).isoformat()
        for offset in range(100)
    ]
    record = _audit_aligned_raster(
        raster_path,
        expected_crs=expected_crs,
        expected_transform=expected_transform,
        expected_shape=expected_shape,
        expected_band_name=None,
    )
    metadata = _audit_metadata(
        metadata_path,
        required={
            "interval_start",
            "interval_end_exclusive",
            "band_dates",
            "quality_contract",
            "source_product",
        },
    )
    condition_records = {}
    for layer in (
        "lunar_irradiance",
        "retrieval_age_days",
        "cloud_detection",
        "cloud_mask_quality",
        "mandatory_quality_flag",
        "snow_flag",
    ):
        condition_records[layer] = _audit_aligned_raster(
            raster_path.parent / f"daily_{layer}.tif",
            expected_crs=expected_crs,
            expected_transform=expected_transform,
            expected_shape=expected_shape,
            expected_band_name=None,
        )
    dates = metadata.get("payload", {}).get("band_dates", [])
    descriptions_ready = record.get("band_descriptions") == [
        f"strict_corrected_radiance_{date}" for date in expected_dates
    ]
    conditions_ready = all(
        condition.get("raster_ready")
        and condition.get("band_count") == 100
        and condition.get("band_descriptions")
        == [f"{name}_{date}" for date in expected_dates]
        for name, condition in condition_records.items()
    )
    record["condition_layers"] = condition_records
    record["band_dates_ready"] = dates == expected_dates
    record["band_descriptions_ready"] = descriptions_ready
    record["metadata"] = metadata
    record["ready"] = (
        record["raster_ready"]
        and record.get("band_count") == 100
        and metadata["ready"]
        and record["band_dates_ready"]
        and descriptions_ready
        and conditions_ready
    )
    return record


def _audit_aligned_raster(
    path: Path,
    *,
    expected_crs: str,
    expected_transform: Affine,
    expected_shape: tuple[int, int],
    expected_band_name: str | None,
) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "raster_ready": False}
    errors = []
    with rasterio.open(path) as dataset:
        if dataset.crs is None or dataset.crs.to_string() != expected_crs:
            errors.append("crs")
        if dataset.transform != expected_transform:
            errors.append("transform")
        if (dataset.height, dataset.width) != expected_shape:
            errors.append("shape")
        if expected_band_name is not None and dataset.descriptions[0] != expected_band_name:
            errors.append("band_name")
        record = {
            "path": str(path),
            "exists": True,
            "sha256": sha256_file(path),
            "band_count": dataset.count,
            "band_descriptions": list(dataset.descriptions),
            "dtype": list(dataset.dtypes),
            "errors": errors,
            "raster_ready": not errors,
        }
    return record


def _audit_metadata(path: Path, *, required: set[str]) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "missing_fields": sorted(required),
            "ready": False,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(required - set(payload))
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "missing_fields": missing,
        "ready": not missing,
        "payload": payload,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    print(audit_gate2_inputs(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
