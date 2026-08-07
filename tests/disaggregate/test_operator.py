from __future__ import annotations

import numpy as np

from nocturne.disaggregate.kernels import circular_mean_kernel
from nocturne.disaggregate.operator import (
    allocate_by_native_footprints,
    allocation_gain_from_components,
    apply_fork_form_allocation,
    direct_upsample_baseline,
    summarize_allocation_result,
    uniform_normalized_convolution_baseline,
)


def test_allocation_gain_is_proxy_only_ratio_with_explicit_validity() -> None:
    proxy = np.array([[0.4, 1.0], [2.0, 3.0]], dtype=np.float32)
    denominator = np.array([[0.5, 1.0], [1.0, 0.0]], dtype=np.float32)
    valid = np.array([[True, True], [False, True]])

    gain = allocation_gain_from_components(
        proxy,
        denominator,
        valid_mask=valid,
        denominator_epsilon=0.25,
    )

    assert np.allclose(gain[[0, 0, 1], [0, 1, 1]], [0.8, 1.0, 12.0])
    assert np.isnan(gain[1, 0])


def _apply(radiance: np.ndarray, proxy: np.ndarray):
    return apply_fork_form_allocation(
        radiance,
        proxy,
        kernel=circular_mean_kernel(radius_m=20, resolution_m=10),
        denominator_epsilon_relative=1e-6,
        denominator_instability_threshold_relative=0.05,
        minimum_valid_support_fraction=1.0,
        support_fraction_tolerance=1e-6,
    )


def test_constant_fields_are_constant_away_from_boundaries() -> None:
    radiance = np.full((31, 31), 7.0)
    proxy = np.full((31, 31), 3.0)

    result = _apply(radiance, proxy)

    assert np.allclose(result.allocation[result.valid_output_mask], 7.0)
    assert np.allclose(
        result.operator_consistency_error[result.operator_consistency_valid_mask],
        0.0,
        atol=1e-6,
    )
    assert result.boundary_mask.any()
    assert not result.valid_output_mask[result.boundary_mask].any()
    assert np.isclose(result.proxy_normalization.mean_after, 1.0)


def test_direct_and_uniform_nulls_are_distinct() -> None:
    radiance = np.zeros((31, 31), dtype=float)
    radiance[15, 15] = 10.0
    direct = direct_upsample_baseline(radiance)
    uniform = uniform_normalized_convolution_baseline(
        radiance,
        kernel=circular_mean_kernel(radius_m=20, resolution_m=10),
        denominator_epsilon_relative=1e-6,
        denominator_instability_threshold_relative=0.05,
    )

    assert direct[15, 15] == 10.0
    assert 0 < uniform.allocation[15, 15] < direct[15, 15]
    assert not np.allclose(
        direct[uniform.valid_output_mask],
        uniform.allocation[uniform.valid_output_mask],
    )


def test_nodata_reduces_support_and_propagates_to_primary_valid_mask() -> None:
    radiance = np.ones((31, 31), dtype=float)
    radiance[15, 15] = np.nan
    proxy = np.ones_like(radiance)

    result = _apply(radiance, proxy)

    assert result.radiance_support_fraction[15, 15] < 1.0
    assert result.invalid_radiance_neighborhood_mask[15, 15]
    assert not result.valid_output_mask[15, 15]
    assert np.isnan(result.allocation[15, 15])
    assert result.valid_output_mask[5, 5]


def test_negative_output_is_clipped_only_after_diagnostic_is_recorded() -> None:
    radiance = np.full((31, 31), -2.0)
    proxy = np.ones_like(radiance)

    result = _apply(radiance, proxy)

    assert result.negative_radiance_input_mask.all()
    assert result.negative_preclip_output_mask[result.valid_output_mask].all()
    assert np.all(result.allocation[result.valid_output_mask] == 0)


