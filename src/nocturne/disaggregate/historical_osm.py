"""Checkpointed historical OSM extraction for the 2024 structural comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize, unary_union

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.preview.paths import resolve_project_path

SNAPSHOT_TIME = "2024-03-01T00:00:00Z"
OVERPASS_ENDPOINT = "https://overpass.kumi.systems/api/interpreter"
INITIAL_TILE_DEGREES = 0.05
MINIMUM_TILE_DEGREES = 0.0125


def extract_historical_osm(
    config_path: str | Path,
    *,
    city_ids: list[str] | None = None,
) -> list[Path]:
    """Extract buildings and roads at the locked 2024 timestamp."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    grids = build_city_grid_specs(config_path)
    requested = set(city_ids or config["cities"]["selected_city_ids"])
    root = resolve_project_path(config["outputs"]["root"]) / "inputs" / "osm_2024_snapshot"
    outputs = []
    for grid in grids:
        if grid.city_id not in requested:
            continue
        city_root = root / grid.city_id
        tile_root = city_root / "tiles"
        tile_root.mkdir(parents=True, exist_ok=True)
        leaf_paths = _download_adaptive_tiles(
            bounds=grid.source_wgs84_bounds,
            tile_root=tile_root,
        )
        buildings, roads, extraction_metrics = _consolidate(leaf_paths)
        buildings_path = city_root / "buildings.parquet"
        roads_path = city_root / "segments.parquet"
        _write_geoparquet(buildings_path, buildings, kind="building")
        _write_geoparquet(roads_path, roads, kind="segment")
        manifest = {
            "schema_version": 1,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source": "OpenStreetMap history via Overpass attic data",
            "source_url": OVERPASS_ENDPOINT,
            "license": "ODbL-1.0",
            "snapshot_time_utc": SNAPSHOT_TIME,
            "city_id": grid.city_id,
            "requested_bounds": list(grid.source_wgs84_bounds),
            "query_contract": (
                "building-tagged ways and relations plus highway-tagged ways; "
                "out geom; adaptive nonoverlapping bbox tiles"
            ),
            "tile_count": len(leaf_paths),
            "metrics": extraction_metrics,
            "buildings": _file_record(buildings_path),
            "segments": _file_record(roads_path),
            "limitations": [
                "snapshot represents OSM database state, not independently verified construction date",
                "building multipolygon relations are reconstructed from returned member geometries",
                "OSM coverage and tagging completeness vary spatially",
            ],
        }
        manifest_path = city_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        outputs.append(manifest_path)
    return outputs


def _download_adaptive_tiles(
    *,
    bounds: tuple[float, float, float, float],
    tile_root: Path,
) -> list[Path]:
    pending = _regular_tiles(bounds, INITIAL_TILE_DEGREES)
    leaves: list[Path] = []
    while pending:
        failures = []
        completed = 0
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(_download_tile, tile, tile_root): tile for tile in pending
            }
            for future in as_completed(futures):
                tile = futures[future]
                try:
                    leaves.append(future.result())
                    completed += 1
                    print(
                        f"historical OSM: completed {completed}/{len(pending)} "
                        f"tiles at this level",
                        flush=True,
                    )
                except Exception as error:
                    width = tile[2] - tile[0]
                    height = tile[3] - tile[1]
                    if min(width, height) <= MINIMUM_TILE_DEGREES + 1e-9:
                        raise RuntimeError(f"Historical OSM tile failed at minimum size: {tile}") from error
                    failures.extend(_subdivide(tile))
        pending = failures
    return sorted(set(leaves))


def _regular_tiles(
    bounds: tuple[float, float, float, float], size: float
) -> list[tuple[float, float, float, float]]:
    xmin, ymin, xmax, ymax = bounds
    columns = math.ceil((xmax - xmin) / size)
    rows = math.ceil((ymax - ymin) / size)
    return [
        (
            xmin + column * (xmax - xmin) / columns,
            ymin + row * (ymax - ymin) / rows,
            xmin + (column + 1) * (xmax - xmin) / columns,
            ymin + (row + 1) * (ymax - ymin) / rows,
        )
        for row in range(rows)
        for column in range(columns)
    ]


def _subdivide(
    tile: tuple[float, float, float, float]
) -> list[tuple[float, float, float, float]]:
    xmin, ymin, xmax, ymax = tile
    xmid = (xmin + xmax) / 2
    ymid = (ymin + ymax) / 2
    return [
        (xmin, ymin, xmid, ymid),
        (xmid, ymin, xmax, ymid),
        (xmin, ymid, xmid, ymax),
        (xmid, ymid, xmax, ymax),
    ]


