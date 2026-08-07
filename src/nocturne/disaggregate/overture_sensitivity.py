"""Run non-radiance-selected Overture rasterization cutout sensitivities."""

from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.windows import Window

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.grids import (
    build_city_grid_specs,
    expanded_grid_shape,
    expanded_grid_transform,
)
from nocturne.disaggregate.overture_bundle import (
    _rasterize_building_fraction,
    _rasterize_weighted_road_length,
)
from nocturne.preview.paths import resolve_project_path


def run_overture_rasterization_sensitivity(
    config_path: str | Path,
    *,
    city_ids: list[str] | None = None,
) -> list[Path]:
    """Compare the primary rasterization with finer settings on fixed cutouts."""

    config = load_disaggregation_config(config_path)
    grids = build_city_grid_specs(config_path)
    requested = set(city_ids or [grid.city_id for grid in grids])
    unknown = requested - {grid.city_id for grid in grids}
    if unknown:
        raise ValueError(f"Unknown requested cities: {sorted(unknown)}")

    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "overture_rasterization"
        / "v1_nonradiance_cutouts"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    summary_path = output_root / "summary.json"
    prior_by_city: dict[str, dict[str, Any]] = {}
    if summary_path.exists():
        prior = json.loads(summary_path.read_text(encoding="utf-8"))
        if prior.get("config_sha256") == disaggregation_config_sha256(config_path):
            prior_by_city = {
                record["city_id"]: record for record in prior.get("cities", [])
            }
    city_records = [
        record
        for city_id, record in prior_by_city.items()
        if city_id not in requested
    ]
    written: list[Path] = []
    for grid in grids:
        if grid.city_id not in requested:
            continue
        record, city_written = _run_city_sensitivity(
            config_path=Path(config_path),
            config=config,
            grid=grid,
            output_root=output_root,
        )
        city_records.append(record)
        written.extend(city_written)

    city_order = {
        city_id: index
        for index, city_id in enumerate(config["cities"]["selected_city_ids"])
    }
    city_records.sort(key=lambda record: city_order[record["city_id"]])
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at_utc": datetime.now(UTC).isoformat(),
                "experiment_id": config["experiment"]["id"],
                "contract_version": config["experiment"]["contract_version"],
                "config_sha256": disaggregation_config_sha256(config_path),
                "selection_uses_vnp_radiance": False,
                "cities": city_records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(summary_path)
    csv_path = output_root / "cutout_metrics.csv"
    _write_metrics_csv(csv_path, city_records)
    written.append(csv_path)
    index_path = output_root / "index.html"
    index_path.write_text(_index_html(city_records), encoding="utf-8")
    written.append(index_path)
    return written


