from shapely.geometry import LineString, Polygon

from nocturne.disaggregate.water_reference import is_reference_water


def test_reference_water_requires_selected_class_and_areal_geometry() -> None:
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])
    assert is_reference_water("river", polygon)
    assert not is_reference_water("swimming_pool", polygon)
    assert not is_reference_water("river", LineString([(0, 0), (1, 1)]))
