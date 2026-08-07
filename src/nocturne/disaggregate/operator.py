"""Pure-array Fork-form radiance allocation and diagnostics.

The implementation is independent of Earth Engine and geospatial I/O. Arrays
must already share one explicitly aligned grid. Invalid values are represented
by NaN or explicit masks; water must never be encoded as invalid radiance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import ndimage, signal

from nocturne.disaggregate.kernels import AllocationKernel


@dataclass(frozen=True)
class ProxyNormalization:
    support_pixel_count: int
    mean_before: float
    divisor: float
    mean_after: float

    def to_metadata(self) -> dict[str, float | int]:
        return {
            "proxy_normalization_support_pixel_count": self.support_pixel_count,
            "proxy_mean_before_normalization": self.mean_before,
            "proxy_normalization_divisor": self.divisor,
            "proxy_mean_after_normalization": self.mean_after,
        }


@dataclass(frozen=True)
class AllocationResult:
    allocation: np.ndarray
    normalized_proxy: np.ndarray
    convolved_radiance: np.ndarray
    convolved_proxy: np.ndarray
    reaggregated_allocation: np.ndarray
    operator_consistency_error: np.ndarray
    radiance_support_fraction: np.ndarray
    proxy_support_fraction: np.ndarray
    allocation_support_fraction: np.ndarray
    geometric_support_fraction: np.ndarray
    valid_output_mask: np.ndarray
    operator_consistency_valid_mask: np.ndarray
    boundary_mask: np.ndarray
    invalid_radiance_neighborhood_mask: np.ndarray
    invalid_proxy_neighborhood_mask: np.ndarray
    denominator_floor_mask: np.ndarray
    denominator_instability_mask: np.ndarray
    negative_radiance_input_mask: np.ndarray
    negative_preclip_output_mask: np.ndarray
    proxy_normalization: ProxyNormalization
    denominator_epsilon: float
    kernel: AllocationKernel
    metadata: dict[str, Any]


@dataclass(frozen=True)
class NativeFootprintAllocationResult:
    allocation: np.ndarray
    normalized_proxy: np.ndarray
    fine_coverage_fraction: np.ndarray
    cell_proxy_mean: np.ndarray
    cell_proxy_support_fraction: np.ndarray
    cell_reaggregated_allocation: np.ndarray
    cell_operator_consistency_error: np.ndarray
    cell_valid_mask: np.ndarray
    denominator_floor_cell_mask: np.ndarray
    negative_preclip_output_mask: np.ndarray
    proxy_normalization: ProxyNormalization
    denominator_epsilon: float
    metadata: dict[str, Any]


def allocation_gain_from_components(
    normalized_proxy: np.ndarray,
    convolved_proxy: np.ndarray,
    *,
    valid_mask: np.ndarray,
    denominator_epsilon: float,
) -> np.ndarray:
    """Return the radiance-blind fine-grid gain rho/(k tensor rho)."""

    proxy = _as_2d_float(normalized_proxy, name="normalized_proxy")
    denominator = _as_2d_float(convolved_proxy, name="convolved_proxy")
    if proxy.shape != denominator.shape:
        raise ValueError("Normalized and convolved proxy shapes differ")
    valid = _as_matching_bool(valid_mask, shape=proxy.shape, name="valid_mask")
    epsilon = float(denominator_epsilon)
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("Denominator epsilon must be finite and positive")
    valid &= np.isfinite(proxy) & np.isfinite(denominator)
    gain = np.full(proxy.shape, np.nan, dtype=np.float32)
    gain[valid] = (
        proxy[valid].astype(np.float64)
        / np.maximum(denominator[valid].astype(np.float64), epsilon)
    ).astype(np.float32)
    return gain


def normalize_proxy_mean_one(
    proxy: np.ndarray,
    *,
    valid_mask: np.ndarray | None = None,
    divisor: float | None = None,
) -> tuple[np.ndarray, ProxyNormalization]:
    """Normalize a nonnegative proxy over its finite declared analysis support."""

    array = _as_2d_float(proxy, name="proxy")
    support = np.isfinite(array)
    if valid_mask is not None:
        support &= _as_matching_bool(valid_mask, shape=array.shape, name="valid_mask")
    if np.any(array[support] < 0):
        raise ValueError("Structural allocation proxy must be nonnegative")
    support_count = int(support.sum())
    if support_count == 0:
        raise ValueError("Structural allocation proxy has no finite analysis support")
    mean_before = float(np.mean(array[support], dtype=np.float64))
    resolved_divisor = mean_before if divisor is None else float(divisor)
    if not math.isfinite(resolved_divisor) or resolved_divisor <= 0:
        raise ValueError("Proxy-normalization divisor must be finite and positive")
    normalized = np.full(array.shape, np.nan, dtype=np.float32)
    normalized[support] = (array[support] / resolved_divisor).astype(np.float32)
    mean_after = float(np.mean(normalized[support], dtype=np.float64))
    return normalized, ProxyNormalization(
        support_pixel_count=support_count,
        mean_before=mean_before,
        divisor=resolved_divisor,
        mean_after=mean_after,
    )


def apply_fork_form_allocation(
    radiance: np.ndarray,
    proxy: np.ndarray,
    *,
    kernel: AllocationKernel,
    denominator_epsilon_relative: float,
    denominator_instability_threshold_relative: float,
    minimum_valid_support_fraction: float = 1.0,
    support_fraction_tolerance: float = 1e-6,
    domain_mask: np.ndarray | None = None,
    radiance_valid_mask: np.ndarray | None = None,
    proxy_valid_mask: np.ndarray | None = None,
    proxy_normalization_divisor: float | None = None,
    denominator_reference_mean_after_normalization: float | None = None,
) -> AllocationResult:
    """Apply the declared locally normalized allocation and compute diagnostics."""

    source = _as_2d_float(radiance, name="radiance")
    structural = _as_2d_float(proxy, name="proxy")
    if source.shape != structural.shape:
        raise ValueError(
            f"Radiance shape {source.shape} does not match proxy shape {structural.shape}"
        )
    shape = source.shape
    domain = (
        np.ones(shape, dtype=bool)
        if domain_mask is None
        else _as_matching_bool(domain_mask, shape=shape, name="domain_mask")
    )
    source_valid = np.isfinite(source) & domain
    if radiance_valid_mask is not None:
        source_valid &= _as_matching_bool(
            radiance_valid_mask,
            shape=shape,
            name="radiance_valid_mask",
        )
    structural_valid = np.isfinite(structural) & domain
    if proxy_valid_mask is not None:
        structural_valid &= _as_matching_bool(
            proxy_valid_mask,
            shape=shape,
            name="proxy_valid_mask",
        )
    normalized_proxy, normalization = normalize_proxy_mean_one(
        structural,
        valid_mask=structural_valid,
        divisor=proxy_normalization_divisor,
    )
    structural_valid = np.isfinite(normalized_proxy) & structural_valid

    minimum_support = float(minimum_valid_support_fraction)
    tolerance = float(support_fraction_tolerance)
    if not 0.0 < minimum_support <= 1.0:
        raise ValueError("Minimum valid kernel support must be in (0, 1]")
    if tolerance <= 0:
        raise ValueError("Support-fraction tolerance must be positive")
    epsilon_relative = float(denominator_epsilon_relative)
    instability_relative = float(denominator_instability_threshold_relative)
    if not epsilon_relative > 0:
        raise ValueError("Relative denominator epsilon must be positive")
    if not instability_relative >= epsilon_relative:
        raise ValueError("Instability threshold must be at least the denominator epsilon")

    convolved_radiance, radiance_support, geometric_support = _masked_kernel_mean(
        source,
        valid_mask=source_valid,
        domain_mask=domain,
        kernel=kernel,
    )
    convolved_proxy, proxy_support, proxy_geometric_support = _masked_kernel_mean(
        normalized_proxy,
        valid_mask=structural_valid,
        domain_mask=domain,
        kernel=kernel,
    )
    if not np.allclose(
        geometric_support,
        proxy_geometric_support,
        rtol=0,
        atol=tolerance,
    ):
        raise AssertionError("Common-grid geometric support differs between inputs")

    denominator_reference = (
        normalization.mean_after
        if denominator_reference_mean_after_normalization is None
        else float(denominator_reference_mean_after_normalization)
    )
    if not math.isfinite(denominator_reference) or denominator_reference <= 0:
        raise ValueError(
            "Denominator reference after normalization must be finite and positive"
        )
    epsilon = epsilon_relative * denominator_reference
    instability_threshold = instability_relative * denominator_reference
    finite_denominator = np.isfinite(convolved_proxy)
    denominator_floor_mask = (
        finite_denominator & (convolved_proxy < epsilon) & domain
    )
    denominator_instability_mask = (
        finite_denominator & (convolved_proxy < instability_threshold) & domain
    )
    boundary_mask = domain & (geometric_support < 1.0 - tolerance)
    invalid_radiance_neighborhood = domain & (
        radiance_support < geometric_support - tolerance
    )
    invalid_proxy_neighborhood = domain & (
        proxy_support < geometric_support - tolerance
    )
    valid_output = (
        structural_valid
        & np.isfinite(convolved_radiance)
        & finite_denominator
        & (radiance_support >= minimum_support - tolerance)
        & (proxy_support >= minimum_support - tolerance)
        & (geometric_support >= minimum_support - tolerance)
    )

    preclip = np.full(shape, np.nan, dtype=np.float32)
    safe_denominator = np.maximum(convolved_proxy, epsilon)
    preclip_values = (
        normalized_proxy[valid_output].astype(np.float64)
        * convolved_radiance[valid_output].astype(np.float64)
        / safe_denominator[valid_output].astype(np.float64)
    )
    preclip[valid_output] = preclip_values.astype(np.float32)
    negative_preclip = np.isfinite(preclip) & (preclip < 0)
    allocation = np.full(shape, np.nan, dtype=np.float32)
    allocation[valid_output] = np.maximum(preclip[valid_output], 0.0)

    (
        reaggregated,
        allocation_support,
        allocation_geometric_support,
    ) = _masked_kernel_mean(
        allocation,
        valid_mask=np.isfinite(allocation),
        domain_mask=domain,
        kernel=kernel,
    )
    if not np.allclose(
        geometric_support,
        allocation_geometric_support,
        rtol=0,
        atol=tolerance,
    ):
        raise AssertionError("Allocation reaggregation changed geometric support")
    consistency_valid = (
        source_valid
        & np.isfinite(reaggregated)
        & (allocation_support >= minimum_support - tolerance)
        & (geometric_support >= minimum_support - tolerance)
    )
    consistency_error = np.full(shape, np.nan, dtype=np.float32)
    consistency_error[consistency_valid] = (
        source[consistency_valid] - reaggregated[consistency_valid]
    ).astype(np.float32)

    metadata = {
        "operator_name": "fork_form_locally_normalized_radiance_allocation",
        "formula": "L_tilde = h * (k tensor l) / max(k tensor h, epsilon)",
        "exact_conservation_assumed": False,
        "edge_padding": "constant_invalid",
        "minimum_valid_kernel_support_fraction": minimum_support,
        "support_fraction_tolerance": tolerance,
        "denominator_epsilon_relative": epsilon_relative,
        "denominator_epsilon_reference": "normalized_proxy_mean",
        "denominator_reference_mean_after_normalization": denominator_reference,
        "denominator_instability_threshold_relative": instability_relative,
        "negative_radiance_policy": (
            "retain_in_numerator_then_clip_negative_output_after_recording"
        ),
        "output_nodata": "nan",
        **kernel.to_metadata(),
        **normalization.to_metadata(),
    }
    return AllocationResult(
        allocation=allocation,
        normalized_proxy=normalized_proxy,
        convolved_radiance=convolved_radiance,
        convolved_proxy=convolved_proxy,
        reaggregated_allocation=reaggregated,
        operator_consistency_error=consistency_error,
        radiance_support_fraction=radiance_support,
        proxy_support_fraction=proxy_support,
        allocation_support_fraction=allocation_support,
        geometric_support_fraction=geometric_support,
        valid_output_mask=valid_output,
        operator_consistency_valid_mask=consistency_valid,
        boundary_mask=boundary_mask,
        invalid_radiance_neighborhood_mask=invalid_radiance_neighborhood,
        invalid_proxy_neighborhood_mask=invalid_proxy_neighborhood,
        denominator_floor_mask=denominator_floor_mask,
        denominator_instability_mask=denominator_instability_mask,
        negative_radiance_input_mask=np.isfinite(source) & (source < 0) & domain,
        negative_preclip_output_mask=negative_preclip,
        proxy_normalization=normalization,
        denominator_epsilon=epsilon,
        kernel=kernel,
        metadata=metadata,
    )


def direct_upsample_baseline(
    radiance: np.ndarray,
    *,
    domain_mask: np.ndarray | None = None,
    radiance_valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Return the no-allocation baseline without smoothing."""

    source = _as_2d_float(radiance, name="radiance")
    valid = np.isfinite(source)
    if domain_mask is not None:
        valid &= _as_matching_bool(domain_mask, shape=source.shape, name="domain_mask")
    if radiance_valid_mask is not None:
        valid &= _as_matching_bool(
            radiance_valid_mask,
            shape=source.shape,
            name="radiance_valid_mask",
        )
    output = np.full(source.shape, np.nan, dtype=np.float32)
    output[valid] = source[valid].astype(np.float32)
    return output


