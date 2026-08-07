"""Build audited 10 m Overture structure bundles for empirical Day 2 runs."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import rasterio
import shapely
from affine import Affine
from pyproj import Transformer
from rasterio.enums import MergeAlg
from rasterio.features import rasterize

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.export import sha256_file
from nocturne.disaggregate.grids import (
    CityGridSpec,
    build_city_grid_specs,
    expanded_grid_shape,
    expanded_grid_transform,
)
from nocturne.preview.paths import resolve_project_path


def build_overture_structure_bundles(
    config_path: str | Path,
    *,
    city_ids: list[str] | None = None,
) -> list[Path]:
    """Build one four-band COG and provenance manifest for each selected city."""

    config = load_disaggregation_config(config_path)
    grids = build_city_grid_specs(config_path)
    requested = set(city_ids or [grid.city_id for grid in grids])
    unknown = requested - {grid.city_id for grid in grids}
    if unknown:
        raise ValueError(f"Unknown requested cities: {sorted(unknown)}")

    written: list[Path] = []
    for grid in grids:
        if grid.city_id not in requested:
            continue
        print(f"{grid.city_id}: building Overture structure bundle", flush=True)
        bundle_path, manifest_path = _build_city_bundle(
            config_path=Path(config_path),
            config=config,
            grid=grid,
        )
        written.extend([bundle_path, manifest_path])
    return written


def _build_city_bundle(
    *,
    config_path: Path,
    config: dict[str, Any],
    grid: CityGridSpec,
) -> tuple[Path, Path]:
    built_config = config["allocation_proxies"]["built_form"]
    rasterization_config = built_config["rasterization"]
    input_root = resolve_project_path(built_config["overture_input_root"]) / grid.city_id
    buildings_path = input_root / "buildings.parquet"
    segments_path = input_root / "segments.parquet"
    source_records = [
        _validate_source(
            buildings_path,
            expected_release=built_config["overture_release"],
            expected_type="building",
        ),
        _validate_source(
            segments_path,
            expected_release=built_config["overture_release"],
            expected_type="segment",
        ),
    ]

    halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    shape = expanded_grid_shape(grid, halo_m=halo_m)
    transform = Affine(*expanded_grid_transform(grid, halo_m=halo_m))
    transformer = Transformer.from_crs(
        rasterization_config["source_crs"],
        grid.crs,
        always_xy=True,
    )
    building_config = rasterization_config["building_fraction"]
    road_config = rasterization_config["weighted_road_length"]

    print(
        f"{grid.city_id}: rasterizing building union at "
        f"{building_config['subpixel_resolution_m']} m",
        flush=True,
    )
    building_fraction, building_metrics = _rasterize_building_fraction(
        buildings_path,
        shape=shape,
        transform=transform,
        source_to_target=transformer,
        target_resolution_m=grid.resolution_m,
        subpixel_resolution_m=int(building_config["subpixel_resolution_m"]),
        progress_label=grid.city_id,
    )
    print(
        f"{grid.city_id}: allocating weighted road centerline length at "
        f"≤{road_config['maximum_segment_length_m']} m segments",
        flush=True,
    )
    road_length, road_metrics = _rasterize_weighted_road_length(
        segments_path,
        shape=shape,
        transform=transform,
        source_to_target=transformer,
        road_weights=built_config["road_class_weights"],
        unlisted_road_class_policy=built_config["unlisted_road_class_policy"],
        maximum_segment_length_m=float(road_config["maximum_segment_length_m"]),
        conservation_relative_tolerance=float(
            road_config["length_conservation_relative_tolerance"]
        ),
        progress_label=grid.city_id,
    )

    pixel_area_m2 = abs(transform.a * transform.e - transform.b * transform.d)
    weighted_road_density_m_per_km2 = (
        road_length.astype(np.float64) / pixel_area_m2 * 1_000_000.0
    )
    road_density_normalized = np.clip(
        weighted_road_density_m_per_km2
        / float(built_config["road_density_saturation_m_per_km2"]),
        0,
        1,
    ).astype(np.float32)
    base_proxy = (
        float(built_config["building_weight"]) * np.sqrt(building_fraction)
        + float(built_config["road_weight"]) * road_density_normalized
    ).astype(np.float32)
    mapped_infrastructure = (
        (building_fraction > 0) | (road_length > 0)
    ).astype(np.float32)
    layers = (
        building_fraction.astype(np.float32, copy=False),
        road_density_normalized,
        base_proxy,
        mapped_infrastructure,
    )

    output_config = config["outputs"]["day2_inputs"]
    output_directory = resolve_project_path(output_config["root"]) / grid.city_id
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / output_config["overture_bundle_filename"]
    tags = {
        "experiment_id": config["experiment"]["id"],
        "contract_version": config["experiment"]["contract_version"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "city_id": grid.city_id,
        "overture_release": built_config["overture_release"],
        "temporal_semantics": built_config["temporal_semantics"],
        "rasterization_decision_id": rasterization_config["decision_id"],
        "rasterization_contract": rasterization_config,
        "building_weight": built_config["building_weight"],
        "road_weight": built_config["road_weight"],
        "road_density_saturation_m_per_km2": built_config[
            "road_density_saturation_m_per_km2"
        ],
        "road_class_weights": built_config["road_class_weights"],
        "source_records": source_records,
        "water_weight_applied": False,
        "proxy_floor_applied": False,
    }
    _write_multiband_cog_atomic(
        output_path,
        layers=layers,
        band_names=output_config["overture_bands"],
        crs=grid.crs,
        transform=transform,
        overview_resampling=rasterization_config["output_overview_resampling"],
        tags=tags,
    )

    manifest_path = output_directory / "overture_structure_bundle.json"
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": config["experiment"]["id"],
        "contract_version": config["experiment"]["contract_version"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "city_id": grid.city_id,
        "crs": grid.crs,
        "shape": list(shape),
        "transform": list(transform)[:6],
        "bands": list(output_config["overture_bands"]),
        "rasterization_contract": rasterization_config,
        "source_records": source_records,
        "building_metrics": building_metrics,
        "road_metrics": road_metrics,
        "output": {
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{grid.city_id}: wrote {output_path}", flush=True)
    return output_path, manifest_path


def _rasterize_building_fraction(
    path: Path,
    *,
    shape: tuple[int, int],
    transform: Affine,
    source_to_target: Transformer,
    target_resolution_m: int,
    subpixel_resolution_m: int,
    progress_label: str | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    if target_resolution_m % subpixel_resolution_m:
        raise ValueError("Building subpixel resolution must divide the target resolution")
    factor = target_resolution_m // subpixel_resolution_m
    sub_shape = (shape[0] * factor, shape[1] * factor)
    sub_transform = Affine(
        subpixel_resolution_m,
        0,
        transform.c,
        0,
        -subpixel_resolution_m,
        transform.f,
    )
    parquet = pq.ParquetFile(path)
    processed = 0
    repaired = 0
    polygon_parts = 0
    projected_area_sum_m2 = 0.0

    with tempfile.TemporaryDirectory(prefix="nocturne-overture-buildings-") as temp:
        occupancy_path = Path(temp) / "building_occupancy.uint8"
        occupancy = np.memmap(
            occupancy_path,
            dtype=np.uint8,
            mode="w+",
            shape=sub_shape,
        )
        occupancy[:] = 0
        for batch_index, batch in enumerate(
            parquet.iter_batches(columns=["geometry"], batch_size=25_000),
            start=1,
        ):
            geometries = shapely.from_wkb(
                batch.column(0).to_numpy(zero_copy_only=False)
            )
            processed += len(geometries)
            projected = shapely.transform(
                geometries,
                source_to_target.transform,
                interleaved=False,
            )
            invalid = ~shapely.is_valid(projected)
            repaired += int(invalid.sum())
            if invalid.any():
                projected = projected.copy()
                projected[invalid] = shapely.make_valid(projected[invalid])
            polygons = _polygon_parts(projected)
            nonempty = ~shapely.is_empty(polygons)
            polygons = polygons[nonempty]
            if len(polygons):
                polygon_parts += len(polygons)
                projected_area_sum_m2 += float(shapely.area(polygons).sum())
                _burn_polygon_batch(
                    occupancy,
                    polygons=polygons,
                    transform=sub_transform,
                )
            if progress_label and (batch_index == 1 or batch_index % 20 == 0):
                print(
                    f"{progress_label}: buildings {processed:,}/"
                    f"{parquet.metadata.num_rows:,}",
                    flush=True,
                )
        occupancy.flush()

        building_fraction = np.empty(shape, dtype=np.float32)
        output_row_chunk = 128
        for row_start in range(0, shape[0], output_row_chunk):
            row_stop = min(shape[0], row_start + output_row_chunk)
            subpixel_rows = np.asarray(
                occupancy[row_start * factor : row_stop * factor, :]
            )
            building_fraction[row_start:row_stop] = subpixel_rows.reshape(
                row_stop - row_start,
                factor,
                shape[1],
                factor,
            ).mean(axis=(1, 3), dtype=np.float32)
        occupied_subpixels = int(np.count_nonzero(occupancy))
        del occupancy

    sampled_union_area_m2 = occupied_subpixels * subpixel_resolution_m**2
    return building_fraction, {
        "source_feature_count": processed,
        "repaired_invalid_geometry_count": repaired,
        "polygon_part_count": polygon_parts,
        "source_polygon_part_area_sum_m2_before_union": projected_area_sum_m2,
        "sampled_binary_union_area_m2": sampled_union_area_m2,
        "subpixel_resolution_m": subpixel_resolution_m,
        "target_resolution_m": target_resolution_m,
        "fraction_increment": 1.0 / factor**2,
        "nonzero_target_pixel_count": int(np.count_nonzero(building_fraction)),
        "maximum_fraction": float(building_fraction.max()),
    }


def _burn_polygon_batch(
    occupancy: np.memmap,
    *,
    polygons: np.ndarray,
    transform: Affine,
) -> None:
    left, bottom, right, top = shapely.total_bounds(polygons)
    height, width = occupancy.shape
    column_start = max(0, math.floor((left - transform.c) / transform.a) - 1)
    column_stop = min(width, math.ceil((right - transform.c) / transform.a) + 1)
    row_start = max(0, math.floor((transform.f - top) / -transform.e) - 1)
    row_stop = min(height, math.ceil((transform.f - bottom) / -transform.e) + 1)
    if column_stop <= column_start or row_stop <= row_start:
        return
    local_shape = (row_stop - row_start, column_stop - column_start)
    local_transform = transform * Affine.translation(column_start, row_start)
    burned = rasterize(
        ((geometry, 1) for geometry in polygons),
        out_shape=local_shape,
        transform=local_transform,
        fill=0,
        all_touched=False,
        merge_alg=MergeAlg.replace,
        dtype=np.uint8,
        skip_invalid=False,
    )
    target = occupancy[row_start:row_stop, column_start:column_stop]
    np.maximum(target, burned, out=target)


def _rasterize_weighted_road_length(
    path: Path,
    *,
    shape: tuple[int, int],
    transform: Affine,
    source_to_target: Transformer,
    road_weights: dict[str, float],
    unlisted_road_class_policy: str,
    maximum_segment_length_m: float,
    conservation_relative_tolerance: float,
    progress_label: str | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    if maximum_segment_length_m <= 0:
        raise ValueError("Road maximum segment length must be positive")
    parquet = pq.ParquetFile(path)
    weighted_length = np.zeros(shape, dtype=np.float32)
    flat_output = weighted_length.ravel()
    processed = 0
    retained_roads = 0
    repaired = 0
    input_weighted_length_m = 0.0
    allocated_weighted_length_m = 0.0
    observed_classes: set[str] = set()
    extent = shapely.box(
        transform.c,
        transform.f + transform.e * shape[0],
        transform.c + transform.a * shape[1],
        transform.f,
    )

    for batch_index, batch in enumerate(
        parquet.iter_batches(
            columns=["geometry", "subtype", "class"],
            batch_size=5_000,
        ),
        start=1,
    ):
        processed += batch.num_rows
        subtype = np.asarray(batch.column(1).to_pylist(), dtype=object)
        road_mask = subtype == "road"
        if not road_mask.any():
            continue
        geometries = shapely.from_wkb(
            batch.column(0).filter(road_mask).to_numpy(zero_copy_only=False)
        )
        class_values = np.asarray(
            [
                value or "unknown"
                for value in batch.column(2).filter(road_mask).to_pylist()
            ],
            dtype=object,
        )
        batch_classes = {str(value) for value in class_values}
        observed_classes.update(batch_classes)
        unlisted = batch_classes - set(road_weights)
        if unlisted and unlisted_road_class_policy == "error":
            raise ValueError(
                f"Unlisted Overture road classes in {path}: {sorted(unlisted)}"
            )
        class_weights = np.asarray(
            [float(road_weights[str(value)]) for value in class_values],
            dtype=np.float64,
        )
        projected = shapely.transform(
            geometries,
            source_to_target.transform,
            interleaved=False,
        )
        invalid = ~shapely.is_valid(projected)
        repaired += int(invalid.sum())
        if invalid.any():
            projected = projected.copy()
            projected[invalid] = shapely.make_valid(projected[invalid])
        clipped = shapely.intersection(projected, extent)
        lines, parent = _line_parts(clipped)
        if not len(lines):
            continue
        weights = class_weights[parent]
        nonempty = ~shapely.is_empty(lines)
        lines = lines[nonempty]
        weights = weights[nonempty]
        if not len(lines):
            continue
        retained_roads += len(lines)
        input_weighted_length_m += float((shapely.length(lines) * weights).sum())
        allocated = _accumulate_segmentized_line_lengths(
            flat_output,
            lines=lines,
            weights=weights,
            shape=shape,
            transform=transform,
            maximum_segment_length_m=maximum_segment_length_m,
        )
        allocated_weighted_length_m += allocated
        if progress_label and (batch_index == 1 or batch_index % 20 == 0):
            print(
                f"{progress_label}: segments {processed:,}/"
                f"{parquet.metadata.num_rows:,}",
                flush=True,
            )

    relative_error = (
        abs(allocated_weighted_length_m - input_weighted_length_m)
        / input_weighted_length_m
        if input_weighted_length_m
        else 0.0
    )
    if relative_error > conservation_relative_tolerance:
        raise ValueError(
            "Weighted road-length allocation failed conservation tolerance: "
            f"{relative_error} > {conservation_relative_tolerance}"
        )
    output_sum = float(weighted_length.sum(dtype=np.float64))
    return weighted_length, {
        "source_segment_count": processed,
        "retained_road_part_count": retained_roads,
        "repaired_invalid_geometry_count": repaired,
        "observed_road_classes": sorted(observed_classes),
        "input_weighted_centerline_length_m": input_weighted_length_m,
        "allocated_weighted_centerline_length_m_before_float32_accumulation": (
            allocated_weighted_length_m
        ),
        "output_weighted_centerline_length_m": output_sum,
        "allocation_relative_error_before_float32_accumulation": relative_error,
        "float32_accumulation_relative_error": (
            abs(output_sum - allocated_weighted_length_m)
            / allocated_weighted_length_m
            if allocated_weighted_length_m
            else 0.0
        ),
        "maximum_segment_length_m": maximum_segment_length_m,
        "assumed_road_width_m": None,
        "nonzero_target_pixel_count": int(np.count_nonzero(weighted_length)),
    }


def _accumulate_segmentized_line_lengths(
    flat_output: np.ndarray,
    *,
    lines: np.ndarray,
    weights: np.ndarray,
    shape: tuple[int, int],
    transform: Affine,
    maximum_segment_length_m: float,
) -> float:
    segmented = shapely.segmentize(
        lines,
        max_segment_length=maximum_segment_length_m,
    )
    coordinate_counts = shapely.get_num_coordinates(segmented).astype(np.int64)
    coordinates = shapely.get_coordinates(segmented)
    if len(coordinates) < 2:
        return 0.0
    pair_mask = np.ones(len(coordinates) - 1, dtype=bool)
    ends = np.cumsum(coordinate_counts)[:-1] - 1
    pair_mask[ends] = False
    starts = coordinates[:-1][pair_mask]
    stops = coordinates[1:][pair_mask]
    segment_lengths = np.linalg.norm(stops - starts, axis=1)
    coordinate_line_index = np.repeat(
        np.arange(len(segmented), dtype=np.int64),
        coordinate_counts,
    )
    segment_weights = weights[coordinate_line_index[:-1][pair_mask]]
    weighted_segment_lengths = segment_lengths * segment_weights
    midpoints = (starts + stops) * 0.5
    columns = np.floor((midpoints[:, 0] - transform.c) / transform.a).astype(
        np.int64
    )
    rows = np.floor((transform.f - midpoints[:, 1]) / -transform.e).astype(
        np.int64
    )
    inside = (
        (rows >= 0)
        & (rows < shape[0])
        & (columns >= 0)
        & (columns < shape[1])
    )
    flat_indices = rows[inside] * shape[1] + columns[inside]
    np.add.at(
        flat_output,
        flat_indices,
        weighted_segment_lengths[inside].astype(flat_output.dtype),
    )
    return float(weighted_segment_lengths[inside].sum())


def _polygon_parts(geometries: np.ndarray) -> np.ndarray:
    parts, _ = shapely.get_parts(geometries, return_index=True)
    for _ in range(2):
        multipart = np.isin(shapely.get_type_id(parts), [6, 7])
        if not multipart.any():
            break
        expanded, _ = shapely.get_parts(parts[multipart], return_index=True)
        parts = np.concatenate([parts[~multipart], expanded])
    return parts[np.isin(shapely.get_type_id(parts), [3, 6])]


def _line_parts(geometries: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    parts, parent = shapely.get_parts(geometries, return_index=True)
    for _ in range(2):
        multipart = np.isin(shapely.get_type_id(parts), [5, 7])
        if not multipart.any():
            break
        expanded, expanded_parent = shapely.get_parts(
            parts[multipart],
            return_index=True,
        )
        parent_for_multipart = parent[multipart][expanded_parent]
        parts = np.concatenate([parts[~multipart], expanded])
        parent = np.concatenate([parent[~multipart], parent_for_multipart])
    line_mask = shapely.get_type_id(parts) == 1
    return parts[line_mask], parent[line_mask]


def _validate_source(
    path: Path,
    *,
    expected_release: str,
    expected_type: str,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    state_path = path.with_suffix(path.suffix + ".state")
    if not state_path.exists():
        raise FileNotFoundError(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("last_release") != expected_release:
        raise ValueError(f"Unexpected Overture release in {state_path}")
    if state.get("type") != expected_type:
        raise ValueError(f"Unexpected Overture type in {state_path}")
    if (
        state.get("analysis_geometry")
        != "exact_50_km_projected_square_plus_source_halo"
    ):
        raise ValueError(f"Unexpected Overture analysis geometry in {state_path}")
    parquet = pq.ParquetFile(path)
    return {
        "path": str(path),
        "state_path": str(state_path),
        "release": state["last_release"],
        "type": state["type"],
        "bbox": state["bbox"],
        "feature_count": parquet.metadata.num_rows,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_multiband_cog_atomic(
    path: Path,
    *,
    layers: tuple[np.ndarray, ...],
    band_names: list[str],
    crs: str,
    transform: Affine,
    overview_resampling: str,
    tags: dict[str, Any],
) -> None:
    if len(layers) != len(band_names):
        raise ValueError("Overture layer count differs from the band contract")
    shape = layers[0].shape
    if any(layer.shape != shape for layer in layers):
        raise ValueError("Overture bundle layers do not share one shape")
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}.",
        suffix=".tif",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
    try:
        profile = {
            "driver": "COG",
            "height": shape[0],
            "width": shape[1],
            "count": len(layers),
            "dtype": "float32",
            "crs": crs,
            "transform": transform,
            "compress": "DEFLATE",
            "blocksize": 512,
            "overview_resampling": overview_resampling,
            "BIGTIFF": "IF_SAFER",
        }
        with rasterio.open(temporary_path, "w", **profile) as dataset:
            for index, (layer, band_name) in enumerate(
                zip(layers, band_names, strict=True),
                start=1,
            ):
                dataset.write(layer.astype(np.float32, copy=False), index)
                dataset.set_band_description(index, band_name)
            dataset.update_tags(
                **{
                    key: _tag_value(value)
                    for key, value in tags.items()
                    if value is not None
                }
            )
        _validate_multiband_cog(
            temporary_path,
            expected_shape=shape,
            expected_transform=transform,
            expected_crs=crs,
            expected_bands=band_names,
        )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _validate_multiband_cog(
    path: Path,
    *,
    expected_shape: tuple[int, int],
    expected_transform: Affine,
    expected_crs: str,
    expected_bands: list[str],
) -> None:
    with rasterio.open(path) as dataset:
        if dataset.driver != "GTiff":
            raise ValueError(f"Overture bundle is not a GeoTIFF: {path}")
        if dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") != "COG":
            raise ValueError(f"Overture bundle is not marked as a COG: {path}")
        if (dataset.height, dataset.width) != expected_shape:
            raise ValueError(f"Overture bundle shape mismatch: {path}")
        if dataset.transform != expected_transform:
            raise ValueError(f"Overture bundle transform mismatch: {path}")
        if dataset.crs is None or dataset.crs.to_string() != expected_crs:
            raise ValueError(f"Overture bundle CRS mismatch: {path}")
        if list(dataset.descriptions) != expected_bands:
            raise ValueError(f"Overture bundle band mismatch: {path}")


def _tag_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build 10 m Overture structure bundles for empirical Day 2."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    parser.add_argument(
        "--city",
        action="append",
        dest="city_ids",
        help="Build only this city ID; repeat to select multiple cities.",
    )
    args = parser.parse_args(argv)
    for path in build_overture_structure_bundles(
        args.config,
        city_ids=args.city_ids,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