def _run_city_sensitivity(
    *,
    config_path: Path,
    config: dict[str, Any],
    grid,
    output_root: Path,
) -> tuple[dict[str, Any], list[Path]]:
    input_config = config["outputs"]["day2_inputs"]
    input_root = resolve_project_path(input_config["root"]) / grid.city_id
    overture_path = input_root / input_config["overture_bundle_filename"]
    earth_engine_path = input_root / input_config["earth_engine_bundle_filename"]
    built_config = config["allocation_proxies"]["built_form"]
    rasterization = built_config["rasterization"]
    cutout_config = rasterization["cutout_sensitivity"]
    halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    halo_pixels = round(halo_m / grid.resolution_m)
    cutout_pixels = round(cutout_config["size_m"] / grid.resolution_m)
    if cutout_pixels * grid.resolution_m != cutout_config["size_m"]:
        raise ValueError("Overture cutout size must align to the target grid")
    if grid.height % cutout_pixels or grid.width % cutout_pixels:
        raise ValueError("Overture cutout blocks must divide the analysis square")

    selections = _select_city_cutouts(
        overture_path,
        earth_engine_path,
        analysis_shape=(grid.height, grid.width),
        halo_pixels=halo_pixels,
        block_pixels=cutout_pixels,
        minimum_infrastructure_fraction=float(
            cutout_config["sparse_minimum_infrastructure_fraction"]
        ),
    )
    full_shape = expanded_grid_shape(grid, halo_m=halo_m)
    full_transform = Affine(*expanded_grid_transform(grid, halo_m=halo_m))
    transformer = Transformer.from_crs(
        rasterization["source_crs"],
        grid.crs,
        always_xy=True,
    )
    source_root = resolve_project_path(built_config["overture_input_root"]) / grid.city_id
    fine_building_resolution = int(
        rasterization["building_fraction"]["cutout_sensitivity_resolution_m"]
    )
    fine_road_segment_length = float(
        rasterization["weighted_road_length"][
            "cutout_sensitivity_maximum_segment_length_m"
        ]
    )
    print(
        f"{grid.city_id}: building {fine_building_resolution} m sensitivity grid",
        flush=True,
    )
    fine_building, fine_building_metrics = _rasterize_building_fraction(
        source_root / "buildings.parquet",
        shape=full_shape,
        transform=full_transform,
        source_to_target=transformer,
        target_resolution_m=grid.resolution_m,
        subpixel_resolution_m=fine_building_resolution,
        progress_label=f"{grid.city_id}-fine",
    )
    print(
        f"{grid.city_id}: road ≤{fine_road_segment_length} m sensitivity grid",
        flush=True,
    )
    fine_road_length, fine_road_metrics = _rasterize_weighted_road_length(
        source_root / "segments.parquet",
        shape=full_shape,
        transform=full_transform,
        source_to_target=transformer,
        road_weights=built_config["road_class_weights"],
        unlisted_road_class_policy=built_config["unlisted_road_class_policy"],
        maximum_segment_length_m=fine_road_segment_length,
        conservation_relative_tolerance=float(
            rasterization["weighted_road_length"][
                "length_conservation_relative_tolerance"
            ]
        ),
        progress_label=f"{grid.city_id}-fine",
    )
    pixel_area_m2 = abs(
        full_transform.a * full_transform.e
        - full_transform.b * full_transform.d
    )
    fine_road_normalized = np.clip(
        fine_road_length.astype(np.float64)
        / pixel_area_m2
        * 1_000_000.0
        / float(built_config["road_density_saturation_m_per_km2"]),
        0,
        1,
    ).astype(np.float32)

    arrays: dict[str, np.ndarray] = {}
    cutout_records = []
    target_to_wgs84 = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    with rasterio.open(overture_path) as overture:
        band_lookup = {
            name: index
            for index, name in enumerate(overture.descriptions, start=1)
            if name
        }
        for selection in selections:
            row_start = halo_pixels + selection["block_row"] * cutout_pixels
            column_start = halo_pixels + selection["block_column"] * cutout_pixels
            window = Window(
                column_start,
                row_start,
                cutout_pixels,
                cutout_pixels,
            )
            primary_building = overture.read(
                band_lookup["building_fraction"],
                window=window,
            ).astype(np.float32)
            primary_road = overture.read(
                band_lookup["weighted_road_density_normalized"],
                window=window,
            ).astype(np.float32)
            row_stop = row_start + cutout_pixels
            column_stop = column_start + cutout_pixels
            sensitivity_building = fine_building[
                row_start:row_stop,
                column_start:column_stop,
            ]
            sensitivity_road = fine_road_normalized[
                row_start:row_stop,
                column_start:column_stop,
            ]
            role = selection["role"]
            arrays[f"{role}_building_primary_2m"] = primary_building
            arrays[f"{role}_building_sensitivity_1m"] = sensitivity_building
            arrays[f"{role}_road_primary_1m"] = primary_road
            arrays[f"{role}_road_sensitivity_0_5m"] = sensitivity_road

            cutout_transform = full_transform * Affine.translation(
                column_start,
                row_start,
            )
            center_x = (
                cutout_transform.c + cutout_transform.a * cutout_pixels / 2
            )
            center_y = (
                cutout_transform.f + cutout_transform.e * cutout_pixels / 2
            )
            center_lon, center_lat = target_to_wgs84.transform(center_x, center_y)
            cutout_records.append(
                {
                    **selection,
                    "pixel_window": {
                        "row_start": row_start,
                        "row_stop": row_stop,
                        "column_start": column_start,
                        "column_stop": column_stop,
                    },
                    "center": {
                        "longitude": center_lon,
                        "latitude": center_lat,
                    },
                    "building_comparison": _comparison_metrics(
                        primary_building,
                        sensitivity_building,
                        quantity_scale=pixel_area_m2,
                        quantity_name="sampled_building_area_m2",
                    ),
                    "road_comparison": _comparison_metrics(
                        primary_road,
                        sensitivity_road,
                        quantity_scale=None,
                        quantity_name=None,
                    ),
                }
            )

    arrays_path = output_root / f"{grid.city_id}_cutouts.npz"
    np.savez_compressed(arrays_path, **arrays)
    figure_path = output_root / f"{grid.city_id}_rasterization_sensitivity.png"
    _write_city_figure(
        figure_path,
        city_id=grid.city_id,
        cutouts=cutout_records,
        arrays=arrays,
    )
    del fine_building, fine_road_length, fine_road_normalized

    primary_manifest = json.loads(
        (input_root / "overture_structure_bundle.json").read_text(encoding="utf-8")
    )
    record = {
        "city_id": grid.city_id,
        "selection_method": cutout_config["selection_method"],
        "selection_uses_vnp_radiance": False,
        "cutout_size_m": cutout_config["size_m"],
        "primary_bundle_sha256": primary_manifest["output"]["sha256"],
        "primary_building_subpixel_resolution_m": rasterization[
            "building_fraction"
        ]["subpixel_resolution_m"],
        "sensitivity_building_subpixel_resolution_m": fine_building_resolution,
        "primary_road_maximum_segment_length_m": rasterization[
            "weighted_road_length"
        ]["maximum_segment_length_m"],
        "sensitivity_road_maximum_segment_length_m": fine_road_segment_length,
        "fine_building_full_extent_metrics": fine_building_metrics,
        "fine_road_full_extent_metrics": fine_road_metrics,
        "cutouts": cutout_records,
        "arrays_path": str(arrays_path),
        "figure_path": str(figure_path),
    }
    return record, [arrays_path, figure_path]


