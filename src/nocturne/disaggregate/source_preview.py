"""Render readable, display-only previews of multiband Day 2 source bundles."""

from __future__ import annotations

import argparse
import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.grids import (
    build_city_grid_specs,
    expanded_grid_shape,
    expanded_grid_transform,
)
from nocturne.preview.paths import resolve_project_path

DISPLAY_LAYERS = (
    ("vnp_median_corrected_radiance", "VIIRS radiance · log1p", "magma", "log"),
    ("vnp_valid_observation_count", "VIIRS valid observations", "viridis", "linear"),
    (
        "s2_base_proxy_unwatered_unfloored",
        "S2 structural base proxy",
        "inferno",
        "linear",
    ),
    (
        "s2_spectral_water_weight",
        "S2 spectral-water weight",
        "Blues_r",
        "linear",
    ),
    (
        "s2_common_valid_observation_count",
        "S2 common-valid observations",
        "viridis",
        "linear",
    ),
    (
        "s2_sufficient_observation_support",
        "S2 sufficient support",
        "gray",
        "binary",
    ),
    (
        "persistent_water_occurrence_percent",
        "JRC water occurrence (%)",
        "Blues",
        "linear",
    ),
    ("persistent_water_weight", "Persistent-water weight", "Blues_r", "linear"),
    ("persistent_water_mask", "Persistent-water mask", "gray_r", "binary"),
)
VNP_COVERAGE_LAYERS = (
    ("vnp_median_corrected_radiance", "Strict corrected median · log1p", "magma", "log"),
    ("vnp_source_observation_count", "Native corrected source count", "viridis", "linear"),
    ("vnp_valid_observation_count", "Strict retained count", "viridis", "linear"),
    ("vnp_quality_retained_fraction", "Strict retained fraction", "viridis", "linear"),
    (
        "vnp_broad_median_corrected_radiance",
        "Broad corrected median · log1p",
        "magma",
        "log",
    ),
    ("vnp_broad_valid_observation_count", "Broad retained count", "viridis", "linear"),
    (
        "vnp_gap_filled_recent7d_median_radiance",
        "Gap-filled ≤7 d · log1p",
        "magma",
        "log",
    ),
    ("vnp_gap_filled_recent7d_day_count", "Gap-filled ≤7 d day count", "viridis", "linear"),
    (
        "vnp_gap_filled_recent30d_median_radiance",
        "Gap-filled ≤30 d · log1p",
        "magma",
        "log",
    ),
    (
        "vnp_gap_filled_recent30d_day_count",
        "Gap-filled ≤30 d day count",
        "viridis",
        "linear",
    ),
    (
        "vnp_gap_filled_recent90d_median_radiance",
        "Gap-filled ≤90 d · log1p",
        "magma",
        "log",
    ),
    (
        "vnp_gap_filled_recent90d_day_count",
        "Gap-filled ≤90 d day count",
        "viridis",
        "linear",
    ),
    (
        "vnp_fresh_high_quality_retrieval_count",
        "Fresh high-quality retrieval count",
        "viridis",
        "linear",
    ),
    (
        "vnp_latest_high_quality_retrieval_days_median",
        "Median retrieval age (days)",
        "plasma",
        "linear",
    ),
    (
        "vnp_latest_high_quality_retrieval_days_p90",
        "P90 retrieval age (days)",
        "plasma",
        "linear",
    ),
    (
        "persistent_water_occurrence_percent",
        "Independent JRC water occurrence (%)",
        "Blues",
        "linear",
    ),
)
OVERTURE_STRUCTURE_LAYERS = (
    ("building_fraction", "Overture building coverage fraction", "viridis", "linear"),
    (
        "weighted_road_density_normalized",
        "Weighted road density · normalized",
        "magma",
        "linear",
    ),
    (
        "built_form_base_proxy_unwatered_unfloored",
        "Built-form base · unwatered/unfloored",
        "inferno",
        "linear",
    ),
    (
        "mapped_infrastructure_mask",
        "Mapped building or road support",
        "gray_r",
        "binary",
    ),
)


