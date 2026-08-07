from __future__ import annotations

import numpy as np
import pytest

from nocturne.disaggregate.overture_sensitivity import (
    _aligned_block_mean,
    _comparison_metrics,
    _select_block_indices,
)


def test_aligned_block_mean_and_nonradiance_selection_are_deterministic() -> None:
    values = np.arange(16, dtype=float).reshape(4, 4)
    assert _aligned_block_mean(values, 2).tolist() == [
        [2.5, 4.5],
        [10.5, 12.5],
    ]

    building = np.asarray([[0.9, 0.2], [0.1, 0.4]])
    infrastructure = np.asarray([[0.9, 0.5], [0.2, 0.8]])
    water = np.asarray([[0.0, 10.0], [80.0, 50.0]])
    selected = _select_block_indices(
        building,
        infrastructure,
        water,
        minimum_infrastructure_fraction=0.05,
    )

    assert selected["dense_building"] == (0, 0)
    assert selected["sparse_built"] == (0, 1)
    assert selected["water_adjacent_infrastructure"] == (1, 1)


def test_comparison_metrics_records_quantity_change() -> None:
    primary = np.asarray([[0.0, 0.5], [1.0, 0.5]])
    sensitivity = np.asarray([[0.0, 0.6], [0.9, 0.5]])

    metrics = _comparison_metrics(
        primary,
        sensitivity,
        quantity_scale=100,
        quantity_name="sampled_building_area_m2",
    )

    assert metrics["mean_absolute_difference"] == pytest.approx(0.05)
    assert metrics["changed_pixel_fraction"] == pytest.approx(0.5)
    assert metrics["primary_sampled_building_area_m2"] == pytest.approx(200)
    assert metrics["sensitivity_sampled_building_area_m2"] == pytest.approx(200)