def _select_city_cutouts(
    overture_path: Path,
    earth_engine_path: Path,
    *,
    analysis_shape: tuple[int, int],
    halo_pixels: int,
    block_pixels: int,
    minimum_infrastructure_fraction: float,
) -> list[dict[str, Any]]:
    height, width = analysis_shape
    window = Window(halo_pixels, halo_pixels, width, height)
    with rasterio.open(overture_path) as overture:
        bands = {
            name: index
            for index, name in enumerate(overture.descriptions, start=1)
            if name
        }
        building = overture.read(bands["building_fraction"], window=window)
        infrastructure = overture.read(
            bands["mapped_infrastructure_mask"],
            window=window,
        )
    with rasterio.open(earth_engine_path) as earth_engine:
        bands = {
            name: index
            for index, name in enumerate(earth_engine.descriptions, start=1)
            if name
        }
        water = earth_engine.read(
            bands["persistent_water_occurrence_percent"],
            window=window,
        )
    building_mean = _aligned_block_mean(building, block_pixels)
    infrastructure_mean = _aligned_block_mean(infrastructure, block_pixels)
    water_mean = _aligned_block_mean(water, block_pixels)
    selected = _select_block_indices(
        building_mean,
        infrastructure_mean,
        water_mean,
        minimum_infrastructure_fraction=minimum_infrastructure_fraction,
    )
    records = []
    for role, (row, column) in selected.items():
        records.append(
            {
                "role": role,
                "block_row": int(row),
                "block_column": int(column),
                "selection_scores": {
                    "mean_building_fraction": float(building_mean[row, column]),
                    "mapped_infrastructure_fraction": float(
                        infrastructure_mean[row, column]
                    ),
                    "mean_jrc_water_occurrence_percent": float(
                        water_mean[row, column]
                    ),
                    "water_adjacent_infrastructure_score": float(
                        water_mean[row, column]
                        * infrastructure_mean[row, column]
                    ),
                },
            }
        )
    return records