def write_day2_source_previews(
    config_path: str | Path,
    *,
    input_root: str | Path = "drafts",
) -> list[Path]:
    """Write a nine-panel PNG per city and a small local inspection page."""

    config = load_disaggregation_config(config_path)
    source_root = resolve_project_path(input_root)
    output_root = resolve_project_path(config["outputs"]["previews"]) / "day2_sources"
    output_root.mkdir(parents=True, exist_ok=True)
    input_config = config["outputs"]["day2_inputs"]
    audited_input_root = resolve_project_path(input_config["root"])
    halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    records = []
    written: list[Path] = []

    for grid in build_city_grid_specs(config_path):
        source_path = _source_bundle_path(
            source_root,
            city_id=grid.city_id,
            artifact_version=input_config["artifact_version"],
        )
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        figure_path = output_root / f"{grid.city_id}_ee_source_bundle.png"
        record = _write_city_figure(
            source_path,
            output_path=figure_path,
            expected_shape=expanded_grid_shape(grid, halo_m=halo_m),
            expected_transform=expanded_grid_transform(grid, halo_m=halo_m),
            expected_crs=grid.crs,
            expected_bands=input_config["earth_engine_bands"],
        )
        record["vnp_qa_comparison"] = _summarize_vnp_qa_comparison(
            source_path,
            analysis_shape=(grid.height, grid.width),
        )
        record["city_id"] = grid.city_id
        vnp_figure_path = output_root / f"{grid.city_id}_vnp_coverage.png"
        _write_layer_grid(
            source_path,
            output_path=vnp_figure_path,
            layers=VNP_COVERAGE_LAYERS,
            columns=4,
            title=(
                f"{grid.city_id} · VNP coverage and gap-filled sensitivities\n"
                "display-only overview stretches"
            ),
        )
        record["vnp_coverage_preview_path"] = str(vnp_figure_path)
        overture_path = (
            audited_input_root
            / grid.city_id
            / input_config["overture_bundle_filename"]
        )
        if not overture_path.exists():
            raise FileNotFoundError(overture_path)
        overture_figure_path = output_root / f"{grid.city_id}_overture_structure.png"
        _write_layer_grid(
            overture_path,
            output_path=overture_figure_path,
            layers=OVERTURE_STRUCTURE_LAYERS,
            columns=2,
            title=(
                f"{grid.city_id} · Overture structure bundle\n"
                "display-only overview stretches"
            ),
        )
        record["overture_source_path"] = str(overture_path)
        record["overture_preview_path"] = str(overture_figure_path)
        records.append(record)
        written.extend([figure_path, vnp_figure_path, overture_figure_path])

    summary_path = output_root / "source_bundle_inspection.json"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at_utc": datetime.now(UTC).isoformat(),
                "display_contract": (
                    "overview resampling and percentile stretches are for visual "
                    "inspection only; source rasters are not modified"
                ),
                "sources": records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(summary_path)

    index_path = output_root / "index.html"
    index_path.write_text(_index_html(records), encoding="utf-8")
    written.append(index_path)
    return written


def _write_city_figure(
    source_path: Path,
    *,
    output_path: Path,
    expected_shape: tuple[int, int],
    expected_transform: tuple[float, float, float, float, float, float],
    expected_crs: str,
    expected_bands: list[str],
) -> dict[str, Any]:
    with rasterio.open(source_path) as dataset:
        if list(dataset.descriptions) != expected_bands:
            raise ValueError(
                f"{source_path} band order differs from the export contract"
            )
        band_lookup = {
            description: index
            for index, description in enumerate(dataset.descriptions, start=1)
            if description
        }
        missing = [name for name, *_ in DISPLAY_LAYERS if name not in band_lookup]
        if missing:
            raise ValueError(f"{source_path} lacks display bands: {missing}")
        scale = min(1.0, 1100.0 / max(dataset.height, dataset.width))
        display_shape = (
            max(1, round(dataset.height * scale)),
            max(1, round(dataset.width * scale)),
        )
        figure, axes = plt.subplots(3, 3, figsize=(15, 14), constrained_layout=True)
        band_summaries = []
        for axis, (name, title, cmap, display_mode) in zip(
            axes.flat,
            DISPLAY_LAYERS,
            strict=True,
        ):
            categorical = display_mode == "binary"
            values = dataset.read(
                band_lookup[name],
                out_shape=display_shape,
                masked=True,
                resampling=Resampling.nearest if categorical else Resampling.average,
            ).astype(np.float64)
            array = values.filled(np.nan)
            finite = array[np.isfinite(array)]
            if display_mode == "log":
                shown = np.log1p(np.maximum(array, 0))
                finite_shown = shown[np.isfinite(shown)]
                vmin, vmax = _percentile_limits(finite_shown)
            elif display_mode == "binary":
                shown = array
                vmin, vmax = 0.0, 1.0
            else:
                shown = array
                vmin, vmax = _percentile_limits(finite)
            image = axis.imshow(shown, cmap=cmap, vmin=vmin, vmax=vmax)
            axis.set_title(title, fontsize=10)
            axis.set_xticks([])
            axis.set_yticks([])
            figure.colorbar(image, ax=axis, fraction=0.046, pad=0.02)
            band_summaries.append(
                {
                    "band": name,
                    "valid_overview_pixels": int(finite.size),
                    "minimum": float(np.min(finite)) if finite.size else None,
                    "median": float(np.median(finite)) if finite.size else None,
                    "maximum": float(np.max(finite)) if finite.size else None,
                    "display_mode": display_mode,
                }
            )

        actual_shape = (dataset.height, dataset.width)
        actual_transform = tuple(dataset.transform)[:6]
        shape_valid = actual_shape == expected_shape
        transform_valid = np.allclose(actual_transform, expected_transform, atol=1e-9)
        crs_valid = dataset.crs is not None and dataset.crs.to_string() == expected_crs
        status = "GRID CONTRACT PASS" if all(
            [shape_valid, transform_valid, crs_valid]
        ) else "GRID CONTRACT FAIL — DO NOT RUN OPERATOR"
        figure.suptitle(
            f"{source_path.stem}\n{status} · display-only overview stretches",
            fontsize=15,
            fontweight="bold",
        )
        figure.savefig(output_path, dpi=160)
        plt.close(figure)
        return {
            "source_path": str(source_path),
            "preview_path": str(output_path),
            "actual_shape": list(actual_shape),
            "expected_shape": list(expected_shape),
            "shape_valid": shape_valid,
            "actual_transform": list(actual_transform),
            "expected_transform": list(expected_transform),
            "transform_valid": bool(transform_valid),
            "actual_crs": dataset.crs.to_string() if dataset.crs else None,
            "expected_crs": expected_crs,
            "crs_valid": crs_valid,
            "nodata": dataset.nodata,
            "cog_layout": dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT"),
            "band_descriptions": list(dataset.descriptions),
            "grid_contract_valid": all([shape_valid, transform_valid, crs_valid]),
            "bands": band_summaries,
        }


