from __future__ import annotations

import json

import numpy as np
import rasterio
from affine import Affine

from nocturne.disaggregate.gate2 import _audit_water_reference


def test_water_reference_requires_grid_band_and_provenance(tmp_path) -> None:
    raster_path = tmp_path / "water_reference.tif"
    metadata_path = tmp_path / "metadata.json"
    transform = Affine(10, 0, 100, 0, -10, 200)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=4,
        width=5,
        count=1,
        dtype="uint8",
        crs="EPSG:32618",
        transform=transform,
    ) as dataset:
        dataset.write(np.zeros((4, 5), dtype=np.uint8), 1)
        dataset.set_band_description(1, "water_reference_mask")
    metadata_path.write_text(
        json.dumps(
            {
                "source_name": "test",
                "source_version": "v1",
                "acquisition_or_coverage_dates": ["2024-01-01"],
                "water_class_definition": "fixture",
                "license": "fixture",
                "source_url_or_identifier": "fixture",
            }
        )
    )

    audit = _audit_water_reference(
        raster_path,
        metadata_path,
        expected_crs="EPSG:32618",
        expected_transform=transform,
        expected_shape=(4, 5),
    )

    assert audit["ready"] is True
    assert audit["metadata"]["missing_fields"] == []
