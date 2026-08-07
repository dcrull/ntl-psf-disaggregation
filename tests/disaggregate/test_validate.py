from __future__ import annotations

import numpy as np
import pytest

from nocturne.disaggregate.validate import (
    allocated_direct_region_metrics,
    matched_low_proxy_boundary_metrics,
    shoreline_distance_band_metrics,
)


def test_allocated_direct_region_metrics_use_ratio_of_sums_on_common_support() -> None:
    direct = np.array([[2.0, 4.0], [-3.0, np.nan]], dtype=np.float32)
    allocation = np.array([[1.0, 1.0], [5.0, 9.0]], dtype=np.float32)
    region = np.ones((2, 2), dtype=bool)

    metrics = allocated_direct_region_metrics(
        allocation,
        direct_radiance=direct,
        region_mask=region,
    )

    assert metrics["common_support_pixel_count"] == 3
    assert metrics["allocated_radiance_sum"] == pytest.approx(7.0)
    assert metrics["positive_direct_radiance_sum"] == pytest.approx(6.0)
    assert metrics["allocated_to_direct_ratio"] == pytest.approx(7.0 / 6.0)
    assert metrics["reduction_fraction_vs_direct"] == pytest.approx(-1.0 / 6.0)


def test_shoreline_distance_bands_separate_water_and_landward_transfer() -> None:
    water = np.zeros((7, 9), dtype=bool)
    water[:, :2] = True
    reference = np.ones(water.shape, dtype=np.float32)
    allocation = reference.copy()
    allocation[water] = 0.5
    allocation[:, 2:4] = 1.5

    rows = shoreline_distance_band_metrics(
        allocation,
        reference_allocation=reference,
        water_reference_mask=water,
        resolution_m=10,
        distance_edges_m=[0, 10, 30],
    )

    assert [row["band"] for row in rows] == [
        "water",
        "land_0_10m",
        "land_10_30m",
        "land_gt_30m",
    ]
    assert rows[0]["comparison_pixel_count"] == 14
    assert rows[0]["difference_mean"] == pytest.approx(-0.5)
    assert rows[1]["comparison_pixel_count"] == 7
    assert rows[1]["difference_mean"] == pytest.approx(0.5)
    assert rows[2]["comparison_pixel_count"] == 14
    assert rows[2]["difference_mean"] == pytest.approx(0.25)
    assert rows[3]["difference_mean"] == pytest.approx(0.0)


def test_shoreline_metrics_reject_empty_reference_water() -> None:
    values = np.ones((4, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="no valid water"):
        shoreline_distance_band_metrics(
            values,
            reference_allocation=values,
            water_reference_mask=np.zeros(values.shape, dtype=bool),
            resolution_m=10,
            distance_edges_m=[0, 100],
        )


def test_matched_inland_boundary_excludes_water_reference_area() -> None:
    reference = np.ones((8, 8), dtype=np.float32)
    allocation = reference.copy()
    allocation[:, 4:] += 2
    low_proxy = np.zeros(reference.shape, dtype=bool)
    low_proxy[:, 4:] = True
    excluded = np.zeros(reference.shape, dtype=bool)
    excluded[:2] = True

    rows = matched_low_proxy_boundary_metrics(
        allocation,
        reference_allocation=reference,
        low_proxy_land_mask=low_proxy,
        excluded_mask=excluded,
        resolution_m=10,
        distance_edges_m=[0, 20],
    )

    assert rows[0]["comparison_pixel_count"] == 24
    assert rows[0]["difference_mean"] == pytest.approx(2.0)
    assert all(row["comparison_pixel_count"] <= 24 for row in rows)
