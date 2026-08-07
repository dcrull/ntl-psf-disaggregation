"""Build and compare 2024 OSM and contemporary Overture structural proxies."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import rasterio
from affine import Affine
from pyproj import Transformer

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.export import sha256_file
from nocturne.disaggregate.grids import (
    build_city_grid_specs,
    expanded_grid_shape,
    expanded_grid_transform,
)
from nocturne.disaggregate.overture_bundle import (
    _rasterize_building_fraction,
    _rasterize_weighted_road_length,
    _write_multiband_cog_atomic,
)
from nocturne.preview.paths import resolve_project_path


def build_and_compare_historical_proxies(
    config_path: str | Path,
    *,
    city_ids: list[str] | None = None,
) -> list[Path]:
    """Rasterize historical OSM using the locked formula and compare inputs."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    grids = build_city_grid_specs(config_path)
    requested = set(city_ids or config["cities"]["selected_city_ids"])
    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "structural_vintage"
        / "v1_osm_2024"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    written: list[Path] = []
    for grid in grids:
        if grid.city_id not in requested:
            continue
        historical_path, exclusions = _build_historical_bundle(
            config, grid, output_root=output_root
        )
        current_path = (
            resolve_project_path(config["outputs"]["day2_inputs"]["root"])
            / grid.city_id
            / config["outputs"]["day2_inputs"]["overture_bundle_filename"]
        )
        city_rows, figure_path = _compare_city(
            grid.city_id,
            current_path=current_path,
            historical_path=historical_path,
            output_root=output_root,
        )
        for row in city_rows:
            row["excluded_historical_osm_road_features"] = exclusions
        rows.extend(city_rows)
        written.extend([historical_path, figure_path])

    csv_path = output_root / "proxy_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at_utc": datetime.now(UTC).isoformat(),
                "comparison": (
                    "2024-03-01 OSM database snapshot versus 2026-07-22 "
                    "Overture structural inputs, rasterized with the same formula"
                ),
                "interpretation_limit": (
                    "This is a combined vintage/source-coverage sensitivity, "
                    "not a clean temporal-only experiment."
                ),
                "historical_bundle_sha256": {
                    path.parent.name: sha256_file(path)
                    for path in written
                    if path.name == "osm_2024_structure_bundle.tif"
                },
                "comparison_csv": str(csv_path),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return [*written, csv_path, manifest_path]


