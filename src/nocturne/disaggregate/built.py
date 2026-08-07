from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely
from pyproj import Transformer

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.gate0 import (
    _artifact_metadata,
    _gate0_output_root,
    _gate_analysis_samples,
    _gate_metrics,
    _write_gate_figure,
)
from nocturne.experiment.manifest import build_experiment_manifest, load_experiment_config
from nocturne.preview.paths import resolve_project_path


def run_built_form_gate0(config_path: str | Path) -> list[Path]:
    config = load_disaggregation_config(config_path)
    cities = _load_pilot_cities(config)
    output_root = _gate0_output_root(config)
    overture_root = resolve_project_path(
        config["allocation_proxies"]["built_form"]["overture_input_root"]
    )

    written: list[Path] = []
    summary_rows = []
    for city in cities.itertuples(index=False):
        s2_sample_path = output_root / f"{city.city_id}_s2_only_samples.csv"
        if not s2_sample_path.exists():
            raise FileNotFoundError(
                f"Run nocturne.disaggregate.gate0 before built-form aggregation: {s2_sample_path}"
            )
        samples = pd.read_csv(s2_sample_path)
        built = aggregate_overture_to_samples(
            samples,
            buildings_path=overture_root / city.city_id / "buildings.parquet",
            segments_path=overture_root / city.city_id / "segments.parquet",
            city=city,
            config=config,
        )
        metrics = _gate_metrics(
            built,
            city_id=city.city_id,
            allocation_proxy="built_form_primary",
            config=config,
        )
        metrics.update(_artifact_metadata(config_path, config))
        metrics["overture_release"] = config["allocation_proxies"]["built_form"][
            "overture_release"
        ]
        metrics["built_form_temporal_semantics"] = config["allocation_proxies"][
            "built_form"
        ]["temporal_semantics"]
        summary_rows.append(metrics)

        sample_path = output_root / f"{city.city_id}_built_form_samples.csv"
        built.to_csv(sample_path, index=False)
        written.append(sample_path)
        figure_path = output_root / f"{city.city_id}_built_form_gate0.png"
        _write_gate_figure(
            _gate_analysis_samples(
                built,
                allocation_proxy="built_form_primary",
                config=config,
            ),
            city=city,
            allocation_label="Overture built-form allocation proxy",
            metrics=metrics,
            output_path=figure_path,
        )
        written.append(figure_path)

    summary = pd.DataFrame(summary_rows)
    summary_path = output_root / "built_form_gate0_summary.csv"
    summary.to_csv(summary_path, index=False)
    written.append(summary_path)
    json_path = output_root / "built_form_gate0_summary.json"
    json_path.write_text(
        json.dumps(summary.to_dict(orient="records"), indent=2) + "\n",
        encoding="utf-8",
    )
    written.append(json_path)
    return written


def aggregate_overture_to_samples(
    samples: pd.DataFrame,
    *,
    buildings_path: Path,
    segments_path: Path,
    city,
    config,
) -> pd.DataFrame:
    table = samples.copy()
    transformer = Transformer.from_crs(
        "EPSG:4326",
        _utm_crs(float(city.center_lon), float(city.center_lat)),
        always_xy=True,
    )
    cell_polygons_wgs84 = shapely.from_wkt(
        table["coarse_cell_polygon_wkt"].to_numpy(dtype=str)
    )
    cell_polygons_projected = shapely.transform(
        cell_polygons_wgs84,
        transformer.transform,
        interleaved=False,
    )
    cell_tree = shapely.STRtree(cell_polygons_projected)
    built_config = config["allocation_proxies"]["built_form"]
    required_bbox = (
        float(table["coarse_cell_west"].min()),
        float(table["coarse_cell_south"].min()),
        float(table["coarse_cell_east"].max()),
        float(table["coarse_cell_north"].max()),
    )
    _validate_overture_source(
        buildings_path,
        expected_release=built_config["overture_release"],
        required_bbox=required_bbox,
    )
    _validate_overture_source(
        segments_path,
        expected_release=built_config["overture_release"],
        required_bbox=required_bbox,
    )

    building_area = _aggregate_geometry_measure(
        buildings_path,
        cell_tree=cell_tree,
        cell_polygons=cell_polygons_projected,
        transformer=transformer,
        row_count=len(table),
        geometry_kind="area",
    )
    road_length = _aggregate_geometry_measure(
        segments_path,
        cell_tree=cell_tree,
        cell_polygons=cell_polygons_projected,
        transformer=transformer,
        row_count=len(table),
        geometry_kind="weighted_road_length",
        road_weights=built_config["road_class_weights"],
        unlisted_road_class_policy=built_config["unlisted_road_class_policy"],
    )

    cell_area_m2 = shapely.area(cell_polygons_projected)
    table_area_m2 = table["coarse_cell_area_m2"].to_numpy(dtype=float)
    if not np.allclose(cell_area_m2, table_area_m2, rtol=1e-9, atol=0.01):
        raise ValueError("Stored coarse-cell areas do not match the actual projected polygons")
    building_fraction_unclipped = building_area / cell_area_m2
    building_fraction = np.clip(building_fraction_unclipped, 0, 1)
    road_density_m_per_km2 = road_length / cell_area_m2 * 1_000_000.0
    road_saturation = float(built_config["road_density_saturation_m_per_km2"])
    road_density = np.clip(road_density_m_per_km2 / road_saturation, 0, 1)

    building_weight = float(built_config["building_weight"])
    road_weight = float(built_config["road_weight"])
    if built_config["building_fraction_transform"] != "sqrt":
        raise ValueError("Only the declared sqrt building transform is implemented")
    raw = building_weight * np.sqrt(building_fraction) + road_weight * road_density
    raw *= table["persistent_water_weight_mean"].to_numpy(dtype=float)
    floor = float(config["validation"]["water_handling"]["proxy_floor"])
    proxy = floor + (1.0 - floor) * raw

    table["building_footprint_area_m2_intersection_allocated"] = building_area
    table["building_footprint_fraction_unclipped"] = building_fraction_unclipped
    table["building_footprint_fraction"] = building_fraction
    table["weighted_road_length_m_intersection_allocated"] = road_length
    table["weighted_road_density_m_per_km2"] = road_density_m_per_km2
    table["weighted_road_density_normalized"] = road_density
    table["proxy_mean"] = proxy
    table["overture_release"] = built_config["overture_release"]
    table["built_form_temporal_semantics"] = built_config["temporal_semantics"]
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and evaluate coarse Overture proxy.")
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    for path in run_built_form_gate0(args.config):
        print(path)
    return 0