def _summarize_vnp_qa_comparison(
    source_path: Path,
    *,
    analysis_shape: tuple[int, int],
) -> dict[str, Any]:
    """Compare strict and broad QA on the core square without loading it at once."""

    required_bands = (
        "vnp_median_corrected_radiance",
        "vnp_source_observation_count",
        "vnp_valid_observation_count",
        "vnp_broad_median_corrected_radiance",
        "vnp_broad_valid_observation_count",
        "persistent_water_occurrence_percent",
        "persistent_water_mask",
    )
    with rasterio.open(source_path) as dataset:
        band_lookup = {
            description: index
            for index, description in enumerate(dataset.descriptions, start=1)
            if description
        }
        missing = [name for name in required_bands if name not in band_lookup]
        if missing:
            raise ValueError(f"{source_path} lacks VNP QA comparison bands: {missing}")

        analysis_height, analysis_width = analysis_shape
        extra_rows = dataset.height - analysis_height
        extra_columns = dataset.width - analysis_width
        if extra_rows < 0 or extra_columns < 0 or extra_rows % 2 or extra_columns % 2:
            raise ValueError(
                f"{source_path} cannot be symmetrically cropped to {analysis_shape}"
            )
        core_row_start = extra_rows // 2
        core_column_start = extra_columns // 2
        core_row_stop = core_row_start + analysis_height
        core_column_stop = core_column_start + analysis_width

        pixel_count = 0
        strict_count = 0
        broad_count = 0
        common_count = 0
        broad_only_count = 0
        strict_sum = 0.0
        broad_sum = 0.0
        strict_square_sum = 0.0
        broad_square_sum = 0.0
        cross_sum = 0.0
        absolute_difference_sum = 0.0
        signed_difference_sum = 0.0
        broad_only_source_count_sum = 0.0
        broad_only_strict_count_sum = 0.0
        broad_only_broad_count_sum = 0.0
        broad_only_water_occurrence_sum = 0.0
        broad_only_zero_water_count = 0
        broad_only_persistent_water_count = 0

        strict_band = band_lookup["vnp_median_corrected_radiance"]
        for _, block in dataset.block_windows(strict_band):
            column_start = max(int(block.col_off), core_column_start)
            row_start = max(int(block.row_off), core_row_start)
            column_stop = min(
                int(block.col_off + block.width),
                core_column_stop,
            )
            row_stop = min(
                int(block.row_off + block.height),
                core_row_stop,
            )
            if column_stop <= column_start or row_stop <= row_start:
                continue
            window = Window(
                column_start,
                row_start,
                column_stop - column_start,
                row_stop - row_start,
            )
            strict = dataset.read(strict_band, window=window, masked=True).astype(
                np.float64
            )
            broad = dataset.read(
                band_lookup["vnp_broad_median_corrected_radiance"],
                window=window,
                masked=True,
            ).astype(np.float64)
            strict_valid = ~np.ma.getmaskarray(strict)
            broad_valid = ~np.ma.getmaskarray(broad)
            common = strict_valid & broad_valid
            broad_only = broad_valid & ~strict_valid

            pixel_count += strict_valid.size
            strict_count += int(strict_valid.sum())
            broad_count += int(broad_valid.sum())
            common_count += int(common.sum())
            broad_only_count += int(broad_only.sum())

            strict_values = np.ma.getdata(strict)[common]
            broad_values = np.ma.getdata(broad)[common]
            difference = broad_values - strict_values
            strict_sum += float(strict_values.sum())
            broad_sum += float(broad_values.sum())
            strict_square_sum += float(np.square(strict_values).sum())
            broad_square_sum += float(np.square(broad_values).sum())
            cross_sum += float((strict_values * broad_values).sum())
            absolute_difference_sum += float(np.abs(difference).sum())
            signed_difference_sum += float(difference.sum())

            if broad_only.any():
                source_counts = dataset.read(
                    band_lookup["vnp_source_observation_count"],
                    window=window,
                )
                strict_counts = dataset.read(
                    band_lookup["vnp_valid_observation_count"],
                    window=window,
                )
                broad_counts = dataset.read(
                    band_lookup["vnp_broad_valid_observation_count"],
                    window=window,
                )
                water_occurrence = dataset.read(
                    band_lookup["persistent_water_occurrence_percent"],
                    window=window,
                )
                persistent_water = dataset.read(
                    band_lookup["persistent_water_mask"],
                    window=window,
                )
                broad_only_source_count_sum += float(source_counts[broad_only].sum())
                broad_only_strict_count_sum += float(strict_counts[broad_only].sum())
                broad_only_broad_count_sum += float(broad_counts[broad_only].sum())
                broad_only_water_occurrence_sum += float(
                    water_occurrence[broad_only].sum()
                )
                broad_only_zero_water_count += int(
                    (water_occurrence[broad_only] == 0).sum()
                )
                broad_only_persistent_water_count += int(
                    (persistent_water[broad_only] > 0).sum()
                )

        covariance_numerator = common_count * cross_sum - strict_sum * broad_sum
        variance_product = (
            (common_count * strict_square_sum - strict_sum**2)
            * (common_count * broad_square_sum - broad_sum**2)
        )
        correlation = (
            covariance_numerator / math.sqrt(variance_product)
            if variance_product > 0
            else None
        )
        pixel_area_km2 = abs(
            dataset.transform.a * dataset.transform.e
            - dataset.transform.b * dataset.transform.d
        ) / 1_000_000.0

    return {
        "analysis_support": "core_square_excluding_source_halo",
        "analysis_shape": list(analysis_shape),
        "analysis_pixel_count": pixel_count,
        "strict_primary_coverage_fraction": strict_count / pixel_count,
        "broad_coverage_fraction": broad_count / pixel_count,
        "broad_only_coverage_fraction": broad_only_count / pixel_count,
        "broad_only_area_km2": broad_only_count * pixel_area_km2,
        "common_coverage_fraction": common_count / pixel_count,
        "common_support": {
            "pixel_count": common_count,
            "strict_mean_radiance": strict_sum / common_count,
            "broad_mean_radiance": broad_sum / common_count,
            "broad_minus_strict_mean_radiance": signed_difference_sum / common_count,
            "mean_absolute_difference": absolute_difference_sum / common_count,
            "pearson_correlation": correlation,
        },
        "broad_only_support": {
            "pixel_count": broad_only_count,
            "mean_source_observation_count": (
                broad_only_source_count_sum / broad_only_count
                if broad_only_count
                else None
            ),
            "mean_strict_observation_count": (
                broad_only_strict_count_sum / broad_only_count
                if broad_only_count
                else None
            ),
            "mean_broad_observation_count": (
                broad_only_broad_count_sum / broad_only_count
                if broad_only_count
                else None
            ),
            "mean_jrc_water_occurrence_percent": (
                broad_only_water_occurrence_sum / broad_only_count
                if broad_only_count
                else None
            ),
            "jrc_zero_occurrence_fraction": (
                broad_only_zero_water_count / broad_only_count
                if broad_only_count
                else None
            ),
            "persistent_water_mask_fraction": (
                broad_only_persistent_water_count / broad_only_count
                if broad_only_count
                else None
            ),
        },
    }


