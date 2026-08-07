"""Download and audit compact strict-QA daily VNP stacks for Gate 2."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.gee import (
    build_vnp_daily_collection,
    initialize_earth_engine_from_config,
)
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.preview.paths import resolve_project_path

DAILY_GRID_RESOLUTION_M = 500
CONDITION_LAYERS = (
    "lunar_irradiance",
    "retrieval_age_days",
    "cloud_detection",
    "cloud_mask_quality",
    "mandatory_quality_flag",
    "snow_flag",
)


def build_daily_vnp_stacks(config_path: str | Path) -> list[Path]:
    """Download two-city daily radiance and observation-condition COGs."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    ee = initialize_earth_engine_from_config(config)
    dates = _date_strings(
        config["date_window"]["start"],
        config["date_window"]["end_exclusive"],
    )
    if len(dates) != 100:
        raise ValueError(f"Expected 100 daily dates, found {len(dates)}")
    output_root = (
        resolve_project_path(config["outputs"]["root"])
        / "inputs"
        / "gate2_daily_vnp"
    )
    written = []
    for grid in build_city_grid_specs(config_path):
        city_root = output_root / grid.city_id
        city_root.mkdir(parents=True, exist_ok=True)
        transform, shape = _daily_grid(grid)
        region = ee.Geometry.Rectangle(
            [
                transform.c,
                transform.f + transform.e * shape[0],
                transform.c + transform.a * shape[1],
                transform.f,
            ],
            proj=grid.crs,
            geodesic=False,
        )
        daily = build_vnp_daily_collection(
            ee,
            region=region,
            config=config,
            quality_variant="primary",
        ).sort("system:time_start")
        layer_images = _daily_layer_images(ee, daily, config=config, dates=dates)
        records = {}
        for layer_name, image in layer_images.items():
            filename = (
                "daily_vnp_stack.tif"
                if layer_name == "strict_corrected_radiance"
                else f"daily_{layer_name}.tif"
            )
            path = city_root / filename
            print(f"{grid.city_id}: downloading {layer_name}", flush=True)
            _download_image(
                image,
                path=path,
                crs=grid.crs,
                transform=transform,
                shape=shape,
                band_names=[f"{layer_name}_{date}" for date in dates],
            )
            records[layer_name] = _file_record(path)
            written.append(path)
        metadata_path = city_root / "metadata.json"
        metadata = {
            "schema_version": 1,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "config_sha256": disaggregation_config_sha256(config_path),
            "city_id": grid.city_id,
            "source_product": config["sources"]["vnp46a2"]["collection"],
            "interval_start": config["date_window"]["start"],
            "interval_end_exclusive": config["date_window"]["end_exclusive"],
            "band_dates": dates,
            "quality_contract": config["sources"]["vnp46a2"]["quality_contracts"][
                "primary"
            ],
            "grid_contract": {
                "crs": grid.crs,
                "transform": list(transform)[:6],
                "shape": list(shape),
                "resolution_m": DAILY_GRID_RESOLUTION_M,
                "alignment": "same_projected_origin_and_extent_as_10m_analysis_grid",
                "continuous_resampling": "nearest_for_consistency_with_primary_vnp_authority",
                "categorical_resampling": "nearest",
            },
            "mask_contract": (
                "all radiance and condition layers share the strict-QA valid mask"
            ),
            "layers": records,
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(metadata_path)
    return written


def _daily_layer_images(ee, daily, *, config: dict[str, Any], dates: list[str]):
    target = config["sources"]["vnp46a2"]["target_band"]
    radiance = daily.select(target).toBands().rename(
        [f"strict_corrected_radiance_{date}" for date in dates]
    )
    cloud = daily.select("QF_Cloud_Mask").map(lambda image: image.toUint16())
    layers = {
        "strict_corrected_radiance": radiance,
        "lunar_irradiance": daily.select("DNB_Lunar_Irradiance")
        .toBands()
        .rename([f"lunar_irradiance_{date}" for date in dates]),
        "retrieval_age_days": daily.select("Latest_High_Quality_Retrieval")
        .toBands()
        .rename([f"retrieval_age_days_{date}" for date in dates]),
        "cloud_detection": cloud.map(
            lambda image: image.rightShift(6).bitwiseAnd(3)
        )
        .toBands()
        .rename([f"cloud_detection_{date}" for date in dates]),
        "cloud_mask_quality": cloud.map(
            lambda image: image.rightShift(4).bitwiseAnd(3)
        )
        .toBands()
        .rename([f"cloud_mask_quality_{date}" for date in dates]),
        "mandatory_quality_flag": daily.select("Mandatory_Quality_Flag")
        .toBands()
        .rename([f"mandatory_quality_flag_{date}" for date in dates]),
        "snow_flag": daily.select("Snow_Flag")
        .toBands()
        .rename([f"snow_flag_{date}" for date in dates]),
    }
    return {
        name: image.toFloat().unmask(-9999.0, False)
        for name, image in layers.items()
    }


def _download_image(
    image,
    *,
    path: Path,
    crs: str,
    transform: Affine,
    shape: tuple[int, int],
    band_names: list[str],
) -> None:
    url = image.getDownloadURL(
        {
            "name": path.stem,
            "crs": crs,
            "crs_transform": list(transform)[:6],
            "dimensions": [shape[1], shape[0]],
            "format": "GEO_TIFF",
            "filePerBand": False,
        }
    )
    with tempfile.TemporaryDirectory(prefix="nocturne-daily-vnp-") as directory:
        payload_path = Path(directory) / "payload"
        urllib.request.urlretrieve(url, payload_path)
        source_path = payload_path
        if zipfile.is_zipfile(payload_path):
            with zipfile.ZipFile(payload_path) as archive:
                names = [name for name in archive.namelist() if name.endswith(".tif")]
                if len(names) != 1:
                    raise ValueError(f"Expected one GeoTIFF, found {names}")
                archive.extract(names[0], directory)
                source_path = Path(directory) / names[0]
        with rasterio.open(source_path) as source:
            if source.count != len(band_names):
                raise ValueError(
                    f"Daily stack band mismatch: {source.count} != {len(band_names)}"
                )
            data = source.read()
            profile = source.profile.copy()
        profile.update(
            driver="COG",
            compress="DEFLATE",
            blocksize=128,
            nodata=-9999.0,
            BIGTIFF="IF_SAFER",
        )
        temporary = path.with_suffix(".tmp.tif")
        with rasterio.open(temporary, "w", **profile) as output:
            output.write(data.astype(np.float32, copy=False))
            output.descriptions = tuple(band_names)
        temporary.replace(path)


def _daily_grid(grid) -> tuple[Affine, tuple[int, int]]:
    if grid.width * grid.resolution_m % DAILY_GRID_RESOLUTION_M:
        raise ValueError("Analysis width is not divisible by the daily grid resolution")
    transform = Affine(
        DAILY_GRID_RESOLUTION_M,
        0,
        grid.transform[2],
        0,
        -DAILY_GRID_RESOLUTION_M,
        grid.transform[5],
    )
    return transform, (
        grid.height * grid.resolution_m // DAILY_GRID_RESOLUTION_M,
        grid.width * grid.resolution_m // DAILY_GRID_RESOLUTION_M,
    )


def _date_strings(start: str, end_exclusive: str) -> list[str]:
    start_date = datetime.fromisoformat(start).date()
    end_date = datetime.fromisoformat(end_exclusive).date()
    return [
        (start_date + timedelta(days=offset)).isoformat()
        for offset in range((end_date - start_date).days)
    ]


def _file_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    for path in build_daily_vnp_stacks(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
