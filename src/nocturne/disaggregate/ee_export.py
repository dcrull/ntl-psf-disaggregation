"""Queue the aligned Earth Engine source bundles required by Day 2."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.gee import (
    build_persistent_water_layers,
    build_s2_allocation_components,
    build_s2_indices,
    build_vnp_gap_filled_sensitivity,
    build_vnp_median,
    initialize_earth_engine_from_config,
)
from nocturne.disaggregate.grids import (
    CityGridSpec,
    build_city_grid_specs,
    earth_engine_source_region_for_grid,
    expanded_grid_shape,
    expanded_grid_transform,
)
from nocturne.preview.paths import resolve_project_path


@dataclass(frozen=True)
class EarthEngineExportGrid:
    """The expanded, aligned raster grid supplied to Earth Engine builders."""

    crs: str
    transform: tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class EarthEngineExportRecord:
    artifact_version: str
    city_id: str
    task_id: str
    task_state: str
    description: str
    drive_folder: str
    drive_filename: str
    local_expected_path: str
    crs: str
    transform: tuple[float, float, float, float, float, float]
    shape: tuple[int, int]
    source_halo_m: float
    bands: tuple[str, ...]


def resolve_drive_folder(export_config: dict[str, Any]) -> str:
    """Resolve the private Drive destination without committing its name."""

    folder_env = str(export_config.get("drive_folder_env", "NTL_PSF_EE_DRIVE_FOLDER"))
    folder = os.environ.get(folder_env) or export_config.get("drive_folder")
    if not folder:
        raise RuntimeError(f"Set {folder_env} to the Google Drive export folder")
    return str(folder)


def build_day2_earth_engine_image(
    ee,
    *,
    region,
    grid: CityGridSpec,
    config: dict[str, Any],
):
    """Build the ordered Day 2 source bundle without changing VNP authority."""

    halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    target_grid = EarthEngineExportGrid(
        crs=grid.crs,
        transform=expanded_grid_transform(grid, halo_m=halo_m),
    )
    indices = build_s2_indices(
        ee,
        region=region,
        config=config,
        target_grid=target_grid,
    )
    s2 = build_s2_allocation_components(
        ee,
        region=region,
        config=config,
        indices=indices,
        target_grid=target_grid,
    )
    water = build_persistent_water_layers(
        ee,
        region=region,
        config=config,
        target_grid=target_grid,
        mode="soft",
    )
    vnp_primary = build_vnp_median(
        ee,
        region=region,
        config=config,
        quality_variant="primary",
    )
    vnp_broad = build_vnp_median(
        ee,
        region=region,
        config=config,
        quality_variant="broad_sensitivity",
    )
    gap_filled_by_age = {
        int(maximum_age_days): build_vnp_gap_filled_sensitivity(
            ee,
            region=region,
            config=config,
            maximum_age_days=int(maximum_age_days),
        )
        for maximum_age_days in config["sources"]["vnp46a2"]["gap_filled_sensitivity"][
            "retrieval_age_sensitivities_days"
        ]
    }
    projection = ee.Projection(grid.crs, list(target_grid.transform))
    vnp_radiance = (
        vnp_primary.select("vnp_median_corrected_ntl")
        .reproject(projection)
        .rename("vnp_median_corrected_radiance")
    )
    vnp_layers = [vnp_radiance]
    vnp_layers.extend(
        [
            vnp_primary.select(name).reproject(projection).rename(name)
            for name in (
                "vnp_valid_observation_count",
                "vnp_source_observation_count",
                "vnp_quality_rejected_observation_count",
                "vnp_quality_retained_fraction",
            )
        ]
    )
    vnp_layers.extend(
        [
            vnp_broad.select("vnp_median_corrected_ntl")
            .reproject(projection)
            .rename("vnp_broad_median_corrected_radiance"),
            vnp_broad.select("vnp_valid_observation_count")
            .reproject(projection)
            .rename("vnp_broad_valid_observation_count"),
        ]
    )
    for maximum_age_days, gap_filled in gap_filled_by_age.items():
        names = (
            f"vnp_gap_filled_recent{maximum_age_days}d_median_radiance",
            f"vnp_gap_filled_recent{maximum_age_days}d_day_count",
        )
        vnp_layers.extend(
            [
                gap_filled.select(name).reproject(projection).rename(name)
                for name in names
            ]
        )
    primary_gap_filled = gap_filled_by_age[
        int(
            config["sources"]["vnp46a2"]["gap_filled_sensitivity"][
                "maximum_retrieval_age_days"
            ]
        )
    ]
    vnp_layers.extend(
        [
            primary_gap_filled.select(name).reproject(projection).rename(name)
            for name in (
                "vnp_gap_filled_source_observation_count",
                "vnp_fresh_high_quality_retrieval_count",
                "vnp_latest_high_quality_retrieval_days_median",
                "vnp_latest_high_quality_retrieval_days_p90",
            )
        ]
    )
    persistent_water_mask = (
        water.select("persistent_water_occurrence_percent")
        .gte(float(config["sources"]["water"]["persistent_occurrence_threshold"]))
        .And(water.select("persistent_water_observation_support"))
        .rename("persistent_water_mask")
    )
    layers = [
        *vnp_layers,
        s2.select("s2_base_proxy_unwatered_unfloored"),
        s2.select("s2_spectral_water_weight"),
        s2.select("s2_common_valid_observation_count"),
        s2.select("s2_sufficient_observation_support"),
        water.select("persistent_water_occurrence_percent"),
        water.select("persistent_water_valid_observation_count"),
        water.select("persistent_water_observation_support"),
        water.select("persistent_water_weight"),
        persistent_water_mask,
    ]
    expected_bands = list(config["outputs"]["day2_inputs"]["earth_engine_bands"])
    image = ee.Image(layers[0]).addBands(layers[1:]).select(expected_bands)
    return (
        image.toFloat()
        .unmask(-9999.0, False)
        .clip(region)
        .set(
            {
                "nocturne:experiment_id": config["experiment"]["id"],
                "nocturne:contract_version": config["experiment"]["contract_version"],
                "nocturne:city_id": grid.city_id,
                "nocturne:interval_start": config["date_window"]["start"],
                "nocturne:interval_end_exclusive": (
                    config["date_window"]["end_exclusive"]
                ),
                "nocturne:vnp_radiance_resampling": "nearest",
                "nocturne:vnp_primary_authority": ("strict_quality_corrected_radiance"),
                "nocturne:vnp_gap_filled_role": (
                    "recent_30_day_sensitivity_not_automatic_replacement"
                ),
                "nocturne:s2_continuous_resampling": (
                    config["grid"]["continuous_resampling"]["method"]
                ),
                "nocturne:categorical_resampling": (
                    config["grid"]["categorical_resampling"]["method"]
                ),
                "nocturne:water_changes_vnp_authority": False,
            }
        )
    )


def queue_day2_earth_engine_exports(
    config_path: str | Path,
    *,
    start_tasks: bool = True,
) -> Path:
    """Create one Drive export per city and persist its complete local contract."""

    config = load_disaggregation_config(config_path)
    ee = initialize_earth_engine_from_config(config)
    export_config = config["earth_engine"]["export"]
    input_config = config["outputs"]["day2_inputs"]
    artifact_version = input_config["artifact_version"]
    halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    edge_inset_m = float(config["earth_engine"]["export"]["region_edge_inset_m"])
    config_hash = disaggregation_config_sha256(config_path)
    input_root = resolve_project_path(input_config["root"])
    drive_folder = resolve_drive_folder(export_config)
    records: list[EarthEngineExportRecord] = []

    for grid in build_city_grid_specs(config_path):
        region = earth_engine_source_region_for_grid(
            ee,
            grid,
            halo_m=halo_m,
            edge_inset_m=edge_inset_m,
        )
        image = build_day2_earth_engine_image(
            ee,
            region=region,
            grid=grid,
            config=config,
        )
        description = (
            f"nocturne_day2_{grid.city_id}_{artifact_version}_{config_hash[:10]}"
        )
        filename = f"{grid.city_id}_ee_source_bundle_{artifact_version}"
        transform = expanded_grid_transform(grid, halo_m=halo_m)
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=description,
            folder=drive_folder,
            fileNamePrefix=filename,
            region=region,
            crs=grid.crs,
            crsTransform=list(transform),
            maxPixels=int(export_config["max_pixels"]),
            fileFormat=export_config["file_format"],
            formatOptions={
                "cloudOptimized": bool(export_config["cloud_optimized"]),
                "noData": -9999.0,
            },
        )
        if start_tasks:
            task.start()
        status = task.status()
        records.append(
            EarthEngineExportRecord(
                artifact_version=artifact_version,
                city_id=grid.city_id,
                task_id=str(task.id),
                task_state=str(status.get("state", "UNSUBMITTED")),
                description=description,
                drive_folder=drive_folder,
                drive_filename=f"{filename}.tif",
                local_expected_path=str(
                    input_root
                    / grid.city_id
                    / input_config["earth_engine_bundle_filename"]
                ),
                crs=grid.crs,
                transform=transform,
                shape=expanded_grid_shape(grid, halo_m=halo_m),
                source_halo_m=halo_m,
                bands=tuple(input_config["earth_engine_bands"]),
            )
        )

    manifest_path = (
        resolve_project_path(config["outputs"]["manifests"])
        / "day2_earth_engine_exports.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": config["experiment"]["id"],
        "contract_version": config["experiment"]["contract_version"],
        "artifact_version": artifact_version,
        "config_sha256": config_hash,
        "tasks_started": start_tasks,
        "destination": "google_drive",
        "nodata": -9999.0,
        "export_region_edge_inset_m": edge_inset_m,
        "resampling_contract": {
            "s2_continuous": config["grid"]["continuous_resampling"]["method"],
            "categorical_masks_counts_and_jrc": (
                config["grid"]["categorical_resampling"]["method"]
            ),
            "vnp_radiance_primary": "nearest",
            "vnp_radiance_bilinear": "retained_for_later_sensitivity_not_this_bundle",
        },
        "water_contract": {
            "changes_vnp_authority": False,
            "persistent_mask_is_operator_input_not_output_nodata": True,
        },
        "exports": [asdict(record) for record in records],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Queue aligned Day 2 source-bundle exports to Google Drive."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Create task definitions but do not submit them.",
    )
    args = parser.parse_args(argv)
    print(
        queue_day2_earth_engine_exports(
            args.config,
            start_tasks=not args.prepare_only,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
