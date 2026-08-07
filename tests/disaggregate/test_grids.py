from __future__ import annotations

from nocturne.disaggregate.grids import (
    build_city_grid_specs,
    earth_engine_source_region_for_grid,
    expanded_grid_shape,
    expanded_grid_transform,
    utm_crs_for_lon_lat,
)


def test_pilot_city_utm_zones() -> None:
    assert utm_crs_for_lon_lat(-74.006, 40.7128) == "EPSG:32618"
    assert utm_crs_for_lon_lat(77.1025, 28.7041) == "EPSG:32643"


def test_city_grids_are_ten_meter_aligned() -> None:
    specs = build_city_grid_specs("configs/psf_disaggregation.yaml")
    assert [spec.city_id for spec in specs] == ["usa_new_york", "india_delhi"]
    for spec in specs:
        assert spec.resolution_m == 10
        assert spec.width == 5000
        assert spec.height == 5000
        assert spec.east - spec.west == 50_000
        assert spec.north - spec.south == 50_000
        assert spec.west % 10 == 0
        assert spec.south % 10 == 0
        assert spec.east % 10 == 0
        assert spec.north % 10 == 0
        assert spec.analysis_wgs84_ring[0] == spec.analysis_wgs84_ring[-1]
        assert expanded_grid_shape(spec, halo_m=1000) == (5200, 5200)
        expanded = expanded_grid_transform(spec, halo_m=1000)
        assert expanded[0] == 10
        assert expanded[2] == spec.west - 1000
        assert expanded[5] == spec.north + 1000


def test_earth_engine_export_region_uses_only_the_declared_edge_inset() -> None:
    class Geometry:
        @staticmethod
        def Rectangle(bounds, *, proj, geodesic):
            return bounds, proj, geodesic

    fake_earth_engine = type("FakeEarthEngine", (), {"Geometry": Geometry})

    grid = build_city_grid_specs("configs/psf_disaggregation.yaml")[0]
    bounds, projection, geodesic = earth_engine_source_region_for_grid(
        fake_earth_engine,
        grid,
        halo_m=1000,
        edge_inset_m=0.01,
    )

    assert bounds == [
        grid.west - 1000 + 0.01,
        grid.south - 1000 + 0.01,
        grid.east + 1000 - 0.01,
        grid.north + 1000 - 0.01,
    ]
    assert projection == grid.crs
    assert geodesic is False
