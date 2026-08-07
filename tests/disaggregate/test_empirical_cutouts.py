from __future__ import annotations

import numpy as np

from nocturne.disaggregate.empirical_cutouts import (
    _aligned_nanmean,
    _select_block_indices_with_eligibility,
)


def test_aligned_nanmean_ignores_nodata_without_inventing_support() -> None:
    values = np.asarray(
        [
            [1.0, np.nan, 3.0, 5.0],
            [3.0, 5.0, np.nan, 7.0],
            [9.0, 9.0, np.nan, np.nan],
            [7.0, 7.0, np.nan, np.nan],
        ]
    )

    result = _aligned_nanmean(values, 2)

    assert np.allclose(result[0], [3.0, 5.0])
    assert result[1, 0] == 8.0
    assert np.isnan(result[1, 1])


def test_cutout_selection_excludes_unsupported_high_score_edges() -> None:
    building = np.asarray(
        [
            [0.99, 0.2, 0.1],
            [0.1, 0.8, 0.2],
            [0.1, 0.3, 0.4],
        ]
    )
    infrastructure = np.asarray(
        [
            [1.0, 0.5, 0.4],
            [0.2, 0.9, 0.5],
            [0.3, 0.7, 0.8],
        ]
    )
    water = np.asarray(
        [
            [0.0, 5.0, 90.0],
            [10.0, 0.0, 20.0],
            [80.0, 5.0, 60.0],
        ]
    )
    eligible = np.asarray(
        [
            [False, False, False],
            [False, True, True],
            [False, True, True],
        ]
    )

    selected = _select_block_indices_with_eligibility(
        building,
        infrastructure,
        water,
        eligible_mask=eligible,
        minimum_infrastructure_fraction=0.05,
    )

    assert selected["dense_building"] == (1, 1)
    assert selected["water_adjacent_infrastructure"] == (2, 2)
    assert all(eligible[index] for index in selected.values())