def uniform_normalized_convolution_baseline(
    radiance: np.ndarray,
    *,
    kernel: AllocationKernel,
    denominator_epsilon_relative: float,
    denominator_instability_threshold_relative: float,
    minimum_valid_support_fraction: float = 1.0,
    support_fraction_tolerance: float = 1e-6,
    domain_mask: np.ndarray | None = None,
    radiance_valid_mask: np.ndarray | None = None,
) -> AllocationResult:
    """Return the declared h=1 smoothed null using the same operator and guards."""

    source = _as_2d_float(radiance, name="radiance")
    domain = (
        np.ones(source.shape, dtype=bool)
        if domain_mask is None
        else _as_matching_bool(domain_mask, shape=source.shape, name="domain_mask")
    )
    uniform = np.full(source.shape, np.nan, dtype=np.float32)
    uniform[domain] = 1.0
    return apply_fork_form_allocation(
        source,
        uniform,
        kernel=kernel,
        denominator_epsilon_relative=denominator_epsilon_relative,
        denominator_instability_threshold_relative=(
            denominator_instability_threshold_relative
        ),
        minimum_valid_support_fraction=minimum_valid_support_fraction,
        support_fraction_tolerance=support_fraction_tolerance,
        domain_mask=domain,
        radiance_valid_mask=radiance_valid_mask,
    )


