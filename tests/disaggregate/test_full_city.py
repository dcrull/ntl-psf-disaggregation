from __future__ import annotations

import numpy as np
from rasterio.windows import Window

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.full_city import (
    _result_layers,
    build_configuration_matrix,
    expanded_window,
    iter_core_windows,
)
from nocturne.disaggregate.kernels import circular_mean_kernel
from nocturne.disaggregate.operator import apply_fork_form_allocation


def test_frozen_full_city_matrix_has_declared_city_counts() -> None:
    config = load_disaggregation_config("configs/psf_disaggregation.yaml")
    new_york = build_configuration_matrix(config, "usa_new_york")
    delhi = build_configuration_matrix(config, "india_delhi")

    assert len(new_york) == 23
    assert len(delhi) == 22
    assert sum(item.kind == "native" for item in new_york) == 2
    assert sum(item.radiance_contract == "broad" for item in new_york) == 1
    assert not any(item.radiance_contract == "broad" for item in delhi)


def test_core_windows_cover_non_divisible_shape_once() -> None:
    coverage = np.zeros((13, 15), dtype=np.uint8)
    windows = list(iter_core_windows(coverage.shape, tile_pixels=6))
    for window in windows:
        row = int(window.row_off)
        column = int(window.col_off)
        coverage[
            row : row + int(window.height),
            column : column + int(window.width),
        ] += 1

    assert len(windows) == 9
    assert np.all(coverage == 1)


def test_expanded_window_clips_to_real_geometric_support() -> None:
    processing, crop = expanded_window(
        Window(0, 1, 4, 5),
        halo=3,
        bounds_shape=(10, 11),
    )

    assert processing == Window(0, 0, 7, 9)
    assert crop == (slice(1, 6), slice(0, 4))


def test_two_radius_tiled_core_matches_whole_array_operator() -> None:
    rng = np.random.default_rng(7)
    radiance = rng.uniform(0, 10, size=(31, 33)).astype(np.float32)
    proxy = rng.uniform(0.1, 2, size=radiance.shape).astype(np.float32)
    kernel = circular_mean_kernel(radius_m=2, resolution_m=1)
    kwargs = {
        "kernel": kernel,
        "denominator_epsilon_relative": 1e-6,
        "denominator_instability_threshold_relative": 1e-3,
        "proxy_normalization_divisor": float(proxy.mean()),
        "denominator_reference_mean_after_normalization": 1.0,
    }
    whole = apply_fork_form_allocation(radiance, proxy, **kwargs)
    core = Window(8, 7, 11, 12)
    processing, crop = expanded_window(
        core,
        halo=2 * kernel.halo_rows,
        bounds_shape=radiance.shape,
    )
    rows = slice(int(processing.row_off), int(processing.row_off + processing.height))
    columns = slice(int(processing.col_off), int(processing.col_off + processing.width))
    tiled = apply_fork_form_allocation(
        radiance[rows, columns],
        proxy[rows, columns],
        **kwargs,
    )
    layers = _result_layers(tiled, crop=crop, insufficient_threshold=0.05)
    expected = whole.operator_consistency_error[7:19, 8:19]

    np.testing.assert_allclose(
        layers["operator_consistency_error"],
        expected,
        rtol=1e-5,
        atol=1e-5,
        equal_nan=True,
    )