def _build_historical_bundle(config, grid, *, output_root: Path) -> tuple[Path, int]:
    built = config["allocation_proxies"]["built_form"]
    source_root = (
        resolve_project_path(config["outputs"]["root"])
        / "inputs"
        / "osm_2024_snapshot"
        / grid.city_id
    )
    buildings_path = source_root / "buildings.parquet"
    segments_path = source_root / "segments.parquet"
    if not buildings_path.exists() or not segments_path.exists():
        raise FileNotFoundError(f"Historical extraction incomplete for {grid.city_id}")

    allowed = set(built["road_class_weights"])
    road_table = pq.read_table(segments_path)
    retained = road_table.filter(pc.is_in(road_table["class"], value_set=pa.array(sorted(allowed))))
    exclusions = road_table.num_rows - retained.num_rows
    filtered_path = source_root / "segments_formula_eligible.parquet"
    pq.write_table(retained, filtered_path, compression="zstd")

    halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    shape = expanded_grid_shape(grid, halo_m=halo_m)
    transform = Affine(*expanded_grid_transform(grid, halo_m=halo_m))
    transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    rasterization = built["rasterization"]
    building, building_metrics = _rasterize_building_fraction(
        buildings_path,
        shape=shape,
        transform=transform,
        source_to_target=transformer,
        target_resolution_m=grid.resolution_m,
        subpixel_resolution_m=int(
            rasterization["building_fraction"]["subpixel_resolution_m"]
        ),
        progress_label=f"{grid.city_id} historical OSM",
    )
    road_length, road_metrics = _rasterize_weighted_road_length(
        filtered_path,
        shape=shape,
        transform=transform,
        source_to_target=transformer,
        road_weights=built["road_class_weights"],
        unlisted_road_class_policy="error",
        maximum_segment_length_m=float(
            rasterization["weighted_road_length"]["maximum_segment_length_m"]
        ),
        conservation_relative_tolerance=float(
            rasterization["weighted_road_length"][
                "length_conservation_relative_tolerance"
            ]
        ),
        progress_label=f"{grid.city_id} historical OSM",
    )
    density = np.clip(
        road_length.astype(np.float64)
        / (grid.resolution_m**2)
        * 1_000_000
        / float(built["road_density_saturation_m_per_km2"]),
        0,
        1,
    ).astype(np.float32)
    proxy = (
        float(built["building_weight"]) * np.sqrt(building)
        + float(built["road_weight"]) * density
    ).astype(np.float32)
    mapped = ((building > 0) | (road_length > 0)).astype(np.float32)

    city_root = output_root / grid.city_id
    city_root.mkdir(parents=True, exist_ok=True)
    output_path = city_root / "osm_2024_structure_bundle.tif"
    _write_multiband_cog_atomic(
        output_path,
        layers=(building, density, proxy, mapped),
        band_names=config["outputs"]["day2_inputs"]["overture_bands"],
        crs=grid.crs,
        transform=transform,
        overview_resampling=rasterization["output_overview_resampling"],
        tags={
            "source": "OpenStreetMap history via Overpass attic data",
            "snapshot_time_utc": "2024-03-01T00:00:00Z",
            "formula": "same weights/transforms as contemporary primary proxy",
            "excluded_unlisted_road_features": exclusions,
        },
    )
    (city_root / "osm_2024_structure_bundle.json").write_text(
        json.dumps(
            {
                "building_metrics": building_metrics,
                "road_metrics": road_metrics,
                "excluded_unlisted_road_features": exclusions,
                "output_sha256": sha256_file(output_path),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path, exclusions


def _compare_city(
    city_id: str, *, current_path: Path, historical_path: Path, output_root: Path
) -> tuple[list[dict[str, Any]], Path]:
    with rasterio.open(current_path) as current, rasterio.open(historical_path) as old:
        if current.shape != old.shape or current.transform != old.transform:
            raise ValueError(f"Proxy grids differ for {city_id}")
        trim = (current.width - 5000) // 2
        window = rasterio.windows.Window(trim, trim, 5000, 5000)
        current_data = current.read(window=window).astype(np.float64)
        old_data = old.read(window=window).astype(np.float64)
        names = list(current.descriptions)

    rows = []
    for index, name in enumerate(names):
        a = current_data[index].ravel()
        b = old_data[index].ravel()
        rows.append(
            {
                "city_id": city_id,
                "layer": name,
                "current_sum": float(a.sum()),
                "historical_sum": float(b.sum()),
                "historical_to_current_sum_ratio": float(b.sum() / a.sum())
                if a.sum()
                else float("nan"),
                "mean_absolute_difference": float(np.mean(np.abs(b - a))),
                "root_mean_squared_difference": float(np.sqrt(np.mean((b - a) ** 2))),
                "pearson_correlation": float(np.corrcoef(a, b)[0, 1]),
                "current_nonzero_fraction": float(np.mean(a > 0)),
                "historical_nonzero_fraction": float(np.mean(b > 0)),
            }
        )

    figure, axes = plt.subplots(3, 3, figsize=(13, 12), constrained_layout=True)
    for row, index in enumerate((0, 2)):
        vmax = float(np.quantile(np.concatenate([current_data[index].ravel(), old_data[index].ravel()]), 0.995))
        axes[row, 0].imshow(current_data[index], vmin=0, vmax=vmax, cmap="viridis")
        axes[row, 1].imshow(old_data[index], vmin=0, vmax=vmax, cmap="viridis")
        limit = float(np.quantile(np.abs(old_data[index] - current_data[index]), 0.995))
        axes[row, 2].imshow(
            old_data[index] - current_data[index],
            vmin=-limit,
            vmax=limit,
            cmap="RdBu_r",
        )
        axes[row, 0].set_ylabel(names[index].replace("_", " "))
    sample = slice(None, None, 100)
    axes[2, 0].hexbin(
        current_data[2].ravel()[sample],
        old_data[2].ravel()[sample],
        gridsize=80,
        bins="log",
        mincnt=1,
    )
    axes[2, 0].set(xlabel="current proxy", ylabel="2024 OSM proxy")
    difference = old_data[2] - current_data[2]
    axes[2, 1].hist(difference.ravel()[sample], bins=100)
    axes[2, 1].set(xlabel="2024 OSM − current proxy", ylabel="sampled pixels")
    axes[2, 2].axis("off")
    for axis, title in zip(axes[0], ("Current Overture", "2024 OSM", "Difference")):
        axis.set_title(title)
    for axis in axes[:2].ravel():
        axis.set_xticks([])
        axis.set_yticks([])
    figure.suptitle(f"{city_id}: structural source/vintage sensitivity")
    figure_path = output_root / city_id / "proxy_comparison.png"
    figure.savefig(figure_path, dpi=160)
    plt.close(figure)
    return rows, figure_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--city", action="append", dest="city_ids")
    args = parser.parse_args()
    for output in build_and_compare_historical_proxies(
        args.config, city_ids=args.city_ids
    ):
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
