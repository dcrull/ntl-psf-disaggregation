"""Gate 2 shoreline factorial over frozen full-city allocation artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyarrow.parquet as pq
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import rasterize
from scipy import ndimage
from shapely import from_wkb
from shapely.ops import transform

from nocturne.disaggregate.config import disaggregation_config_sha256, load_disaggregation_config
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.disaggregate.validate import (
    matched_low_proxy_boundary_metrics,
    shoreline_distance_band_metrics,
    water_allocation_metrics,
)
from nocturne.preview.paths import resolve_project_path

SHORELINE_VERSION = "v1_overture_mapped_water"


def run_shoreline_factorial(config_path: str | Path) -> Path:
    """Evaluate saved strict circular-reference allocations against mapped water."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    raster_root = (
        resolve_project_path(config["outputs"]["rasters"]) / "full_city" / "v1_resumable_tiled"
    )
    source_manifest_path = raster_root / "artifact_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    config_hash = disaggregation_config_sha256(config_path)
    if source_manifest.get("complete") is not True or source_manifest["config_sha256"] != config_hash:
        raise ValueError("Full-city manifest is incomplete or belongs to another configuration")
    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "shoreline"
        / SHORELINE_VERSION
    )
    output_root.mkdir(parents=True, exist_ok=True)
    edges = tuple(config["validation"]["water_handling"]["shoreline_distance_edges_m"])
    grids = {grid.city_id: grid for grid in build_city_grid_specs(config_path)}
    summary_rows: list[dict[str, Any]] = []
    band_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    stratum_rows: list[dict[str, Any]] = []
    city_strata: dict[str, tuple[np.ndarray, dict[str, np.ndarray]]] = {}
    reference_sources: dict[str, dict[str, dict[str, str]]] = {}

    for city in source_manifest["cities"]:
        city_id = city["city_id"]
        grid = grids[city_id]
        records = _eligible_records(city["configurations"])
        water_path = (
            resolve_project_path(config["outputs"]["root"])
            / "inputs"
            / "gate2_water_reference"
            / city_id
            / "water_reference.tif"
        )
        reference_root = water_path.parent
        infrastructure_path = (
            reference_root / "overture_infrastructure_2026-07-22.0.parquet"
        )
        reference_sources[city_id] = {
            "water_reference": _file_record(water_path),
            "water_metadata": _file_record(reference_root / "metadata.json"),
            "overture_infrastructure": _file_record(infrastructure_path),
        }
        with rasterio.open(water_path) as dataset:
            water = dataset.read(1).astype(bool)
        distance = ndimage.distance_transform_edt(~water, sampling=grid.resolution_m)
        adjacent = (~water) & (distance > 0) & (distance <= edges[1])
        strata = _waterfront_strata(
            config,
            city_id=city_id,
            grid=grid,
            water=water,
            distance=distance,
        )
        city_strata[city_id] = (water, strata)
        direct = next(record for record in records if record["configuration"]["kind"] == "direct")
        direct_allocation = _read_allocation(Path(direct["path"]))
        baselines: dict[str, np.ndarray] = {}
        proxy_controls: dict[str, np.ndarray] = {}
        for proxy in ("built_form_primary", "s2_only_ablation"):
            baseline = next(
                record
                for record in records
                if record["configuration"].get("proxy") == proxy
                and record["configuration"].get("water_variant") == "no_water_prior"
            )
            baselines[proxy] = _read_allocation(Path(baseline["path"]))
            proxy_controls[proxy] = _matched_low_proxy_mask(
                config, city_id=city_id, proxy=proxy, water=water, distance=distance
            )

        for record in records:
            spec = record["configuration"]
            allocation = _read_allocation(Path(record["path"]))
            if spec["kind"] == "direct":
                reference = direct_allocation
                reference_name = spec["name"]
            elif spec["kind"] == "uniform":
                reference = direct_allocation
                reference_name = direct["configuration"]["name"]
            else:
                reference = baselines[spec["proxy"]]
                reference_name = f"{spec['proxy']}__no_water_prior"
            metrics = water_allocation_metrics(
                allocation,
                source_radiance=direct_allocation,
                water_reference_mask=water,
                adjacent_land_mask=adjacent,
                reference_allocation=reference,
            )
            summary_rows.append(
                {
                    "city_id": city_id,
                    "configuration": spec["name"],
                    "kind": spec["kind"],
                    "proxy": spec.get("proxy"),
                    "water_variant": spec.get("water_variant"),
                    "reference_configuration": reference_name,
                    **{key: value for key, value in metrics.items() if key != "interpretation"},
                    "operator_consistency_mae": record["metrics"].get(
                        "operator_consistency_mae"
                    ),
                    "insufficient_proxy_support_pixel_count": record["metrics"][
                        "insufficient_proxy_support_mask_pixel_count"
                    ],
                }
            )
            for side_name, side_mask in (("mapped_water", water), ("adjacent_land_0_100m", adjacent)):
                for stratum_name, stratum_mask in strata.items():
                    mask = (
                        side_mask
                        & stratum_mask
                        & np.isfinite(allocation)
                        & np.isfinite(reference)
                    )
                    stratum_rows.append(
                        _stratum_record(
                            city_id=city_id,
                            configuration=spec["name"],
                            proxy=spec.get("proxy"),
                            water_variant=spec.get("water_variant"),
                            reference_configuration=reference_name,
                            side=side_name,
                            stratum=stratum_name,
                            allocation=allocation,
                            reference=reference,
                            mask=mask,
                        )
                    )
            for band in shoreline_distance_band_metrics(
                allocation,
                reference_allocation=reference,
                water_reference_mask=water,
                resolution_m=grid.resolution_m,
                distance_edges_m=edges,
            ):
                band_rows.append(
                    {
                        "city_id": city_id,
                        "configuration": spec["name"],
                        "proxy": spec.get("proxy"),
                        "water_variant": spec.get("water_variant"),
                        "reference_configuration": reference_name,
                        **band,
                    }
                )
            if spec.get("proxy"):
                excluded = water | (distance <= edges[-1])
                for band in matched_low_proxy_boundary_metrics(
                    allocation,
                    reference_allocation=reference,
                    low_proxy_land_mask=proxy_controls[spec["proxy"]],
                    excluded_mask=excluded,
                    resolution_m=grid.resolution_m,
                    distance_edges_m=edges,
                ):
                    control_rows.append(
                        {
                            "city_id": city_id,
                            "configuration": spec["name"],
                            "proxy": spec["proxy"],
                            "water_variant": spec["water_variant"],
                            "reference_configuration": reference_name,
                            **band,
                        }
                    )
            del allocation

    paths = {
        "summary": output_root / "summary.csv",
        "shoreline_bands": output_root / "shoreline_bands.csv",
        "matched_inland_low_proxy_bands": output_root / "matched_inland_low_proxy_bands.csv",
        "waterfront_infrastructure_strata": output_root
        / "waterfront_infrastructure_strata.csv",
    }
    _write_csv(paths["summary"], summary_rows)
    _write_csv(paths["shoreline_bands"], band_rows)
    _write_csv(paths["matched_inland_low_proxy_bands"], control_rows)
    _write_csv(paths["waterfront_infrastructure_strata"], stratum_rows)
    figure_path = output_root / "water_allocation_share.png"
    _plot_water_share(summary_rows, figure_path)
    strata_figure_path = output_root / "waterfront_infrastructure_strata.png"
    _plot_strata(city_strata, strata_figure_path)
    difference_figure_paths = _plot_difference_maps(
        source_manifest,
        city_strata,
        output_root=output_root,
    )
    artifacts = {name: _file_record(path) for name, path in paths.items()}
    artifacts["water_allocation_share_figure"] = _file_record(figure_path)
    artifacts["waterfront_infrastructure_strata_figure"] = _file_record(
        strata_figure_path
    )
    for city_id, path in difference_figure_paths.items():
        artifacts[f"{city_id}_water_variant_difference_maps"] = _file_record(path)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifact_version": SHORELINE_VERSION,
        "config_sha256": config_hash,
        "source_manifest": _file_record(source_manifest_path),
        "reference_sources": reference_sources,
        "water_reference_contract": (
            "pinned Overture mapped areal water; independent of JRC, OSM-derived, "
            "not an exhaustive optical classification"
        ),
        "comparison_contract": (
            "stationary variants compare with the matching proxy no-water result; "
            "uniform compares with direct; direct is self-referenced"
        ),
        "matched_control_contract": (
            "lowest proxy-valued inland pixels more than 1500 m from mapped water; "
            "target area equals mapped-water area but is capped at 10% of eligible "
            "inland support so surrounding boundary bands remain measurable"
        ),
        "waterfront_strata_contract": (
            "mutually exclusive priority: mapped pier/quay, mapped bridge, mapped "
            "building, mapped road, ordinary shoreline; reported separately over "
            "mapped water and adjacent land within 100 m"
        ),
        "artifacts": artifacts,
        "prohibition": "lower allocated-water share alone does not select a winner",
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _eligible_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record["configuration"]["radiance_contract"] == "strict"
        and (
            record["configuration"]["kind"] in {"direct", "uniform"}
            or record["configuration"].get("kernel_name") == "circular_mean_reference"
        )
    ]