def _write_layer_grid(
    source_path: Path,
    *,
    output_path: Path,
    layers,
    columns: int,
    title: str,
) -> None:
    rows = (len(layers) + columns - 1) // columns
    with rasterio.open(source_path) as dataset:
        band_lookup = {
            description: index
            for index, description in enumerate(dataset.descriptions, start=1)
            if description
        }
        missing = [name for name, *_ in layers if name not in band_lookup]
        if missing:
            raise ValueError(f"{source_path} lacks diagnostic bands: {missing}")
        scale = min(1.0, 1000.0 / max(dataset.height, dataset.width))
        display_shape = (
            max(1, round(dataset.height * scale)),
            max(1, round(dataset.width * scale)),
        )
        figure, axes = plt.subplots(
            rows,
            columns,
            figsize=(4.6 * columns, 4.2 * rows),
            constrained_layout=True,
        )
        for axis, (name, panel_title, cmap, display_mode) in zip(
            np.asarray(axes).flat,
            layers,
            strict=False,
        ):
            categorical = display_mode == "binary"
            values = dataset.read(
                band_lookup[name],
                out_shape=display_shape,
                masked=True,
                resampling=Resampling.nearest if categorical else Resampling.average,
            ).astype(np.float64)
            array = values.filled(np.nan)
            if display_mode == "log":
                shown = np.log1p(np.maximum(array, 0))
                finite = shown[np.isfinite(shown)]
                vmin, vmax = _percentile_limits(finite)
            elif display_mode == "binary":
                shown = array
                vmin, vmax = 0.0, 1.0
            else:
                shown = array
                finite = shown[np.isfinite(shown)]
                vmin, vmax = _percentile_limits(finite)
            image = axis.imshow(shown, cmap=cmap, vmin=vmin, vmax=vmax)
            axis.set_title(panel_title, fontsize=9)
            axis.set_xticks([])
            axis.set_yticks([])
            figure.colorbar(image, ax=axis, fraction=0.046, pad=0.02)
        for axis in list(np.asarray(axes).flat)[len(layers) :]:
            axis.set_visible(False)
        figure.suptitle(title, fontsize=15, fontweight="bold")
        figure.savefig(output_path, dpi=150)
        plt.close(figure)


