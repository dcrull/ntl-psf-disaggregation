from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from nocturne.disaggregate.source_preview import (
    _source_bundle_path,
    _summarize_vnp_qa_comparison,
)
from nocturne.disaggregate.vnp_coverage import _dominant_background


def test_dominant_native_vnp_background_uses_largest_day_count() -> None:
    values = {
        "vnp_background_land_desert_day_count": 0,
        "vnp_background_land_no_desert_day_count": 1,
        "vnp_background_inland_water_day_count": 0,
        "vnp_background_sea_water_day_count": 98,
        "vnp_background_coastal_day_count": 0,
    }

    assert _dominant_background(values) == "sea_water"


def test_source_preview_prefers_the_versioned_bundle(tmp_path) -> None:
    fallback = tmp_path / "usa_new_york_ee_source_bundle.tif"
    versioned = (
        tmp_path
        / "usa_new_york_ee_source_bundle_v2_vnp_coverage_diagnostics.tif"
    )
    fallback.touch()
    versioned.touch()

    assert (
        _source_bundle_path(
            tmp_path,
            city_id="usa_new_york",
            artifact_version="v2_vnp_coverage_diagnostics",
        )
        == versioned
    )


def test_source_preview_summarizes_strict_and_broad_qa_on_core_square(
    tmp_path,
) -> None:
    path = tmp_path / "bundle.tif"
    descriptions = (
        "vnp_median_corrected_radiance",
        "vnp_source_observation_count",
        "vnp_valid_observation_count",
        "vnp_broad_median_corrected_radiance",
        "vnp_broad_valid_observation_count",
        "persistent_water_occurrence_percent",
        "persistent_water_mask",
    )
    arrays = np.zeros((len(descriptions), 4, 4), dtype=np.float32)
    arrays[0] = 10
    arrays[1] = 12
    arrays[2] = 10
    arrays[3] = 11
    arrays[4] = 11
    arrays[5] = 0
    arrays[6] = 0
    arrays[0, 1, 1] = -9999
    arrays[2, 1, 1] = 8
    arrays[3, 1, 1] = 20
    arrays[4, 1, 1] = 9
    arrays[5, 1, 1] = 95
    arrays[6, 1, 1] = 1

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=len(descriptions),
        dtype="float32",
        crs="EPSG:32618",
        transform=from_origin(0, 40, 10, 10),
        nodata=-9999,
        tiled=True,
        blockxsize=16,
        blockysize=16,
    ) as dataset:
        dataset.write(arrays)
        for index, description in enumerate(descriptions, start=1):
            dataset.set_band_description(index, description)

    summary = _summarize_vnp_qa_comparison(path, analysis_shape=(2, 2))

    assert summary["strict_primary_coverage_fraction"] == pytest.approx(0.75)
    assert summary["broad_coverage_fraction"] == pytest.approx(1.0)
    assert summary["broad_only_area_km2"] == pytest.approx(0.0001)
    assert summary["common_support"]["strict_mean_radiance"] == pytest.approx(10)
    assert summary["common_support"]["broad_mean_radiance"] == pytest.approx(11)
    assert summary["broad_only_support"]["mean_strict_observation_count"] == 8
    assert summary["broad_only_support"]["persistent_water_mask_fraction"] == 1