def _matched_low_proxy_mask(
    config: dict[str, Any],
    *,
    city_id: str,
    proxy: str,
    water: np.ndarray,
    distance: np.ndarray,
) -> np.ndarray:
    inputs = resolve_project_path(config["outputs"]["rasters"]) / "day2_inputs" / city_id
    if proxy == "built_form_primary":
        path, band = inputs / "overture_structure_bundle.tif", 3
    else:
        path, band = inputs / "ee_source_bundle.tif", 18
    with rasterio.open(path) as dataset:
        # Both registered input bundles have a 100-pixel source halo.
        proxy_values = dataset.read(band, window=((100, 5100), (100, 5100)))
    eligible = (~water) & (distance > 1500) & np.isfinite(proxy_values)
    count = min(int(water.sum()), max(1, int(eligible.sum()) // 10))
    values = proxy_values[eligible]
    threshold = np.partition(values, count - 1)[count - 1]
    control = eligible & (proxy_values <= threshold)
    if int(control.sum()) > count:
        indices = np.flatnonzero(control)
        control.flat[indices[count:]] = False
    return control


def _read_allocation(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return dataset.read(1)


def _waterfront_strata(
    config: dict[str, Any],
    *,
    city_id: str,
    grid: Any,
    water: np.ndarray,
    distance: np.ndarray,
) -> dict[str, np.ndarray]:
    inputs = resolve_project_path(config["outputs"]["rasters"]) / "day2_inputs" / city_id
    with rasterio.open(inputs / "overture_structure_bundle.tif") as dataset:
        building = dataset.read(1, window=((100, 5100), (100, 5100))) > 0
        road = dataset.read(2, window=((100, 5100), (100, 5100))) > 0
    infrastructure_path = (
        resolve_project_path(config["outputs"]["root"])
        / "inputs"
        / "gate2_water_reference"
        / city_id
        / "overture_infrastructure_2026-07-22.0.parquet"
    )
    table = pq.read_table(
        infrastructure_path, columns=["class", "subtype", "geometry"]
    )
    transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    geometries = from_wkb(table["geometry"].to_numpy())
    classes = table["class"].to_pylist()
    subtypes = table["subtype"].to_pylist()

    def feature_mask(labels: set[str]) -> np.ndarray:
        selected = (
            transform(transformer.transform, geometry)
            for geometry, water_class, subtype in zip(
                geometries, classes, subtypes, strict=True
            )
            if water_class in labels or subtype in labels
        )
        return rasterize(
            ((geometry, 1) for geometry in selected),
            out_shape=water.shape,
            transform=rasterio.Affine(*grid.transform),
            fill=0,
            dtype="uint8",
            all_touched=True,
        ).astype(bool)

    pier = feature_mask({"pier", "quay"})
    bridge = feature_mask({"bridge"})
    zone = water | ((~water) & (distance > 0) & (distance <= 100))
    strata = {
        "mapped_pier_or_quay": zone & pier,
        "mapped_bridge": zone & bridge & ~pier,
        "mapped_building": zone & building & ~pier & ~bridge,
        "mapped_road": zone & road & ~pier & ~bridge & ~building,
    }
    occupied = np.logical_or.reduce(tuple(strata.values()))
    strata["ordinary_shoreline"] = zone & ~occupied
    return strata


def _stratum_record(
    *,
    city_id: str,
    configuration: str,
    proxy: str | None,
    water_variant: str | None,
    reference_configuration: str,
    side: str,
    stratum: str,
    allocation: np.ndarray,
    reference: np.ndarray,
    mask: np.ndarray,
) -> dict[str, Any]:
    current = allocation[mask].astype(np.float64)
    baseline = reference[mask].astype(np.float64)
    difference = current - baseline
    return {
        "city_id": city_id,
        "configuration": configuration,
        "proxy": proxy,
        "water_variant": water_variant,
        "reference_configuration": reference_configuration,
        "side": side,
        "stratum": stratum,
        "comparison_pixel_count": int(difference.size),
        "allocation_sum": float(current.sum()) if difference.size else None,
        "allocation_mean": float(current.mean()) if difference.size else None,
        "reference_allocation_sum": float(baseline.sum()) if difference.size else None,
        "difference_sum": float(difference.sum()) if difference.size else None,
        "difference_mean": float(difference.mean()) if difference.size else None,
        "difference_mean_absolute": (
            float(np.abs(difference).mean()) if difference.size else None
        ),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot_water_share(rows: list[dict[str, Any]], path: Path) -> None:
    variants = [
        row
        for row in rows
        if row["kind"] == "stationary"
        and row["water_variant"] != "no_water_prior"
    ]
    cities = sorted({row["city_id"] for row in variants})
    figure, axes = plt.subplots(1, len(cities), figsize=(12, 5), squeeze=False)
    for index, city_id in enumerate(cities):
        selected = [row for row in variants if row["city_id"] == city_id]
        labels = [
            f"{row['proxy'].replace('_', ' ')}\n{row['water_variant'].replace('_', ' ')}"
            for row in selected
        ]
        axes[0, index].barh(
            labels, [row["allocated_radiance_over_water_share"] for row in selected]
        )
        axes[0, index].set_title(city_id)
        axes[0, index].set_xlabel("allocated-radiance share over mapped water")
        axes[0, index].grid(axis="x", alpha=0.25)
    figure.suptitle("Gate 2 mapped-water diagnostic (not a selection metric)")
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_strata(
    city_strata: dict[str, tuple[np.ndarray, dict[str, np.ndarray]]],
    path: Path,
) -> None:
    names = [
        "ordinary_shoreline",
        "mapped_road",
        "mapped_building",
        "mapped_bridge",
        "mapped_pier_or_quay",
    ]
    colors = ["#d9d9d9", "#fdae61", "#d7191c", "#2c7bb6", "#542788"]
    figure, axes = plt.subplots(1, len(city_strata), figsize=(12, 6), squeeze=False)
    for column, (city_id, (water, strata)) in enumerate(city_strata.items()):
        labels = np.zeros(water.shape, dtype=np.uint8)
        for value, name in enumerate(names, start=1):
            labels[strata[name]] = value
        factor = 5
        reduced = labels.reshape(
            labels.shape[0] // factor,
            factor,
            labels.shape[1] // factor,
            factor,
        ).max(axis=(1, 3))
        masked = np.ma.masked_equal(reduced, 0)
        cmap = matplotlib.colors.ListedColormap(colors)
        norm = matplotlib.colors.BoundaryNorm(np.arange(0.5, 6.5), cmap.N)
        axes[0, column].imshow(masked, cmap=cmap, norm=norm, interpolation="nearest")
        axes[0, column].set_title(city_id)
        axes[0, column].set_axis_off()
    handles = [
        plt.Line2D([0], [0], marker="s", linestyle="", color=color, label=name.replace("_", " "))
        for name, color in zip(names, colors, strict=True)
    ]
    figure.legend(handles=handles, loc="lower center", ncol=3)
    figure.suptitle("Mapped waterfront infrastructure strata (water and 0–100 m land)")
    figure.tight_layout(rect=(0, 0.08, 1, 0.95))
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_difference_maps(
    source_manifest: dict[str, Any],
    city_strata: dict[str, tuple[np.ndarray, dict[str, np.ndarray]]],
    *,
    output_root: Path,
) -> dict[str, Path]:
    outputs = {}
    for city in source_manifest["cities"]:
        city_id = city["city_id"]
        records = _eligible_records(city["configurations"])
        variants = [
            "persistent_only_soft",
            "spectral_only_soft",
            "combined_soft",
            "combined_hard_persistent_sensitivity_only",
            "soft_with_mapped_infrastructure_override",
        ]
        panels: list[tuple[str, str, np.ndarray]] = []
        for proxy in ("built_form_primary", "s2_only_ablation"):
            baseline_record = next(
                record
                for record in records
                if record["configuration"].get("proxy") == proxy
                and record["configuration"].get("water_variant") == "no_water_prior"
            )
            baseline = _read_reduced(Path(baseline_record["path"]))
            for variant in variants:
                record = next(
                    record
                    for record in records
                    if record["configuration"].get("proxy") == proxy
                    and record["configuration"].get("water_variant") == variant
                )
                panels.append(
                    (proxy, variant, _read_reduced(Path(record["path"])) - baseline)
                )
        finite = np.concatenate(
            [np.abs(values[np.isfinite(values)]) for _, _, values in panels]
        )
        limit = float(np.quantile(finite, 0.99)) if finite.size else 1.0
        limit = max(limit, np.finfo(np.float32).eps)
        water = city_strata[city_id][0]
        factor = 5
        water_reduced = water.reshape(
            water.shape[0] // factor,
            factor,
            water.shape[1] // factor,
            factor,
        ).max(axis=(1, 3))
        figure, axes = plt.subplots(
            2, 5, figsize=(18, 9), squeeze=False, constrained_layout=True
        )
        image = None
        for index, (proxy, variant, values) in enumerate(panels):
            row, column = divmod(index, 5)
            image = axes[row, column].imshow(
                values,
                cmap="RdBu_r",
                vmin=-limit,
                vmax=limit,
                interpolation="nearest",
            )
            axes[row, column].contour(
                water_reduced, levels=[0.5], colors="black", linewidths=0.25
            )
            axes[row, column].set_title(variant.replace("_", " "), fontsize=9)
            axes[row, column].set_axis_off()
            if column == 0:
                axes[row, column].text(
                    -0.05,
                    0.5,
                    proxy.replace("_", " "),
                    transform=axes[row, column].transAxes,
                    rotation=90,
                    va="center",
                    ha="right",
                    fontsize=10,
                )
        assert image is not None
        figure.colorbar(
            image,
            ax=axes.ravel().tolist(),
            label="allocation difference versus matching no-water prior",
            shrink=0.75,
            orientation="horizontal",
            pad=0.02,
        )
        figure.suptitle(
            f"{city_id}: water-variant allocation differences (black = mapped-water edge)"
        )
        path = output_root / f"{city_id}_water_variant_difference_maps.png"
        figure.savefig(path, dpi=180)
        plt.close(figure)
        outputs[city_id] = path
    return outputs


def _read_reduced(path: Path, size: int = 1000) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return dataset.read(
            1,
            out_shape=(size, size),
            resampling=Resampling.average,
        )


def _file_record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    print(run_shoreline_factorial(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
