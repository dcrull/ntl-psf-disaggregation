"""Audit the real raster inputs required before a city-scale Day 2 run."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rasterio
from affine import Affine

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.grids import (
    build_city_grid_specs,
    expanded_grid_shape,
    expanded_grid_transform,
)
from nocturne.preview.paths import resolve_project_path


def audit_day2_inputs(config_path: str | Path) -> Path:
    """Write an audit that is explicit about missing or misaligned real inputs."""

    config = load_disaggregation_config(config_path)
    input_config = config["outputs"]["day2_inputs"]
    input_root = resolve_project_path(input_config["root"])
    halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    city_audits = []
    for grid in build_city_grid_specs(config_path):
        expected_shape = expanded_grid_shape(grid, halo_m=halo_m)
        expected_transform = Affine(*expanded_grid_transform(grid, halo_m=halo_m))
        bundles = [
            _audit_raster_bundle(
                input_root / grid.city_id / input_config["earth_engine_bundle_filename"],
                expected_crs=grid.crs,
                expected_transform=expected_transform,
                expected_shape=expected_shape,
                expected_bands=input_config["earth_engine_bands"],
                band_order_authority="day2_earth_engine_exports.json",
            ),
            _audit_raster_bundle(
                input_root / grid.city_id / input_config["overture_bundle_filename"],
                expected_crs=grid.crs,
                expected_transform=expected_transform,
                expected_shape=expected_shape,
                expected_bands=input_config["overture_bands"],
                band_order_authority="embedded_band_descriptions",
            ),
        ]
        city_audits.append(
            {
                "city_id": grid.city_id,
                "ready": all(bundle["valid"] for bundle in bundles),
                "expected_crs": grid.crs,
                "expected_transform": list(expected_transform)[:6],
                "expected_shape": list(expected_shape),
                "source_halo_m": halo_m,
                "bundles": bundles,
            }
        )

    output_path = (
        resolve_project_path(config["outputs"]["manifests"]) / "day2_input_audit.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": config["experiment"]["id"],
        "contract_version": config["experiment"]["contract_version"],
        "artifact_version": input_config["artifact_version"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "ready_for_two_city_operator_run": all(
            city["ready"] for city in city_audits
        ),
        "policy": (
            "do not fabricate empirical city outputs from preview PNGs; run the "
            "operator only after every declared 10 m georeferenced bundle passes"
        ),
        "cities": city_audits,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _audit_raster_bundle(
    path: Path,
    *,
    expected_crs: str,
    expected_transform: Affine,
    expected_shape: tuple[int, int],
    expected_bands: list[str],
    band_order_authority: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "valid": False,
        "expected_bands": list(expected_bands),
        "band_order_authority": band_order_authority,
        "errors": [],
    }
    if not path.exists():
        record["errors"].append("missing")
        return record

    try:
        with rasterio.open(path) as dataset:
            record.update(
                {
                    "driver": dataset.driver,
                    "crs": dataset.crs.to_string() if dataset.crs else None,
                    "transform": list(dataset.transform)[:6],
                    "shape": [dataset.height, dataset.width],
                    "band_count": dataset.count,
                    "embedded_band_descriptions": list(dataset.descriptions),
                    "image_structure": dataset.tags(ns="IMAGE_STRUCTURE"),
                }
            )
            if dataset.crs != rasterio.crs.CRS.from_string(expected_crs):
                record["errors"].append("crs_mismatch")
            if dataset.transform != expected_transform:
                record["errors"].append("transform_mismatch")
            if (dataset.height, dataset.width) != expected_shape:
                record["errors"].append("shape_mismatch")
            if dataset.count != len(expected_bands):
                record["errors"].append("band_count_mismatch")
            descriptions = list(dataset.descriptions)
            if any(description is not None for description in descriptions):
                if descriptions != list(expected_bands):
                    record["errors"].append("embedded_band_order_mismatch")
            elif band_order_authority == "embedded_band_descriptions":
                record["errors"].append("missing_embedded_band_descriptions")
    except (OSError, rasterio.errors.RasterioError) as error:
        record["errors"].append(f"raster_open_error:{error}")
        return record

    record["sha256"] = _sha256_file(path)
    record["bytes"] = path.stat().st_size
    record["valid"] = not record["errors"]
    return record


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit real Day 2 raster inputs without fabricating city outputs."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    output_path = audit_day2_inputs(args.config)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
