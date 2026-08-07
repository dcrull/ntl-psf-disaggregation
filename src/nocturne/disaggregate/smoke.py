from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.gee import (
    build_s2_composite,
    build_vnp_daily_collection,
    build_vnp_median,
    build_vnp_source_collection,
    initialize_earth_engine_from_config,
)
from nocturne.disaggregate.grids import (
    build_city_grid_specs,
    earth_engine_region_for_grid,
)
from nocturne.experiment.manifest import build_experiment_manifest, load_experiment_config
from nocturne.preview.paths import resolve_project_path


def run_catalog_smoke_test(config_path: str | Path) -> dict[str, object]:
    config = load_disaggregation_config(config_path)
    ee = initialize_earth_engine_from_config(config)
    cities = _load_pilot_cities(config)
    grids = {grid.city_id: grid for grid in build_city_grid_specs(config_path)}
    results = []
    for city in cities.itertuples(index=False):
        grid = grids[city.city_id]
        region = earth_engine_region_for_grid(ee, grid)
        s2 = build_s2_composite(
            ee,
            region=region,
            config=config,
            target_grid=grid,
        )
        vnp_source = build_vnp_source_collection(ee, region=region, config=config)
        vnp_daily = build_vnp_daily_collection(ee, region=region, config=config)
        vnp_median = build_vnp_median(ee, region=region, config=config)
        results.append(
            {
                "city_id": city.city_id,
                "analysis_grid": grid.to_dict(),
                "s2_source_image_count": _s2_source_count(ee, region=region, config=config),
                "s2_source_datatake_count": _s2_datatake_count(
                    ee,
                    region=region,
                    config=config,
                ),
                "s2_source_image_ids": _source_image_ids(
                    ee,
                    collection=config["sources"]["sentinel2"]["collection"],
                    region=region,
                    config=config,
                ),
                "s2_output_bands": s2.bandNames().getInfo(),
                "s2_valid_observation_count": _band_summary(
                    ee,
                    s2.select("s2_valid_observation_count"),
                    region=region,
                    scale=100,
                ),
                "s2_sufficient_observation_support": _band_summary(
                    ee,
                    s2.select("s2_sufficient_observation_support"),
                    region=region,
                    scale=100,
                ),
                "vnp_source_image_count": vnp_source.size().getInfo(),
                "vnp_daily_image_count": vnp_daily.size().getInfo(),
                "vnp_source_image_ids": _source_image_ids(
                    ee,
                    collection=config["sources"]["vnp46a2"]["collection"],
                    region=region,
                    config=config,
                ),
                "vnp_output_bands": vnp_median.bandNames().getInfo(),
                "vnp_median_corrected_ntl": _band_summary(
                    ee,
                    vnp_median.select("vnp_median_corrected_ntl"),
                    region=region,
                    scale=500,
                ),
                "vnp_valid_observation_count": _band_summary(
                    ee,
                    vnp_median.select("vnp_valid_observation_count"),
                    region=region,
                    scale=500,
                ),
                "vnp_source_observation_count": _band_summary(
                    ee,
                    vnp_median.select("vnp_source_observation_count"),
                    region=region,
                    scale=500,
                ),
                "vnp_quality_retained_fraction": _band_summary(
                    ee,
                    vnp_median.select("vnp_quality_retained_fraction"),
                    region=region,
                    scale=500,
                ),
                "vnp_sufficient_observation_support": _band_summary(
                    ee,
                    vnp_median.select("vnp_sufficient_observation_support"),
                    region=region,
                    scale=500,
                ),
            }
        )
    return {
        "experiment_id": config["experiment"]["id"],
        "experiment_contract_version": config["experiment"]["contract_version"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "earth_engine_project": config["earth_engine"]["project"],
        "date_window": config["date_window"],
        "created_at": datetime.now(UTC).isoformat(),
        "cities": results,
    }


def write_catalog_smoke_test(config_path: str | Path) -> Path:
    config = load_disaggregation_config(config_path)
    output_path = resolve_project_path(config["outputs"]["previews"]) / "catalog_smoke_test.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = run_catalog_smoke_test(config_path)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live S2/VNP Earth Engine source checks.")
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    print(write_catalog_smoke_test(args.config))
    return 0


def _load_pilot_cities(config):
    source_config = load_experiment_config(config["cities"]["source_config"])
    _, cities = build_experiment_manifest(source_config)
    selected = cities[cities["city_id"].isin(config["cities"]["selected_city_ids"])].copy()
    by_id = selected.set_index("city_id")
    return by_id.loc[config["cities"]["selected_city_ids"]].reset_index()


def _s2_source_count(ee, *, region, config) -> int:
    source = config["sources"]["sentinel2"]
    window = config["date_window"]
    return (
        ee.ImageCollection(source["collection"])
        .filterBounds(region)
        .filterDate(window["start"], window["end_exclusive"])
        .size()
        .getInfo()
    )


def _s2_datatake_count(ee, *, region, config) -> int:
    source = config["sources"]["sentinel2"]
    window = config["date_window"]
    return (
        ee.ImageCollection(source["collection"])
        .filterBounds(region)
        .filterDate(window["start"], window["end_exclusive"])
        .aggregate_array("DATATAKE_IDENTIFIER")
        .distinct()
        .size()
        .getInfo()
    )


def _band_summary(ee, image, *, region, scale: int) -> dict[str, float | None]:
    reducer = (
        ee.Reducer.minMax()
        .combine(reducer2=ee.Reducer.mean(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.count(), sharedInputs=True)
    )
    return image.reduceRegion(
        reducer=reducer,
        geometry=region,
        scale=scale,
        bestEffort=True,
        maxPixels=10_000_000,
        tileScale=16,
    ).getInfo()


def _source_image_ids(ee, *, collection: str, region, config) -> list[str]:
    window = config["date_window"]
    return (
        ee.ImageCollection(collection)
        .filterBounds(region)
        .filterDate(window["start"], window["end_exclusive"])
        .aggregate_array("system:index")
        .getInfo()
    )


if __name__ == "__main__":
    raise SystemExit(main())
