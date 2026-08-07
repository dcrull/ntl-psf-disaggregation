from __future__ import annotations

import numpy as np

from nocturne.disaggregate.kernels import circular_mean_kernel
from nocturne.disaggregate.operator import apply_fork_form_allocation
from nocturne.disaggregate.validate import water_allocation_metrics
from nocturne.disaggregate.water import WATER_VARIANTS, build_water_proxy_variant


def test_all_water_variants_preserve_radiance_authority_and_report_transfer() -> None:
    shape = (61, 61)
    water = np.zeros(shape, dtype=bool)
    water[:, 31:] = True
    adjacent_land = np.zeros(shape, dtype=bool)
    adjacent_land[:, 27:31] = True
    infrastructure = np.zeros(shape, dtype=bool)
    infrastructure[29:32, 30:34] = True

    base_proxy = np.where(water, 0.6, 1.0)
    persistent_weight = np.where(water, 0.0, 1.0)
    spectral_weight = np.where(water, 0.2, 1.0)
    radiance = np.where(water, 4.0, 10.0)
    authority_before = radiance.copy()
    kernel = circular_mean_kernel(radius_m=20, resolution_m=10)

    results = {}
    for variant in WATER_VARIANTS:
        proxy_variant = build_water_proxy_variant(
            base_proxy,
            variant=variant,
            persistent_water_weight=persistent_weight,
            spectral_water_weight=spectral_weight,
            persistent_water_mask=water,
            mapped_infrastructure_mask=infrastructure,
            proxy_floor=0.05,
        )
        results[variant] = apply_fork_form_allocation(
            radiance,
            proxy_variant.proxy,
            kernel=kernel,
            denominator_epsilon_relative=1e-6,
            denominator_instability_threshold_relative=0.05,
        )
        assert np.array_equal(radiance, authority_before)
        assert np.nanmin(results[variant].allocation) >= 0

    reference = results["no_water_prior"].allocation
    reference_metrics = water_allocation_metrics(
        reference,
        source_radiance=radiance,
        water_reference_mask=water,
        adjacent_land_mask=adjacent_land,
    )
    hard_metrics = water_allocation_metrics(
        results["combined_hard_persistent_sensitivity_only"].allocation,
        source_radiance=radiance,
        water_reference_mask=water,
        adjacent_land_mask=adjacent_land,
        reference_allocation=reference,
    )

    assert reference_metrics["positive_source_radiance_authority_over_water"] > 0
    assert (
        hard_metrics["positive_source_radiance_authority_over_water"]
        == reference_metrics["positive_source_radiance_authority_over_water"]
    )
    assert (
        hard_metrics["allocated_radiance_over_water"]
        < reference_metrics["allocated_radiance_over_water"]
    )
    assert hard_metrics["adjacent_land_transfer_absolute_sum_vs_reference"] > 0
    assert "does not select a winner" in hard_metrics["interpretation"]


def test_infrastructure_override_restores_combined_water_modifier() -> None:
    base = np.ones((3, 3), dtype=float)
    persistent = np.full((3, 3), 0.2)
    spectral = np.full((3, 3), 0.5)
    infrastructure = np.zeros((3, 3), dtype=bool)
    infrastructure[1, 1] = True

    result = build_water_proxy_variant(
        base,
        variant="soft_with_mapped_infrastructure_override",
        persistent_water_weight=persistent,
        spectral_water_weight=spectral,
        persistent_water_mask=np.ones((3, 3), dtype=bool),
        mapped_infrastructure_mask=infrastructure,
        proxy_floor=0.05,
    )

    assert result.water_modifier[1, 1] == 1.0
    assert np.isclose(result.water_modifier[0, 0], 0.1)
    assert result.proxy[1, 1] > result.proxy[0, 0]
    assert result.infrastructure_override_mask[1, 1]
