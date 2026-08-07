from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from nocturne.preview.cities import load_candidate_cities
from nocturne.preview.dates import DateWindow
from nocturne.preview.paths import resolve_project_path


def load_experiment_config(config_path: str | Path) -> dict[str, Any]:
    path = resolve_project_path(config_path, must_exist=True)
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise TypeError(f"Experiment config must be a mapping: {path}")
    return config


def build_experiment_manifest(config: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    """Expand an experiment config into a dataset manifest and city manifest table."""

    _validate_config(config)
    experiment = config["experiment"]
    city_config = config["candidate_cities"]
    date_window = DateWindow.parse(config["date_window"]["start"], config["date_window"]["end"])

    cities = load_candidate_cities(
        city_config["workbook"],
        sheet_name=city_config.get("sheet_name", "cities"),
        radius_km=float(city_config["analysis_radius_km"]),
    )
    cities = _select_cities(cities, city_config.get("selected_city_ids"))
    cities = _city_manifest_columns(
        cities,
        default_timezone=city_config.get("default_timezone", "UTC"),
        timezone_source=city_config.get("timezone_source", "configured_default"),
    )

    split_rules = _build_split_rules(config["split_rules"], cities)
    output_locations = _resolve_output_locations(config["outputs"])

    manifest: dict[str, Any] = {
        "schema_version": int(experiment.get("schema_version", 1)),
        "experiment_id": experiment["id"],
        "description": experiment.get("description", ""),
        "created_at": datetime.now(UTC).isoformat(),
        "config": {
            "candidate_city_workbook": str(resolve_project_path(city_config["workbook"])),
            "candidate_city_sheet": city_config.get("sheet_name", "cities"),
            "selected_city_ids": cities["city_id"].tolist(),
            "analysis_radius_km": float(city_config["analysis_radius_km"]),
            "date_window": {"start": date_window.start.isoformat(), "end": date_window.end.isoformat()},
        },
        "target": config["target"],
        "feature_groups": config["feature_groups"],
        "split_rules": split_rules,
        "outputs": output_locations,
        "city_manifest": {
            "path": output_locations["city_manifest"],
            "city_count": len(cities),
            "required_fields": [
                "city_id",
                "city",
                "country",
                "center_lat",
                "center_lon",
                "bbox_west",
                "bbox_south",
                "bbox_east",
                "bbox_north",
                "timezone",
                "osm_coverage_score",
                "selection_notes",
                "source_row_id",
            ],
        },
        "status": "manifest_built_not_ingested",
    }
    return manifest, cities


def write_experiment_manifest(config_path: str | Path) -> dict[str, Path]:
    """Build and write the dataset manifest files declared by a config."""

    config = load_experiment_config(config_path)
    manifest, cities = build_experiment_manifest(config)
    outputs = manifest["outputs"]

    city_manifest_path = Path(outputs["city_manifest"])
    yaml_path = Path(outputs["dataset_manifest_yaml"])
    json_path = Path(outputs["dataset_manifest_json"])
    for path in (city_manifest_path, yaml_path, json_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    cities.to_csv(city_manifest_path, index=False)
    yaml_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    json_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "city_manifest": city_manifest_path,
        "dataset_manifest_yaml": yaml_path,
        "dataset_manifest_json": json_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a nocturne experiment dataset manifest.")
    parser.add_argument(
        "config",
        nargs="?",
        default="configs/first_experiment.yaml",
        help="Path to the experiment YAML config.",
    )
    args = parser.parse_args(argv)
    written = write_experiment_manifest(args.config)
    for name, path in written.items():
        print(f"{name}: {path}")
    return 0


def _validate_config(config: dict[str, Any]) -> None:
    required = {
        "experiment",
        "candidate_cities",
        "date_window",
        "target",
        "feature_groups",
        "split_rules",
        "outputs",
    }
    missing = required - set(config)
    if missing:
        raise ValueError(f"Experiment config is missing required sections: {sorted(missing)}")
    DateWindow.parse(config["date_window"]["start"], config["date_window"]["end"])


def _select_cities(cities: pd.DataFrame, selected_city_ids: list[str] | None) -> pd.DataFrame:
    if selected_city_ids is None:
        return cities.copy()

    selected = cities[cities["city_id"].isin(selected_city_ids)].copy()
    missing = set(selected_city_ids) - set(selected["city_id"])
    if missing:
        raise ValueError(f"Selected city IDs are not in the candidate workbook: {sorted(missing)}")
    return selected


def _city_manifest_columns(
    cities: pd.DataFrame,
    *,
    default_timezone: str,
    timezone_source: str,
) -> pd.DataFrame:
    manifest = cities.copy()
    manifest["analysis_radius_km"] = manifest["preview_radius_km"]
    manifest["timezone"] = default_timezone
    manifest["timezone_source"] = timezone_source
    manifest["selection_notes"] = manifest.apply(_selection_notes, axis=1)

    columns = [
        "city_id",
        "city",
        "country",
        "center_lat",
        "center_lon",
        "analysis_radius_km",
        "bbox_west",
        "bbox_south",
        "bbox_east",
        "bbox_north",
        "timezone",
        "timezone_source",
        "osm_coverage_score",
        "selection_notes",
        "source_row_id",
        "urban_density_people_per_km2",
        "urban_pop_latest",
        "urban_metro_gdp_latest_usd_b",
        "population_density_basis",
        "gdp_basis_caveat",
        "osm_completeness_note",
        "population_density_source_url",
        "gdp_source_url",
        "osm_map_source_url",
    ]
    return manifest[[column for column in columns if column in manifest.columns]]


def _selection_notes(row: pd.Series) -> str:
    candidates = [
        row.get("selection_rationale"),
        row.get("osm_completeness_note"),
        row.get("gdp_basis_caveat"),
        row.get("population_density_basis"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _build_split_rules(split_config: dict[str, Any], cities: pd.DataFrame) -> dict[str, Any]:
    train = DateWindow.parse(split_config["train"]["date_start"], split_config["train"]["date_end"])
    validation = DateWindow.parse(
        split_config["validation"]["date_start"],
        split_config["validation"]["date_end"],
    )
    if validation.start <= train.end:
        raise ValueError("Validation split must start after the training split ends")

    cross_city = dict(split_config.get("cross_city_validation", {}))
    if cross_city.get("enabled", False):
        cross_city["holdout_city_ids"] = _deterministic_city_holdout(
            cities["city_id"].tolist(),
            holdout_fraction=float(cross_city.get("holdout_fraction", 0.2)),
            seed=int(cross_city.get("seed", 0)),
        )

    return {
        "strategy": split_config["strategy"],
        "train": {"date_start": train.start.isoformat(), "date_end": train.end.isoformat()},
        "validation": {
            "date_start": validation.start.isoformat(),
            "date_end": validation.end.isoformat(),
        },
        "cross_city_validation": cross_city,
        "notes": split_config.get("notes", []),
    }


def _deterministic_city_holdout(
    city_ids: list[str],
    *,
    holdout_fraction: float,
    seed: int,
) -> list[str]:
    if not 0 <= holdout_fraction < 1:
        raise ValueError("cross-city holdout_fraction must be in [0, 1)")
    if not city_ids or holdout_fraction == 0:
        return []

    import random

    rng = random.Random(seed)
    shuffled = list(city_ids)
    rng.shuffle(shuffled)
    count = max(1, round(len(shuffled) * holdout_fraction))
    return sorted(shuffled[:count])


def _resolve_output_locations(outputs: dict[str, str]) -> dict[str, str]:
    resolved = {}
    for key, value in outputs.items():
        if key == "reports":
            resolved[key] = str(resolve_project_path(value))
        else:
            resolved[key] = str(resolve_project_path(value))
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