def _download_tile(
    tile: tuple[float, float, float, float], tile_root: Path
) -> Path:
    key = "_".join(f"{value:.7f}" for value in tile)
    output = tile_root / f"{key}.json"
    if output.exists():
        payload = json.loads(output.read_text(encoding="utf-8"))
        if "elements" in payload:
            return output
    xmin, ymin, xmax, ymax = tile
    bbox = f"{ymin:.7f},{xmin:.7f},{ymax:.7f},{xmax:.7f}"
    query = (
        f'[out:json][timeout:300][date:"{SNAPSHOT_TIME}"];'
        f'(way["building"]({bbox});relation["building"]({bbox});'
        f'way["highway"]({bbox}););out geom;'
    )
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            request = urllib.request.Request(
                OVERPASS_ENDPOINT,
                data=data,
                headers={"User-Agent": "nocturne-research/0.1"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                body = response.read()
            payload = json.loads(body)
            if "elements" not in payload:
                raise ValueError("Overpass response lacks elements")
            temporary = output.with_suffix(".tmp")
            temporary.write_bytes(body)
            temporary.replace(output)
            return output
        except (HTTPError, OSError, ValueError) as error:
            last_error = error
            if attempt < 4:
                retry_after = (
                    error.headers.get("Retry-After")
                    if isinstance(error, HTTPError) and error.headers
                    else None
                )
                delay = float(retry_after) if retry_after else float(2**attempt)
                time.sleep(min(delay, 60.0))
    assert last_error is not None
    raise last_error


def _consolidate(
    paths: list[Path],
) -> tuple[list[tuple[str, bytes]], list[tuple[str, bytes, str, str]], dict[str, int]]:
    elements: dict[tuple[str, int], dict[str, Any]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for element in payload["elements"]:
            elements.setdefault((element["type"], int(element["id"])), element)
    buildings = []
    roads = []
    rejected_buildings = 0
    rejected_roads = 0
    for (element_type, element_id), element in elements.items():
        tags = element.get("tags", {})
        if "building" in tags:
            geometry = _building_geometry(element)
            if geometry is None or geometry.is_empty:
                rejected_buildings += 1
            else:
                buildings.append((f"{element_type}/{element_id}", shapely.to_wkb(geometry)))
        if element_type == "way" and "highway" in tags:
            geometry = _way_line(element)
            if geometry is None or geometry.is_empty:
                rejected_roads += 1
            else:
                road_class = tags.get("highway") or "unknown"
                roads.append(
                    (
                        f"{element_type}/{element_id}",
                        shapely.to_wkb(geometry),
                        "road",
                        road_class,
                    )
                )
    metrics = {
        "deduplicated_element_count": len(elements),
        "building_feature_count": len(buildings),
        "road_feature_count": len(roads),
        "rejected_building_count": rejected_buildings,
        "rejected_road_count": rejected_roads,
    }
    return buildings, roads, metrics


def _building_geometry(element: dict[str, Any]):
    if element["type"] == "way":
        coordinates = _coordinates(element.get("geometry", []))
        if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
            return None
        return Polygon(coordinates)
    lines = []
    for member in element.get("members", []):
        coordinates = _coordinates(member.get("geometry", []))
        if len(coordinates) >= 2:
            lines.append(LineString(coordinates))
    polygons = list(polygonize(lines))
    if not polygons:
        return None
    merged = unary_union(polygons)
    if isinstance(merged, Polygon):
        return merged
    if isinstance(merged, MultiPolygon):
        return merged
    parts = [geometry for geometry in getattr(merged, "geoms", []) if isinstance(geometry, Polygon)]
    return MultiPolygon(parts) if parts else None


def _way_line(element: dict[str, Any]):
    coordinates = _coordinates(element.get("geometry", []))
    return LineString(coordinates) if len(coordinates) >= 2 else None


def _coordinates(records: list[dict[str, Any]]) -> list[tuple[float, float]]:
    return [
        (float(record["lon"]), float(record["lat"]))
        for record in records
        if "lon" in record and "lat" in record
    ]


def _write_geoparquet(path: Path, rows: list[tuple], *, kind: str) -> None:
    if kind == "building":
        table = pa.table(
            {
                "id": [row[0] for row in rows],
                "geometry": pa.array([row[1] for row in rows], type=pa.binary()),
            }
        )
    else:
        table = pa.table(
            {
                "id": [row[0] for row in rows],
                "geometry": pa.array([row[1] for row in rows], type=pa.binary()),
                "subtype": [row[2] for row in rows],
                "class": [row[3] for row in rows],
            }
        )
    metadata = dict(table.schema.metadata or {})
    metadata[b"geo"] = json.dumps(
        {
            "version": "1.1.0",
            "primary_column": "geometry",
            "columns": {
                "geometry": {
                    "encoding": "WKB",
                    "geometry_types": ["Polygon", "MultiPolygon"]
                    if kind == "building"
                    else ["LineString"],
                    "crs": "OGC:CRS84",
                }
            },
        }
    ).encode("utf-8")
    pq.write_table(table.replace_schema_metadata(metadata), path, compression="zstd")


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "feature_count": pq.ParquetFile(path).metadata.num_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--city", action="append", dest="city_ids")
    args = parser.parse_args()
    for output in extract_historical_osm(args.config, city_ids=args.city_ids):
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
