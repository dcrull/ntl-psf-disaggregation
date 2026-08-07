"""Cloud-Optimized GeoTIFF export for Day 2 allocation artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling

from nocturne.disaggregate.operator import AllocationResult


@dataclass(frozen=True)
class AllocationArtifactIdentity:
    city_id: str
    interval_start: str
    interval_end_exclusive: str
    allocation_proxy: str
    water_variant: str
    kernel_type: str
    kernel_parameter_name: str | None
    kernel_parameter_value: float | None
    vnp_resampling: str
    config_sha256: str
    analysis_semantics: str = "locally_normalized_radiance_allocation"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_allocation_cog_bundle(
    result: AllocationResult,
    *,
    output_directory: str | Path,
    identity: AllocationArtifactIdentity,
    crs: str,
    transform: Affine | tuple[float, float, float, float, float, float],
    extra_metadata: Mapping[str, Any] | None = None,
) -> list[Path]:
    """Write one inspectable COG per product/diagnostic plus a checksum manifest."""

    output_root = Path(output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    affine = transform if isinstance(transform, Affine) else Affine(*transform)
    float_layers = {
        "allocation": result.allocation,
        "operator_consistency_error": result.operator_consistency_error,
        "convolved_radiance": result.convolved_radiance,
        "convolved_proxy": result.convolved_proxy,
        "radiance_support_fraction": result.radiance_support_fraction,
        "proxy_support_fraction": result.proxy_support_fraction,
        "allocation_support_fraction": result.allocation_support_fraction,
        "geometric_support_fraction": result.geometric_support_fraction,
    }
    mask_layers = {
        "valid_output_mask": result.valid_output_mask,
        "operator_consistency_valid_mask": result.operator_consistency_valid_mask,
        "boundary_mask": result.boundary_mask,
        "invalid_radiance_neighborhood_mask": (
            result.invalid_radiance_neighborhood_mask
        ),
        "invalid_proxy_neighborhood_mask": result.invalid_proxy_neighborhood_mask,
        "denominator_floor_mask": result.denominator_floor_mask,
        "denominator_instability_mask": result.denominator_instability_mask,
        "negative_radiance_input_mask": result.negative_radiance_input_mask,
        "negative_preclip_output_mask": result.negative_preclip_output_mask,
    }
    shared_tags = {
        **identity.to_dict(),
        "exact_conservation_assumed": False,
        "output_claim": "analysis_only_not_independent_10m_measurement",
        "kernel_semantics": result.kernel.semantics,
    }
    written: list[Path] = []
    file_records = []
    for name, values in float_layers.items():
        path = output_root / f"{name}.tif"
        write_cog(
            path,
            values,
            crs=crs,
            transform=affine,
            band_name=name,
            tags=shared_tags,
            categorical=False,
        )
        written.append(path)
        file_records.append(_file_record(path, band_name=name))
    for name, values in mask_layers.items():
        path = output_root / f"{name}.tif"
        write_cog(
            path,
            values.astype(np.uint8),
            crs=crs,
            transform=affine,
            band_name=name,
            tags=shared_tags,
            categorical=True,
        )
        written.append(path)
        file_records.append(_file_record(path, band_name=name))

    manifest_path = output_root / "manifest.json"
    manifest = {
        "schema_version": 1,
        "identity": identity.to_dict(),
        "operator_metadata": result.metadata,
        "extra_metadata": dict(extra_metadata or {}),
        "files": file_records,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written.append(manifest_path)
    return written


def write_cog(
    path: str | Path,
    values: np.ndarray,
    *,
    crs: str,
    transform: Affine | tuple[float, float, float, float, float, float],
    band_name: str,
    tags: Mapping[str, Any] | None = None,
    categorical: bool = False,
) -> Path:
    """Write and validate one single-band Cloud-Optimized GeoTIFF."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    array = np.asarray(values)
    if array.ndim != 2:
        raise ValueError("COG export requires a two-dimensional array")
    affine = transform if isinstance(transform, Affine) else Affine(*transform)
    if categorical:
        data = array.astype(np.uint8, copy=False)
        nodata: float | int = 255
        resampling = Resampling.nearest
    else:
        data = array.astype(np.float32, copy=False)
        nodata = np.nan
        resampling = Resampling.average
    profile = {
        "driver": "COG",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": data.dtype,
        "crs": crs,
        "transform": affine,
        "nodata": nodata,
        "compress": "DEFLATE",
        "blocksize": 512,
        "overview_resampling": resampling.name,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(output_path, "w", **profile) as dataset:
        dataset.write(data, 1)
        dataset.set_band_description(1, band_name)
        if tags:
            dataset.update_tags(
                **{
                    key: _tag_value(value)
                    for key, value in tags.items()
                    if value is not None
                }
            )
    validate_cog(
        output_path,
        expected_crs=crs,
        expected_transform=affine,
        expected_shape=data.shape,
        expected_band_name=band_name,
    )
    return output_path


def validate_cog(
    path: str | Path,
    *,
    expected_crs: str,
    expected_transform: Affine,
    expected_shape: tuple[int, int],
    expected_band_name: str,
) -> None:
    """Fail if a written artifact lost its grid or COG layout contract."""

    with rasterio.open(path) as dataset:
        if dataset.driver != "GTiff":
            raise ValueError(f"COG did not reopen as GeoTIFF: {path}")
        if dataset.crs is None or dataset.crs.to_string() != rasterio.crs.CRS.from_string(
            expected_crs
        ).to_string():
            raise ValueError(f"COG CRS mismatch: {path}")
        if dataset.transform != expected_transform:
            raise ValueError(f"COG affine transform mismatch: {path}")
        if (dataset.height, dataset.width) != expected_shape:
            raise ValueError(f"COG shape mismatch: {path}")
        if dataset.descriptions[0] != expected_band_name:
            raise ValueError(f"COG band description mismatch: {path}")
        layout = dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT")
        if layout != "COG":
            raise ValueError(f"GeoTIFF is not marked with COG layout: {path}")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path: Path, *, band_name: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "band_name": band_name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _tag_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)
