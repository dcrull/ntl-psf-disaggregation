"""Exact projected-native-cell branch of the tiled full-city executor."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import shapely
from rasterio.windows import Window

from nocturne.disaggregate.empirical_cutouts import (
    _load_native_cells,
    _native_footprint_cutout,
    _read_processing_inputs,
)
from nocturne.disaggregate.export import sha256_file
from nocturne.disaggregate.full_city import (
    BAND_NAMES,
    MASK_LAYER_NAMES,
    _atomic_json,
    _completed_artifact_is_valid,
    _create_working_raster,
    _load_or_initialize_checkpoint,
    _MetricAccumulator,
    _promote_to_cog,
    _validate_final_cog,
    _window_checksum,
    _window_id,
    _write_tile,
    iter_core_windows,
)
from nocturne.disaggregate.water import build_water_proxy_variant


def run_native_configuration(
    config: dict[str, Any],
    *,
    config_hash: str,
    grid,
    spec,
    ee_path: Path,
    overture_path: Path,
    normalization: dict[str, Any],
    output_root: Path,
    analysis_window: Window,
    tile_pixels: int,
    strict_minimum: int,
    broad_minimum: int,
) -> dict[str, Any]:
    """Tile native output while assigning cell metrics to one centroid tile."""

    output_root.mkdir(parents=True, exist_ok=True)
    final_path = output_root / "products.tif"
    metrics_path = output_root / "metrics.json"
    if _completed_artifact_is_valid(final_path, metrics_path, config_hash=config_hash, grid=grid):
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    native_cells = _load_native_cells(config, grid.city_id, target_crs=grid.crs)
    polygons = np.asarray(native_cells["projected_polygon"].tolist(), dtype=object)
    working_path = output_root / "products.working.tif"
    checkpoint_path = output_root / "checkpoint.json"
    checkpoint = _load_or_initialize_checkpoint(
        checkpoint_path,
        working_path=working_path,
        config_hash=config_hash,
        spec=spec,
        grid=grid,
        tile_pixels=tile_pixels,
        halo_pixels=0,
    )
    if not working_path.exists():
        _create_working_raster(working_path, grid=grid)
    completed = dict(checkpoint["tiles"])
    metrics = _MetricAccumulator()
    native_tile_metrics = dict(checkpoint.get("native_tile_metrics", {}))
    source_transform = None
    with rasterio.open(ee_path) as source:
        source_transform = source.transform
        source_shape = (source.height, source.width)

    for core_local in iter_core_windows((grid.height, grid.width), tile_pixels):
        tile_id = _window_id(core_local)
        if (
            tile_id in completed
            and _window_checksum(working_path, core_local) == completed[tile_id]
        ):
            metrics.add_from_raster(working_path, core_local)
            continue
        core_source = Window(
            analysis_window.col_off + core_local.col_off,
            analysis_window.row_off + core_local.row_off,
            core_local.width,
            core_local.height,
        )
        core_transform = rasterio.windows.transform(core_source, source_transform)
        core_bounds = rasterio.transform.array_bounds(
            int(core_source.height), int(core_source.width), core_transform
        )
        core_polygon = shapely.box(*core_bounds)
        selected_mask = shapely.intersects(polygons, core_polygon)
        selected_polygons = polygons[selected_mask]
        tile_cell_metrics: list[dict[str, Any]] = []
        if not selected_mask.any():
            layers = _empty_native_layers((int(core_local.height), int(core_local.width)))
        else:
            total_bounds = shapely.total_bounds(selected_polygons)
            processing = _bounds_window(
                total_bounds,
                transform=source_transform,
                shape=source_shape,
            )
            components, transforms = _read_processing_inputs(
                ee_path,
                overture_path,
                window=processing,
                core_window=core_source,
                strict_minimum_observations=strict_minimum,
                broad_minimum_observations=broad_minimum,
            )
            proxy = build_water_proxy_variant(
                components[f"{spec.proxy}_base"],
                variant=spec.water_variant,
                persistent_water_weight=components["persistent_water_weight"],
                spectral_water_weight=components["spectral_water_weight"],
                persistent_water_mask=components["persistent_water_mask"],
                mapped_infrastructure_mask=components["mapped_infrastructure_mask"],
                proxy_floor=float(config["validation"]["water_handling"]["proxy_floor"]),
            ).proxy
            result = _native_footprint_cutout(
                proxy,
                normalization_divisor=float(normalization[spec.proxy][spec.water_variant]["mean"]),
                native_cells=native_cells,
                core_transform=transforms["core"],
                core_shape=(int(core_local.height), int(core_local.width)),
                processing_transform=transforms["processing"],
                processing_shape=proxy.shape,
                config=config,
            )
            selected = native_cells.loc[selected_mask].reset_index(drop=True)
            selected_centroids = shapely.centroid(selected_polygons)
            left, bottom, right, top = core_bounds
            owned = (
                (shapely.get_x(selected_centroids) >= left)
                & (shapely.get_x(selected_centroids) < right)
                & (shapely.get_y(selected_centroids) >= bottom)
                & (shapely.get_y(selected_centroids) < top)
            )
            for index in np.flatnonzero(owned):
                error = float(result.cell_operator_consistency_error[index])
                tile_cell_metrics.append(
                    {
                        "coarse_cell_id": str(selected.iloc[index]["coarse_cell_id"]),
                        "operator_consistency_error": error if np.isfinite(error) else None,
                        "valid": bool(result.cell_valid_mask[index]),
                        "denominator_floor": bool(result.denominator_floor_cell_mask[index]),
                        "proxy_support_fraction": float(result.cell_proxy_support_fraction[index]),
                    }
                )
            row_offset = int(core_source.row_off - processing.row_off)
            col_offset = int(core_source.col_off - processing.col_off)
            crop = (
                slice(row_offset, row_offset + int(core_source.height)),
                slice(col_offset, col_offset + int(core_source.width)),
            )
            layers = _native_layers(result, crop=crop)
        _write_tile(working_path, core_local, layers)
        completed[tile_id] = _window_checksum(working_path, core_local)
        native_tile_metrics[tile_id] = tile_cell_metrics
        checkpoint["tiles"] = completed
        checkpoint["native_tile_metrics"] = native_tile_metrics
        _atomic_json(checkpoint_path, checkpoint)
        metrics.add(layers)

    cell_records = [
        record for tile_id in sorted(native_tile_metrics) for record in native_tile_metrics[tile_id]
    ]
    cell_metrics = _summarize_cell_records(cell_records)
    _promote_to_cog(working_path, final_path, spec=spec, config_hash=config_hash)
    _validate_final_cog(final_path, grid=grid)
    record = {
        "configuration": asdict(spec),
        "status": "complete",
        "path": str(final_path),
        "sha256": sha256_file(final_path),
        "shape": [grid.height, grid.width],
        "crs": grid.crs,
        "transform": list(grid.transform),
        "band_descriptions": list(BAND_NAMES),
        "tile_pixels": tile_pixels,
        "metric_ownership": "native_cell_projected_centroid_in_analysis_square",
        "native_cell_source": {
            "path": native_cells.attrs["source_path"],
            "sha256": native_cells.attrs["source_sha256"],
        },
        "normalization": normalization[spec.proxy][spec.water_variant],
        "metrics": {
            **metrics.finish(),
            **cell_metrics,
            "native_cell_records": cell_records,
        },
    }
    _atomic_json(metrics_path, record)
    return record


def _bounds_window(bounds: np.ndarray, *, transform, shape: tuple[int, int]) -> Window:
    min_x, min_y, max_x, max_y = (float(value) for value in bounds)
    resolution = abs(float(transform.a))
    col0 = max(0, math.floor((min_x - transform.c) / resolution))
    col1 = min(shape[1], math.ceil((max_x - transform.c) / resolution))
    row0 = max(0, math.floor((transform.f - max_y) / resolution))
    row1 = min(shape[0], math.ceil((transform.f - min_y) / resolution))
    return Window(col0, row0, col1 - col0, row1 - row0)


def _native_layers(result, *, crop: tuple[slice, slice]) -> dict[str, np.ndarray]:
    allocation = result.allocation[crop]
    finite = np.isfinite(allocation)
    nan = np.full(allocation.shape, np.nan, dtype=np.float32)
    false = np.zeros(allocation.shape, dtype=bool)
    insufficient = (
        np.isfinite(result.normalized_proxy[crop])
        & ~finite
        & (result.fine_coverage_fraction[crop] > 0)
    )
    return {
        "allocation": allocation,
        "operator_consistency_error": nan,
        "radiance_support_fraction": result.fine_coverage_fraction[crop],
        "proxy_support_fraction": result.fine_coverage_fraction[crop],
        "allocation_support_fraction": finite.astype(np.float32),
        "geometric_support_fraction": result.fine_coverage_fraction[crop],
        "valid_output_mask": finite,
        "operator_consistency_valid_mask": false,
        "boundary_mask": (result.fine_coverage_fraction[crop] < 1)
        & (result.fine_coverage_fraction[crop] > 0),
        "invalid_radiance_neighborhood_mask": false,
        "invalid_proxy_neighborhood_mask": insufficient,
        "denominator_floor_mask": false,
        "denominator_instability_mask": false,
        "negative_radiance_input_mask": false,
        "negative_preclip_output_mask": result.negative_preclip_output_mask[crop],
        "insufficient_proxy_support_mask": insufficient,
    }


def _empty_native_layers(shape: tuple[int, int]) -> dict[str, np.ndarray]:
    nan = np.full(shape, np.nan, dtype=np.float32)
    false = np.zeros(shape, dtype=bool)
    return {
        **{name: nan for name in BAND_NAMES if name not in MASK_LAYER_NAMES},
        **{name: false for name in MASK_LAYER_NAMES},
    }


def _summarize_cell_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    errors = np.asarray(
        [
            record["operator_consistency_error"]
            for record in records
            if record["operator_consistency_error"] is not None
        ],
        dtype=np.float64,
    )
    return {
        "owned_native_cell_count": len(records),
        "valid_native_cell_count": sum(record["valid"] for record in records),
        "denominator_floor_native_cell_count": sum(
            record["denominator_floor"] for record in records
        ),
        "native_cell_operator_consistency_sample_count": int(errors.size),
        "native_cell_operator_consistency_bias": (float(errors.mean()) if errors.size else None),
        "native_cell_operator_consistency_mae": (
            float(np.abs(errors).mean()) if errors.size else None
        ),
        "native_cell_operator_consistency_rmse": (
            float(np.sqrt(np.square(errors).mean())) if errors.size else None
        ),
    }
