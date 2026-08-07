"""Resumable tiled Day 2 full-city allocation executor.

The executor deliberately processes one configuration at a time.  Its working
GeoTIFF is checkpointed after every reporting core and is promoted to a COG
only after every core has been read back and checksum-verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.shutil import copy as rio_copy
from rasterio.windows import Window

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.day2 import audit_day2_inputs
from nocturne.disaggregate.empirical_cutouts import (
    PRIMARY_WATER_VARIANT,
    PROXY_NAMES,
    _citywide_proxy_normalization,
    _operator_kwargs,
    _read_processing_inputs,
)
from nocturne.disaggregate.export import sha256_file
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.disaggregate.kernels import kernel_from_config
from nocturne.disaggregate.operator import (
    AllocationResult,
    apply_fork_form_allocation,
    direct_upsample_baseline,
    uniform_normalized_convolution_baseline,
)
from nocturne.disaggregate.water import WATER_VARIANTS, build_water_proxy_variant
from nocturne.preview.paths import resolve_project_path

FULL_CITY_VERSION = "v1_resumable_tiled"
DEFAULT_TILE_PIXELS = 512
FLOAT_LAYER_NAMES = (
    "allocation",
    "operator_consistency_error",
    "radiance_support_fraction",
    "proxy_support_fraction",
    "allocation_support_fraction",
    "geometric_support_fraction",
)
MASK_LAYER_NAMES = (
    "valid_output_mask",
    "operator_consistency_valid_mask",
    "boundary_mask",
    "invalid_radiance_neighborhood_mask",
    "invalid_proxy_neighborhood_mask",
    "denominator_floor_mask",
    "denominator_instability_mask",
    "negative_radiance_input_mask",
    "negative_preclip_output_mask",
    "insufficient_proxy_support_mask",
)
BAND_NAMES = FLOAT_LAYER_NAMES + MASK_LAYER_NAMES


@dataclass(frozen=True)
class FullCityConfiguration:
    name: str
    kind: str
    proxy: str | None
    water_variant: str | None
    kernel_name: str | None
    fwhm_m: float | None = None
    radiance_contract: str = "strict"


def build_configuration_matrix(config: dict[str, Any], city_id: str) -> list[FullCityConfiguration]:
    """Return the frozen 23/22 configuration matrix in deterministic order."""

    matrix = [
        FullCityConfiguration("direct_upsample", "direct", None, None, None),
        FullCityConfiguration(
            "uniform_normalized_convolution",
            "uniform",
            None,
            None,
            "circular_mean_reference",
        ),
    ]
    for proxy in PROXY_NAMES:
        for water in WATER_VARIANTS:
            matrix.append(
                FullCityConfiguration(
                    f"{proxy}__{water}__circular_mean_reference",
                    "stationary",
                    proxy,
                    water,
                    "circular_mean_reference",
                )
            )
    gaussian = next(
        item for item in config["kernels"]["sensitivities"] if item["type"] == "gaussian"
    )
    for proxy in PROXY_NAMES:
        for value in gaussian["values"]:
            fwhm = float(value)
            matrix.append(
                FullCityConfiguration(
                    f"{proxy}__{PRIMARY_WATER_VARIANT}__gaussian_fwhm_{fwhm:g}m",
                    "stationary",
                    proxy,
                    PRIMARY_WATER_VARIANT,
                    "gaussian",
                    fwhm_m=fwhm,
                )
            )
    for proxy in PROXY_NAMES:
        matrix.append(
            FullCityConfiguration(
                f"{proxy}__{PRIMARY_WATER_VARIANT}__native_vnp_footprint",
                "native",
                proxy,
                PRIMARY_WATER_VARIANT,
                "native_vnp_footprint",
            )
        )
    if city_id == "usa_new_york":
        matrix.append(
            FullCityConfiguration(
                "built_form_primary__combined_soft__circular_mean_reference__broad_qa",
                "stationary",
                "built_form_primary",
                PRIMARY_WATER_VARIANT,
                "circular_mean_reference",
                radiance_contract="broad",
            )
        )
    expected = 23 if city_id == "usa_new_york" else 22
    if len(matrix) != expected:
        raise AssertionError(f"Full-city matrix for {city_id} has {len(matrix)}, not {expected}")
    return matrix


def iter_core_windows(
    shape: tuple[int, int], tile_pixels: int = DEFAULT_TILE_PIXELS
) -> Iterable[Window]:
    if tile_pixels <= 0:
        raise ValueError("Tile size must be positive")
    height, width = shape
    for row in range(0, height, tile_pixels):
        for column in range(0, width, tile_pixels):
            yield Window(
                column,
                row,
                min(tile_pixels, width - column),
                min(tile_pixels, height - row),
            )


def expanded_window(
    core: Window, *, halo: int, bounds_shape: tuple[int, int]
) -> tuple[Window, tuple[slice, slice]]:
    """Expand a core without boundless padding and return its crop slices."""

    height, width = bounds_shape
    col0 = max(0, int(core.col_off) - halo)
    row0 = max(0, int(core.row_off) - halo)
    col1 = min(width, int(core.col_off + core.width) + halo)
    row1 = min(height, int(core.row_off + core.height) + halo)
    processing = Window(col0, row0, col1 - col0, row1 - row0)
    crop = (
        slice(int(core.row_off) - row0, int(core.row_off + core.height) - row0),
        slice(int(core.col_off) - col0, int(core.col_off + core.width) - col0),
    )
    return processing, crop


def run_full_city(
    config_path: str | Path,
    *,
    tile_pixels: int = DEFAULT_TILE_PIXELS,
    only_city: str | None = None,
    only_configuration: str | None = None,
) -> Path:
    """Execute or resume the declared two-city matrix."""

    _require_single_threaded_numerics()
    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    audit_path = audit_day2_inputs(config_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not audit["ready_for_two_city_operator_run"]:
        raise ValueError(f"Day 2 input audit is not ready: {audit_path}")
    config_hash = disaggregation_config_sha256(config_path)
    output_root = (
        resolve_project_path(config["outputs"]["rasters"]) / "full_city" / FULL_CITY_VERSION
    )
    output_root.mkdir(parents=True, exist_ok=True)
    city_records = []
    for grid in build_city_grid_specs(config_path):
        if only_city and grid.city_id != only_city:
            continue
        records = _run_city(
            config,
            config_hash=config_hash,
            grid=grid,
            output_root=output_root / grid.city_id,
            tile_pixels=tile_pixels,
            only_configuration=only_configuration,
        )
        city_records.append({"city_id": grid.city_id, "configurations": records})
    manifest_path = output_root / "artifact_manifest.json"
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifact_version": FULL_CITY_VERSION,
        "config_sha256": config_hash,
        "day2_input_audit": str(audit_path),
        "tile_pixels": tile_pixels,
        "cities": city_records,
        "complete": (
            only_city is None
            and only_configuration is None
            and len(city_records) == 2
            and all(
                len(city["configurations"]) == (23 if city["city_id"] == "usa_new_york" else 22)
                for city in city_records
            )
        ),
    }
    if payload["complete"]:
        gallery_path = output_root / "overview_gallery.png"
        _write_overview_gallery(gallery_path, city_records)
        payload["overview_gallery"] = {
            "path": str(gallery_path),
            "sha256": sha256_file(gallery_path),
        }
    _atomic_json(manifest_path, payload)
    return manifest_path


def _run_city(
    config: dict[str, Any],
    *,
    config_hash: str,
    grid,
    output_root: Path,
    tile_pixels: int,
    only_configuration: str | None,
) -> list[dict[str, Any]]:
    input_config = config["outputs"]["day2_inputs"]
    input_root = resolve_project_path(input_config["root"])
    ee_path = input_root / grid.city_id / input_config["earth_engine_bundle_filename"]
    overture_path = input_root / grid.city_id / input_config["overture_bundle_filename"]
    source_halo = round(
        float(config["cities"]["analysis_geometry"]["source_halo_m"]) / grid.resolution_m
    )
    analysis_window = Window(source_halo, source_halo, grid.width, grid.height)
    strict_minimum = int(
        config["sources"]["vnp46a2"]["quality_contracts"]["primary"]["minimum_valid_observations"]
    )
    broad_minimum = int(
        config["sources"]["vnp46a2"]["quality_contracts"]["broad_sensitivity"][
            "minimum_valid_observations"
        ]
    )
    normalization = _citywide_proxy_normalization(
        ee_path,
        overture_path,
        analysis_window=analysis_window,
        proxy_floor=float(config["validation"]["water_handling"]["proxy_floor"]),
        strict_minimum_observations=strict_minimum,
        broad_minimum_observations=broad_minimum,
        chunk_pixels=tile_pixels,
    )
    records = []
    for spec in build_configuration_matrix(config, grid.city_id):
        if only_configuration and spec.name != only_configuration:
            continue
        if spec.kind == "native":
            # Native cells require polygon-overlap tiling and have their own
            # implementation entry point.  Refuse a silent stationary substitute.
            record = _run_native_configuration(
                config,
                config_hash=config_hash,
                grid=grid,
                spec=spec,
                ee_path=ee_path,
                overture_path=overture_path,
                normalization=normalization,
                output_root=output_root / spec.name,
                analysis_window=analysis_window,
                tile_pixels=tile_pixels,
                strict_minimum=strict_minimum,
                broad_minimum=broad_minimum,
            )
        else:
            record = _run_stationary_configuration(
                config,
                config_hash=config_hash,
                grid=grid,
                spec=spec,
                ee_path=ee_path,
                overture_path=overture_path,
                normalization=normalization,
                output_root=output_root / spec.name,
                analysis_window=analysis_window,
                tile_pixels=tile_pixels,
                strict_minimum=strict_minimum,
                broad_minimum=broad_minimum,
            )
        metrics_path = output_root / spec.name / "metrics.json"
        record["metrics_sidecar"] = {
            "path": str(metrics_path),
            "sha256": sha256_file(metrics_path),
        }
        records.append(record)
    return records


def _run_stationary_configuration(
    config: dict[str, Any],
    *,
    config_hash: str,
    grid,
    spec: FullCityConfiguration,
    ee_path: Path,
    overture_path: Path,
    normalization: dict[str, Any],
    output_root: Path,
    analysis_window: Window,
    tile_pixels: int,
    strict_minimum: int,
    broad_minimum: int,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    final_path = output_root / "products.tif"
    metrics_path = output_root / "metrics.json"
    if _completed_artifact_is_valid(
        final_path,
        metrics_path,
        config_hash=config_hash,
        grid=grid,
    ):
        return json.loads(metrics_path.read_text(encoding="utf-8"))

    kernel = None
    if spec.kind != "direct":
        kernel = (
            kernel_from_config(config, kernel_type="gaussian", fwhm_m=spec.fwhm_m)
            if spec.kernel_name == "gaussian"
            else kernel_from_config(config, kernel_type="circular_mean")
        )
    # The allocation needs one radius; consistency reaggregation needs two.
    halo = 0 if kernel is None else 2 * max(int(kernel.halo_rows), int(kernel.halo_columns))
    working_path = output_root / "products.working.tif"
    checkpoint_path = output_root / "checkpoint.json"
    checkpoint = _load_or_initialize_checkpoint(
        checkpoint_path,
        working_path=working_path,
        config_hash=config_hash,
        spec=spec,
        grid=grid,
        tile_pixels=tile_pixels,
        halo_pixels=halo,
    )
    if not working_path.exists():
        _create_working_raster(working_path, grid=grid)

    metrics = _MetricAccumulator()
    completed = dict(checkpoint["tiles"])
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
        processing, crop = expanded_window(
            core_source,
            halo=halo,
            bounds_shape=(5200, 5200),
        )
        components, _ = _read_processing_inputs(
            ee_path,
            overture_path,
            window=processing,
            core_window=core_source,
            strict_minimum_observations=strict_minimum,
            broad_minimum_observations=broad_minimum,
        )
        layers = _calculate_stationary_tile(
            config,
            spec=spec,
            components=components,
            normalization=normalization,
            kernel=kernel,
            crop=crop,
        )
        _write_tile(working_path, core_local, layers)
        checksum = _window_checksum(working_path, core_local)
        completed[tile_id] = checksum
        checkpoint["tiles"] = completed
        _atomic_json(checkpoint_path, checkpoint)
        metrics.add(layers)

    expected_tiles = len(list(iter_core_windows((grid.height, grid.width), tile_pixels)))
    if len(completed) != expected_tiles:
        raise AssertionError("Not every reporting core was checkpointed")
    _promote_to_cog(working_path, final_path, spec=spec, config_hash=config_hash)
    _validate_final_cog(final_path, grid=grid)
    finished_metrics = metrics.finish()
    if (
        spec.kind == "stationary"
        and spec.kernel_name == "circular_mean_reference"
        and spec.radiance_contract == "strict"
    ):
        reference_path = (
            output_root.parent
            / f"{spec.proxy}__no_water_prior__circular_mean_reference"
            / "products.tif"
        )
        finished_metrics["water_comparison_to_no_water"] = _water_comparison(
            final_path,
            reference_path,
            ee_path=ee_path,
            analysis_window=analysis_window,
            tile_pixels=tile_pixels,
        )
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
        "processing_halo_pixels": halo,
        "checkpoint_tile_count": expected_tiles,
        "normalization": (
            normalization[spec.proxy][spec.water_variant] if spec.proxy is not None else None
        ),
        "metrics": finished_metrics,
    }
    _atomic_json(metrics_path, record)
    return record


def _calculate_stationary_tile(
    config: dict[str, Any],
    *,
    spec: FullCityConfiguration,
    components: dict[str, np.ndarray],
    normalization: dict[str, Any],
    kernel,
    crop: tuple[slice, slice],
) -> dict[str, np.ndarray]:
    radiance = (
        components["broad_radiance"]
        if spec.radiance_contract == "broad"
        else components["strict_radiance"]
    )
    radiance_valid = (
        components["broad_valid_mask"]
        if spec.radiance_contract == "broad"
        else components["strict_valid_mask"]
    )
    if spec.kind == "direct":
        allocation = direct_upsample_baseline(radiance, radiance_valid_mask=radiance_valid)[crop]
        return _baseline_layers(allocation)
    if spec.kind == "uniform":
        result = uniform_normalized_convolution_baseline(
            radiance,
            kernel=kernel,
            radiance_valid_mask=radiance_valid,
            **_operator_kwargs(config),
        )
    else:
        proxy = build_water_proxy_variant(
            components[f"{spec.proxy}_base"],
            variant=str(spec.water_variant),
            persistent_water_weight=components["persistent_water_weight"],
            spectral_water_weight=components["spectral_water_weight"],
            persistent_water_mask=components["persistent_water_mask"],
            mapped_infrastructure_mask=components["mapped_infrastructure_mask"],
            proxy_floor=float(config["validation"]["water_handling"]["proxy_floor"]),
        ).proxy
        result = apply_fork_form_allocation(
            radiance,
            proxy,
            kernel=kernel,
            radiance_valid_mask=radiance_valid,
            proxy_normalization_divisor=float(
                normalization[str(spec.proxy)][str(spec.water_variant)]["mean"]
            ),
            denominator_reference_mean_after_normalization=1.0,
            **_operator_kwargs(config),
        )
    return _result_layers(
        result,
        crop=crop,
        insufficient_threshold=float(
            config["validation"]["gate0"]["insufficient_proxy_mean_threshold"]
        ),
    )


def _run_native_configuration(*args, **kwargs) -> dict[str, Any]:
    """Run native polygons without ever substituting a stationary footprint.

    Native implementation is intentionally isolated because cells, not pixels,
    own its metric records.  Importing lazily keeps stationary workers small.
    """

    from nocturne.disaggregate.full_city_native import run_native_configuration

    return run_native_configuration(*args, **kwargs)


def _result_layers(
    result: AllocationResult,
    *,
    crop: tuple[slice, slice],
    insufficient_threshold: float,
) -> dict[str, np.ndarray]:
    return {
        "allocation": result.allocation[crop],
        "operator_consistency_error": result.operator_consistency_error[crop],
        "radiance_support_fraction": result.radiance_support_fraction[crop],
        "proxy_support_fraction": result.proxy_support_fraction[crop],
        "allocation_support_fraction": result.allocation_support_fraction[crop],
        "geometric_support_fraction": result.geometric_support_fraction[crop],
        "valid_output_mask": result.valid_output_mask[crop],
        "operator_consistency_valid_mask": result.operator_consistency_valid_mask[crop],
        "boundary_mask": result.boundary_mask[crop],
        "invalid_radiance_neighborhood_mask": (result.invalid_radiance_neighborhood_mask[crop]),
        "invalid_proxy_neighborhood_mask": result.invalid_proxy_neighborhood_mask[crop],
        "denominator_floor_mask": result.denominator_floor_mask[crop],
        "denominator_instability_mask": result.denominator_instability_mask[crop],
        "negative_radiance_input_mask": result.negative_radiance_input_mask[crop],
        "negative_preclip_output_mask": result.negative_preclip_output_mask[crop],
        "insufficient_proxy_support_mask": (
            np.isfinite(result.convolved_proxy[crop])
            & (result.convolved_proxy[crop] < insufficient_threshold)
        ),
    }


def _baseline_layers(allocation: np.ndarray) -> dict[str, np.ndarray]:
    finite = np.isfinite(allocation)
    nan = np.full(allocation.shape, np.nan, dtype=np.float32)
    false = np.zeros(allocation.shape, dtype=bool)
    return {
        **{name: (allocation if name == "allocation" else nan) for name in FLOAT_LAYER_NAMES},
        **{name: (finite if name == "valid_output_mask" else false) for name in MASK_LAYER_NAMES},
    }


class _MetricAccumulator:
    def __init__(self) -> None:
        self.pixel_count = 0
        self.counts = {name: 0 for name in MASK_LAYER_NAMES}
        self.error_count = 0
        self.error_sum = 0.0
        self.error_abs_sum = 0.0
        self.error_square_sum = 0.0

    def add(self, layers: dict[str, np.ndarray]) -> None:
        self.pixel_count += int(layers["allocation"].size)
        for name in MASK_LAYER_NAMES:
            self.counts[name] += int(np.asarray(layers[name], dtype=bool).sum())
        error = np.asarray(layers["operator_consistency_error"], dtype=np.float64)
        error = error[np.isfinite(error)]
        self.error_count += int(error.size)
        self.error_sum += float(error.sum())
        self.error_abs_sum += float(np.abs(error).sum())
        self.error_square_sum += float(np.square(error).sum())

    def add_from_raster(self, path: Path, window: Window) -> None:
        with rasterio.open(path) as dataset:
            arrays = {
                name: dataset.read(index + 1, window=_read_window(window))
                for index, name in enumerate(BAND_NAMES)
            }
        self.add(arrays)

    def finish(self) -> dict[str, Any]:
        count = self.error_count
        return {
            "pixel_count": self.pixel_count,
            **{f"{name}_pixel_count": value for name, value in self.counts.items()},
            "operator_consistency_sample_count": count,
            "operator_consistency_bias": self.error_sum / count if count else None,
            "operator_consistency_mae": self.error_abs_sum / count if count else None,
            "operator_consistency_rmse": (
                (self.error_square_sum / count) ** 0.5 if count else None
            ),
        }


def _create_working_raster(path: Path, *, grid) -> None:
    profile = {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": len(BAND_NAMES),
        "dtype": "float32",
        "crs": grid.crs,
        "transform": Affine(*grid.transform),
        "nodata": np.nan,
        "compress": "DEFLATE",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dataset:
        for index, name in enumerate(BAND_NAMES, start=1):
            dataset.set_band_description(index, name)


def _write_tile(path: Path, window: Window, layers: dict[str, np.ndarray]) -> None:
    with rasterio.open(path, "r+") as dataset:
        for index, name in enumerate(BAND_NAMES, start=1):
            dataset.write(
                np.asarray(layers[name], dtype=np.float32),
                index,
                window=window,
            )


def _window_checksum(path: Path, window: Window) -> str:
    digest = hashlib.sha256()
    with rasterio.open(path) as dataset:
        for index in range(1, len(BAND_NAMES) + 1):
            digest.update(dataset.read(index, window=_read_window(window)).tobytes())
    return digest.hexdigest()


def _read_window(window: Window) -> tuple[tuple[int, int], tuple[int, int]]:
    """Use integer index tuples to avoid Rasterio/NumPy 2.5 shape mutation."""

    return (
        (int(window.row_off), int(window.row_off + window.height)),
        (int(window.col_off), int(window.col_off + window.width)),
    )


def _promote_to_cog(
    working_path: Path,
    final_path: Path,
    *,
    spec: FullCityConfiguration,
    config_hash: str,
) -> None:
    temporary = final_path.with_suffix(".tmp.tif")
    # COGs are immutable in Rasterio/GDAL 3. Updating metadata after creation
    # can invalidate their byte layout, so attach all final tags to the tiled
    # working GeoTIFF and let the COG driver copy them during translation.
    with rasterio.open(working_path, "r+") as dataset:
        dataset.update_tags(
            configuration=spec.name,
            config_sha256=config_hash,
            analysis_semantics="full_city_tiled_allocation",
            exact_conservation_assumed="false",
        )
    rio_copy(
        working_path,
        temporary,
        driver="COG",
        compress="DEFLATE",
        blocksize=512,
        overview_resampling=Resampling.average.name,
        BIGTIFF="IF_SAFER",
    )
    temporary.replace(final_path)


def _water_comparison(
    allocation_path: Path,
    reference_path: Path,
    *,
    ee_path: Path,
    analysis_window: Window,
    tile_pixels: int,
) -> dict[str, Any]:
    """Compare one circular water variant to its corresponding no-water run."""

    if not reference_path.exists():
        raise ValueError(f"No-water reference must complete first: {reference_path}")
    count = 0
    difference_sum = 0.0
    absolute_sum = 0.0
    water_count = 0
    water_difference_sum = 0.0
    with (
        rasterio.open(allocation_path) as allocation,
        rasterio.open(reference_path) as reference,
        rasterio.open(ee_path) as source,
    ):
        bands = {
            name: index
            for index, name in enumerate(source.descriptions, start=1)
            if name is not None
        }
        water_band = bands["persistent_water_mask"]
        for local in iter_core_windows((allocation.height, allocation.width), tile_pixels):
            current = allocation.read(1, window=_read_window(local)).astype(np.float64)
            baseline = reference.read(1, window=_read_window(local)).astype(np.float64)
            source_window = Window(
                analysis_window.col_off + local.col_off,
                analysis_window.row_off + local.row_off,
                local.width,
                local.height,
            )
            water_raw = source.read(water_band, window=_read_window(source_window))
            valid = np.isfinite(current) & np.isfinite(baseline)
            difference = current[valid] - baseline[valid]
            count += int(difference.size)
            difference_sum += float(difference.sum())
            absolute_sum += float(np.abs(difference).sum())
            water = valid & np.isfinite(water_raw) & (water_raw >= 0.5)
            water_difference = current[water] - baseline[water]
            water_count += int(water_difference.size)
            water_difference_sum += float(water_difference.sum())
    return {
        "reference_path": str(reference_path),
        "reference_sha256": sha256_file(reference_path),
        "comparison_pixel_count": count,
        "mean_allocation_difference": difference_sum / count if count else None,
        "mean_absolute_allocation_difference": absolute_sum / count if count else None,
        "persistent_water_pixel_count": water_count,
        "persistent_water_mean_allocation_difference": (
            water_difference_sum / water_count if water_count else None
        ),
    }


def _write_overview_gallery(path: Path, city_records: list[dict[str, Any]]) -> None:
    """Write the gallery only after every final COG has passed reopen checks."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = max(len(city["configurations"]) for city in city_records)
    figure, axes = plt.subplots(
        rows,
        len(city_records),
        figsize=(8, max(12, rows * 1.7)),
        squeeze=False,
    )
    for column, city in enumerate(city_records):
        configurations = city["configurations"]
        for row in range(rows):
            axis = axes[row, column]
            axis.set_axis_off()
            if row >= len(configurations):
                continue
            record = configurations[row]
            raster_path = Path(record["path"])
            with rasterio.open(raster_path) as dataset:
                _validate_final_cog(raster_path, grid=_RecordGrid(record))
                image = dataset.read(
                    1,
                    out_shape=(160, 160),
                    resampling=Resampling.average,
                ).astype(np.float32)
            finite = image[np.isfinite(image)]
            if finite.size:
                low, high = np.percentile(finite, (2, 98))
                if high <= low:
                    high = low + 1
                axis.imshow(image, cmap="magma", vmin=low, vmax=high)
            axis.set_title(record["configuration"]["name"], fontsize=6)
            if row == 0:
                axis.text(
                    0.5,
                    1.18,
                    city["city_id"],
                    transform=axis.transAxes,
                    ha="center",
                    fontsize=9,
                    weight="bold",
                )
    figure.suptitle("PSF disaggregation full-city allocation overview", fontsize=12)
    figure.tight_layout()
    figure.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(figure)


