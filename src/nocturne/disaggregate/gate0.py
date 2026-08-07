from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from scipy.stats import spearmanr

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.gee import (
    build_persistent_water_weight,
    build_s2_indices,
    build_s2_only_allocation_proxy,
    build_vnp_median,
    initialize_earth_engine_from_config,
)
from nocturne.disaggregate.grids import (
    build_city_grid_specs,
    earth_engine_region_for_grid,
)
from nocturne.experiment.manifest import build_experiment_manifest, load_experiment_config
from nocturne.preview.paths import resolve_project_path


def run_s2_gate0(config_path: str | Path) -> list[Path]:
    config = load_disaggregation_config(config_path)
    ee = initialize_earth_engine_from_config(config)
    cities = _load_pilot_cities(config)
    grids = {grid.city_id: grid for grid in build_city_grid_specs(config_path)}
    output_root = _gate0_output_root(config)
    output_root.mkdir(parents=True, exist_ok=True)
    config_sha256_value = disaggregation_config_sha256(config_path)

    summary_rows = []
    written: list[Path] = []
    for city in cities.itertuples(index=False):
        grid = grids[city.city_id]
        samples = _sample_s2_proxy_at_vnp_support(
            ee,
            grid=grid,
            config=config,
            city_id=city.city_id,
            chunk_cache_root=output_root / "chunks" / city.city_id,
            config_sha256_value=config_sha256_value,
        )
        samples = _add_spatial_fields(samples, city=city, config=config)
        metrics = _gate_metrics(
            samples,
            city_id=city.city_id,
            allocation_proxy="s2_only_ablation",
            config=config,
        )
        metrics.update(_artifact_metadata(config_path, config))
        summary_rows.append(metrics)

        sample_path = output_root / f"{city.city_id}_s2_only_samples.csv"
        samples.to_csv(sample_path, index=False)
        written.append(sample_path)
        figure_path = output_root / f"{city.city_id}_s2_only_gate0.png"
        _write_gate_figure(
            _gate_analysis_samples(
                samples,
                allocation_proxy="s2_only_ablation",
                config=config,
            ),
            city=city,
            allocation_label="S2-only allocation proxy",
            metrics=metrics,
            output_path=figure_path,
        )
        written.append(figure_path)

    summary = pd.DataFrame(summary_rows)
    summary_path = output_root / "s2_only_gate0_summary.csv"
    summary.to_csv(summary_path, index=False)
    written.append(summary_path)
    json_path = output_root / "s2_only_gate0_summary.json"
    json_path.write_text(
        json.dumps(summary.to_dict(orient="records"), indent=2) + "\n",
        encoding="utf-8",
    )
    written.append(json_path)
    return written


