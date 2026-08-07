"""Small, explicit validation metrics for allocation artifacts."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import numpy as np
from scipy import ndimage


def allocated_direct_region_metrics(
    allocation: np.ndarray,
    *,
    direct_radiance: np.ndarray,
    region_mask: np.ndarray,
) -> dict[str, Any]:
    """Summarize allocated versus direct radiance on common regional support.

    The ratio is a ratio of regional sums, not a mean of unstable pixelwise
    ratios. Negative direct observations are clipped to zero, matching the
    positive-radiance authority convention used by the water audit.
    """

    output = _float_2d(allocation, name="allocation")
    direct = _float_2d(direct_radiance, name="direct_radiance")
    if output.shape != direct.shape:
        raise ValueError("Allocation and direct-radiance shapes differ")
    region = _bool_matching(region_mask, shape=output.shape, name="region_mask")
    common = region & np.isfinite(output) & np.isfinite(direct)
    allocated_sum = float(output[common].sum(dtype=np.float64))
    direct_sum = float(np.maximum(direct[common], 0.0).sum(dtype=np.float64))
    ratio = allocated_sum / direct_sum if direct_sum > 0 else None
    return {
        "region_pixel_count": int(region.sum()),
        "common_support_pixel_count": int(common.sum()),
        "allocated_radiance_sum": allocated_sum,
        "positive_direct_radiance_sum": direct_sum,
        "allocated_to_direct_ratio": ratio,
        "reduction_fraction_vs_direct": 1.0 - ratio if ratio is not None else None,
    }


def water_allocation_metrics(
    allocation: np.ndarray,
    *,
    source_radiance: np.ndarray,
    water_reference_mask: np.ndarray,
    adjacent_land_mask: np.ndarray,
    reference_allocation: np.ndarray | None = None,
) -> dict[str, Any]:
    """Quantify water allocation and adjacent-land transfer without ranking variants."""

    output = _float_2d(allocation, name="allocation")
    source = _float_2d(source_radiance, name="source_radiance")
    if source.shape != output.shape:
        raise ValueError("Source radiance and allocation shapes differ")
    water = _bool_matching(
        water_reference_mask,
        shape=output.shape,
        name="water_reference_mask",
    )
    adjacent = _bool_matching(
        adjacent_land_mask,
        shape=output.shape,
        name="adjacent_land_mask",
    )
    if np.any(water & adjacent):
        raise ValueError("Water and adjacent-land metric masks must be disjoint")

    finite_output = np.isfinite(output)
    allocated_total = float(output[finite_output].sum(dtype=np.float64))
    allocated_water = float(output[finite_output & water].sum(dtype=np.float64))
    positive_source = np.where(np.isfinite(source), np.maximum(source, 0.0), 0.0)
    positive_authority_total = float(positive_source.sum(dtype=np.float64))
    positive_authority_water = float(positive_source[water].sum(dtype=np.float64))
    metrics: dict[str, Any] = {
        "allocated_radiance_total": allocated_total,
        "allocated_radiance_over_water": allocated_water,
        "allocated_radiance_over_water_share": (
            allocated_water / allocated_total if allocated_total > 0 else None
        ),
        "positive_source_radiance_authority_total": positive_authority_total,
        "positive_source_radiance_authority_over_water": positive_authority_water,
        "positive_source_radiance_authority_over_water_share": (
            positive_authority_water / positive_authority_total
            if positive_authority_total > 0
            else None
        ),
        "water_output_valid_pixel_count": int((finite_output & water).sum()),
        "adjacent_land_output_valid_pixel_count": int((finite_output & adjacent).sum()),
        "interpretation": (
            "diagnostic only; lower allocated-water radiance does not select a winner"
        ),
    }
    if reference_allocation is None:
        metrics.update(
            {
                "adjacent_land_transfer_sum_vs_reference": None,
                "adjacent_land_transfer_mean_vs_reference": None,
                "adjacent_land_transfer_absolute_sum_vs_reference": None,
            }
        )
        return metrics

    reference = _float_2d(reference_allocation, name="reference_allocation")
    if reference.shape != output.shape:
        raise ValueError("Reference allocation shape differs")
    comparison = adjacent & np.isfinite(output) & np.isfinite(reference)
    difference = output[comparison].astype(np.float64) - reference[comparison].astype(np.float64)
    metrics.update(
        {
            "adjacent_land_transfer_comparison_pixel_count": int(difference.size),
            "adjacent_land_transfer_sum_vs_reference": (
                float(difference.sum()) if difference.size else None
            ),
            "adjacent_land_transfer_mean_vs_reference": (
                float(difference.mean()) if difference.size else None
            ),
            "adjacent_land_transfer_absolute_sum_vs_reference": (
                float(np.abs(difference).sum()) if difference.size else None
            ),
        }
    )
    return metrics


def proxy_disagreement(
    first: np.ndarray,
    second: np.ndarray,
) -> tuple[np.ndarray, dict[str, float | int | None]]:
    """Return a signed allocation difference and summary over common support."""

    left = _float_2d(first, name="first")
    right = _float_2d(second, name="second")
    if left.shape != right.shape:
        raise ValueError("Proxy-allocation shapes differ")
    common = np.isfinite(left) & np.isfinite(right)
    difference = np.full(left.shape, np.nan, dtype=np.float32)
    difference[common] = left[common] - right[common]
    values = difference[common].astype(np.float64)
    return difference, {
        "common_support_pixel_count": int(values.size),
        "mean_signed_difference": float(values.mean()) if values.size else None,
        "mean_absolute_difference": (float(np.abs(values).mean()) if values.size else None),
        "root_mean_square_difference": (
            float(np.sqrt(np.mean(values * values))) if values.size else None
        ),
    }


def shoreline_distance_band_metrics(
    allocation: np.ndarray,
    *,
    reference_allocation: np.ndarray,
    water_reference_mask: np.ndarray,
    valid_reference_mask: np.ndarray | None = None,
    resolution_m: float,
    distance_edges_m: tuple[float, ...] | list[float],
) -> list[dict[str, Any]]:
    """Summarize allocation transfer over water and landward shoreline bands.

    Distance is measured from each land pixel to the nearest declared water
    pixel. Water itself is reported as a separate band. The function compares
    two already aligned allocations and never treats lower water allocation as
    intrinsically better.
    """

    output = _float_2d(allocation, name="allocation")
    reference = _float_2d(reference_allocation, name="reference_allocation")
    if output.shape != reference.shape:
        raise ValueError("Allocation and reference-allocation shapes differ")
    water = _bool_matching(
        water_reference_mask,
        shape=output.shape,
        name="water_reference_mask",
    )
    valid_reference = (
        np.ones(output.shape, dtype=bool)
        if valid_reference_mask is None
        else _bool_matching(
            valid_reference_mask,
            shape=output.shape,
            name="valid_reference_mask",
        )
    )
    water &= valid_reference
    if not np.any(water):
        raise ValueError("Water reference has no valid water pixels")
    resolution = float(resolution_m)
    if not np.isfinite(resolution) or resolution <= 0:
        raise ValueError("Resolution must be finite and positive")
    edges = np.asarray(distance_edges_m, dtype=np.float64)
    if (
        edges.ndim != 1
        or edges.size < 2
        or edges[0] != 0
        or np.any(~np.isfinite(edges))
        or np.any(np.diff(edges) <= 0)
    ):
        raise ValueError("Shoreline distance edges must start at zero and increase strictly")
    land = valid_reference & ~water
    distance = ndimage.distance_transform_edt(~water, sampling=resolution)
    common = np.isfinite(output) & np.isfinite(reference) & valid_reference
    difference = output.astype(np.float64) - reference.astype(np.float64)
    records = [
        _difference_band_record(
            "water",
            common & water,
            difference=difference,
            allocation=output,
            reference=reference,
            distance_min_m=None,
            distance_max_m=0.0,
        )
    ]
    for lower, upper in pairwise(edges):
        mask = common & land & (distance > lower) & (distance <= upper)
        records.append(
            _difference_band_record(
                f"land_{lower:g}_{upper:g}m",
                mask,
                difference=difference,
                allocation=output,
                reference=reference,
                distance_min_m=float(lower),
                distance_max_m=float(upper),
            )
        )
    beyond = common & land & (distance > edges[-1])
    records.append(
        _difference_band_record(
            f"land_gt_{edges[-1]:g}m",
            beyond,
            difference=difference,
            allocation=output,
            reference=reference,
            distance_min_m=float(edges[-1]),
            distance_max_m=None,
        )
    )
    return records


def matched_low_proxy_boundary_metrics(
    allocation: np.ndarray,
    *,
    reference_allocation: np.ndarray,
    low_proxy_land_mask: np.ndarray,
    excluded_mask: np.ndarray,
    resolution_m: float,
    distance_edges_m: tuple[float, ...] | list[float],
) -> list[dict[str, Any]]:
    """Return an inland low-proxy boundary control using the same distance bands."""

    low_proxy = _bool_matching(
        low_proxy_land_mask,
        shape=np.asarray(allocation).shape,
        name="low_proxy_land_mask",
    )
    excluded = _bool_matching(
        excluded_mask,
        shape=low_proxy.shape,
        name="excluded_mask",
    )
    control = low_proxy & ~excluded
    if not np.any(control):
        raise ValueError("Inland low-proxy control has no eligible pixels")
    return shoreline_distance_band_metrics(
        allocation,
        reference_allocation=reference_allocation,
        water_reference_mask=control,
        valid_reference_mask=~excluded,
        resolution_m=resolution_m,
        distance_edges_m=distance_edges_m,
    )


def _difference_band_record(
    name: str,
    mask: np.ndarray,
    *,
    difference: np.ndarray,
    allocation: np.ndarray,
    reference: np.ndarray,
    distance_min_m: float | None,
    distance_max_m: float | None,
) -> dict[str, Any]:
    values = difference[mask]
    current = allocation[mask].astype(np.float64)
    baseline = reference[mask].astype(np.float64)
    return {
        "band": name,
        "distance_min_m_exclusive": distance_min_m,
        "distance_max_m_inclusive": distance_max_m,
        "comparison_pixel_count": int(values.size),
        "allocation_sum": float(current.sum()) if values.size else None,
        "reference_allocation_sum": float(baseline.sum()) if values.size else None,
        "difference_sum": float(values.sum()) if values.size else None,
        "difference_mean": float(values.mean()) if values.size else None,
        "difference_mean_absolute": (float(np.abs(values).mean()) if values.size else None),
    }


def _float_2d(value: np.ndarray, *, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError(f"{name} must be two-dimensional")
    return array


def _bool_matching(
    value: np.ndarray,
    *,
    shape: tuple[int, int],
    name: str,
) -> np.ndarray:
    array = np.asarray(value, dtype=bool)
    if array.ndim != 2 or array.shape != shape:
        raise ValueError(f"{name} shape {array.shape} does not match {shape}")
    return array
