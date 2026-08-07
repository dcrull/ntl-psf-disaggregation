from __future__ import annotations

import numpy as np
import rasterio
from rasterio.transform import from_origin

from nocturne.disaggregate.day2 import _audit_raster_bundle


def test_day2_bundle_audit_accepts_exact_grid_and_band_order(tmp_path) -> None:
    path = tmp_path / "bundle.tif"
    transform = from_origin(500_000, 4_500_000, 10, 10)
    expected_bands = ["radiance", "support"]
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=7,
        height=5,
        count=2,
        dtype="float32",
        crs="EPSG:32618",
        transform=transform,
    ) as dataset:
        dataset.write(np.ones((2, 5, 7), dtype=np.float32))
        for index, name in enumerate(expected_bands, start=1):
            dataset.set_band_description(index, name)

    audit = _audit_raster_bundle(
        path,
        expected_crs="EPSG:32618",
        expected_transform=transform,
        expected_shape=(5, 7),
        expected_bands=expected_bands,
        band_order_authority="embedded_band_descriptions",
    )

    assert audit["valid"] is True
    assert audit["errors"] == []
    assert len(audit["sha256"]) == 64


def test_day2_bundle_audit_rejects_silent_band_order_change(tmp_path) -> None:
    path = tmp_path / "bundle.tif"
    transform = from_origin(500_000, 4_500_000, 10, 10)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=7,
        height=5,
        count=2,
        dtype="float32",
        crs="EPSG:32618",
        transform=transform,
    ) as dataset:
        dataset.write(np.ones((2, 5, 7), dtype=np.float32))
        dataset.set_band_description(1, "support")
        dataset.set_band_description(2, "radiance")

    audit = _audit_raster_bundle(
        path,
        expected_crs="EPSG:32618",
        expected_transform=transform,
        expected_shape=(5, 7),
        expected_bands=["radiance", "support"],
        band_order_authority="embedded_band_descriptions",
    )

    assert audit["valid"] is False
    assert "embedded_band_order_mismatch" in audit["errors"]
