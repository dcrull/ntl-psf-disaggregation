from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pyproj import Transformer

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.experiment.manifest import build_experiment_manifest, load_experiment_config
from nocturne.preview.paths import resolve_project_path


@dataclass(frozen=True)
class CityGridSpec:
    city_id: str
    center_lat: float
    center_lon: float
    crs: str
    resolution_m: int
    center_x: float
    center_y: float
    west: float
    south: float
    east: float
    north: float
    width: int
    height: int
    analysis_wgs84_bounds: tuple[float, float, float, float]
    analysis_wgs84_ring: tuple[tuple[float, float], ...]
    source_wgs84_bounds: tuple[float, float, float, float]

    @property
    def transform(self) -> tuple[float, float, float, float, float, float]:
        return (self.resolution_m, 0.0, self.west, 0.0, -self.resolution_m, self.north)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["transform"] = list(self.transform)
        return payload


def build_city_grid_specs(config_path: str | Path) -> list[CityGridSpec]:
    config = load_disaggregation_config(config_path)
    city_config_path = config["cities"]["source_config"]
    source_config = load_experiment_config(city_config_path)
    _, cities = build_experiment_manifest(source_config)
    selected = cities[cities["city_id"].isin(config["cities"]["selected_city_ids"])].copy()
    missing = set(config["cities"]["selected_city_ids"]) - set(selected["city_id"])
    if missing:
        raise ValueError(f"Pilot cities missing from source manifest: {sorted(missing)}")

    resolution_m = int(config["grid"]["resolution_m"])
    geometry = config["cities"]["analysis_geometry"]
    side_length_km = float(geometry["side_length_km"])
    center_snap_to_grid = bool(geometry.get("center_snap_to_grid", True))
    source_halo_m = float(geometry["source_halo_m"])
    specs_by_id = {
        row.city_id: _grid_spec_for_city(
            row,
            resolution_m=resolution_m,
            side_length_km=side_length_km,
            center_snap_to_grid=center_snap_to_grid,
            source_halo_m=source_halo_m,
        )
        for row in selected.itertuples(index=False)
    }
    return [specs_by_id[city_id] for city_id in config["cities"]["selected_city_ids"]]