def summarize_existing_s2_gate0(config_path: str | Path) -> list[Path]:
    """Rebuild Gate 0 summaries and figures without repeating Earth Engine sampling."""

    config = load_disaggregation_config(config_path)
    cities = _load_pilot_cities(config)
    output_root = _gate0_output_root(config)
    summary_rows = []
    written: list[Path] = []
    for city in cities.itertuples(index=False):
        sample_path = output_root / f"{city.city_id}_s2_only_samples.csv"
        samples = pd.read_csv(sample_path)
        metrics = _gate_metrics(
            samples,
            city_id=city.city_id,
            allocation_proxy="s2_only_ablation",
            config=config,
        )
        metrics.update(_artifact_metadata(config_path, config))
        summary_rows.append(metrics)
        figure_path = output_root / f"{city.city_id}_s2_only_gate0.png"
        _write_gate_figure(
            _gate_analysis_samples(
                samples,
                allocation_proxy="s2_only_ablation",
                config=config,
            ),
            city=city,
            allocation_label="S2-only allocation proxy",
            metrics=metrics,
            output_path=figure_path,
        )
        written.append(figure_path)

    summary = pd.DataFrame(summary_rows)
    summary_path = output_root / "s2_only_gate0_summary.csv"
    summary.to_csv(summary_path, index=False)
    written.append(summary_path)
    json_path = output_root / "s2_only_gate0_summary.json"
    json_path.write_text(
        json.dumps(summary.to_dict(orient="records"), indent=2) + "\n",
        encoding="utf-8",
    )
    written.append(json_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Gate 0 for the S2-only ablation.")
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    parser.add_argument(
        "--summarize-existing",
        action="store_true",
        help="Rebuild figures and metrics from saved samples without querying Earth Engine.",
    )
    args = parser.parse_args(argv)
    run = summarize_existing_s2_gate0 if args.summarize_existing else run_s2_gate0
    for path in run(args.config):
        print(path)
    return 0


def _sample_s2_proxy_at_vnp_support(
    ee,
    *,
    grid,
    config,
    city_id: str,
    chunk_cache_root: Path,
    config_sha256_value: str,
) -> pd.DataFrame:
    divisions = int(config["validation"]["gate0"].get("interactive_chunk_divisions", 4))
    workers = int(config["validation"]["gate0"].get("interactive_workers", 4))
    attempts = int(config["validation"]["gate0"]["interactive_chunk_attempts"])
    halo_m = float(config["validation"]["gate0"]["aggregation_halo_m"])
    rows: list[dict[str, object]] = []
    chunks = _rectangular_chunks(grid.analysis_wgs84_bounds, divisions=divisions)
    analysis_region = earth_engine_region_for_grid(ee, grid)
    source = config["sources"]["vnp46a2"]
    window = config["date_window"]
    vnp_projection_info = (
        ee.ImageCollection(source["collection"])
        .filterDate(window["start"], window["end_exclusive"])
        .first()
        .select(source["target_band"])
        .projection()
        .getInfo()
    )

    chunk_cache_root.mkdir(parents=True, exist_ok=True)

    def sample_chunk(chunk_number, chunk_bounds):
        for attempt in range(1, attempts + 1):
            try:
                core_region = ee.Geometry.Rectangle(
                    chunk_bounds,
                    proj="EPSG:4326",
                    geodesic=False,
                )
                sample_region = core_region.intersection(analysis_region, maxError=1)
                processing_region = core_region.buffer(halo_m).bounds(maxError=1)
                chunk_rows = _sample_s2_proxy_chunk(
                    ee,
                    processing_region=processing_region,
                    sample_region=sample_region,
                    config=config,
                    target_grid=grid,
                )
                for row in chunk_rows:
                    row["gate0_chunk_number"] = chunk_number
                return chunk_number, chunk_bounds, chunk_rows
            except Exception:
                if attempt == attempts:
                    raise
                print(
                    f"{city_id}: Gate 0 chunk {chunk_number}/{len(chunks)} "
                    f"attempt {attempt}/{attempts} failed; retrying",
                    flush=True,
                )
        raise AssertionError("unreachable")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for chunk_number, chunk_bounds in enumerate(chunks, start=1):
            cached_rows = _load_gate0_chunk_cache(
                chunk_cache_root / f"chunk_{chunk_number:02d}.json",
                city_id=city_id,
                chunk_number=chunk_number,
                chunk_bounds=chunk_bounds,
                config_sha256_value=config_sha256_value,
            )
            if cached_rows is not None:
                rows.extend(cached_rows)
                print(
                    f"{city_id}: reused Gate 0 chunk "
                    f"{chunk_number}/{len(chunks)} ({len(cached_rows)} cells)",
                    flush=True,
                )
                continue
            future = executor.submit(sample_chunk, chunk_number, chunk_bounds)
            futures[future] = chunk_number
        for future in as_completed(futures):
            chunk_number, chunk_bounds, chunk_rows = future.result()
            _write_gate0_chunk_cache(
                chunk_cache_root / f"chunk_{chunk_number:02d}.json",
                city_id=city_id,
                chunk_number=chunk_number,
                chunk_bounds=chunk_bounds,
                config_sha256_value=config_sha256_value,
                rows=chunk_rows,
            )
            rows.extend(chunk_rows)
            print(
                f"{city_id}: completed Gate 0 chunk "
                f"{chunk_number}/{len(chunks)} ({len(chunk_rows)} cells)",
                flush=True,
            )
    table = (
        pd.DataFrame(rows)
        .sort_values(["longitude", "latitude", "gate0_chunk_number"])
        .drop_duplicates(subset=["longitude", "latitude"], keep="first")
        .reset_index(drop=True)
    )
    return _attach_native_vnp_cells(
        table,
        projection_info=vnp_projection_info,
        target_grid=grid,
    )


def _load_gate0_chunk_cache(
    path: Path,
    *,
    city_id: str,
    chunk_number: int,
    chunk_bounds,
    config_sha256_value: str,
) -> list[dict[str, object]] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if (
        payload.get("city_id") != city_id
        or payload.get("chunk_number") != chunk_number
        or payload.get("chunk_bounds") != list(map(float, chunk_bounds))
        or payload.get("config_sha256") != config_sha256_value
    ):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("row_count") != len(rows):
        return None
    return rows


def _write_gate0_chunk_cache(
    path: Path,
    *,
    city_id: str,
    chunk_number: int,
    chunk_bounds,
    config_sha256_value: str,
    rows: list[dict[str, object]],
) -> None:
    payload = {
        "city_id": city_id,
        "chunk_number": chunk_number,
        "chunk_bounds": list(map(float, chunk_bounds)),
        "config_sha256": config_sha256_value,
        "row_count": len(rows),
        "rows": rows,
    }
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _sample_s2_proxy_chunk(
    ee,
    *,
    processing_region,
    sample_region,
    config,
    target_grid,
) -> list[dict[str, object]]:
    s2 = build_s2_indices(
        ee,
        region=processing_region,
        config=config,
        target_grid=target_grid,
    )
    proxy = build_s2_only_allocation_proxy(
        ee,
        region=processing_region,
        config=config,
        indices=s2,
        normalize=False,
        target_grid=target_grid,
    )
    water_weight = build_persistent_water_weight(
        ee,
        region=processing_region,
        config=config,
        target_grid=target_grid,
    )
    vnp = build_vnp_median(ee, region=processing_region, config=config)
    vnp_projection = vnp.select("vnp_median_corrected_ntl").projection()

    proxy_coarse = (
        proxy.reduceResolution(reducer=ee.Reducer.mean(), bestEffort=False, maxPixels=4096)
        .reproject(vnp_projection)
        .rename("proxy_mean")
    )
    s2_count_coarse = (
        s2.select("s2_valid_observation_count")
        .reduceResolution(reducer=ee.Reducer.mean(), bestEffort=False, maxPixels=4096)
        .reproject(vnp_projection)
        .rename("s2_valid_count_mean")
    )
    s2_support_coarse = (
        s2.select("s2_sufficient_observation_support")
        .reduceResolution(reducer=ee.Reducer.mean(), bestEffort=False, maxPixels=4096)
        .reproject(vnp_projection)
        .rename("s2_supported_area_fraction")
    )
    water_weight_coarse = (
        water_weight.reduceResolution(
            reducer=ee.Reducer.mean(),
            bestEffort=False,
            maxPixels=4096,
        )
        .reproject(vnp_projection)
        .rename("persistent_water_weight_mean")
    )
    sample_image = (
        proxy_coarse.addBands(
            [s2_count_coarse, s2_support_coarse, water_weight_coarse]
        )
        .addBands(
            vnp.select(
                [
                    "vnp_median_corrected_ntl",
                    "vnp_valid_observation_count",
                    "vnp_source_observation_count",
                    "vnp_quality_rejected_observation_count",
                    "vnp_quality_retained_fraction",
                    "vnp_sufficient_observation_support",
                ]
            )
        )
        .addBands(
            ee.Image.pixelArea()
            .reproject(vnp_projection)
            .rename("coarse_cell_area_m2_earth_engine")
        )
        .addBands(ee.Image.pixelLonLat())
    )
    payload = sample_image.sample(
        region=sample_region,
        projection=vnp_projection,
        geometries=False,
        dropNulls=True,
        tileScale=16,
    ).getInfo()
    return [feature["properties"] for feature in payload.get("features", [])]


def _rectangular_chunks(bounds, *, divisions: int) -> list[list[float]]:
    west, south, east, north = map(float, bounds)
    longitude_edges = np.linspace(west, east, divisions + 1)
    latitude_edges = np.linspace(south, north, divisions + 1)
    return [
        [
            longitude_edges[column],
            latitude_edges[row],
            longitude_edges[column + 1],
            latitude_edges[row + 1],
        ]
        for row in range(divisions)
        for column in range(divisions)
    ]


def _attach_native_vnp_cells(
    samples: pd.DataFrame,
    *,
    projection_info: dict[str, object],
    target_grid,
) -> pd.DataFrame:
    transform = projection_info.get("transform")
    if not isinstance(transform, list) or len(transform) != 6:
        raise ValueError(f"Unexpected VNP projection transform: {projection_info}")
    x_scale, x_skew, x_origin, y_skew, y_scale, y_origin = map(float, transform)
    if abs(x_skew) > 1e-12 or abs(y_skew) > 1e-12:
        raise ValueError("Skewed VNP grids require a general affine polygon implementation")

    table = samples.copy()
    longitude = table["longitude"].to_numpy(dtype=float)
    latitude = table["latitude"].to_numpy(dtype=float)
    columns = np.rint((longitude - x_origin) / x_scale - 0.5).astype(np.int64)
    rows = np.rint((latitude - y_origin) / y_scale - 0.5).astype(np.int64)

    first_x = x_origin + columns * x_scale
    second_x = x_origin + (columns + 1) * x_scale
    first_y = y_origin + rows * y_scale
    second_y = y_origin + (rows + 1) * y_scale
    west = np.minimum(first_x, second_x)
    east = np.maximum(first_x, second_x)
    south = np.minimum(first_y, second_y)
    north = np.maximum(first_y, second_y)
    polygons_wgs84 = shapely.box(west, south, east, north)
    transformer = Transformer.from_crs("EPSG:4326", target_grid.crs, always_xy=True)
    polygons_projected = shapely.transform(
        polygons_wgs84,
        transformer.transform,
        interleaved=False,
    )
    projected_area = shapely.area(polygons_projected)

    table["coarse_cell_id"] = [
        f"vnp_r{row}_c{column}" for row, column in zip(rows, columns, strict=True)
    ]
    table["coarse_cell_west"] = west
    table["coarse_cell_south"] = south
    table["coarse_cell_east"] = east
    table["coarse_cell_north"] = north
    table["coarse_cell_polygon_wkt"] = shapely.to_wkt(
        polygons_wgs84,
        rounding_precision=12,
    )
    table["coarse_cell_area_m2"] = projected_area
    if "coarse_cell_area_m2_earth_engine" in table:
        table["coarse_cell_area_relative_difference"] = (
            table["coarse_cell_area_m2_earth_engine"].to_numpy(dtype=float)
            - projected_area
        ) / projected_area
    table["vnp_source_crs"] = str(projection_info.get("crs"))
    table["vnp_source_x_scale_degrees"] = x_scale
    table["vnp_source_y_scale_degrees"] = y_scale
    return table


def _add_spatial_fields(samples: pd.DataFrame, *, city, config) -> pd.DataFrame:
    table = samples.copy()
    transformer = Transformer.from_crs(
        "EPSG:4326",
        _utm_crs(float(city.center_lon), float(city.center_lat)),
        always_xy=True,
    )
    x, y = transformer.transform(table["longitude"].to_numpy(), table["latitude"].to_numpy())
    center_x, center_y = transformer.transform(float(city.center_lon), float(city.center_lat))
    table["x_m"] = x
    table["y_m"] = y
    table["radius_m"] = np.hypot(x - center_x, y - center_y)
    block_size = int(config["validation"]["gate0"]["spatial_block_size_m"])
    table["block_id"] = [
        f"{int(np.floor(x_value / block_size))}_{int(np.floor(y_value / block_size))}"
        for x_value, y_value in zip(x, y, strict=True)
    ]
    return table


def _gate_metrics(
    samples: pd.DataFrame,
    *,
    city_id: str,
    allocation_proxy: str,
    config,
) -> dict[str, object]:
    input_sample_count = len(samples)
    samples = _gate_analysis_samples(
        samples,
        allocation_proxy=allocation_proxy,
        config=config,
    )
    if samples.empty:
        raise ValueError(f"No Gate 0 samples remain for {allocation_proxy}")
    proxy = samples["proxy_mean"].to_numpy(dtype=float)
    vnp = samples["vnp_median_corrected_ntl"].to_numpy(dtype=float)
    radius = samples["radius_m"].to_numpy(dtype=float)
    block = (
        samples.groupby("block_id", as_index=False)[["proxy_mean", "vnp_median_corrected_ntl"]]
        .mean()
        .dropna()
    )
    citywide = _spearman(proxy, vnp)
    block_spearman = _spearman(
        block["proxy_mean"].to_numpy(),
        block["vnp_median_corrected_ntl"].to_numpy(),
    )
    proxy_residual = _radial_residual(proxy, radius)
    vnp_residual = _radial_residual(np.log1p(vnp), radius)
    detrended = _spearman(proxy_residual, vnp_residual)

    gate = config["validation"]["gate0"]
    threshold = float(gate["insufficient_proxy_mean_threshold"])
    water_weight = samples["persistent_water_weight_mean"].to_numpy(dtype=float)
    land_threshold = float(gate["minimum_land_weight_for_support"])
    land_eligible = water_weight >= land_threshold
    insufficient = proxy <= threshold
    insufficient_fraction = float(np.mean(insufficient[land_eligible]))
    excluded_water_fraction = float(np.mean(~land_eligible))
    total_vnp = float(np.sum(np.clip(vnp, 0, None)))
    unattributable_vnp_fraction = (
        float(np.sum(np.clip(vnp[insufficient], 0, None)) / total_vnp)
        if total_vnp > 0
        else 0.0
    )
    checks = {
        "citywide": citywide >= float(gate["minimum_citywide_spearman"]),
        "block": block_spearman >= float(gate["minimum_block_spearman"]),
        "detrended": detrended >= float(gate["minimum_detrended_spearman"]),
        "support": insufficient_fraction
        <= float(gate["maximum_insufficient_proxy_fraction"]),
    }
    return {
        "city_id": city_id,
        "allocation_proxy": allocation_proxy,
        "sample_count": len(samples),
        "input_sample_count": input_sample_count,
        "excluded_s2_coarse_support_fraction": (
            1.0 - len(samples) / input_sample_count
            if allocation_proxy == "s2_only_ablation" and input_sample_count
            else 0.0
        ),
        "minimum_s2_coarse_support_fraction": (
            float(config["validation"]["gate0"]["minimum_s2_coarse_support_fraction"])
            if allocation_proxy == "s2_only_ablation"
            else None
        ),
        "block_count": len(block),
        "citywide_spearman": citywide,
        "block_aggregate_spearman": block_spearman,
        "block_mean_spearman": block_spearman,
        "radially_detrended_spearman": detrended,
        "mean_s2_valid_observation_count": float(samples["s2_valid_count_mean"].mean()),
        "minimum_s2_valid_observation_count": float(samples["s2_valid_count_mean"].min()),
        "mean_vnp_valid_observation_count": float(
            samples["vnp_valid_observation_count"].mean()
        ),
        "minimum_vnp_valid_observation_count": float(
            samples["vnp_valid_observation_count"].min()
        ),
        "mean_vnp_quality_retained_fraction": float(
            samples["vnp_quality_retained_fraction"].mean()
        ),
        "mean_native_coarse_cell_area_m2": float(samples["coarse_cell_area_m2"].mean()),
        "excluded_water_cell_fraction": excluded_water_fraction,
        "insufficient_land_proxy_fraction": insufficient_fraction,
        "vnp_radiance_fraction_in_insufficient_cells": unattributable_vnp_fraction,
        "automated_checks": checks,
        "automated_result": "go" if all(checks.values()) else "review_or_prune",
        "claim_limit": "coarse association only; no within-pixel NTL validation",
    }


def _gate_analysis_samples(
    samples: pd.DataFrame,
    *,
    allocation_proxy: str,
    config,
) -> pd.DataFrame:
    if allocation_proxy != "s2_only_ablation":
        return samples
    threshold = float(
        config["validation"]["gate0"]["minimum_s2_coarse_support_fraction"]
    )
    if "s2_supported_area_fraction" not in samples:
        raise ValueError("S2 Gate 0 requires the coarse supported-area fraction")
    return samples[samples["s2_supported_area_fraction"] >= threshold].copy()


def _write_gate_figure(
    samples: pd.DataFrame,
    *,
    city,
    allocation_label: str,
    metrics,
    output_path: Path,
) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(12, 10), constrained_layout=True)
    scatter_kwargs = {
        "s": 5,
        "linewidths": 0,
        "rasterized": True,
    }
    proxy_map = axes[0, 0].scatter(
        samples["longitude"],
        samples["latitude"],
        c=samples["proxy_mean"],
        cmap="YlOrRd",
        **scatter_kwargs,
    )
    figure.colorbar(proxy_map, ax=axes[0, 0], label="coarse proxy mean")
    axes[0, 0].set_title(allocation_label)

    vnp_map = axes[0, 1].scatter(
        samples["longitude"],
        samples["latitude"],
        c=np.log1p(samples["vnp_median_corrected_ntl"]),
        cmap="magma",
        **scatter_kwargs,
    )
    figure.colorbar(vnp_map, ax=axes[0, 1], label="log1p median VNP")
    axes[0, 1].set_title("VNP radiometric authority")

    axes[1, 0].hexbin(
        samples["proxy_mean"],
        samples["vnp_median_corrected_ntl"],
        gridsize=45,
        mincnt=1,
        bins="log",
        cmap="viridis",
    )
    axes[1, 0].set_xlabel("coarse proxy mean")
    axes[1, 0].set_ylabel("median VNP radiance")
    axes[1, 0].set_title(f"Citywide Spearman = {metrics['citywide_spearman']:.3f}")

    block = samples.groupby("block_id", as_index=False)[
        ["proxy_mean", "vnp_median_corrected_ntl"]
    ].mean()
    axes[1, 1].scatter(
        block["proxy_mean"],
        block["vnp_median_corrected_ntl"],
        s=24,
        alpha=0.75,
    )
    axes[1, 1].set_xlabel("5 km block proxy mean")
    axes[1, 1].set_ylabel("5 km block median VNP mean")
    axes[1, 1].set_title(f"Block Spearman = {metrics['block_mean_spearman']:.3f}")

    for axis in axes.flat[:2]:
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("longitude")
        axis.set_ylabel("latitude")
    figure.suptitle(
        f"{city.city}: {allocation_label} Gate 0 — {metrics['automated_result']}\n"
        "Coarse association is not within-pixel NTL validation",
        fontsize=14,
    )
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def _spearman(first: np.ndarray, second: np.ndarray) -> float:
    result = spearmanr(first, second, nan_policy="omit")
    return float(result.statistic)