def _aligned_block_mean(values: np.ndarray, block_pixels: int) -> np.ndarray:
    if values.shape[0] % block_pixels or values.shape[1] % block_pixels:
        raise ValueError("Array shape must divide evenly into aligned cutout blocks")
    return values.reshape(
        values.shape[0] // block_pixels,
        block_pixels,
        values.shape[1] // block_pixels,
        block_pixels,
    ).mean(axis=(1, 3))


def _select_block_indices(
    building_mean: np.ndarray,
    infrastructure_mean: np.ndarray,
    water_mean: np.ndarray,
    *,
    minimum_infrastructure_fraction: float,
) -> dict[str, tuple[int, int]]:
    if not (
        building_mean.shape == infrastructure_mean.shape == water_mean.shape
    ):
        raise ValueError("Cutout-selection surfaces must share one shape")
    dense_flat = int(np.nanargmax(building_mean))
    dense = np.unravel_index(dense_flat, building_mean.shape)

    eligible = (
        np.isfinite(building_mean)
        & np.isfinite(infrastructure_mean)
        & (infrastructure_mean >= minimum_infrastructure_fraction)
    )
    eligible[dense] = False
    if not eligible.any():
        raise ValueError("No eligible sparse-built cutout block")
    sparse_target = float(np.quantile(building_mean[eligible], 0.25))
    sparse_distance = np.where(
        eligible,
        np.abs(building_mean - sparse_target),
        np.inf,
    )
    sparse = np.unravel_index(int(np.argmin(sparse_distance)), building_mean.shape)

    waterfront_score = water_mean * infrastructure_mean
    waterfront_eligible = eligible.copy()
    waterfront_eligible[sparse] = False
    if not waterfront_eligible.any():
        raise ValueError("No eligible water-adjacent cutout block")
    waterfront = np.unravel_index(
        int(np.argmax(np.where(waterfront_eligible, waterfront_score, -np.inf))),
        building_mean.shape,
    )
    return {
        "dense_building": (int(dense[0]), int(dense[1])),
        "sparse_built": (int(sparse[0]), int(sparse[1])),
        "water_adjacent_infrastructure": (
            int(waterfront[0]),
            int(waterfront[1]),
        ),
    }


def _comparison_metrics(
    primary: np.ndarray,
    sensitivity: np.ndarray,
    *,
    quantity_scale: float | None,
    quantity_name: str | None,
) -> dict[str, Any]:
    x = np.asarray(primary, dtype=np.float64)
    y = np.asarray(sensitivity, dtype=np.float64)
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    difference = y - x
    correlation = (
        float(np.corrcoef(x, y)[0, 1])
        if x.size > 1 and np.std(x) > 0 and np.std(y) > 0
        else None
    )
    record: dict[str, Any] = {
        "pixel_count": int(x.size),
        "primary_mean": float(x.mean()),
        "sensitivity_mean": float(y.mean()),
        "sensitivity_minus_primary_mean": float(difference.mean()),
        "mean_absolute_difference": float(np.abs(difference).mean()),
        "maximum_absolute_difference": float(np.abs(difference).max()),
        "changed_pixel_fraction": float((np.abs(difference) > 1e-6).mean()),
        "pearson_correlation": correlation,
    }
    if quantity_scale is not None and quantity_name is not None:
        primary_quantity = float(x.sum() * quantity_scale)
        sensitivity_quantity = float(y.sum() * quantity_scale)
        record[f"primary_{quantity_name}"] = primary_quantity
        record[f"sensitivity_{quantity_name}"] = sensitivity_quantity
        record[f"{quantity_name}_relative_change"] = (
            (sensitivity_quantity - primary_quantity) / primary_quantity
            if primary_quantity
            else None
        )
    return record


