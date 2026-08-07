from __future__ import annotations

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import rasterio
import shapely
from affine import Affine
from pyproj import Transformer

from nocturne.disaggregate.overture_bundle import (
    _rasterize_building_fraction,
    _rasterize_weighted_road_length,
    _write_multiband_cog_atomic,
)


def test_overture_rasterization_preserves_building_union_and_road_length(
    tmp_path,
) -> None:
    buildings_path = tmp_path / "buildings.parquet"
    segments_path = tmp_path / "segments.parquet"
    building = shapely.box(0, 0, 10, 10)
    road = shapely.LineString([(0, 15), (20, 15)])
    pq.write_table(
        pa.table({"geometry": pa.array([shapely.to_wkb(building)])}),
        buildings_path,
    )
    pq.write_table(
        pa.table(
            {
                "geometry": pa.array([shapely.to_wkb(road)]),
                "subtype": ["road"],
                "class": ["primary"],
            }
        ),
        segments_path,
    )
    transform = Affine(10, 0, 0, 0, -10, 20)
    identity = Transformer.from_crs("EPSG:32618", "EPSG:32618", always_xy=True)

    building_fraction, building_metrics = _rasterize_building_fraction(
        buildings_path,
        shape=(2, 2),
        transform=transform,
        source_to_target=identity,
        target_resolution_m=10,
        subpixel_resolution_m=2,
    )
    road_length, road_metrics = _rasterize_weighted_road_length(
        segments_path,
        shape=(2, 2),
        transform=transform,
        source_to_target=identity,
        road_weights={"primary": 1.0},
        unlisted_road_class_policy="error",
        maximum_segment_length_m=1,
        conservation_relative_tolerance=1e-6,
    )

    assert building_fraction.tolist() == [[0.0, 0.0], [1.0, 0.0]]
    assert building_metrics["sampled_binary_union_area_m2"] == 100
    assert road_length[0].tolist() == pytest.approx([10.0, 10.0])
    assert road_length[1].tolist() == [0.0, 0.0]
    assert road_metrics["input_weighted_centerline_length_m"] == pytest.approx(20)
    assert road_metrics[
        "allocation_relative_error_before_float32_accumulation"
    ] == pytest.approx(0)


def test_overture_bundle_writer_preserves_band_and_grid_contract(tmp_path) -> None:
    path = tmp_path / "overture_structure_bundle.tif"
    bands = [
        "building_fraction",
        "weighted_road_density_normalized",
        "built_form_base_proxy_unwatered_unfloored",
        "mapped_infrastructure_mask",
    ]
    layers = tuple(
        np.full((32, 32), value, dtype=np.float32)
        for value in (0.1, 0.2, 0.3, 1.0)
    )
    transform = Affine(10, 0, 100, 0, -10, 200)

    _write_multiband_cog_atomic(
        path,
        layers=layers,
        band_names=bands,
        crs="EPSG:32618",
        transform=transform,
        overview_resampling="nearest",
        tags={"decision_id": "OVERTURE-RASTER-001"},
    )

    with rasterio.open(path) as dataset:
        assert dataset.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        assert list(dataset.descriptions) == bands
        assert dataset.transform == transform
        assert dataset.tags()["decision_id"] == "OVERTURE-RASTER-001"
