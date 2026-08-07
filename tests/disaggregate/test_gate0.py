from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from pyproj import Transformer

from nocturne.disaggregate.built import _aggregate_geometry_measure
from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.gate0 import (
    _attach_native_vnp_cells,
    _gate_analysis_samples,
    _gate_metrics,
    _load_gate0_chunk_cache,
    _rectangular_chunks,
    _write_gate0_chunk_cache,
)


def test_rectangular_chunks_cover_bounds() -> None:
    chunks = _rectangular_chunks([-2, -1, 2, 1], divisions=2)
    assert chunks == [
        [-2.0, -1.0, 0.0, 0.0],
        [0.0, -1.0, 2.0, 0.0],
        [-2.0, 0.0, 0.0, 1.0],
        [0.0, 0.0, 2.0, 1.0],
    ]


def test_water_exclusion_is_not_counted_as_unsupported_land() -> None:
    config = load_disaggregation_config("configs/psf_disaggregation.yaml")
    samples = pd.DataFrame(
        {
            "proxy_mean": [0.05, 0.20, 0.30, 0.40, 0.50, 0.60],
            "vnp_median_corrected_ntl": [1, 2, 3, 4, 5, 6],
            "persistent_water_weight_mean": [0.0, 1, 1, 1, 1, 1],
            "s2_valid_count_mean": [10, 10, 10, 10, 10, 10],
            "vnp_valid_observation_count": [20, 20, 20, 20, 20, 20],
            "vnp_quality_retained_fraction": [0.8, 0.8, 0.8, 0.8, 0.8, 0.8],
            "coarse_cell_area_m2": [180_000] * 6,
            "radius_m": np.arange(6, dtype=float) ** 1.5,
            "block_id": [f"block-{index}" for index in range(6)],
        }
    )

    metrics = _gate_metrics(
        samples,
        city_id="test_city",
        allocation_proxy="test_proxy",
        config=config,
    )

    assert metrics["excluded_water_cell_fraction"] == 1 / 6
    assert metrics["insufficient_land_proxy_fraction"] == 0
    assert metrics["automated_checks"]["support"] is True


def test_native_vnp_cell_polygons_use_the_source_affine() -> None:
    samples = pd.DataFrame(
        {
            "longitude": [0.25, 0.75],
            "latitude": [0.75, 0.25],
            "coarse_cell_area_m2_earth_engine": [1.0, 1.0],
        }
    )
    grid = SimpleNamespace(crs="EPSG:32631")
    attached = _attach_native_vnp_cells(
        samples,
        projection_info={
            "crs": "EPSG:4326",
            "transform": [0.5, 0, 0, 0, -0.5, 1],
        },
        target_grid=grid,
    )

    assert attached["coarse_cell_id"].tolist() == ["vnp_r0_c0", "vnp_r1_c1"]
    assert attached["coarse_cell_west"].tolist() == [0.0, 0.5]
    assert attached["coarse_cell_east"].tolist() == [0.5, 1.0]
    assert (attached["coarse_cell_area_m2"] > 0).all()


def test_s2_gate0_requires_declared_coarse_footprint_support() -> None:
    config = load_disaggregation_config("configs/psf_disaggregation.yaml")
    samples = pd.DataFrame(
        {
            "s2_supported_area_fraction": [0.89, 0.90, 1.0],
            "proxy_mean": [0.2, 0.3, 0.4],
        }
    )

    eligible = _gate_analysis_samples(
        samples,
        allocation_proxy="s2_only_ablation",
        config=config,
    )

    assert eligible["s2_supported_area_fraction"].tolist() == [0.90, 1.0]


def test_gate0_chunk_cache_is_config_scoped_and_complete(tmp_path) -> None:
    path = tmp_path / "chunk_01.json"
    rows = [{"longitude": 1.0, "latitude": 2.0}]
    bounds = [0.0, 0.0, 2.0, 3.0]
    _write_gate0_chunk_cache(
        path,
        city_id="test_city",
        chunk_number=1,
        chunk_bounds=bounds,
        config_sha256_value="abc123",
        rows=rows,
    )

    assert _load_gate0_chunk_cache(
        path,
        city_id="test_city",
        chunk_number=1,
        chunk_bounds=bounds,
        config_sha256_value="abc123",
    ) == rows
    assert (
        _load_gate0_chunk_cache(
            path,
            city_id="test_city",
            chunk_number=1,
            chunk_bounds=bounds,
            config_sha256_value="different",
        )
        is None
    )


def test_overture_area_is_split_by_exact_cell_intersection(tmp_path) -> None:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32631", always_xy=True)
    cells_wgs84 = np.asarray(
        [
            shapely.box(0.00, 0.00, 0.01, 0.01),
            shapely.box(0.01, 0.00, 0.02, 0.01),
        ]
    )
    cells_projected = shapely.transform(
        cells_wgs84,
        transformer.transform,
        interleaved=False,
    )
    source_wgs84 = shapely.box(0.005, 0.002, 0.015, 0.008)
    source_path = tmp_path / "buildings.parquet"
    pq.write_table(
        pa.table({"geometry": [shapely.to_wkb(source_wgs84)]}),
        source_path,
    )

    actual = _aggregate_geometry_measure(
        source_path,
        cell_tree=shapely.STRtree(cells_projected),
        cell_polygons=cells_projected,
        transformer=transformer,
        row_count=2,
        geometry_kind="area",
    )
    projected_source = shapely.transform(
        source_wgs84,
        transformer.transform,
        interleaved=False,
    )
    expected = shapely.area(shapely.intersection(cells_projected, projected_source))

    assert np.all(actual > 0)
    assert np.allclose(actual, expected)
    assert np.isclose(actual.sum(), shapely.area(projected_source))


def test_overture_unlisted_road_class_fails_explicitly(tmp_path) -> None:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32631", always_xy=True)
    cell = np.asarray([shapely.box(0.00, 0.00, 0.02, 0.02)])
    cell_projected = shapely.transform(
        cell,
        transformer.transform,
        interleaved=False,
    )
    source_path = tmp_path / "segments.parquet"
    pq.write_table(
        pa.table(
            {
                "geometry": [
                    shapely.to_wkb(
                        shapely.LineString([(0.001, 0.001), (0.019, 0.019)])
                    )
                ],
                "subtype": ["road"],
                "class": ["new_unregistered_class"],
            }
        ),
        source_path,
    )

    with pytest.raises(ValueError, match="Unlisted Overture road classes"):
        _aggregate_geometry_measure(
            source_path,
            cell_tree=shapely.STRtree(cell_projected),
            cell_polygons=cell_projected,
            transformer=transformer,
            row_count=1,
            geometry_kind="weighted_road_length",
            road_weights={"primary": 1.0},
            unlisted_road_class_policy="error",
        )