def _write_city_figure(
    path: Path,
    *,
    city_id: str,
    cutouts: list[dict[str, Any]],
    arrays: dict[str, np.ndarray],
) -> None:
    figure, axes = plt.subplots(
        len(cutouts),
        6,
        figsize=(21, 3.8 * len(cutouts)),
        constrained_layout=True,
    )
    for row, cutout in enumerate(cutouts):
        role = cutout["role"]
        building_primary = arrays[f"{role}_building_primary_2m"]
        building_fine = arrays[f"{role}_building_sensitivity_1m"]
        road_primary = arrays[f"{role}_road_primary_1m"]
        road_fine = arrays[f"{role}_road_sensitivity_0_5m"]
        panels = (
            (building_primary, "Building · 2 m", "viridis", 0, 1),
            (building_fine, "Building · 1 m", "viridis", 0, 1),
            (
                building_fine - building_primary,
                "Building difference",
                "RdBu_r",
                None,
                None,
            ),
            (road_primary, "Road · ≤1 m", "magma", 0, 1),
            (road_fine, "Road · ≤0.5 m", "magma", 0, 1),
            (
                road_fine - road_primary,
                "Road difference",
                "RdBu_r",
                None,
                None,
            ),
        )
        for column, (values, title, cmap, vmin, vmax) in enumerate(panels):
            if vmin is None:
                limit = float(np.percentile(np.abs(values), 99))
                limit = max(limit, 1e-6)
                vmin, vmax = -limit, limit
            image = axes[row, column].imshow(
                values,
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
            )
            axes[row, column].set_title(title, fontsize=9)
            axes[row, column].set_xticks([])
            axes[row, column].set_yticks([])
            figure.colorbar(image, ax=axes[row, column], fraction=0.046, pad=0.02)
            if column == 0:
                axes[row, column].set_ylabel(role.replace("_", " "), fontsize=10)
    figure.suptitle(
        f"{city_id} · Overture rasterization cutout sensitivity\n"
        "cutouts selected without VNP radiance",
        fontsize=15,
        fontweight="bold",
    )
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _write_metrics_csv(path: Path, city_records: list[dict[str, Any]]) -> None:
    rows = []
    for city in city_records:
        for cutout in city["cutouts"]:
            row = {
                "city_id": city["city_id"],
                "role": cutout["role"],
                "center_longitude": cutout["center"]["longitude"],
                "center_latitude": cutout["center"]["latitude"],
            }
            for prefix in ("building", "road"):
                for key, value in cutout[f"{prefix}_comparison"].items():
                    row[f"{prefix}_{key}"] = value
            rows.append(row)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _index_html(city_records: list[dict[str, Any]]) -> str:
    cards = []
    for city in city_records:
        figure_name = Path(city["figure_path"]).name
        cards.append(
            "<figure>"
            f"<h2>{html.escape(city['city_id'])}</h2>"
            f"<img src=\"{html.escape(figure_name)}\">"
            "<figcaption>Primary versus finer rasterization on cutouts selected "
            "without VNP radiance.</figcaption>"
            "</figure>"
        )
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Overture rasterization sensitivity</title>
<style>
body { margin: 2rem; color: #202124; background: #f8f9fa; font: 15px system-ui; }
figure { margin: 0 0 1.5rem; padding: 1rem; background: white; border: 1px solid #dadce0; }
img { display: block; width: 100%; height: auto; }
</style>
</head>
<body>
<h1>Overture rasterization sensitivity</h1>
<p>Cutouts are aligned 1 km blocks selected from structural and JRC-water
inputs without consulting VNP radiance. Difference panels use symmetric
display-only stretches.</p>
""" + "\n".join(cards) + """
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run finer Overture rasterization checks on fixed cutouts."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    parser.add_argument(
        "--city",
        action="append",
        dest="city_ids",
        help="Run only this city ID; repeat to select multiple cities.",
    )
    args = parser.parse_args(argv)
    for path in run_overture_rasterization_sensitivity(
        args.config,
        city_ids=args.city_ids,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