class _RecordGrid:
    """Minimal grid adapter for final artifact revalidation."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.crs = record["crs"]
        self.transform = tuple(record["transform"])


def _validate_final_cog(path: Path, *, grid) -> None:
    with rasterio.open(path) as dataset:
        if (dataset.height, dataset.width) != (5000, 5000):
            raise ValueError(f"Full-city COG shape mismatch: {path}")
        if dataset.crs is None or dataset.crs.to_string() != grid.crs:
            raise ValueError(f"Full-city COG CRS mismatch: {path}")
        if dataset.transform != Affine(*grid.transform):
            raise ValueError(f"Full-city COG transform mismatch: {path}")
        if dataset.descriptions != BAND_NAMES:
            raise ValueError(f"Full-city COG band descriptions mismatch: {path}")
        if dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") != "COG":
            raise ValueError(f"Full-city artifact is not a COG: {path}")


def _completed_artifact_is_valid(path: Path, metrics_path: Path, *, config_hash: str, grid) -> bool:
    if not path.exists() or not metrics_path.exists():
        return False
    try:
        record = json.loads(metrics_path.read_text(encoding="utf-8"))
        if record.get("status") != "complete":
            return False
        if record.get("sha256") != sha256_file(path):
            return False
        if record["configuration"] is None:
            return False
        _validate_final_cog(path, grid=grid)
        with rasterio.open(path) as dataset:
            return dataset.tags().get("config_sha256") == config_hash
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return False


def _load_or_initialize_checkpoint(
    path: Path,
    *,
    working_path: Path,
    config_hash: str,
    spec: FullCityConfiguration,
    grid,
    tile_pixels: int,
    halo_pixels: int,
) -> dict[str, Any]:
    identity = {
        "schema_version": 1,
        "config_sha256": config_hash,
        "configuration": asdict(spec),
        "shape": [grid.height, grid.width],
        "crs": grid.crs,
        "transform": list(grid.transform),
        "tile_pixels": tile_pixels,
        "processing_halo_pixels": halo_pixels,
        "working_path": str(working_path),
    }
    if path.exists():
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        if {key: checkpoint.get(key) for key in identity} != identity:
            raise ValueError(f"Checkpoint identity does not match requested run: {path}")
        return checkpoint
    return {**identity, "tiles": {}}


def _window_id(window: Window) -> str:
    return (
        f"r{int(window.row_off):05d}_c{int(window.col_off):05d}_"
        f"h{int(window.height):04d}_w{int(window.width):04d}"
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _require_single_threaded_numerics() -> None:
    bad = {
        name: os.environ.get(name)
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        if os.environ.get(name) != "1"
    }
    if bad:
        raise RuntimeError(
            "Set OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, and MKL_NUM_THREADS=1 "
            f"before the full-city run; current values: {bad}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    parser.add_argument("--tile-pixels", type=int, default=DEFAULT_TILE_PIXELS)
    parser.add_argument("--city")
    parser.add_argument("--configuration")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the frozen matrix without executing it.",
    )
    args = parser.parse_args(argv)
    config = load_disaggregation_config(args.config)
    if args.list:
        for grid in build_city_grid_specs(args.config):
            if args.city and grid.city_id != args.city:
                continue
            for spec in build_configuration_matrix(config, grid.city_id):
                print(f"{grid.city_id}\t{spec.name}")
        return 0
    print(
        run_full_city(
            args.config,
            tile_pixels=args.tile_pixels,
            only_city=args.city,
            only_configuration=args.configuration,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