def _radial_residual(values: np.ndarray, radius: np.ndarray) -> np.ndarray:
    valid = np.isfinite(values) & np.isfinite(radius)
    coefficients = np.polyfit(radius[valid], values[valid], deg=2)
    fitted = np.polyval(coefficients, radius)
    return values - fitted


def _utm_crs(lon: float, lat: float) -> str:
    zone = min(60, max(1, int((lon + 180.0) // 6.0) + 1))
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return f"EPSG:{epsg}"


def _gate0_output_root(config) -> Path:
    artifact_version = config["validation"]["gate0"]["artifact_version"]
    return (
        resolve_project_path(config["outputs"]["validation"])
        / "gate0"
        / artifact_version
    )


def _artifact_metadata(config_path: str | Path, config) -> dict[str, object]:
    return {
        "artifact_version": config["validation"]["gate0"]["artifact_version"],
        "experiment_contract_version": config["experiment"]["contract_version"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "analysis_geometry": "50_km_projected_square",
        "vnp_quality_variant": "primary",
        "vnp_quality_decision_id": config["sources"]["vnp46a2"]["quality_decision_id"],
        "resampling_decision_id": config["grid"]["continuous_resampling"]["decision_id"],
        "continuous_resampling": config["grid"]["continuous_resampling"]["method"],
        "categorical_resampling": config["grid"]["categorical_resampling"]["method"],
        "s2_composite_decision_id": config["sources"]["sentinel2"][
            "composite_decision_id"
        ],
        "s2_composite_method": config["sources"]["sentinel2"]["composite_method"],
        "s2_minimum_common_valid_observations": config["sources"]["sentinel2"][
            "minimum_common_valid_observations"
        ],
        "s2_coarse_support_decision_id": config["validation"]["gate0"][
            "s2_coarse_support_decision_id"
        ],
        "minimum_s2_coarse_support_fraction": config["validation"]["gate0"][
            "minimum_s2_coarse_support_fraction"
        ],
        "gate0_aggregation_halo_m": config["validation"]["gate0"]["aggregation_halo_m"],
        "gate0_status": "current_corrected_rerun",
    }


def _load_pilot_cities(config):
    source_config = load_experiment_config(config["cities"]["source_config"])
    _, cities = build_experiment_manifest(source_config)
    selected = cities[cities["city_id"].isin(config["cities"]["selected_city_ids"])].copy()
    by_id = selected.set_index("city_id")
    return by_id.loc[config["cities"]["selected_city_ids"]].reset_index()


if __name__ == "__main__":
    raise SystemExit(main())