def write_city_grid_manifest(config_path: str | Path) -> Path:
    config = load_disaggregation_config(config_path)
    output_path = resolve_project_path(config["outputs"]["manifests"]) / "city_grids.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment_id": config["experiment"]["id"],
        "experiment_contract_version": config["experiment"]["contract_version"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "grid_semantics": (
            "exact projected square centered on the manifest point snapped to the working grid"
        ),
        "analysis_geometry": config["cities"]["analysis_geometry"],
        "resampling_contract": {
            "continuous": config["grid"]["continuous_resampling"],
            "categorical": config["grid"]["categorical_resampling"],
        },
        "cities": [spec.to_dict() for spec in build_city_grid_specs(config_path)],
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def utm_crs_for_lon_lat(lon: float, lat: float) -> str:
    zone = min(60, max(1, int((lon + 180.0) // 6.0) + 1))
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return f"EPSG:{epsg}"


def earth_engine_region_for_grid(ee, grid: CityGridSpec):
    return ee.Geometry.Polygon(
        [list(grid.analysis_wgs84_ring)],
        proj="EPSG:4326",
        geodesic=False,
    )


def earth_engine_source_region_for_grid(
    ee,
    grid: CityGridSpec,
    *,
    halo_m: float,
    edge_inset_m: float = 0.0,
):
    """Return the projected source square with an optional export-only inset."""

    halo = float(halo_m)
    if halo < 0:
        raise ValueError("Source-region halo must be nonnegative")
    inset = float(edge_inset_m)
    if inset < 0 or inset >= grid.resolution_m / 2:
        raise ValueError("Source-region edge inset must be in [0, half a pixel)")
    return ee.Geometry.Rectangle(
        [
            grid.west - halo + inset,
            grid.south - halo + inset,
            grid.east + halo - inset,
            grid.north + halo - inset,
        ],
        proj=grid.crs,
        geodesic=False,
    )


def expanded_grid_transform(
    grid: CityGridSpec,
    *,
    halo_m: float,
) -> tuple[float, float, float, float, float, float]:
    halo = float(halo_m)
    if halo < 0:
        raise ValueError("Expanded-grid halo must be nonnegative")
    if abs(halo / grid.resolution_m - round(halo / grid.resolution_m)) > 1e-9:
        raise ValueError("Expanded-grid halo must align to the working resolution")
    return (
        grid.resolution_m,
        0.0,
        grid.west - halo,
        0.0,
        -grid.resolution_m,
        grid.north + halo,
    )


def expanded_grid_shape(grid: CityGridSpec, *, halo_m: float) -> tuple[int, int]:
    halo_pixels = round(float(halo_m) / grid.resolution_m)
    if abs(halo_pixels * grid.resolution_m - float(halo_m)) > 1e-9:
        raise ValueError("Expanded-grid halo must align to the working resolution")
    return grid.height + 2 * halo_pixels, grid.width + 2 * halo_pixels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write aligned 10 m city-grid metadata.")
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    print(write_city_grid_manifest(args.config))
    return 0


def _grid_spec_for_city(
    city,
    *,
    resolution_m: int,
    side_length_km: float,
    center_snap_to_grid: bool,
    source_halo_m: float,
) -> CityGridSpec:
    crs = utm_crs_for_lon_lat(float(city.center_lon), float(city.center_lat))
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    center_x, center_y = transformer.transform(
        float(city.center_lon),
        float(city.center_lat),
    )
    if center_snap_to_grid:
        center_x = round(center_x / resolution_m) * resolution_m
        center_y = round(center_y / resolution_m) * resolution_m

    side_length_m = side_length_km * 1000.0
    side_pixels = round(side_length_m / resolution_m)
    if abs(side_pixels * resolution_m - side_length_m) > 1e-6:
        raise ValueError("The square side length must be an integer number of grid cells")
    if side_pixels % 2:
        raise ValueError("The square side must contain an even number of cells")

    half_side_m = side_length_m / 2.0
    west = center_x - half_side_m
    east = center_x + half_side_m
    south = center_y - half_side_m
    north = center_y + half_side_m
    projected_ring = [
        (west, south),
        (east, south),
        (east, north),
        (west, north),
        (west, south),
    ]
    source_projected_ring = [
        (west - source_halo_m, south - source_halo_m),
        (east + source_halo_m, south - source_halo_m),
        (east + source_halo_m, north + source_halo_m),
        (west - source_halo_m, north + source_halo_m),
        (west - source_halo_m, south - source_halo_m),
    ]
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    geographic_ring = tuple(inverse.transform(x, y) for x, y in projected_ring)
    source_geographic_ring = tuple(
        inverse.transform(x, y) for x, y in source_projected_ring
    )
    longitudes = [lon for lon, _ in geographic_ring]
    latitudes = [lat for _, lat in geographic_ring]
    source_longitudes = [lon for lon, _ in source_geographic_ring]
    source_latitudes = [lat for _, lat in source_geographic_ring]
    return CityGridSpec(
        city_id=city.city_id,
        center_lat=float(city.center_lat),
        center_lon=float(city.center_lon),
        crs=crs,
        resolution_m=resolution_m,
        center_x=center_x,
        center_y=center_y,
        west=west,
        south=south,
        east=east,
        north=north,
        width=side_pixels,
        height=side_pixels,
        analysis_wgs84_bounds=(
            min(longitudes),
            min(latitudes),
            max(longitudes),
            max(latitudes),
        ),
        analysis_wgs84_ring=geographic_ring,
        source_wgs84_bounds=(
            min(source_longitudes),
            min(source_latitudes),
            max(source_longitudes),
            max(source_latitudes),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
