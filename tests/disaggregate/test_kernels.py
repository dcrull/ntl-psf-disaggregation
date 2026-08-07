from __future__ import annotations

import numpy as np
import pytest
import shapely

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.kernels import (
    circular_mean_kernel,
    gaussian_kernel,
    kernel_from_config,
    native_footprint_kernel,
)


def test_circular_reference_is_normalized_and_centered() -> None:
    kernel = circular_mean_kernel(radius_m=20, resolution_m=10)

    assert kernel.weights.shape == (5, 5)
    assert np.isclose(kernel.weights.sum(), 1.0)
    assert kernel.weights[2, 2] > 0
    assert kernel.weights[0, 0] == 0
    assert kernel.weights[2, 0] > 0
    assert kernel.identifier == "circular_mean_radius_m_20"
    with pytest.raises(ValueError):
        kernel.weights[2, 2] = 0


def test_gaussian_fwhm_has_half_max_at_half_fwhm() -> None:
    kernel = gaussian_kernel(fwhm_m=40, resolution_m=10, truncate_sigma=4)
    center = kernel.weights.shape[1] // 2

    assert np.isclose(kernel.weights.sum(), 1.0)
    assert np.isclose(
        kernel.weights[center, center + 2] / kernel.weights[center, center],
        0.5,
        atol=1e-12,
    )
    assert kernel.metadata["truncate_sigma"] == 4.0


def test_native_footprint_kernel_preserves_exact_projected_area() -> None:
    footprint = shapely.box(-17.0, -11.0, 17.0, 11.0)
    kernel = native_footprint_kernel(
        footprint=footprint,
        resolution_m=10,
        footprint_id="vnp_r10_c20",
    )

    assert np.isclose(kernel.weights.sum(), 1.0)
    assert kernel.weights.shape[0] % 2 == 1
    assert kernel.weights.shape[1] % 2 == 1
    assert np.isclose(kernel.metadata["footprint_projected_area_m2"], 34 * 22)
    assert np.isclose(
        kernel.metadata["rasterized_overlap_area_m2"],
        kernel.metadata["footprint_projected_area_m2"],
    )
    assert kernel.metadata["footprint_id"] == "vnp_r10_c20"


def test_kernel_factory_rejects_undeclared_gaussian_width() -> None:
    config = load_disaggregation_config("configs/psf_disaggregation.yaml")

    with pytest.raises(ValueError, match="Undeclared Gaussian FWHM"):
        kernel_from_config(config, kernel_type="gaussian", fwhm_m=900)

    kernel = kernel_from_config(config, kernel_type="gaussian", fwhm_m=1000)
    assert kernel.parameter_name == "fwhm_m"
    assert kernel.parameter_value == 1000
    assert kernel.metadata["truncate_sigma"] == 4.0
