from __future__ import annotations

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from nocturne.disaggregate.heldout import (
    _replace_radiance_from_bundle,
    heldout_predictions,
)


def test_replace_radiance_from_bundle_samples_registered_centroids(tmp_path) -> None:
    path = tmp_path / "bundle.tif"
    profile = {
        "driver": "GTiff",
        "width": 2,
        "height": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:32618",
        "transform": from_origin(0, 20, 10, 10),
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(np.array([[1, 2], [3, 4]], dtype=np.float32), 1)
    table = pd.DataFrame(
        {
            "x_m": [5.0, 15.0],
            "y_m": [15.0, 5.0],
            "vnp_median_corrected_ntl": [99.0, 99.0],
        }
    )

    result = _replace_radiance_from_bundle(table, path, band=1)

    assert result["vnp_median_corrected_ntl"].tolist() == [1.0, 4.0]


def test_heldout_predictions_exclude_target_fold_and_buffer() -> None:
    count = 80
    table = pd.DataFrame(
        {
            "coarse_cell_id": [f"cell-{index}" for index in range(count)],
            "block_id": [f"{int(index * 600 // 5_000)}_0" for index in range(count)],
            "x_m": np.arange(count, dtype=float) * 600,
            "y_m": np.zeros(count),
            "proxy_mean": np.linspace(0.5, 1.5, count),
            "vnp_median_corrected_ntl": np.linspace(10, 30, count),
        }
    )

    result = heldout_predictions(
        table,
        fold_count=5,
        neighbor_count=3,
        buffer_m=500,
        maximum_neighbor_distance_m=20_000,
    )

    assert len(result) == count
    assert (result["retained_neighbor_count"] == 3).all()
    assert (result["nearest_retained_neighbor_distance_m"] > 500).all()
    assert result["neighbors_only_prediction"].notna().all()
    assert result["structural_prediction"].notna().all()
    assert result["allocation_gain"].notna().all()
    assert result["gain_stratum"].notna().all()
    assert (result["distance_to_block_edge_m"] >= 0).all()
