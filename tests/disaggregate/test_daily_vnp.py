from __future__ import annotations

from types import SimpleNamespace

from nocturne.disaggregate.daily_vnp import _daily_grid, _date_strings


def test_daily_dates_cover_locked_half_open_interval() -> None:
    dates = _date_strings("2024-01-11", "2024-04-20")

    assert len(dates) == 100
    assert dates[0] == "2024-01-11"
    assert dates[-1] == "2024-04-19"


def test_daily_grid_preserves_analysis_origin_and_extent() -> None:
    grid = SimpleNamespace(
        width=5000,
        height=5000,
        resolution_m=10,
        transform=(10, 0, 1000, 0, -10, 51000),
    )

    transform, shape = _daily_grid(grid)

    assert shape == (100, 100)
    assert tuple(transform)[:6] == (500, 0, 1000, 0, -500, 51000)
