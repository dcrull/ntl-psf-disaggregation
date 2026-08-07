"""Prepare an independent mapped-water reference for Gate 2."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize
from shapely import from_wkb
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.preview.paths import resolve_project_path

OVERTURE_RELEASE = "2026-06-17.0"
AREAL_WATER_CLASSES = frozenset(
    {
        "bay",
        "canal",
        "fishpond",
        "lake",
        "pond",
        "reservoir",
        "river",
        "strait",
        "tidal_channel",
        "water",
    }
)


def prepare_water_references(config_path: str | Path) -> list[Path]:
    """Rasterize pinned Overture polygon water onto each registered grid."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    root = (
        resolve_project_path(config["outputs"]["root"]) / "inputs" / "gate2_water_reference"
    )
    outputs = []
    for grid in build_city_grid_specs(config_path):
        city_root = root / grid.city_id
        raw_path = city_root / f"overture_water_{OVERTURE_RELEASE}.parquet"
        if not raw_path.exists():
            raise FileNotFoundError(raw_path)
        table = pq.read_table(
            raw_path, columns=["id", "class", "geometry", "sources", "is_intermittent"]
        )
        classes = table["class"].to_pylist()
        geometries = from_wkb(table["geometry"].to_numpy())
        selected = [
            geometry
            for water_class, geometry in zip(classes, geometries, strict=True)
            if is_reference_water(water_class, geometry)
        ]
        transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
        projected = [transform(transformer.transform, geometry) for geometry in selected]
        mask = rasterize(
            ((geometry, 1) for geometry in projected),
            out_shape=(grid.height, grid.width),
            transform=Affine(*grid.transform),
            fill=0,
            dtype="uint8",
            all_touched=False,
        )
        raster_path = city_root / "water_reference.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="COG",
            height=grid.height,
            width=grid.width,
            count=1,
            dtype="uint8",
            crs=grid.crs,
            transform=Affine(*grid.transform),
            compress="DEFLATE",
            blocksize=512,
            overview_resampling="nearest",
        ) as dataset:
            dataset.write(mask, 1)
            dataset.set_band_description(1, "water_reference_mask")
            dataset.update_tags(
                source="Overture Maps water / OpenStreetMap",
                release=OVERTURE_RELEASE,
                class_contract=",".join(sorted(AREAL_WATER_CLASSES)),
            )
        source_records = [
            source
            for sources in table["sources"].to_pylist()
            for source in (sources or [])
        ]
        update_times = sorted(
            source["update_time"]
            for source in source_records
            if source.get("update_time")
        )
        metadata = {
            "source_name": "Overture Maps base/water (primarily OpenStreetMap)",
            "source_version": OVERTURE_RELEASE,
            "acquisition_or_coverage_dates": {
                "release": OVERTURE_RELEASE.split(".")[0],
                "source_update_time_min": update_times[0] if update_times else None,
                "source_update_time_max": update_times[-1] if update_times else None,
            },
            "water_class_definition": (
                "Center-in-pixel rasterization of Polygon and MultiPolygon Overture "
                f"water features whose class is one of {sorted(AREAL_WATER_CLASSES)}. "
                "LineString and Point features are not buffered; swimming pools, "
                "wastewater, basins, drains, ditches, and non-water geometries are excluded."
            ),
            "license": sorted(
                {source["license"] for source in source_records if source.get("license")}
            ),
            "source_url_or_identifier": (
                "s3://overturemaps-us-west-2/release/"
                f"{OVERTURE_RELEASE}/theme=base/type=water/"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "raw_extract": {
                "path": str(raw_path),
                "sha256": _sha256(raw_path),
                "feature_count": table.num_rows,
                "class_counts": dict(sorted(Counter(classes).items())),
            },
            "selected_polygon_feature_count": len(selected),
            "water_pixel_count": int(mask.sum()),
            "grid": {
                "crs": grid.crs,
                "shape": [grid.height, grid.width],
                "transform": list(grid.transform),
                "all_touched": False,
            },
            "limitations": [
                "mapped presence/absence is not an exhaustive optical water classification",
                "source update times vary by feature",
                "narrow waterways mapped only as lines are deliberately absent",
                "the source is independent of JRC but not independent of OpenStreetMap",
            ],
            "raster_sha256": _sha256(raster_path),
        }
        metadata_path = city_root / "metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        outputs.append(metadata_path)
    return outputs


def is_reference_water(water_class: str | None, geometry: BaseGeometry) -> bool:
    """Return whether a feature has defensible areal-water support."""

    return (
        water_class in AREAL_WATER_CLASSES
        and geometry.geom_type in {"Polygon", "MultiPolygon"}
        and not geometry.is_empty
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    for output in prepare_water_references(args.config):
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