def _aggregate_geometry_measure(
    path: Path,
    *,
    cell_tree,
    cell_polygons,
    transformer: Transformer,
    row_count: int,
    geometry_kind: str,
    road_weights: dict[str, float] | None = None,
    unlisted_road_class_policy: str = "error",
) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(path)
    columns = ["geometry"]
    if geometry_kind == "weighted_road_length":
        columns.extend(["subtype", "class"])
    totals = np.zeros(row_count, dtype=np.float64)

    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(columns=columns, batch_size=50_000):
        geometry_values = batch.column(batch.schema.get_field_index("geometry"))
        valid = geometry_values.is_valid().to_numpy(zero_copy_only=False)
        if not valid.any():
            continue
        geometry = shapely.from_wkb(
            geometry_values.filter(valid).to_numpy(zero_copy_only=False)
        )
        if geometry_kind == "weighted_road_length":
            subtype = np.asarray(
                batch.column(batch.schema.get_field_index("subtype"))
                .filter(valid)
                .to_pylist(),
                dtype=object,
            )
            road_mask = subtype == "road"
            if not road_mask.any():
                continue
            geometry = geometry[road_mask]
            road_class = np.asarray(
                batch.column(batch.schema.get_field_index("class"))
                .filter(valid)
                .to_pylist(),
                dtype=object,
            )[road_mask]
        projected = shapely.transform(geometry, transformer.transform, interleaved=False)
        invalid = ~shapely.is_valid(projected)
        if invalid.any():
            projected[invalid] = shapely.make_valid(projected[invalid])
        nonempty = ~shapely.is_empty(projected)
        if not nonempty.any():
            continue
        projected = projected[nonempty]
        if geometry_kind == "weighted_road_length":
            road_class = road_class[nonempty]
            configured_classes = set(road_weights or {})
            observed_classes = {
                str(class_value or "unknown") for class_value in road_class
            }
            unlisted = observed_classes - configured_classes
            if unlisted and unlisted_road_class_policy == "error":
                raise ValueError(
                    f"Unlisted Overture road classes in {path}: {sorted(unlisted)}"
                )
        query_pairs = cell_tree.query(projected, predicate="intersects")
        if query_pairs.size == 0:
            continue
        geometry_index, cell_index = query_pairs
        intersections = shapely.intersection(
            projected[geometry_index],
            cell_polygons[cell_index],
        )
        if geometry_kind == "area":
            measure = shapely.area(intersections)
        elif geometry_kind == "weighted_road_length":
            weights = np.asarray(
                [
                    float((road_weights or {})[class_value or "unknown"])
                    for class_value in road_class[geometry_index]
                ]
            )
            measure = shapely.length(intersections) * weights
        else:
            raise ValueError(f"Unsupported geometry kind: {geometry_kind}")
        totals += np.bincount(
            cell_index,
            weights=measure,
            minlength=row_count,
        )
    return totals


def _validate_overture_source(
    path: Path,
    *,
    expected_release: str,
    required_bbox: tuple[float, float, float, float],
) -> None:
    state_path = Path(f"{path}.state")
    if not state_path.exists():
        raise FileNotFoundError(f"Missing Overture release state: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("last_release") != expected_release:
        raise ValueError(
            f"Overture release mismatch for {path}: "
            f"expected {expected_release}, found {state.get('last_release')}"
        )
    bbox = state.get("bbox", {})
    source_bbox = (
        float(bbox.get("xmin", float("nan"))),
        float(bbox.get("ymin", float("nan"))),
        float(bbox.get("xmax", float("nan"))),
        float(bbox.get("ymax", float("nan"))),
    )
    if not (
        source_bbox[0] <= required_bbox[0]
        and source_bbox[1] <= required_bbox[1]
        and source_bbox[2] >= required_bbox[2]
        and source_bbox[3] >= required_bbox[3]
    ):
        raise ValueError(
            f"Overture source bbox for {path} does not cover the native-cell polygons: "
            f"source={source_bbox}, required={required_bbox}"
        )


def _utm_crs(lon: float, lat: float) -> str:
    zone = min(60, max(1, int((lon + 180.0) // 6.0) + 1))
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return f"EPSG:{epsg}"


def _load_pilot_cities(config):
    source_config = load_experiment_config(config["cities"]["source_config"])
    _, cities = build_experiment_manifest(source_config)
    selected = cities[cities["city_id"].isin(config["cities"]["selected_city_ids"])].copy()
    by_id = selected.set_index("city_id")
    return by_id.loc[config["cities"]["selected_city_ids"]].reset_index()


if __name__ == "__main__":
    raise SystemExit(main())
