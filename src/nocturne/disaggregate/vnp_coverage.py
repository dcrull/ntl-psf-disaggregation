"""Reproducible audit of native VNP retrieval coverage at named NYC sites."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.gee import (
    build_persistent_water_layers,
    build_vnp_gap_filled_sensitivity,
    build_vnp_median,
    build_vnp_source_collection,
    initialize_earth_engine_from_config,
)
from nocturne.disaggregate.grids import (
    build_city_grid_specs,
    earth_engine_source_region_for_grid,
    expanded_grid_transform,
)
from nocturne.preview.paths import resolve_project_path

AUDIT_SITES = {
    "lower_manhattan": (-74.0113, 40.7075),
    "midtown": (-73.9840, 40.7549),
    "central_park": (-73.9665, 40.7812),
    "upper_manhattan": (-73.9450, 40.8340),
    "downtown_brooklyn": (-73.9857, 40.6928),
    "queens": (-73.8719, 40.7282),
    "newark": (-74.1724, 40.7357),
}
VNP_BACKGROUND_CLASSES = {
    0: "land_desert",
    1: "land_no_desert",
    2: "inland_water",
    3: "sea_water",
    5: "coastal",
}


def run_vnp_coverage_audit(config_path: str | Path) -> list[Path]:
    """Query versioned coverage diagnostics on the exact exported UTM grid."""

    config = load_disaggregation_config(config_path)
    ee = initialize_earth_engine_from_config(config)
    grid = next(
        grid
        for grid in build_city_grid_specs(config_path)
        if grid.city_id == "usa_new_york"
    )
    halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    transform = expanded_grid_transform(grid, halo_m=halo_m)
    projection = ee.Projection(grid.crs, list(transform))
    region = earth_engine_source_region_for_grid(ee, grid, halo_m=halo_m)
    source = build_vnp_source_collection(ee, region=region, config=config)
    primary = build_vnp_median(
        ee,
        region=region,
        config=config,
        quality_variant="primary",
    )
    broad = build_vnp_median(
        ee,
        region=region,
        config=config,
        quality_variant="broad_sensitivity",
    )
    gap_filled = build_vnp_gap_filled_sensitivity(
        ee,
        region=region,
        config=config,
    )
    water = build_persistent_water_layers(
        ee,
        region=region,
        config=config,
        target_grid=type(
            "CoverageGrid",
            (),
            {"crs": grid.crs, "transform": transform},
        )(),
        mode="soft",
    )
    persistent_water_mask = (
        water.select("persistent_water_occurrence_percent")
        .gte(float(config["sources"]["water"]["persistent_occurrence_threshold"]))
        .And(water.select("persistent_water_observation_support"))
        .rename("persistent_water_mask")
    )
    background_counts = [
        _vnp_background_class_count(
            ee,
            source,
            class_value=class_value,
            output_name=f"vnp_background_{name}_day_count",
        )
        for class_value, name in VNP_BACKGROUND_CLASSES.items()
    ]
    diagnostic = ee.Image.cat(
        [
            primary.select("vnp_median_corrected_ntl").rename(
                "strict_median_corrected_radiance"
            ),
            primary.select("vnp_valid_observation_count").rename(
                "strict_valid_observation_count"
            ),
            primary.select("vnp_source_observation_count").rename(
                "corrected_source_observation_count"
            ),
            primary.select("vnp_quality_rejected_observation_count"),
            primary.select("vnp_quality_retained_fraction"),
            broad.select("vnp_median_corrected_ntl").rename(
                "broad_median_corrected_radiance"
            ),
            broad.select("vnp_valid_observation_count").rename(
                "broad_valid_observation_count"
            ),
            gap_filled,
            water.select("persistent_water_occurrence_percent"),
            water.select("persistent_water_weight"),
            persistent_water_mask,
            *background_counts,
        ]
    ).reproject(projection)

    rows = []
    for site, (longitude, latitude) in AUDIT_SITES.items():
        values = diagnostic.reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=ee.Geometry.Point([longitude, latitude]),
            crs=grid.crs,
            crsTransform=list(transform),
            maxPixels=100,
        ).getInfo()
        values.update(
            {
                "site": site,
                "longitude": longitude,
                "latitude": latitude,
                "dominant_vnp_background_class": _dominant_background(values),
            }
        )
        rows.append(values)

    output_root = (
        resolve_project_path(config["outputs"]["diagnostics"])
        / "vnp_coverage"
        / "v1_native_retrieval_audit"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "nyc_named_site_coverage.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    json_path = output_root / "nyc_named_site_coverage.json"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": config["experiment"]["id"],
        "contract_version": config["experiment"]["contract_version"],
        "artifact_version": config["outputs"]["day2_inputs"]["artifact_version"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "city_id": grid.city_id,
        "crs": grid.crs,
        "transform": list(transform),
        "audit_role": (
            "post-visual-inspection source diagnostic; not a basis for silently "
            "replacing the strict corrected-radiance primary"
        ),
        "gap_filled_contract": config["sources"]["vnp46a2"][
            "gap_filled_sensitivity"
        ],
        "interpretation": (
            "VNP background classes and retrieval availability are native product "
            "fields evaluated before Nocturne water weighting or convolution"
        ),
        "sites": rows,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return [csv_path, json_path]


def _vnp_background_class_count(
    ee,
    source,
    *,
    class_value: int,
    output_name: str,
):
    def indicator(image):
        background = image.select("QF_Cloud_Mask").rightShift(1).bitwiseAnd(7)
        return background.eq(class_value).rename(output_name)

    return source.map(indicator).sum().rename(output_name)


def _dominant_background(values: dict[str, Any]) -> str | None:
    counts = {
        name: values.get(f"vnp_background_{name}_day_count")
        for name in VNP_BACKGROUND_CLASSES.values()
    }
    finite = {name: float(value) for name, value in counts.items() if value is not None}
    return max(finite, key=finite.get) if finite else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit native VNP retrieval coverage at named NYC sites."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    for path in run_vnp_coverage_audit(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