def test_denominator_floor_and_instability_are_separate_diagnostics() -> None:
    radiance = np.ones((41, 41), dtype=float)
    proxy = np.ones_like(radiance)
    proxy[14:27, 14:27] = 0.0

    result = _apply(radiance, proxy)

    assert result.denominator_floor_mask[20, 20]
    assert result.denominator_instability_mask[20, 20]
    assert result.allocation[20, 20] == 0
    assert result.valid_output_mask[20, 20]


def test_operator_is_deterministic_and_summary_is_claim_bounded() -> None:
    rng = np.random.default_rng(42)
    radiance = rng.uniform(0, 20, size=(41, 41))
    proxy = rng.uniform(0.05, 1, size=(41, 41))

    first = _apply(radiance, proxy)
    second = _apply(radiance, proxy)
    summary = summarize_allocation_result(
        first,
        source_radiance=radiance,
        insufficient_proxy_threshold=0.05,
    )

    assert np.array_equal(first.allocation, second.allocation, equal_nan=True)
    assert summary["exact_conservation_assumed"] is False
    assert "not independent fine-scale validation" in summary["interpretation"]
    assert summary["operator_consistency_sample_count"] > 0


def test_exact_native_footprint_allocation_uses_overlap_areas() -> None:
    proxy = np.asarray([[1.0, 3.0], [1.0, 3.0]])
    result = allocate_by_native_footprints(
        proxy,
        overlap_cell_index=np.asarray([0, 0, 1, 1]),
        overlap_rows=np.asarray([0, 1, 0, 1]),
        overlap_columns=np.asarray([0, 0, 1, 1]),
        overlap_area_m2=np.asarray([100.0, 100.0, 100.0, 100.0]),
        cell_radiance=np.asarray([10.0, 20.0]),
        pixel_area_m2=100.0,
        denominator_epsilon_relative=1e-6,
    )

    assert np.allclose(result.allocation[:, 0], 10.0)
    assert np.allclose(result.allocation[:, 1], 20.0)
    assert np.allclose(result.cell_reaggregated_allocation, [10.0, 20.0])
    assert np.allclose(result.cell_operator_consistency_error, 0.0)
    assert np.all(result.cell_valid_mask)
    assert result.metadata["kernel_type"] == "native_vnp_footprint"


def test_native_footprint_allocation_accepts_citywide_normalization_divisor() -> None:
    proxy = np.asarray([[1.0, 3.0], [1.0, 3.0]])
    result = allocate_by_native_footprints(
        proxy,
        overlap_cell_index=np.asarray([0, 0, 1, 1]),
        overlap_rows=np.asarray([0, 1, 0, 1]),
        overlap_columns=np.asarray([0, 0, 1, 1]),
        overlap_area_m2=np.asarray([100.0, 100.0, 100.0, 100.0]),
        cell_radiance=np.asarray([10.0, 20.0]),
        pixel_area_m2=100.0,
        denominator_epsilon_relative=1e-6,
        proxy_normalization_divisor=4.0,
        denominator_reference_mean_after_normalization=1.0,
    )

    assert result.proxy_normalization.divisor == 4.0
    assert result.proxy_normalization.mean_after == 0.5
    assert result.denominator_epsilon == 1e-6
    assert np.allclose(result.cell_reaggregated_allocation, [10.0, 20.0])


def test_citywide_denominator_reference_is_not_replaced_by_tile_mean() -> None:
    radiance = np.ones((31, 31), dtype=float)
    proxy = np.full((31, 31), 4.0)

    result = apply_fork_form_allocation(
        radiance,
        proxy,
        kernel=circular_mean_kernel(radius_m=20, resolution_m=10),
        denominator_epsilon_relative=1e-6,
        denominator_instability_threshold_relative=0.05,
        proxy_normalization_divisor=2.0,
        denominator_reference_mean_after_normalization=1.0,
    )

    assert result.proxy_normalization.mean_after == 2.0
    assert result.denominator_epsilon == 1e-6
    assert (
        result.metadata["denominator_reference_mean_after_normalization"]
        == 1.0
    )
