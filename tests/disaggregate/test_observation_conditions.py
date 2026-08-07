from __future__ import annotations

import numpy as np

from nocturne.disaggregate.observation_conditions import apply_daily_coarse_operator


def test_daily_operator_preserves_uniform_proxy_and_requires_full_support() -> None:
    radiance = np.full((2, 5, 5), 10.0)
    radiance[1, 2, 2] = np.nan
    proxy = np.ones((5, 5))

    methods, complete = apply_daily_coarse_operator(radiance, proxy)

    assert np.allclose(
        methods["uniform"][0, 1:-1, 1:-1],
        methods["built_form_no_water"][0, 1:-1, 1:-1],
    )
    assert methods["uniform"][0, 2, 2] == 10.0
    assert not complete[1, 2, 2]
    assert np.isnan(methods["built_form_no_water"][1, 2, 2])
