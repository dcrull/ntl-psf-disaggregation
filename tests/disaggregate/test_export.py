from __future__ import annotations

import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from nocturne.disaggregate.export import (
    AllocationArtifactIdentity,
    write_allocation_cog_bundle,
)
from nocturne.disaggregate.kernels import circular_mean_kernel
from nocturne.disaggregate.operator import apply_fork_form_allocation


def test_allocation_bundle_writes_grid_locked_cogs_and_manifest(tmp_path) -> None:
    radiance = np.full((31, 31), 5.0)
    proxy = np.full((31, 31), 1.0)
    result = apply_fork_form_allocation(
        radiance,
        proxy,
        kernel=circular_mean_kernel(radius_m=20, resolution_m=10),
        denominator_epsilon_relative=1e-6,
        denominator_instability_threshold_relative=0.05,
    )
    identity = AllocationArtifactIdentity(
        city_id="synthetic_test",
        interval_start="2024-01-11",
        interval_end_exclusive="2024-04-20",
        allocation_proxy="uniform_normalized_convolution",
        water_variant="no_water_prior",
        kernel_type="circular_mean",
        kernel_parameter_name="radius_m",
        kernel_parameter_value=20,
        vnp_resampling="nearest",
        config_sha256="abc123",
    )
    transform = from_origin(500_000, 4_500_000, 10, 10)

    written = write_allocation_cog_bundle(
        result,
        output_directory=tmp_path,
        identity=identity,
        crs="EPSG:32618",
        transform=transform,
        extra_metadata={"fixture": "unit_test"},
    )

    assert len(written) == 18
    allocation_path = tmp_path / "allocation.tif"
    with rasterio.open(allocation_path) as dataset:
        assert dataset.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        assert dataset.crs.to_string() == "EPSG:32618"
        assert dataset.transform == transform
        assert dataset.descriptions == ("allocation",)
        assert dataset.tags()["output_claim"] == (
            "analysis_only_not_independent_10m_measurement"
        )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["identity"]["city_id"] == "synthetic_test"
    assert manifest["identity"]["kernel_type"] == "circular_mean"
    assert len(manifest["files"]) == 17
    assert all(len(record["sha256"]) == 64 for record in manifest["files"])