def summarize_allocation_result(
    result: AllocationResult,
    *,
    source_radiance: np.ndarray,
    insufficient_proxy_threshold: float,
) -> dict[str, Any]:
    """Return JSON-safe Gate 1 diagnostics without making a correctness claim."""

    source = _as_2d_float(source_radiance, name="source_radiance")
    if source.shape != result.allocation.shape:
        raise ValueError("Source radiance and allocation result shapes differ")
    error = result.operator_consistency_error[
        result.operator_consistency_valid_mask
    ].astype(np.float64)
    if error.size:
        error_metrics = {
            "operator_consistency_sample_count": int(error.size),
            "operator_consistency_bias": float(np.mean(error)),
            "operator_consistency_mae": float(np.mean(np.abs(error))),
            "operator_consistency_rmse": float(np.sqrt(np.mean(error * error))),
        }
    else:
        error_metrics = {
            "operator_consistency_sample_count": 0,
            "operator_consistency_bias": None,
            "operator_consistency_mae": None,
            "operator_consistency_rmse": None,
        }
    finite_positive_authority = np.isfinite(source) & (source > 0)
    total_positive_authority = float(source[finite_positive_authority].sum())
    insufficient = (
        finite_positive_authority
        & np.isfinite(result.convolved_proxy)
        & (result.convolved_proxy < float(insufficient_proxy_threshold))
    )
    insufficient_authority = float(source[insufficient].sum())
    authority_share = (
        insufficient_authority / total_positive_authority
        if total_positive_authority > 0
        else None
    )
    pixel_count = source.size
    return {
        **result.metadata,
        **error_metrics,
        "array_shape": list(source.shape),
        "valid_output_pixel_count": int(result.valid_output_mask.sum()),
        "valid_output_fraction": float(result.valid_output_mask.sum() / pixel_count),
        "boundary_pixel_count": int(result.boundary_mask.sum()),
        "invalid_radiance_neighborhood_pixel_count": int(
            result.invalid_radiance_neighborhood_mask.sum()
        ),
        "invalid_proxy_neighborhood_pixel_count": int(
            result.invalid_proxy_neighborhood_mask.sum()
        ),
        "denominator_floor_pixel_count": int(result.denominator_floor_mask.sum()),
        "denominator_instability_pixel_count": int(
            result.denominator_instability_mask.sum()
        ),
        "negative_radiance_input_pixel_count": int(
            result.negative_radiance_input_mask.sum()
        ),
        "negative_preclip_output_pixel_count": int(
            result.negative_preclip_output_mask.sum()
        ),
        "positive_radiance_authority_total": total_positive_authority,
        "positive_radiance_authority_on_insufficient_proxy_support": (
            insufficient_authority
        ),
        "positive_radiance_authority_insufficient_support_share": authority_share,
        "insufficient_proxy_threshold": float(insufficient_proxy_threshold),
        "interpretation": (
            "operator consistency and support diagnostics; not independent "
            "fine-scale validation"
        ),
    }


