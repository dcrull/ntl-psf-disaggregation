"""Run real-input Day 2 allocation preflights on radiance-blind city cutouts."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import rasterio
import shapely
from affine import Affine
from matplotlib.colors import TwoSlopeNorm
from pyproj import Transformer
from rasterio.windows import Window
from scipy import ndimage

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.day2 import audit_day2_inputs
from nocturne.disaggregate.export import sha256_file, write_cog
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.disaggregate.kernels import kernel_from_config
from nocturne.disaggregate.operator import (
    AllocationResult,
    NativeFootprintAllocationResult,
    allocate_by_native_footprints,
    apply_fork_form_allocation,
    direct_upsample_baseline,
    summarize_allocation_result,
    uniform_normalized_convolution_baseline,
)
from nocturne.disaggregate.validate import (
    proxy_disagreement,
    water_allocation_metrics,
)
from nocturne.disaggregate.water import WATER_VARIANTS, build_water_proxy_variant
from nocturne.preview.paths import resolve_project_path

PROXY_NAMES = ("built_form_primary", "s2_only_ablation")
PRIMARY_WATER_VARIANT = "combined_soft"
EMPIRICAL_CUTOUT_VERSION = "v1_radiance_blind_preflight"


def run_empirical_cutouts(config_path: str | Path) -> list[Path]:
    """Run the frozen real-input matrix on supported, non-radiance-selected cores."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    audit_path = audit_day2_inputs(config_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not audit["ready_for_two_city_operator_run"]:
        raise ValueError(f"Day 2 input audit is not ready: {audit_path}")

    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate1"
        / "empirical_cutouts"
        / EMPIRICAL_CUTOUT_VERSION
    )
    output_root.mkdir(parents=True, exist_ok=True)
    input_config = config["outputs"]["day2_inputs"]
    input_root = resolve_project_path(input_config["root"])
    kernels = {
        "circular_mean_reference": kernel_from_config(
            config,
            kernel_type="circular_mean",
        )
    }
    gaussian_config = next(
        item
        for item in config["kernels"]["sensitivities"]
        if item["type"] == "gaussian"
    )
    for fwhm_m in gaussian_config["values"]:
        kernels[f"gaussian_fwhm_{float(fwhm_m):g}m"] = kernel_from_config(
            config,
            kernel_type="gaussian",
            fwhm_m=float(fwhm_m),
        )
    maximum_halo_pixels = max(
        max(kernel.halo_rows, kernel.halo_columns) for kernel in kernels.values()
    )
    cutout_size_m = int(
        config["allocation_proxies"]["built_form"]["rasterization"][
            "cutout_sensitivity"
        ]["size_m"]
    )
    cutout_pixels = round(cutout_size_m / float(config["grid"]["resolution_m"]))
    if cutout_pixels * float(config["grid"]["resolution_m"]) != cutout_size_m:
        raise ValueError("Empirical cutout size must align to the working grid")
    strict_minimum_observations = int(
        config["sources"]["vnp46a2"]["quality_contracts"]["primary"][
            "minimum_valid_observations"
        ]
    )
    broad_minimum_observations = int(
        config["sources"]["vnp46a2"]["quality_contracts"]["broad_sensitivity"][
            "minimum_valid_observations"
        ]
    )

    all_metrics: list[dict[str, Any]] = []
    city_records = []
    written: list[Path] = []
    for grid in build_city_grid_specs(config_path):
        city_root = output_root / grid.city_id
        city_root.mkdir(parents=True, exist_ok=True)
        ee_path = input_root / grid.city_id / input_config["earth_engine_bundle_filename"]
        overture_path = (
            input_root / grid.city_id / input_config["overture_bundle_filename"]
        )
        selections = _select_empirical_cutouts(
            ee_path,
            overture_path,
            analysis_shape=(grid.height, grid.width),
            source_halo_pixels=round(
                float(config["cities"]["analysis_geometry"]["source_halo_m"])
                / grid.resolution_m
            ),
            block_pixels=cutout_pixels,
            required_processing_halo_pixels=maximum_halo_pixels,
            minimum_infrastructure_fraction=float(
                config["allocation_proxies"]["built_form"]["rasterization"][
                    "cutout_sensitivity"
                ]["sparse_minimum_infrastructure_fraction"]
            ),
        )
        normalization = _citywide_proxy_normalization(
            ee_path,
            overture_path,
            analysis_window=Window(
                round(
                    float(config["cities"]["analysis_geometry"]["source_halo_m"])
                    / grid.resolution_m
                ),
                round(
                    float(config["cities"]["analysis_geometry"]["source_halo_m"])
                    / grid.resolution_m
                ),
                grid.width,
                grid.height,
            ),
            proxy_floor=float(config["validation"]["water_handling"]["proxy_floor"]),
            strict_minimum_observations=strict_minimum_observations,
            broad_minimum_observations=broad_minimum_observations,
        )
        native_cells = _load_native_cells(
            config,
            grid.city_id,
            target_crs=grid.crs,
        )
        cutout_records = []
        for selection in selections:
            record, metrics, paths = _run_one_cutout(
                config=config,
                config_path=config_path,
                grid=grid,
                ee_path=ee_path,
                overture_path=overture_path,
                selection=selection,
                normalization=normalization,
                kernels=kernels,
                maximum_halo_pixels=maximum_halo_pixels,
                native_cells=native_cells,
                output_root=city_root / selection["role"],
            )
            cutout_records.append(record)
            all_metrics.extend(metrics)
            written.extend(paths)
        city_records.append(
            {
                "city_id": grid.city_id,
                "earth_engine_bundle": {
                    "path": str(ee_path),
                    "sha256": sha256_file(ee_path),
                },
                "overture_bundle": {
                    "path": str(overture_path),
                    "sha256": sha256_file(overture_path),
                },
                "native_cell_source": {
                    "path": native_cells.attrs["source_path"],
                    "sha256": native_cells.attrs["source_sha256"],
                    "semantics": (
                        "corrected Gate 0 actual VNP polygons and strict-QA "
                        "cell radiance"
                    ),
                },
                "proxy_normalization": normalization,
                "cutouts": cutout_records,
            }
        )

    summary = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": config["experiment"]["id"],
        "contract_version": config["experiment"]["contract_version"],
        "artifact_version": EMPIRICAL_CUTOUT_VERSION,
        "config_sha256": disaggregation_config_sha256(config_path),
        "input_audit_path": str(audit_path),
        "input_audit_sha256": sha256_file(audit_path),
        "selection": {
            "uses_vnp_radiance": False,
            "method": "aligned_nonradiance_block_extremes_with_kernel_support_margin",
            "core_size_m": cutout_size_m,
            "roles": [
                "dense_building",
                "sparse_built",
                "water_adjacent_infrastructure",
            ],
            "required_processing_halo_pixels": maximum_halo_pixels,
            "reason": (
                "keep every reporting core outside the support boundary of the "
                "largest declared Gaussian kernel"
            ),
        },
        "run_matrix": {
            "radiance_primary": "strict_qa_vnp_median_corrected_radiance",
            "reference_kernel": "circular_mean_radius_500m",
            "reference_proxy_water_factorial": {
                "proxies": list(PROXY_NAMES),
                "water_variants": list(WATER_VARIANTS),
            },
            "kernel_sensitivity": {
                "proxies": list(PROXY_NAMES),
                "water_variant": PRIMARY_WATER_VARIANT,
                "gaussian_fwhm_m": list(gaussian_config["values"]),
                "native_vnp_footprint": "actual_projected_cell_polygon_area_overlap",
            },
            "new_york_broad_qa": (
                "targeted built-form/combined-soft/circular reference only"
            ),
        },
        "water_metric_limitation": (
            "JRC persistent-water mask is an internal allocation prior used here "
            "for operator preflight diagnostics, not independent shoreline validation"
        ),
        "cities": city_records,
        "metrics": all_metrics,
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written.append(summary_path)
    metrics_path = output_root / "metrics.csv"
    _write_metrics_csv(metrics_path, all_metrics)
    written.append(metrics_path)
    index_path = output_root / "index.html"
    index_path.write_text(_index_html(city_records), encoding="utf-8")
    written.append(index_path)
    artifact_manifest_path = output_root / "artifact_manifest.json"
    artifact_files = []
    for path in sorted(output_root.rglob("*")):
        if not path.is_file() or path == artifact_manifest_path:
            continue
        artifact_files.append(
            {
                "path": str(path.relative_to(output_root)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    artifact_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact_version": EMPIRICAL_CUTOUT_VERSION,
                "config_sha256": disaggregation_config_sha256(config_path),
                "files": artifact_files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(artifact_manifest_path)
    return written


def _run_one_cutout(
    *,
    config: dict[str, Any],
    config_path: Path,
    grid,
    ee_path: Path,
    overture_path: Path,
    selection: dict[str, Any],
    normalization: dict[str, dict[str, dict[str, float | int]]],
    kernels: dict[str, Any],
    maximum_halo_pixels: int,
    native_cells: pd.DataFrame,
    output_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[Path]]:
    output_root.mkdir(parents=True, exist_ok=True)
    core = Window(
        selection["column_start"],
        selection["row_start"],
        selection["size_pixels"],
        selection["size_pixels"],
    )
    processing = Window(
        core.col_off - maximum_halo_pixels,
        core.row_off - maximum_halo_pixels,
        core.width + 2 * maximum_halo_pixels,
        core.height + 2 * maximum_halo_pixels,
    )
    core_slice = (
        slice(maximum_halo_pixels, maximum_halo_pixels + int(core.height)),
        slice(maximum_halo_pixels, maximum_halo_pixels + int(core.width)),
    )
    components, transforms = _read_processing_inputs(
        ee_path,
        overture_path,
        window=processing,
        core_window=core,
        strict_minimum_observations=int(
            config["sources"]["vnp46a2"]["quality_contracts"]["primary"][
                "minimum_valid_observations"
            ]
        ),
        broad_minimum_observations=int(
            config["sources"]["vnp46a2"]["quality_contracts"][
                "broad_sensitivity"
            ]["minimum_valid_observations"]
        ),
    )
    operator_kwargs = _operator_kwargs(config)
    proxy_floor = float(config["validation"]["water_handling"]["proxy_floor"])
    proxy_variants = {
        proxy_name: {
            variant: build_water_proxy_variant(
                components[f"{proxy_name}_base"],
                variant=variant,
                persistent_water_weight=components["persistent_water_weight"],
                spectral_water_weight=components["spectral_water_weight"],
                persistent_water_mask=components["persistent_water_mask"],
                mapped_infrastructure_mask=components["mapped_infrastructure_mask"],
                proxy_floor=proxy_floor,
            ).proxy
            for variant in WATER_VARIANTS
        }
        for proxy_name in PROXY_NAMES
    }
    strict_radiance = components["strict_radiance"]
    strict_valid = components["strict_valid_mask"]
    direct = direct_upsample_baseline(
        strict_radiance,
        radiance_valid_mask=strict_valid,
    )
    circular = kernels["circular_mean_reference"]
    uniform = uniform_normalized_convolution_baseline(
        strict_radiance,
        kernel=circular,
        radiance_valid_mask=strict_valid,
        **operator_kwargs,
    )
    stationary: dict[str, AllocationResult] = {"uniform": uniform}
    for proxy_name in PROXY_NAMES:
        for water_variant in WATER_VARIANTS:
            key = f"{proxy_name}__{water_variant}__circular_mean_reference"
            stationary[key] = apply_fork_form_allocation(
                strict_radiance,
                proxy_variants[proxy_name][water_variant],
                kernel=circular,
                radiance_valid_mask=strict_valid,
                proxy_normalization_divisor=float(
                    normalization[proxy_name][water_variant]["mean"]
                ),
                denominator_reference_mean_after_normalization=1.0,
                **operator_kwargs,
            )
        for kernel_name, kernel in kernels.items():
            if kernel_name == "circular_mean_reference":
                continue
            key = f"{proxy_name}__{PRIMARY_WATER_VARIANT}__{kernel_name}"
            stationary[key] = apply_fork_form_allocation(
                strict_radiance,
                proxy_variants[proxy_name][PRIMARY_WATER_VARIANT],
                kernel=kernel,
                radiance_valid_mask=strict_valid,
                proxy_normalization_divisor=float(
                    normalization[proxy_name][PRIMARY_WATER_VARIANT]["mean"]
                ),
                denominator_reference_mean_after_normalization=1.0,
                **operator_kwargs,
            )

    broad_key = None
    if grid.city_id == "usa_new_york":
        broad_key = (
            "built_form_primary__combined_soft__circular_mean_reference__broad_qa"
        )
        stationary[broad_key] = apply_fork_form_allocation(
            components["broad_radiance"],
            proxy_variants["built_form_primary"][PRIMARY_WATER_VARIANT],
            kernel=circular,
            radiance_valid_mask=components["broad_valid_mask"],
            proxy_normalization_divisor=float(
                normalization["built_form_primary"][PRIMARY_WATER_VARIANT]["mean"]
            ),
            denominator_reference_mean_after_normalization=1.0,
            **operator_kwargs,
        )

    native_results = {
        proxy_name: _native_footprint_cutout(
            proxy_variants[proxy_name][PRIMARY_WATER_VARIANT],
            normalization_divisor=float(
                normalization[proxy_name][PRIMARY_WATER_VARIANT]["mean"]
            ),
            native_cells=native_cells,
            core_transform=transforms["core"],
            core_shape=(int(core.height), int(core.width)),
            processing_transform=transforms["processing"],
            processing_shape=strict_radiance.shape,
            config=config,
        )
        for proxy_name in PROXY_NAMES
    }

    core_source = strict_radiance[core_slice]
    core_water = components["persistent_water_mask"][core_slice]
    distance_to_water_m = ndimage.distance_transform_edt(~components["persistent_water_mask"])
    distance_to_water_m *= float(grid.resolution_m)
    core_adjacent = (
        (~components["persistent_water_mask"])
        & (distance_to_water_m > 0)
        & (distance_to_water_m <= 500)
    )[core_slice]
    metrics = _stationary_metrics(
        city_id=grid.city_id,
        role=selection["role"],
        core_source=core_source,
        broad_core_source=components["broad_radiance"][core_slice],
        core_water=core_water,
        core_adjacent=core_adjacent,
        core_slice=core_slice,
        results=stationary,
        insufficient_proxy_threshold=float(
            config["validation"]["gate0"]["insufficient_proxy_mean_threshold"]
        ),
    )
    metrics.extend(
        _native_metrics(
            city_id=grid.city_id,
            role=selection["role"],
            core_source=core_source,
            core_water=core_water,
            core_adjacent=core_adjacent,
            core_slice=core_slice,
            results=native_results,
        )
    )
    primary_built = stationary[
        "built_form_primary__combined_soft__circular_mean_reference"
    ].allocation[core_slice]
    primary_s2 = stationary[
        "s2_only_ablation__combined_soft__circular_mean_reference"
    ].allocation[core_slice]
    disagreement, disagreement_metrics = proxy_disagreement(
        primary_built,
        primary_s2,
    )

    arrays = {
        "strict_radiance": core_source.astype(np.float32),
        "direct_upsample": direct[core_slice].astype(np.float32),
        "persistent_water_mask": core_water,
        "persistent_water_occurrence_percent": components[
            "persistent_water_occurrence_percent"
        ][core_slice].astype(np.float32),
        "adjacent_land_within_500m": core_adjacent,
        "proxy_disagreement_built_minus_s2": disagreement,
    }
    for proxy_name in PROXY_NAMES:
        arrays[f"proxy_{proxy_name}_{PRIMARY_WATER_VARIANT}"] = proxy_variants[
            proxy_name
        ][PRIMARY_WATER_VARIANT][core_slice].astype(np.float32)
    arrays.update(
        {
            f"allocation_{key}": result.allocation[core_slice].astype(np.float32)
            for key, result in stationary.items()
        }
    )
    arrays.update(
        {
            f"allocation_{proxy_name}__combined_soft__native_vnp_footprint": (
                result.allocation[core_slice].astype(np.float32)
            )
            for proxy_name, result in native_results.items()
        }
    )
    arrays_path = output_root / "arrays.npz"
    np.savez_compressed(arrays_path, **arrays)
    figure_path = output_root / "inspection.png"
    _write_cutout_figure(
        figure_path,
        city_id=grid.city_id,
        role=selection["role"],
        arrays=arrays,
    )
    cog_root = output_root / "cogs"
    cog_layers = {
        "strict_vnp_radiance": arrays["strict_radiance"],
        "direct_upsample": arrays["direct_upsample"],
        "uniform_normalized_convolution": arrays[
            "allocation_uniform"
        ],
        "built_form_combined_soft": primary_built,
        "s2_only_combined_soft": primary_s2,
        "built_form_no_water_prior": arrays[
            "allocation_built_form_primary__no_water_prior__circular_mean_reference"
        ],
        "built_form_hard_persistent": arrays[
            "allocation_built_form_primary__combined_hard_persistent_sensitivity_only__circular_mean_reference"
        ],
        "built_form_native_vnp_footprint": arrays[
            "allocation_built_form_primary__combined_soft__native_vnp_footprint"
        ],
        "s2_only_native_vnp_footprint": arrays[
            "allocation_s2_only_ablation__combined_soft__native_vnp_footprint"
        ],
        "proxy_disagreement_built_minus_s2": disagreement,
        "built_form_operator_consistency_error": stationary[
            "built_form_primary__combined_soft__circular_mean_reference"
        ].operator_consistency_error[core_slice],
    }
    tags = {
        "city_id": grid.city_id,
        "cutout_role": selection["role"],
        "interval_start": config["date_window"]["start"],
        "interval_end_exclusive": config["date_window"]["end_exclusive"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "selection_uses_vnp_radiance": False,
        "analysis_semantics": "empirical_operator_preflight_not_validation",
    }
    cog_paths = []
    for name, values in cog_layers.items():
        cog_paths.append(
            write_cog(
                cog_root / f"{name}.tif",
                values,
                crs=grid.crs,
                transform=transforms["core"],
                band_name=name,
                tags=tags,
            )
        )

    record = {
        **selection,
        "processing_window": _window_dict(processing),
        "core_transform": list(transforms["core"])[:6],
        "crs": grid.crs,
        "center": _window_center_wgs84(
            transforms["core"],
            shape=(int(core.height), int(core.width)),
            crs=grid.crs,
        ),
        "figure_path": str(figure_path),
        "arrays_path": str(arrays_path),
        "cog_directory": str(cog_root),
        "strict_valid_core_fraction": float(np.mean(strict_valid[core_slice])),
        "broad_valid_core_fraction": (
            float(np.mean(components["broad_valid_mask"][core_slice]))
            if grid.city_id == "usa_new_york"
            else None
        ),
        "proxy_disagreement": disagreement_metrics,
        "native_cell_counts": {
            proxy_name: int(result.metadata["native_cell_count"])
            for proxy_name, result in native_results.items()
        },
        "metrics_row_count": len(metrics),
    }
    return record, metrics, [arrays_path, figure_path, *cog_paths]


def _citywide_proxy_normalization(
    ee_path: Path,
    overture_path: Path,
    *,
    analysis_window: Window,
    proxy_floor: float,
    strict_minimum_observations: int,
    broad_minimum_observations: int,
    chunk_pixels: int = 512,
) -> dict[str, dict[str, dict[str, float | int]]]:
    totals = {
        proxy: {
            variant: {"sum": 0.0, "count": 0}
            for variant in WATER_VARIANTS
        }
        for proxy in PROXY_NAMES
    }
    row_stop = int(analysis_window.row_off + analysis_window.height)
    column_stop = int(analysis_window.col_off + analysis_window.width)
    for row in range(int(analysis_window.row_off), row_stop, chunk_pixels):
        for column in range(
            int(analysis_window.col_off),
            column_stop,
            chunk_pixels,
        ):
            window = Window(
                column,
                row,
                min(chunk_pixels, column_stop - column),
                min(chunk_pixels, row_stop - row),
            )
            components, _ = _read_processing_inputs(
                ee_path,
                overture_path,
                window=window,
                core_window=window,
                strict_minimum_observations=strict_minimum_observations,
                broad_minimum_observations=broad_minimum_observations,
            )
            for proxy_name in PROXY_NAMES:
                base = components[f"{proxy_name}_base"]
                for variant in WATER_VARIANTS:
                    proxy = build_water_proxy_variant(
                        base,
                        variant=variant,
                        persistent_water_weight=components[
                            "persistent_water_weight"
                        ],
                        spectral_water_weight=components["spectral_water_weight"],
                        persistent_water_mask=components["persistent_water_mask"],
                        mapped_infrastructure_mask=components[
                            "mapped_infrastructure_mask"
                        ],
                        proxy_floor=proxy_floor,
                    ).proxy
                    finite = np.isfinite(proxy)
                    totals[proxy_name][variant]["sum"] += float(
                        proxy[finite].sum(dtype=np.float64)
                    )
                    totals[proxy_name][variant]["count"] += int(finite.sum())

    normalization: dict[str, dict[str, dict[str, float | int]]] = {}
    for proxy_name, variants in totals.items():
        normalization[proxy_name] = {}
        for variant, values in variants.items():
            if values["count"] == 0:
                raise ValueError(
                    f"No finite citywide proxy support for {proxy_name}/{variant}"
                )
            normalization[proxy_name][variant] = {
                "support_pixel_count": values["count"],
                "mean": values["sum"] / values["count"],
                "support": "50_km_analysis_square_including_water",
            }
    return normalization


def _read_processing_inputs(
    ee_path: Path,
    overture_path: Path,
    *,
    window: Window,
    core_window: Window,
    strict_minimum_observations: int,
    broad_minimum_observations: int,
) -> tuple[dict[str, np.ndarray], dict[str, Affine]]:
    with rasterio.open(ee_path) as ee:
        ee_bands = _band_lookup(ee)
        strict_radiance = _read_float(
            ee,
            ee_bands["vnp_median_corrected_radiance"],
            window,
        )
        strict_count = _read_float(
            ee,
            ee_bands["vnp_valid_observation_count"],
            window,
        )
        broad_radiance = _read_float(
            ee,
            ee_bands["vnp_broad_median_corrected_radiance"],
            window,
        )
        broad_count = _read_float(
            ee,
            ee_bands["vnp_broad_valid_observation_count"],
            window,
        )
        s2_base = _read_float(
            ee,
            ee_bands["s2_base_proxy_unwatered_unfloored"],
            window,
        )
        s2_support = _read_float(
            ee,
            ee_bands["s2_sufficient_observation_support"],
            window,
        )
        spectral = _read_float(
            ee,
            ee_bands["s2_spectral_water_weight"],
            window,
        )
        occurrence = _read_float(
            ee,
            ee_bands["persistent_water_occurrence_percent"],
            window,
        )
        persistent_support = _read_float(
            ee,
            ee_bands["persistent_water_observation_support"],
            window,
        )
        persistent_weight = _read_float(
            ee,
            ee_bands["persistent_water_weight"],
            window,
        )
        persistent_mask_raw = _read_float(
            ee,
            ee_bands["persistent_water_mask"],
            window,
        )
        transforms = {
            "processing": ee.window_transform(window),
            "core": ee.window_transform(core_window),
        }
    with rasterio.open(overture_path) as overture:
        overture_bands = _band_lookup(overture)
        built_base = _read_float(
            overture,
            overture_bands["built_form_base_proxy_unwatered_unfloored"],
            window,
        )
        infrastructure_raw = _read_float(
            overture,
            overture_bands["mapped_infrastructure_mask"],
            window,
        )

    s2_valid = np.isfinite(s2_support) & (s2_support >= 0.5)
    s2_base[~s2_valid] = np.nan
    persistent_valid = np.isfinite(persistent_support) & (persistent_support >= 0.5)
    persistent_weight = np.where(
        persistent_valid & np.isfinite(persistent_weight),
        persistent_weight,
        1.0,
    )
    persistent_weight = np.clip(persistent_weight, 0, 1)
    spectral = np.where(np.isfinite(spectral), spectral, 1.0)
    spectral = np.clip(spectral, 0, 1)
    persistent_mask = (
        persistent_valid
        & np.isfinite(persistent_mask_raw)
        & (persistent_mask_raw >= 0.5)
    )
    infrastructure = np.isfinite(infrastructure_raw) & (infrastructure_raw >= 0.5)
    occurrence[~persistent_valid] = np.nan
    return {
        "strict_radiance": strict_radiance,
        "strict_valid_mask": np.isfinite(strict_radiance)
        & np.isfinite(strict_count)
        & (strict_count >= strict_minimum_observations),
        "broad_radiance": broad_radiance,
        "broad_valid_mask": np.isfinite(broad_radiance)
        & np.isfinite(broad_count)
        & (broad_count >= broad_minimum_observations),
        "built_form_primary_base": built_base,
        "s2_only_ablation_base": s2_base,
        "persistent_water_weight": persistent_weight,
        "spectral_water_weight": spectral,
        "persistent_water_mask": persistent_mask,
        "persistent_water_occurrence_percent": occurrence,
        "mapped_infrastructure_mask": infrastructure,
    }, transforms


def _select_empirical_cutouts(
    ee_path: Path,
    overture_path: Path,
    *,
    analysis_shape: tuple[int, int],
    source_halo_pixels: int,
    block_pixels: int,
    required_processing_halo_pixels: int,
    minimum_infrastructure_fraction: float,
) -> list[dict[str, Any]]:
    analysis_window = Window(
        source_halo_pixels,
        source_halo_pixels,
        analysis_shape[1],
        analysis_shape[0],
    )
    with rasterio.open(overture_path) as overture:
        bands = _band_lookup(overture)
        building = _read_float(
            overture,
            bands["building_fraction"],
            analysis_window,
        )
        infrastructure = _read_float(
            overture,
            bands["mapped_infrastructure_mask"],
            analysis_window,
        )
    with rasterio.open(ee_path) as ee:
        bands = _band_lookup(ee)
        water = _read_float(
            ee,
            bands["persistent_water_occurrence_percent"],
            analysis_window,
        )
    building_mean = _aligned_nanmean(building, block_pixels)
    infrastructure_mean = _aligned_nanmean(infrastructure, block_pixels)
    water_mean = _aligned_nanmean(water, block_pixels)
    block_shape = building_mean.shape
    eligible = np.zeros(block_shape, dtype=bool)
    full_height = analysis_shape[0] + 2 * source_halo_pixels
    full_width = analysis_shape[1] + 2 * source_halo_pixels
    for block_row in range(block_shape[0]):
        for block_column in range(block_shape[1]):
            row_start = source_halo_pixels + block_row * block_pixels
            column_start = source_halo_pixels + block_column * block_pixels
            row_stop = row_start + block_pixels
            column_stop = column_start + block_pixels
            eligible[block_row, block_column] = (
                row_start - required_processing_halo_pixels >= 0
                and column_start - required_processing_halo_pixels >= 0
                and row_stop + required_processing_halo_pixels <= full_height
                and column_stop + required_processing_halo_pixels <= full_width
            )
    selected = _select_block_indices_with_eligibility(
        building_mean,
        infrastructure_mean,
        water_mean,
        eligible_mask=eligible,
        minimum_infrastructure_fraction=minimum_infrastructure_fraction,
    )
    records = []
    for role, (block_row, block_column) in selected.items():
        row_start = source_halo_pixels + block_row * block_pixels
        column_start = source_halo_pixels + block_column * block_pixels
        records.append(
            {
                "role": role,
                "block_row": int(block_row),
                "block_column": int(block_column),
                "row_start": int(row_start),
                "row_stop": int(row_start + block_pixels),
                "column_start": int(column_start),
                "column_stop": int(column_start + block_pixels),
                "size_pixels": int(block_pixels),
                "selection_uses_vnp_radiance": False,
                "selection_scores": {
                    "mean_building_fraction": float(
                        building_mean[block_row, block_column]
                    ),
                    "mapped_infrastructure_fraction": float(
                        infrastructure_mean[block_row, block_column]
                    ),
                    "mean_jrc_water_occurrence_percent": float(
                        water_mean[block_row, block_column]
                    ),
                    "water_adjacent_infrastructure_score": float(
                        water_mean[block_row, block_column]
                        * infrastructure_mean[block_row, block_column]
                    ),
                },
            }
        )
    return records


def _select_block_indices_with_eligibility(
    building_mean: np.ndarray,
    infrastructure_mean: np.ndarray,
    water_mean: np.ndarray,
    *,
    eligible_mask: np.ndarray,
    minimum_infrastructure_fraction: float,
) -> dict[str, tuple[int, int]]:
    if not (
        building_mean.shape
        == infrastructure_mean.shape
        == water_mean.shape
        == eligible_mask.shape
    ):
        raise ValueError("Cutout-selection surfaces and eligibility must share one shape")
    finite = (
        np.isfinite(building_mean)
        & np.isfinite(infrastructure_mean)
        & np.isfinite(water_mean)
    )
    eligible = np.asarray(eligible_mask, dtype=bool) & finite
    if not eligible.any():
        raise ValueError("No cutout blocks have complete declared-kernel support")
    dense = np.unravel_index(
        int(np.argmax(np.where(eligible, building_mean, -np.inf))),
        building_mean.shape,
    )
    structural = (
        eligible
        & (infrastructure_mean >= minimum_infrastructure_fraction)
    )
    structural[dense] = False
    if not structural.any():
        raise ValueError("No eligible sparse-built cutout block")
    sparse_target = float(np.quantile(building_mean[structural], 0.25))
    sparse = np.unravel_index(
        int(
            np.argmin(
                np.where(
                    structural,
                    np.abs(building_mean - sparse_target),
                    np.inf,
                )
            )
        ),
        building_mean.shape,
    )
    waterfront_eligible = structural.copy()
    waterfront_eligible[sparse] = False
    if not waterfront_eligible.any():
        raise ValueError("No eligible water-adjacent cutout block")
    waterfront = np.unravel_index(
        int(
            np.argmax(
                np.where(
                    waterfront_eligible,
                    water_mean * infrastructure_mean,
                    -np.inf,
                )
            )
        ),
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


def _load_native_cells(
    config: dict[str, Any],
    city_id: str,
    *,
    target_crs: str,
) -> pd.DataFrame:
    root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate0"
        / config["validation"]["gate0"]["artifact_version"]
    )
    path = root / f"{city_id}_s2_only_samples.csv"
    table = pd.read_csv(
        path,
        usecols=[
            "coarse_cell_id",
            "coarse_cell_polygon_wkt",
            "vnp_median_corrected_ntl",
        ],
    )
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    polygons = shapely.from_wkt(table["coarse_cell_polygon_wkt"].to_numpy(dtype=str))
    table["projected_polygon"] = list(
        shapely.transform(
            polygons,
            transformer.transform,
            interleaved=False,
        )
    )
    table.attrs["source_path"] = str(path)
    table.attrs["source_sha256"] = sha256_file(path)
    return table


def _native_footprint_cutout(
    proxy: np.ndarray,
    *,
    normalization_divisor: float,
    native_cells: pd.DataFrame,
    core_transform: Affine,
    core_shape: tuple[int, int],
    processing_transform: Affine,
    processing_shape: tuple[int, int],
    config: dict[str, Any],
) -> NativeFootprintAllocationResult:
    core_bounds = rasterio.transform.array_bounds(
        core_shape[0],
        core_shape[1],
        core_transform,
    )
    core_polygon = shapely.box(*core_bounds)
    polygons = np.asarray(native_cells["projected_polygon"].tolist(), dtype=object)
    selected_mask = shapely.intersects(polygons, core_polygon)
    selected = native_cells.loc[selected_mask].reset_index(drop=True)
    if selected.empty:
        raise ValueError("No corrected Gate 0 native VNP cells intersect the cutout")

    cell_indices: list[np.ndarray] = []
    rows: list[np.ndarray] = []
    columns: list[np.ndarray] = []
    areas: list[np.ndarray] = []
    resolution = abs(float(processing_transform.a))
    for cell_index, cell in selected.iterrows():
        polygon = cell["projected_polygon"]
        min_x, min_y, max_x, max_y = shapely.bounds(polygon)
        column_start = max(
            0,
            math.floor((min_x - processing_transform.c) / resolution),
        )
        column_stop = min(
            processing_shape[1],
            math.ceil((max_x - processing_transform.c) / resolution),
        )
        row_start = max(
            0,
            math.floor((processing_transform.f - max_y) / resolution),
        )
        row_stop = min(
            processing_shape[0],
            math.ceil((processing_transform.f - min_y) / resolution),
        )
        candidate_rows, candidate_columns = np.meshgrid(
            np.arange(row_start, row_stop, dtype=np.int32),
            np.arange(column_start, column_stop, dtype=np.int32),
            indexing="ij",
        )
        flat_rows = candidate_rows.ravel()
        flat_columns = candidate_columns.ravel()
        left = processing_transform.c + flat_columns * processing_transform.a
        right = left + processing_transform.a
        top = processing_transform.f + flat_rows * processing_transform.e
        bottom = top + processing_transform.e
        pixels = shapely.box(left, bottom, right, top)
        overlap_area = shapely.area(shapely.intersection(pixels, polygon))
        retained = overlap_area > 1e-8
        if not retained.any():
            continue
        cell_indices.append(
            np.full(int(retained.sum()), cell_index, dtype=np.int32)
        )
        rows.append(flat_rows[retained])
        columns.append(flat_columns[retained])
        areas.append(overlap_area[retained].astype(np.float64))
    if not areas:
        raise ValueError("Native cells produced no fine-grid overlap records")
    return allocate_by_native_footprints(
        proxy,
        overlap_cell_index=np.concatenate(cell_indices),
        overlap_rows=np.concatenate(rows),
        overlap_columns=np.concatenate(columns),
        overlap_area_m2=np.concatenate(areas),
        cell_radiance=selected["vnp_median_corrected_ntl"].to_numpy(dtype=float),
        pixel_area_m2=resolution * resolution,
        denominator_epsilon_relative=float(
            config["allocation_proxies"]["denominator_epsilon_relative"]
        ),
        minimum_cell_proxy_support_fraction=float(
            config["validation"]["gate1"]["minimum_valid_kernel_support_fraction"]
        ),
        support_fraction_tolerance=float(
            config["validation"]["gate1"]["support_fraction_tolerance"]
        ),
        proxy_normalization_divisor=normalization_divisor,
        denominator_reference_mean_after_normalization=1.0,
    )


def _stationary_metrics(
    *,
    city_id: str,
    role: str,
    core_source: np.ndarray,
    broad_core_source: np.ndarray,
    core_water: np.ndarray,
    core_adjacent: np.ndarray,
    core_slice: tuple[slice, slice],
    results: dict[str, AllocationResult],
    insufficient_proxy_threshold: float,
) -> list[dict[str, Any]]:
    metrics = []
    no_water_reference = {
        proxy: results[
            f"{proxy}__no_water_prior__circular_mean_reference"
        ].allocation[core_slice]
        for proxy in PROXY_NAMES
    }
    for key, result in results.items():
        cropped = _crop_allocation_result(result, core_slice)
        source = broad_core_source if key.endswith("__broad_qa") else core_source
        row = summarize_allocation_result(
            cropped,
            source_radiance=source,
            insufficient_proxy_threshold=insufficient_proxy_threshold,
        )
        comparison_source = source[cropped.operator_consistency_valid_mask].astype(
            np.float64
        )
        source_mean_absolute = (
            float(np.mean(np.abs(comparison_source)))
            if comparison_source.size
            else None
        )
        row["operator_consistency_source_mean_absolute"] = source_mean_absolute
        row["operator_consistency_nmae_by_source_mean_absolute"] = (
            row["operator_consistency_mae"] / source_mean_absolute
            if row["operator_consistency_mae"] is not None
            and source_mean_absolute is not None
            and source_mean_absolute > 0
            else None
        )
        parts = key.split("__")
        if key == "uniform":
            proxy_name = "uniform_normalized_convolution"
            water_variant = "not_applicable"
            kernel_name = "circular_mean_reference"
            radiance_quality = "strict"
        else:
            proxy_name, water_variant, kernel_name = parts[:3]
            radiance_quality = "broad_sensitivity" if len(parts) == 4 else "strict"
        water_reference = (
            no_water_reference.get(proxy_name)
            if water_variant != "no_water_prior"
            and kernel_name == "circular_mean_reference"
            and radiance_quality == "strict"
            else None
        )
        row.update(
            water_allocation_metrics(
                cropped.allocation,
                source_radiance=source,
                water_reference_mask=core_water,
                adjacent_land_mask=core_adjacent,
                reference_allocation=water_reference,
            )
        )
        row.update(
            {
                "city_id": city_id,
                "cutout_role": role,
                "method_class": (
                    "uniform_baseline"
                    if key == "uniform"
                    else "stationary_kernel_allocation"
                ),
                "allocation_proxy": proxy_name,
                "water_variant": water_variant,
                "kernel_configuration": kernel_name,
                "radiance_quality": radiance_quality,
            }
        )
        metrics.append(row)
    return metrics


def _native_metrics(
    *,
    city_id: str,
    role: str,
    core_source: np.ndarray,
    core_water: np.ndarray,
    core_adjacent: np.ndarray,
    core_slice: tuple[slice, slice],
    results: dict[str, NativeFootprintAllocationResult],
) -> list[dict[str, Any]]:
    metrics = []
    for proxy_name, result in results.items():
        allocation = result.allocation[core_slice]
        errors = result.cell_operator_consistency_error[
            np.isfinite(result.cell_operator_consistency_error)
        ].astype(np.float64)
        reconstructed_cell_source = (
            result.cell_reaggregated_allocation.astype(np.float64)
            + result.cell_operator_consistency_error.astype(np.float64)
        )
        source_mean_absolute = float(
            np.nanmean(np.abs(reconstructed_cell_source))
        )
        error_mae = float(np.abs(errors).mean()) if errors.size else None
        row = {
            **result.metadata,
            "city_id": city_id,
            "cutout_role": role,
            "method_class": "native_footprint_allocation",
            "allocation_proxy": proxy_name,
            "water_variant": PRIMARY_WATER_VARIANT,
            "kernel_configuration": "native_vnp_footprint",
            "radiance_quality": "strict",
            "array_shape": list(allocation.shape),
            "valid_output_pixel_count": int(np.isfinite(allocation).sum()),
            "valid_output_fraction": float(np.isfinite(allocation).mean()),
            "operator_consistency_sample_count": int(errors.size),
            "operator_consistency_bias": (
                float(errors.mean()) if errors.size else None
            ),
            "operator_consistency_mae": error_mae,
            "operator_consistency_rmse": (
                float(np.sqrt(np.mean(errors * errors))) if errors.size else None
            ),
            "operator_consistency_source_mean_absolute": source_mean_absolute,
            "operator_consistency_nmae_by_source_mean_absolute": (
                error_mae / source_mean_absolute
                if error_mae is not None and source_mean_absolute > 0
                else None
            ),
            "interpretation": (
                "actual native-cell area-overlap sensitivity; operator "
                "consistency is cell-level and not independent validation"
            ),
        }
        row.update(
            water_allocation_metrics(
                allocation,
                source_radiance=core_source,
                water_reference_mask=core_water,
                adjacent_land_mask=core_adjacent,
            )
        )
        metrics.append(row)
    return metrics


def _crop_allocation_result(
    result: AllocationResult,
    core_slice: tuple[slice, slice],
) -> AllocationResult:
    array_fields = (
        "allocation",
        "normalized_proxy",
        "convolved_radiance",
        "convolved_proxy",
        "reaggregated_allocation",
        "operator_consistency_error",
        "radiance_support_fraction",
        "proxy_support_fraction",
        "allocation_support_fraction",
        "geometric_support_fraction",
        "valid_output_mask",
        "operator_consistency_valid_mask",
        "boundary_mask",
        "invalid_radiance_neighborhood_mask",
        "invalid_proxy_neighborhood_mask",
        "denominator_floor_mask",
        "denominator_instability_mask",
        "negative_radiance_input_mask",
        "negative_preclip_output_mask",
    )
    return replace(
        result,
        **{
            field: getattr(result, field)[core_slice]
            for field in array_fields
        },
    )


def _write_cutout_figure(
    path: Path,
    *,
    city_id: str,
    role: str,
    arrays: dict[str, np.ndarray],
) -> None:
    panels = [
        ("strict_radiance", "Strict VNP radiance", "magma", "log"),
        (
            "persistent_water_occurrence_percent",
            "JRC occurrence (%)",
            "Blues",
            "linear",
        ),
        ("direct_upsample", "Direct upsample", "magma", "log"),
        (
            "allocation_uniform",
            "Uniform convolution",
            "magma",
            "log",
        ),
        (
            "allocation_built_form_primary__no_water_prior__circular_mean_reference",
            "Built · no water prior",
            "magma",
            "log",
        ),
        (
            "proxy_built_form_primary_combined_soft",
            "Built proxy · combined soft",
            "viridis",
            "linear",
        ),
        (
            "allocation_built_form_primary__combined_soft__circular_mean_reference",
            "Built · circular reference",
            "magma",
            "log",
        ),
        (
            "allocation_built_form_primary__combined_hard_persistent_sensitivity_only__circular_mean_reference",
            "Built · hard sensitivity",
            "magma",
            "log",
        ),
        (
            "allocation_built_form_primary__combined_soft__native_vnp_footprint",
            "Built · native cells",
            "magma",
            "log",
        ),
        (
            "allocation_built_form_primary__combined_soft__gaussian_fwhm_1500m",
            "Built · Gaussian FWHM 1500 m",
            "magma",
            "log",
        ),
        (
            "proxy_s2_only_ablation_combined_soft",
            "S2 proxy · combined soft",
            "viridis",
            "linear",
        ),
        (
            "allocation_s2_only_ablation__combined_soft__circular_mean_reference",
            "S2 · circular reference",
            "magma",
            "log",
        ),
        (
            "allocation_s2_only_ablation__combined_soft__native_vnp_footprint",
            "S2 · native cells",
            "magma",
            "log",
        ),
        (
            "proxy_disagreement_built_minus_s2",
            "Built − S2 allocation",
            "RdBu_r",
            "difference",
        ),
        (
            "persistent_water_mask",
            "Persistent-water mask",
            "gray_r",
            "binary",
        ),
    ]
    figure, axes = plt.subplots(3, 5, figsize=(18, 10.5), constrained_layout=True)
    for axis, (key, title, cmap, mode) in zip(axes.flat, panels, strict=True):
        values = np.asarray(arrays[key])
        shown = values.astype(float)
        kwargs: dict[str, Any] = {"cmap": cmap}
        if not np.isfinite(shown).any():
            axis.set_facecolor("#ecebe6")
            axis.text(
                0.5,
                0.5,
                "No complete\nstrict-QA support",
                ha="center",
                va="center",
                transform=axis.transAxes,
                fontsize=10,
                fontweight="bold",
            )
            axis.set_title(title, fontsize=9)
            axis.set_axis_off()
            continue
        if mode == "log":
            shown = np.log1p(np.maximum(shown, 0))
        if mode == "binary":
            kwargs.update(vmin=0, vmax=1)
        elif mode == "difference":
            finite = shown[np.isfinite(shown)]
            limit = float(np.percentile(np.abs(finite), 98)) if finite.size else 1
            limit = max(limit, np.finfo(float).eps)
            kwargs["norm"] = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
        else:
            finite = shown[np.isfinite(shown)]
            if finite.size:
                low, high = np.percentile(finite, [2, 98])
                if high > low:
                    kwargs.update(vmin=float(low), vmax=float(high))
        image = axis.imshow(shown, **kwargs)
        axis.set_title(title, fontsize=9)
        axis.set_axis_off()
        figure.colorbar(image, ax=axis, fraction=0.046, pad=0.02)
    figure.suptitle(
        f"{city_id} · {role} · empirical allocation preflight\n"
        "1 km reporting core; operators evaluated with full declared halos",
        fontsize=14,
    )
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _write_metrics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for key, value in row.items()
                }
            )


def _index_html(city_records: list[dict[str, Any]]) -> str:
    figures = []
    for city in city_records:
        for cutout in city["cutouts"]:
            figure = Path(cutout["figure_path"])
            relative = Path(city["city_id"]) / cutout["role"] / figure.name
            figures.append(
                "<figure>"
                f"<img src='{html.escape(str(relative))}' "
                f"alt='{html.escape(city['city_id'])} {html.escape(cutout['role'])}'>"
                f"<figcaption>{html.escape(city['city_id'])} · "
                f"{html.escape(cutout['role'])}</figcaption></figure>"
            )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Empirical allocation cutouts</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f4f3ef; color: #202020; }}
main {{ max-width: 1800px; margin: auto; }}
figure {{ background: white; padding: 1rem; margin: 1.5rem 0; border-radius: .4rem; }}
img {{ width: 100%; height: auto; display: block; }}
figcaption {{ margin-top: .6rem; font-weight: 650; }}
code {{ background: #e8e7e2; padding: .1rem .25rem; }}
</style>
</head>
<body><main>
<h1>Day 2 empirical allocation preflight</h1>
<p>Each figure shows a 1 km reporting core selected without VNP radiance.
The operator was evaluated on a larger window covering the complete support of
the largest declared Gaussian kernel. Panel stretches are display-only.</p>
<p>The JRC water panels are internal-prior diagnostics, not independent
shoreline validation. See <code>summary.json</code> and <code>metrics.csv</code>
for numerical results and provenance.</p>
{''.join(figures)}
</main></body></html>
"""


def _operator_kwargs(config: dict[str, Any]) -> dict[str, float]:
    gate1 = config["validation"]["gate1"]
    return {
        "denominator_epsilon_relative": float(
            config["allocation_proxies"]["denominator_epsilon_relative"]
        ),
        "denominator_instability_threshold_relative": float(
            config["validation"]["gate0"]["insufficient_proxy_mean_threshold"]
        ),
        "minimum_valid_support_fraction": float(
            gate1["minimum_valid_kernel_support_fraction"]
        ),
        "support_fraction_tolerance": float(gate1["support_fraction_tolerance"]),
    }


def _aligned_nanmean(values: np.ndarray, block_pixels: int) -> np.ndarray:
    if values.shape[0] % block_pixels or values.shape[1] % block_pixels:
        raise ValueError("Array shape must divide evenly into aligned cutout blocks")
    reshaped = values.reshape(
        values.shape[0] // block_pixels,
        block_pixels,
        values.shape[1] // block_pixels,
        block_pixels,
    )
    finite = np.isfinite(reshaped)
    totals = np.where(finite, reshaped, 0).sum(axis=(1, 3), dtype=np.float64)
    counts = finite.sum(axis=(1, 3))
    output = np.full(counts.shape, np.nan, dtype=np.float64)
    np.divide(totals, counts, out=output, where=counts > 0)
    return output


def _read_float(
    dataset: rasterio.io.DatasetReader,
    band: int,
    window: Window,
) -> np.ndarray:
    return dataset.read(band, window=window, masked=True).filled(np.nan).astype(
        np.float32
    )


def _band_lookup(dataset: rasterio.io.DatasetReader) -> dict[str, int]:
    return {
        name: index
        for index, name in enumerate(dataset.descriptions, start=1)
        if name is not None
    }


def _window_dict(window: Window) -> dict[str, int]:
    return {
        "column_start": int(window.col_off),
        "column_stop": int(window.col_off + window.width),
        "row_start": int(window.row_off),
        "row_stop": int(window.row_off + window.height),
    }


def _window_center_wgs84(
    transform: Affine,
    *,
    shape: tuple[int, int],
    crs: str,
) -> dict[str, float]:
    center_x = transform.c + transform.a * shape[1] / 2
    center_y = transform.f + transform.e * shape[0] / 2
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    longitude, latitude = transformer.transform(center_x, center_y)
    return {"longitude": float(longitude), "latitude": float(latitude)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run real-input empirical allocation cutout preflights."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    for path in run_empirical_cutouts(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