def _source_bundle_path(
    source_root: Path,
    *,
    city_id: str,
    artifact_version: str,
) -> Path:
    versioned = source_root / f"{city_id}_ee_source_bundle_{artifact_version}.tif"
    if versioned.exists():
        return versioned
    return source_root / f"{city_id}_ee_source_bundle.tif"


def _percentile_limits(values: np.ndarray) -> tuple[float, float]:
    if values.size == 0:
        return 0.0, 1.0
    low, high = np.percentile(values, [2, 98])
    if np.isclose(low, high):
        high = low + 1.0
    return float(low), float(high)


def _index_html(records: list[dict[str, Any]]) -> str:
    cards = []
    for record in records:
        status = "PASS" if record["grid_contract_valid"] else "FAIL"
        cards.append(
            "<figure>"
            f"<h2>{html.escape(record['city_id'])} · grid {status}</h2>"
            f"<img src=\"{html.escape(Path(record['preview_path']).name)}\">"
            f"<img src=\"{html.escape(Path(record['vnp_coverage_preview_path']).name)}\">"
            f"<img src=\"{html.escape(Path(record['overture_preview_path']).name)}\">"
            f"<figcaption>actual {record['actual_shape']} · "
            f"expected {record['expected_shape']}</figcaption>"
            "</figure>"
        )
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nocturne Day 2 source bundles</title>
<style>
body { margin: 2rem; color: #202124; background: #f8f9fa; font: 15px system-ui; }
main { display: grid; grid-template-columns: 1fr; gap: 1.2rem; }
figure { margin: 0; padding: 1rem; background: white; border: 1px solid #dadce0; }
img { display: block; width: 100%; height: auto; }
figcaption { margin-top: .6rem; }
</style>
</head>
<body>
<h1>Day 2 Earth Engine source-bundle inspection</h1>
<p>Display overviews use average or nearest-neighbor resampling and percentile
stretches only for visualization. They do not modify the source rasters. A grid
failure quarantines that source from the allocation operator.</p>
<main>""" + "\n".join(cards) + """</main>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render readable local previews of Day 2 source bundles."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    parser.add_argument("--input-root", default="drafts")
    args = parser.parse_args(argv)
    for path in write_day2_source_previews(args.config, input_root=args.input_root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
