"""Versioned coverage-complete broad-QA reporting products."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rasterio.windows import Window

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.day2 import audit_day2_inputs
from nocturne.disaggregate.empirical_cutouts import _citywide_proxy_normalization
from nocturne.disaggregate.export import sha256_file
from nocturne.disaggregate.full_city import (
    DEFAULT_TILE_PIXELS,
    FULL_CITY_VERSION,
    FullCityConfiguration,
    _require_single_threaded_numerics,
    _run_stationary_configuration,
)
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.preview.paths import resolve_project_path

BROAD_REPORTING_VERSION = "v2_broad_qa_reporting"


def broad_reporting_matrix(city_id: str) -> tuple[FullCityConfiguration, ...]:
    """Return the minimal coverage-complete reporting matrix."""

    matrix = [
        FullCityConfiguration(
            "direct_upsample__broad_qa",
            "direct",
            None,
            None,
            None,
            radiance_contract="broad",
        ),
        FullCityConfiguration(
            "uniform_normalized_convolution__broad_qa",
            "uniform",
            None,
            None,
            "circular_mean_reference",
            radiance_contract="broad",
        ),
        FullCityConfiguration(
            "built_form_primary__no_water_prior__circular_mean_reference__broad_qa",
            "stationary",
            "built_form_primary",
            "no_water_prior",
            "circular_mean_reference",
            radiance_contract="broad",
        ),
    ]
    if city_id == "usa_new_york":
        matrix.append(
            FullCityConfiguration(
                "s2_only_ablation__no_water_prior__circular_mean_reference__broad_qa",
                "stationary",
                "s2_only_ablation",
                "no_water_prior",
                "circular_mean_reference",
                radiance_contract="broad",
            )
        )
    return tuple(matrix)


def run_broad_reporting(
    config_path: str | Path,
    *,
    tile_pixels: int = DEFAULT_TILE_PIXELS,
) -> Path:
    """Build broad-QA products while preserving the frozen strict version."""

    _require_single_threaded_numerics()
    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    config_hash = disaggregation_config_sha256(config_path)
    audit_path = audit_day2_inputs(config_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not audit["ready_for_two_city_operator_run"]:
        raise ValueError(f"Day 2 input audit is not ready: {audit_path}")

    raster_base = resolve_project_path(config["outputs"]["rasters"]) / "full_city"
    output_root = raster_base / BROAD_REPORTING_VERSION
    input_config = config["outputs"]["day2_inputs"]
    input_root = resolve_project_path(input_config["root"])
    city_records: list[dict[str, Any]] = []
    for grid in build_city_grid_specs(config_path):
        city_root = output_root / grid.city_id
        ee_path = input_root / grid.city_id / input_config["earth_engine_bundle_filename"]
        overture_path = input_root / grid.city_id / input_config["overture_bundle_filename"]
        source_halo = round(
            float(config["cities"]["analysis_geometry"]["source_halo_m"])
            / grid.resolution_m
        )
        analysis_window = Window(source_halo, source_halo, grid.width, grid.height)
        strict_minimum = int(
            config["sources"]["vnp46a2"]["quality_contracts"]["primary"]
            ["minimum_valid_observations"]
        )
        broad_minimum = int(
            config["sources"]["vnp46a2"]["quality_contracts"]["broad_sensitivity"]
            ["minimum_valid_observations"]
        )
        normalization = _citywide_proxy_normalization(
            ee_path,
            overture_path,
            analysis_window=analysis_window,
            proxy_floor=float(config["validation"]["water_handling"]["proxy_floor"]),
            strict_minimum_observations=strict_minimum,
            broad_minimum_observations=broad_minimum,
            chunk_pixels=tile_pixels,
        )
        records = []
        matrix = broad_reporting_matrix(grid.city_id)
        for spec in matrix:
            record = _run_stationary_configuration(
                config,
                config_hash=config_hash,
                grid=grid,
                spec=spec,
                ee_path=ee_path,
                overture_path=overture_path,
                normalization=normalization,
                output_root=city_root / spec.name,
                analysis_window=analysis_window,
                tile_pixels=tile_pixels,
                strict_minimum=strict_minimum,
                broad_minimum=broad_minimum,
            )
            metrics_path = city_root / spec.name / "metrics.json"
            record["metrics_sidecar"] = {
                "path": str(metrics_path),
                "sha256": sha256_file(metrics_path),
            }
            records.append(record)

        broad_primary = city_root / matrix[2].name
        strict_gain = (
            raster_base
            / FULL_CITY_VERSION
            / grid.city_id
            / "built_form_primary__no_water_prior__circular_mean_reference"
            / "trust_indicators.tif"
        )
        broad_gain = broad_primary / "trust_indicators.tif"
        shutil.copy2(strict_gain, broad_gain)
        city_record = {
                "city_id": grid.city_id,
                "configurations": records,
                "radiance_blind_gain": {
                    "path": str(broad_gain),
                    "sha256": sha256_file(broad_gain),
                    "copied_from": str(strict_gain),
                    "identity_reason": "gain depends on proxy and kernel, not radiance",
                },
            }
        if grid.city_id == "usa_new_york":
            s2_name = matrix[3].name
            strict_s2_gain = (
                raster_base
                / FULL_CITY_VERSION
                / grid.city_id
                / "s2_only_ablation__no_water_prior__circular_mean_reference"
                / "trust_indicators.tif"
            )
            broad_s2_gain = city_root / s2_name / "trust_indicators.tif"
            shutil.copy2(strict_s2_gain, broad_s2_gain)
            city_record["s2_ablation_radiance_blind_gain"] = {
                "path": str(broad_s2_gain),
                "sha256": sha256_file(broad_s2_gain),
                "copied_from": str(strict_s2_gain),
                "identity_reason": "gain depends on proxy and kernel, not radiance",
            }
        city_records.append(city_record)

    manifest = {
        "schema_version": 1,
        "artifact_version": BROAD_REPORTING_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config_sha256": config_hash,
        "day2_input_audit": str(audit_path),
        "reporting_change": (
            "coverage-complete broad-QA median selected for demonstration output; "
            "strict v1 remains immutable conservative sensitivity"
        ),
        "quality_contract": {
            "variant": "broad_sensitivity",
            **config["sources"]["vnp46a2"]["quality_contracts"][
                "broad_sensitivity"
            ],
        },
        "configuration_matrix_by_city": {
            city_id: [asdict(spec) for spec in broad_reporting_matrix(city_id)]
            for city_id in config["cities"]["selected_city_ids"]
        },
        "cities": city_records,
        "complete": len(city_records) == 2,
        "strict_artifacts_modified": False,
    }
    manifest_path = output_root / "artifact_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    print(run_broad_reporting(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