def allocate_by_native_footprints(
    proxy: np.ndarray,
    *,
    overlap_cell_index: np.ndarray,
    overlap_rows: np.ndarray,
    overlap_columns: np.ndarray,
    overlap_area_m2: np.ndarray,
    cell_radiance: np.ndarray,
    pixel_area_m2: float,
    denominator_epsilon_relative: float,
    minimum_cell_proxy_support_fraction: float = 1.0,
    support_fraction_tolerance: float = 1e-6,
    domain_mask: np.ndarray | None = None,
    proxy_valid_mask: np.ndarray | None = None,
    proxy_normalization_divisor: float | None = None,
    denominator_reference_mean_after_normalization: float | None = None,
) -> NativeFootprintAllocationResult:
    """Allocate cell radiance using exact native-polygon/fine-pixel overlaps.

    This is the major aligned-footprint sensitivity. It is deliberately
    separate from the stationary convolution operator: each native source cell
    retains its actual projected polygon and area.
    """

    structural = _as_2d_float(proxy, name="proxy")
    shape = structural.shape
    domain = (
        np.ones(shape, dtype=bool)
        if domain_mask is None
        else _as_matching_bool(domain_mask, shape=shape, name="domain_mask")
    )
    proxy_support = np.isfinite(structural) & domain
    if proxy_valid_mask is not None:
        proxy_support &= _as_matching_bool(
            proxy_valid_mask,
            shape=shape,
            name="proxy_valid_mask",
        )
    normalized_proxy, normalization = normalize_proxy_mean_one(
        structural,
        valid_mask=proxy_support,
        divisor=proxy_normalization_divisor,
    )

    cell_index = np.asarray(overlap_cell_index, dtype=np.int64)
    rows = np.asarray(overlap_rows, dtype=np.int64)
    columns = np.asarray(overlap_columns, dtype=np.int64)
    areas = np.asarray(overlap_area_m2, dtype=np.float64)
    if not (cell_index.ndim == rows.ndim == columns.ndim == areas.ndim == 1):
        raise ValueError("Native-footprint overlap arrays must be one-dimensional")
    if len({len(cell_index), len(rows), len(columns), len(areas)}) != 1:
        raise ValueError("Native-footprint overlap arrays must have equal length")
    if np.any((rows < 0) | (rows >= shape[0])):
        raise ValueError("Native-footprint row index is outside the fine grid")
    if np.any((columns < 0) | (columns >= shape[1])):
        raise ValueError("Native-footprint column index is outside the fine grid")
    if np.any(~np.isfinite(areas)) or np.any(areas <= 0):
        raise ValueError("Native-footprint overlap areas must be finite and positive")
    radiance = np.asarray(cell_radiance, dtype=np.float64)
    if radiance.ndim != 1:
        raise ValueError("Native-cell radiance must be one-dimensional")
    cell_count = len(radiance)
    if cell_count == 0 or np.any((cell_index < 0) | (cell_index >= cell_count)):
        raise ValueError("Native-footprint cell indices do not match cell radiance")
    pixel_area = float(pixel_area_m2)
    if pixel_area <= 0:
        raise ValueError("Fine-pixel area must be positive")
    if float(denominator_epsilon_relative) <= 0:
        raise ValueError("Relative denominator epsilon must be positive")

    total_cell_area = np.bincount(
        cell_index,
        weights=areas,
        minlength=cell_count,
    )
    overlap_proxy = normalized_proxy[rows, columns].astype(np.float64)
    overlap_valid = (
        np.isfinite(overlap_proxy)
        & proxy_support[rows, columns]
        & np.isfinite(radiance[cell_index])
    )
    valid_cell_area = np.bincount(
        cell_index[overlap_valid],
        weights=areas[overlap_valid],
        minlength=cell_count,
    )
    weighted_proxy = np.bincount(
        cell_index[overlap_valid],
        weights=areas[overlap_valid] * overlap_proxy[overlap_valid],
        minlength=cell_count,
    )
    cell_proxy_mean = np.full(cell_count, np.nan, dtype=np.float64)
    np.divide(
        weighted_proxy,
        valid_cell_area,
        out=cell_proxy_mean,
        where=valid_cell_area > 0,
    )
    cell_support_fraction = np.zeros(cell_count, dtype=np.float64)
    np.divide(
        valid_cell_area,
        total_cell_area,
        out=cell_support_fraction,
        where=total_cell_area > 0,
    )
    denominator_reference = (
        normalization.mean_after
        if denominator_reference_mean_after_normalization is None
        else float(denominator_reference_mean_after_normalization)
    )
    if not math.isfinite(denominator_reference) or denominator_reference <= 0:
        raise ValueError(
            "Denominator reference after normalization must be finite and positive"
        )
    epsilon = float(denominator_epsilon_relative) * denominator_reference
    tolerance = float(support_fraction_tolerance)
    minimum_support = float(minimum_cell_proxy_support_fraction)
    cell_valid = (
        np.isfinite(radiance)
        & np.isfinite(cell_proxy_mean)
        & (cell_support_fraction >= minimum_support - tolerance)
    )
    floor_cells = cell_valid & (cell_proxy_mean < epsilon)
    safe_cell_denominator = np.maximum(cell_proxy_mean, epsilon)
    overlap_eligible = overlap_valid & cell_valid[cell_index]
    overlap_preclip = np.full(len(areas), np.nan, dtype=np.float64)
    overlap_preclip[overlap_eligible] = (
        overlap_proxy[overlap_eligible]
        * radiance[cell_index[overlap_eligible]]
        / safe_cell_denominator[cell_index[overlap_eligible]]
    )
    negative_preclip_overlap = np.isfinite(overlap_preclip) & (overlap_preclip < 0)
    overlap_allocation = np.maximum(overlap_preclip, 0.0)

    flat_index = rows * shape[1] + columns
    weighted_contribution = np.zeros(len(areas), dtype=np.float64)
    weighted_contribution[overlap_eligible] = (
        overlap_allocation[overlap_eligible]
        * areas[overlap_eligible]
        / pixel_area
    )
    allocation_flat = np.bincount(
        flat_index[overlap_eligible],
        weights=weighted_contribution[overlap_eligible],
        minlength=shape[0] * shape[1],
    )
    coverage_flat = np.bincount(
        flat_index,
        weights=areas / pixel_area,
        minlength=shape[0] * shape[1],
    )
    allocation = allocation_flat.reshape(shape).astype(np.float32)
    coverage = coverage_flat.reshape(shape).astype(np.float32)
    allocation[coverage <= tolerance] = np.nan

    final_at_overlap = allocation[rows, columns].astype(np.float64)
    final_valid_overlap = np.isfinite(final_at_overlap)
    reaggregated_weight = np.bincount(
        cell_index[final_valid_overlap],
        weights=areas[final_valid_overlap] * final_at_overlap[final_valid_overlap],
        minlength=cell_count,
    )
    reaggregated_area = np.bincount(
        cell_index[final_valid_overlap],
        weights=areas[final_valid_overlap],
        minlength=cell_count,
    )
    reaggregated = np.full(cell_count, np.nan, dtype=np.float64)
    np.divide(
        reaggregated_weight,
        reaggregated_area,
        out=reaggregated,
        where=reaggregated_area > 0,
    )
    cell_error = np.full(cell_count, np.nan, dtype=np.float64)
    comparison_valid = cell_valid & np.isfinite(reaggregated)
    cell_error[comparison_valid] = radiance[comparison_valid] - reaggregated[
        comparison_valid
    ]
    negative_pixel_mask = np.zeros(shape, dtype=bool)
    if negative_preclip_overlap.any():
        negative_pixel_mask.flat[
            np.unique(flat_index[negative_preclip_overlap])
        ] = True
    return NativeFootprintAllocationResult(
        allocation=allocation,
        normalized_proxy=normalized_proxy,
        fine_coverage_fraction=coverage,
        cell_proxy_mean=cell_proxy_mean.astype(np.float32),
        cell_proxy_support_fraction=cell_support_fraction.astype(np.float32),
        cell_reaggregated_allocation=reaggregated.astype(np.float32),
        cell_operator_consistency_error=cell_error.astype(np.float32),
        cell_valid_mask=cell_valid,
        denominator_floor_cell_mask=floor_cells,
        negative_preclip_output_mask=negative_pixel_mask,
        proxy_normalization=normalization,
        denominator_epsilon=epsilon,
        metadata={
            "operator_name": "native_vnp_footprint_area_overlap_sensitivity",
            "kernel_type": "native_vnp_footprint",
            "kernel_semantics": (
                "actual_projected_source_cell_polygon_area_overlap_major_sensitivity"
            ),
            "exact_conservation_assumed": False,
            "minimum_cell_proxy_support_fraction": minimum_support,
            "support_fraction_tolerance": tolerance,
            "fine_pixel_area_m2": pixel_area,
            "denominator_reference_mean_after_normalization": denominator_reference,
            "native_cell_count": cell_count,
            "overlap_record_count": len(areas),
            **normalization.to_metadata(),
        },
    )


