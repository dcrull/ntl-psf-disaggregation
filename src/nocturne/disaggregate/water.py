"""Explicit water-prior variants for structural allocation proxies.

These functions modify only the dimensionless proxy. Observed VIIRS radiance is
never accepted as an argument, which makes accidental water masking of the
radiometric authority impossible inside this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WATER_VARIANTS = (
    "no_water_prior",
    "persistent_only_soft",
    "spectral_only_soft",
    "combined_soft",
    "combined_hard_persistent_sensitivity_only",
    "soft_with_mapped_infrastructure_override",
)


@dataclass(frozen=True)
class WaterProxyVariant:
    name: str
    proxy: np.ndarray
    water_modifier: np.ndarray
    hard_suppression_mask: np.ndarray
    infrastructure_override_mask: np.ndarray
    proxy_floor: float


def build_water_proxy_variant(
    base_proxy: np.ndarray,
    *,
    variant: str,
    persistent_water_weight: np.ndarray,
    spectral_water_weight: np.ndarray,
    persistent_water_mask: np.ndarray,
    mapped_infrastructure_mask: np.ndarray,
    proxy_floor: float,
) -> WaterProxyVariant:
    """Apply one preregistered water variant and then the common proxy floor."""

    if variant not in WATER_VARIANTS:
        raise ValueError(f"Unsupported water variant: {variant}")
    base = _as_float_array(base_proxy, name="base_proxy")
    persistent = _as_unit_weight(
        persistent_water_weight,
        name="persistent_water_weight",
        shape=base.shape,
    )
    spectral = _as_unit_weight(
        spectral_water_weight,
        name="spectral_water_weight",
        shape=base.shape,
    )
    persistent_mask = _as_bool_array(
        persistent_water_mask,
        name="persistent_water_mask",
        shape=base.shape,
    )
    infrastructure = _as_bool_array(
        mapped_infrastructure_mask,
        name="mapped_infrastructure_mask",
        shape=base.shape,
    )
    finite_base = np.isfinite(base)
    if np.any(base[finite_base] < 0):
        raise ValueError("Structural base proxy must be nonnegative")
    floor = float(proxy_floor)
    if not 0.0 <= floor < 1.0:
        raise ValueError("Proxy floor must be in [0, 1)")

    hard_suppression = np.zeros(base.shape, dtype=bool)
    override = np.zeros(base.shape, dtype=bool)
    if variant == "no_water_prior":
        modifier = np.ones(base.shape, dtype=np.float64)
    elif variant == "persistent_only_soft":
        modifier = persistent.copy()
    elif variant == "spectral_only_soft":
        modifier = spectral.copy()
    elif variant == "combined_soft":
        modifier = persistent * spectral
    elif variant == "combined_hard_persistent_sensitivity_only":
        hard_suppression = persistent_mask.copy()
        modifier = spectral * (~persistent_mask).astype(np.float64)
    else:
        combined = persistent * spectral
        override = infrastructure & finite_base
        modifier = np.where(override, 1.0, combined)

    weighted = base * modifier
    proxy = np.full(base.shape, np.nan, dtype=np.float64)
    proxy[finite_base] = floor + (1.0 - floor) * weighted[finite_base]
    return WaterProxyVariant(
        name=variant,
        proxy=proxy,
        water_modifier=modifier,
        hard_suppression_mask=hard_suppression,
        infrastructure_override_mask=override,
        proxy_floor=floor,
    )


def _as_float_array(value: np.ndarray, *, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2:
        raise ValueError(f"{name} must be a two-dimensional array")
    return array


def _as_unit_weight(value: np.ndarray, *, name: str, shape: tuple[int, int]) -> np.ndarray:
    array = _as_float_array(value, name=name)
    if array.shape != shape:
        raise ValueError(f"{name} shape {array.shape} does not match {shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite; encode unsupported JRC pixels as neutral 1")
    if np.any((array < 0) | (array > 1)):
        raise ValueError(f"{name} must be in [0, 1]")
    return array


def _as_bool_array(value: np.ndarray, *, name: str, shape: tuple[int, int]) -> np.ndarray:
    array = np.asarray(value, dtype=bool)
    if array.ndim != 2 or array.shape != shape:
        raise ValueError(f"{name} shape {array.shape} does not match {shape}")
    return array
