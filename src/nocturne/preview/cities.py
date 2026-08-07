from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from nocturne.preview.geo import bbox_from_center_radius
from nocturne.preview.paths import resolve_project_path

DEFAULT_CITY_WORKBOOK = Path("assets/sprint_cities.csv")

_COLUMN_MAP = {
    "City": "city",
    "Country": "country",
    "Lat/lon center": "lat_lon_center",
    "Urban density (people/km²)": "urban_density_people_per_km2",
    "Urban pop (latest)": "urban_pop_latest",
    "Urban/metro GDP latest (US$B)": "urban_metro_gdp_latest_usd_b",
    "OSM coverage (1-5)": "osm_coverage_score",
    "SDGSAT-1 coverage yes/no": "sdgsat1_coverage",
    "Cambridge SDG study yes/no": "cambridge_sdg_study",
    "Population/density basis": "population_density_basis",
    "GDP basis / caveat": "gdp_basis_caveat",
    "OSM completeness note": "osm_completeness_note",
    "Selection rationale": "selection_rationale",
    "Population/density source URL": "population_density_source_url",
    "GDP source URL": "gdp_source_url",
    "OSM map/source URL": "osm_map_source_url",
}


def load_candidate_cities(
    workbook: str | Path = DEFAULT_CITY_WORKBOOK,
    *,
    sheet_name: str = "cities",
    radius_km: float = 25.0,
) -> pd.DataFrame:
    """Load the human-curated candidate city workbook as a preview manifest table."""

    workbook = resolve_project_path(workbook, must_exist=True)
    if workbook.suffix.lower() == ".csv":
        df = pd.read_csv(workbook)
    else:
        df = pd.read_excel(workbook, sheet_name=sheet_name)
    df = df.rename(columns={k: v for k, v in _COLUMN_MAP.items() if k in df.columns})

    missing = {"city", "country", "lat_lon_center"} - set(df.columns)
    if missing:
        raise ValueError(f"Candidate workbook is missing required columns: {sorted(missing)}")

    centers = df["lat_lon_center"].apply(_parse_lat_lon)
    df["center_lat"] = centers.apply(lambda pair: pair[0])
    df["center_lon"] = centers.apply(lambda pair: pair[1])
    df["source_row_id"] = df.index + 2
    df["city_id"] = df.apply(
        lambda row: _slugify(f"{row['country']}-{row['city']}"),
        axis=1,
    )

    bboxes = df.apply(
        lambda row: bbox_from_center_radius(row["center_lat"], row["center_lon"], radius_km),
        axis=1,
    )
    df["preview_radius_km"] = radius_km
    df["bbox_west"] = bboxes.apply(lambda bbox: bbox.west)
    df["bbox_south"] = bboxes.apply(lambda bbox: bbox.south)
    df["bbox_east"] = bboxes.apply(lambda bbox: bbox.east)
    df["bbox_north"] = bboxes.apply(lambda bbox: bbox.north)

    front = [
        "city_id",
        "city",
        "country",
        "center_lat",
        "center_lon",
        "preview_radius_km",
        "bbox_west",
        "bbox_south",
        "bbox_east",
        "bbox_north",
        "urban_density_people_per_km2",
        "urban_pop_latest",
        "urban_metro_gdp_latest_usd_b",
        "osm_coverage_score",
        "source_row_id",
    ]
    ordered = [column for column in front if column in df.columns]
    ordered.extend(column for column in df.columns if column not in ordered)
    return df[ordered]


def _parse_lat_lon(value: object) -> tuple[float, float]:
    if not isinstance(value, str):
        raise TypeError(f"Expected 'lat, lon' string, got {value!r}")
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Expected 'lat, lon' string, got {value!r}")
    return (float(parts[0]), float(parts[1]))


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value
