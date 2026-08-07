"""Declared allocation-kernel builders for the structural-allocation sprint.

The objects in this module are algorithmic neighborhood assumptions. They are
not measurements or estimates of the physical VIIRS point-spread function.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np
import shapely


@dataclass(frozen=True)
class AllocationKernel:
    """A normalized, odd-sized neighborhood kernel with auditable semantics."""

    kernel_type: str
    weights: np.ndarray
    resolution_m: float
    semantics: str
    parameter_name: str | None = None
    parameter_value: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        weights = np.asarray(self.weights, dtype=np.float64)
        if weights.ndim != 2:
            raise ValueError("Allocation-kernel weights must be two-dimensional")
        if not all(size % 2 == 1 for size in weights.shape):
            raise ValueError("Allocation kernels must have odd row and column counts")
        if not np.isfinite(weights).all():
            raise ValueError("Allocation-kernel weights must be finite")
        if np.any(weights < 0):
            raise ValueError("Allocation-kernel weights must be nonnegative")
        total = float(weights.sum(dtype=np.float64))
        if not total > 0:
            raise ValueError("Allocation-kernel weights must have positive mass")
        normalized = np.ascontiguousarray(weights / total)
        normalized.setflags(write=False)
        if float(self.resolution_m) <= 0:
            raise ValueError("Allocation-kernel resolution must be positive")
        object.__setattr__(self, "weights", normalized)
        object.__setattr__(self, "resolution_m", float(self.resolution_m))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def halo_rows(self) -> int:
        return self.weights.shape[0] // 2

    @property
    def halo_columns(self) -> int:
        return self.weights.shape[1] // 2

    @property
    def identifier(self) -> str:
        if self.parameter_name is None:
            return self.kernel_type
        value = f"{float(self.parameter_value):g}"
        return f"{self.kernel_type}_{self.parameter_name}_{value}"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "kernel_type": self.kernel_type,
            "kernel_parameter_name": self.parameter_name,
            "kernel_parameter_value": self.parameter_value,
            "kernel_semantics": self.semantics,
            "kernel_resolution_m": self.resolution_m,
            "kernel_shape": list(self.weights.shape),
            "kernel_mass": float(self.weights.sum(dtype=np.float64)),
            **dict(self.metadata),
        }


def circular_mean_kernel(*, radius_m: float, resolution_m: float) -> AllocationKernel:
    """Return the literal Fork-form circular averaging reference kernel."""

    radius_m = float(radius_m)
    resolution_m = float(resolution_m)
    if radius_m <= 0:
        raise ValueError("Circular-kernel radius must be positive")
    half_size = math.ceil(radius_m / resolution_m)
    offsets = np.arange(-half_size, half_size + 1, dtype=np.float64) * resolution_m
    xx, yy = np.meshgrid(offsets, offsets)
    weights = (xx * xx + yy * yy <= radius_m * radius_m + 1e-9).astype(np.float64)
    return AllocationKernel(
        kernel_type="circular_mean",
        weights=weights,
        resolution_m=resolution_m,
        parameter_name="radius_m",
        parameter_value=radius_m,
        semantics="literal_fork_form_reference_not_measured_viirs_psf",
        metadata={"support_definition": "fine_pixel_centers_within_radius"},
    )


def gaussian_kernel(
    *,
    fwhm_m: float,
    resolution_m: float,
    truncate_sigma: float = 4.0,
) -> AllocationKernel:
    """Return a normalized Gaussian sensitivity with an explicitly named FWHM."""

    fwhm_m = float(fwhm_m)
    resolution_m = float(resolution_m)
    truncate_sigma = float(truncate_sigma)
    if fwhm_m <= 0:
        raise ValueError("Gaussian FWHM must be positive")
    if truncate_sigma < 3.0:
        raise ValueError("Gaussian truncation must retain at least three sigma")
    sigma_m = fwhm_m / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    half_size = math.ceil(truncate_sigma * sigma_m / resolution_m)
    offsets = np.arange(-half_size, half_size + 1, dtype=np.float64) * resolution_m
    xx, yy = np.meshgrid(offsets, offsets)
    weights = np.exp(-0.5 * (xx * xx + yy * yy) / (sigma_m * sigma_m))
    return AllocationKernel(
        kernel_type="gaussian",
        weights=weights,
        resolution_m=resolution_m,
        parameter_name="fwhm_m",
        parameter_value=fwhm_m,
        semantics="named_allocation_sensitivity_not_recovered_viirs_psf",
        metadata={
            "sigma_m": sigma_m,
            "truncate_sigma": truncate_sigma,
            "support_radius_m": half_size * resolution_m,
        },
    )


def native_footprint_kernel(
    *,
    footprint,
    resolution_m: float,
    footprint_id: str | None = None,
) -> AllocationKernel:
    """Rasterize one actual native footprint into exact fine-pixel overlap weights.

    ``footprint`` must use local projected metre coordinates relative to the
    allocation location. The result is a local stationary-kernel sensitivity.
    Full-city use must retain the source polygon ID because native geographic
    cells vary slightly after projection to each city's UTM grid.
    """

    resolution_m = float(resolution_m)
    if resolution_m <= 0:
        raise ValueError("Footprint-kernel resolution must be positive")
    geometry = shapely.make_valid(footprint)
    if shapely.is_empty(geometry) or float(shapely.area(geometry)) <= 0:
        raise ValueError("Native footprint must have positive projected area")
    min_x, min_y, max_x, max_y = shapely.bounds(geometry)
    half_columns = max(
        1,
        math.ceil(max(abs(min_x), abs(max_x)) / resolution_m + 0.5),
    )
    half_rows = max(
        1,
        math.ceil(max(abs(min_y), abs(max_y)) / resolution_m + 0.5),
    )
    weights = np.zeros((2 * half_rows + 1, 2 * half_columns + 1), dtype=np.float64)
    pixel_area_m2 = resolution_m * resolution_m
    for row_offset in range(-half_rows, half_rows + 1):
        center_y = -row_offset * resolution_m
        for column_offset in range(-half_columns, half_columns + 1):
            center_x = column_offset * resolution_m
            pixel = shapely.box(
                center_x - resolution_m / 2.0,
                center_y - resolution_m / 2.0,
                center_x + resolution_m / 2.0,
                center_y + resolution_m / 2.0,
            )
            overlap_area = float(shapely.area(shapely.intersection(geometry, pixel)))
            weights[row_offset + half_rows, column_offset + half_columns] = (
                overlap_area / pixel_area_m2
            )
    nonzero_rows, nonzero_columns = np.nonzero(weights > 0)
    if len(nonzero_rows) == 0:
        raise ValueError("Native footprint did not overlap the fine grid")
    retained_half_rows = max(
        abs(int(nonzero_rows.min()) - half_rows),
        abs(int(nonzero_rows.max()) - half_rows),
    )
    retained_half_columns = max(
        abs(int(nonzero_columns.min()) - half_columns),
        abs(int(nonzero_columns.max()) - half_columns),
    )
    weights = weights[
        half_rows - retained_half_rows : half_rows + retained_half_rows + 1,
        half_columns - retained_half_columns : half_columns + retained_half_columns + 1,
    ]
    footprint_area_m2 = float(shapely.area(geometry))
    rasterized_area_m2 = float(weights.sum(dtype=np.float64) * pixel_area_m2)
    if not np.isclose(rasterized_area_m2, footprint_area_m2, rtol=0, atol=1e-6):
        raise ValueError("Fine-grid overlap weights do not reproduce footprint area")
    return AllocationKernel(
        kernel_type="native_vnp_footprint",
        weights=weights,
        resolution_m=resolution_m,
        parameter_name="projected_area_m2",
        parameter_value=footprint_area_m2,
        semantics="actual_projected_source_cell_overlap_local_sensitivity",
        metadata={
            "footprint_id": footprint_id,
            "footprint_projected_area_m2": footprint_area_m2,
            "rasterized_overlap_area_m2": rasterized_area_m2,
            "support_definition": "exact_polygon_fine_pixel_area_overlap",
            "stationarity_warning": (
                "one local native cell footprint; do not silently apply across a "
                "full city without auditing footprint variation"
            ),
        },
    )


def kernel_from_config(
    config: Mapping[str, Any],
    *,
    kernel_type: str,
    footprint=None,
    footprint_id: str | None = None,
    fwhm_m: float | None = None,
) -> AllocationKernel:
    """Construct one declared kernel and reject undeclared parameter values."""

    resolution_m = float(config["grid"]["resolution_m"])
    if kernel_type == "circular_mean":
        reference = config["kernels"]["reference"]
        return circular_mean_kernel(
            radius_m=float(reference["radius_m"]),
            resolution_m=resolution_m,
        )
    sensitivities = {
        sensitivity["type"]: sensitivity
        for sensitivity in config["kernels"]["sensitivities"]
    }
    if kernel_type == "gaussian":
        if fwhm_m is None:
            raise ValueError("Gaussian sensitivity requires fwhm_m")
        declared = sensitivities["gaussian"]
        if float(fwhm_m) not in {float(value) for value in declared["values"]}:
            raise ValueError(f"Undeclared Gaussian FWHM: {fwhm_m}")
        return gaussian_kernel(
            fwhm_m=fwhm_m,
            resolution_m=resolution_m,
            truncate_sigma=float(declared["truncate_sigma"]),
        )
    if kernel_type == "native_vnp_footprint":
        if footprint is None:
            raise ValueError("Native-footprint sensitivity requires an actual polygon")
        return native_footprint_kernel(
            footprint=footprint,
            resolution_m=resolution_m,
            footprint_id=footprint_id,
        )
    raise ValueError(f"Unsupported allocation-kernel type: {kernel_type}")