def _masked_kernel_mean(
    values: np.ndarray,
    *,
    valid_mask: np.ndarray,
    domain_mask: np.ndarray,
    kernel: AllocationKernel,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = _as_2d_float(values, name="values")
    valid = _as_matching_bool(valid_mask, shape=data.shape, name="valid_mask")
    domain = _as_matching_bool(domain_mask, shape=data.shape, name="domain_mask")
    valid &= domain & np.isfinite(data)
    weights = kernel.weights
    filled = np.where(valid, data, 0.0).astype(np.float32, copy=False)
    weighted_sum = _correlate_constant_zero(filled, weights)
    support = _correlate_constant_zero(valid.astype(np.float32), weights)
    geometric_support = _correlate_constant_zero(
        domain.astype(np.float32),
        weights,
    )
    mean = np.full(data.shape, np.nan, dtype=np.float32)
    np.divide(
        weighted_sum,
        support,
        out=mean,
        where=support > np.finfo(np.float32).eps,
    )
    np.clip(support, 0.0, 1.0, out=support)
    np.clip(geometric_support, 0.0, 1.0, out=geometric_support)
    return mean, support, geometric_support


def _correlate_constant_zero(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Correlate with invalid-zero padding, using FFT for large declared kernels."""

    if weights.size <= 1024:
        return ndimage.correlate(
            values,
            weights,
            mode="constant",
            cval=0.0,
        ).astype(np.float32)
    # fftconvolve performs convolution, so reverse the weights to preserve the
    # footprint-relative correlation convention used by the direct path.
    correlated = signal.fftconvolve(
        values,
        weights[::-1, ::-1],
        mode="same",
    )
    return correlated.astype(np.float32)


def _as_2d_float(value: np.ndarray, *, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError(f"{name} must be a two-dimensional array")
    return array


def _as_matching_bool(
    value: np.ndarray,
    *,
    shape: tuple[int, int],
    name: str,
) -> np.ndarray:
    array = np.asarray(value, dtype=bool)
    if array.ndim != 2 or array.shape != shape:
        raise ValueError(f"{name} shape {array.shape} does not match {shape}")
    return array
