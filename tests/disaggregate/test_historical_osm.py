from nocturne.disaggregate.historical_osm import _regular_tiles, _subdivide


def test_regular_tiles_cover_bounds_without_overlap() -> None:
    tiles = _regular_tiles((0.0, 0.0, 0.2, 0.1), 0.1)
    assert tiles == [(0.0, 0.0, 0.1, 0.1), (0.1, 0.0, 0.2, 0.1)]


def test_subdivide_returns_four_quadrants() -> None:
    assert _subdivide((0.0, 0.0, 2.0, 2.0)) == [
        (0.0, 0.0, 1.0, 1.0),
        (1.0, 0.0, 2.0, 1.0),
        (0.0, 1.0, 1.0, 2.0),
        (1.0, 1.0, 2.0, 2.0),
    ]
