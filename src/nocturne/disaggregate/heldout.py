"""Leakage-safe native-cell held-out preflight for Gate 2."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from scipy.spatial import cKDTree

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.preview.paths import resolve_project_path

HELDOUT_VERSION = "v1_coarse_cell_preflight"
PHYSICS_BUFFERED_VERSION = "v2_physics_buffered_native_cell"
BROAD_PHYSICS_BUFFERED_VERSION = "v3_physics_buffered_native_cell_broad_qa"
NEIGHBOR_COUNT = 12
BUFFER_M = 500.0
PRIMARY_BUFFER_M = 2_550.0
SENSITIVITY_BUFFERS_M = (1_500.0, 2_000.0)
MAXIMUM_NEIGHBOR_DISTANCE_M = 10_000.0


def run_heldout_preflight(config_path: str | Path) -> Path:
    """Run fixed five-fold coarse-cell screening without target leakage."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    fold_count = int(config["validation"]["heldout"]["fold_count"])
    if fold_count != 5 or not config["validation"]["heldout"]["buffer_by_kernel_support"]:
        raise ValueError("Held-out preflight requires the registered five buffered folds")
    gate0_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate0"
        / config["validation"]["gate0"]["artifact_version"]
    )
    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "heldout"
        / HELDOUT_VERSION
    )
    output_root.mkdir(parents=True, exist_ok=True)
    all_rows = []
    summaries = []
    for city_id in config["cities"]["selected_city_ids"]:
        tables = {
            proxy: _load_proxy_table(gate0_root, city_id, proxy=proxy)
            for proxy in ("built_form_primary", "s2_only_ablation")
        }
        common_ids = set(tables["built_form_primary"]["coarse_cell_id"]) & set(
            tables["s2_only_ablation"]["coarse_cell_id"]
        )
        for proxy_name, table in tables.items():
            table = table[table["coarse_cell_id"].isin(common_ids)].copy()
            predictions = heldout_predictions(
                table,
                fold_count=fold_count,
                neighbor_count=NEIGHBOR_COUNT,
                buffer_m=BUFFER_M,
                maximum_neighbor_distance_m=MAXIMUM_NEIGHBOR_DISTANCE_M,
            )
            predictions["city_id"] = city_id
            predictions["proxy"] = proxy_name
            all_rows.append(predictions)
            summaries.extend(_summaries(predictions, city_id=city_id, proxy=proxy_name))
    predictions = pd.concat(all_rows, ignore_index=True)
    predictions_path = output_root / "predictions.csv"
    predictions.to_csv(predictions_path, index=False)
    summary_path = output_root / "summary.csv"
    pd.DataFrame(summaries).to_csv(summary_path, index=False)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifact_version": HELDOUT_VERSION,
        "config_sha256": disaggregation_config_sha256(config_path),
        "method_class": "coarse_cell_heldout_preflight_not_final_high_resolution_fold_run",
        "fold_assignment": "sorted_5km_block_id_round_robin",
        "target_leakage_policy": "all cells in target fold excluded from training",
        "training_buffer_m": BUFFER_M,
        "neighbor_count": NEIGHBOR_COUNT,
        "maximum_neighbor_distance_m": MAXIMUM_NEIGHBOR_DISTANCE_M,
        "neighbors_only_baseline": "inverse_distance_squared",
        "structural_prediction": (
            "neighbors_only_prediction_times_target_proxy_divided_by_"
            "inverse_distance_weighted_training_neighbor_proxy"
        ),
        "predictions": _file_record(predictions_path),
        "summary": _file_record(summary_path),
        "limitations": [
            "screening is evaluated at native-cell level",
            "it does not replace the registered remove-before-convolution high-resolution run",
            "proxy gain is a coarse analogue of the locally normalized operator",
        ],
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def run_physics_buffered_heldout(
    config_path: str | Path,
    *,
    radiance_variant: str = "strict",
) -> Path:
    """Run PSF-derived native-cell held-out buffer sensitivities."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    fold_count = int(config["validation"]["heldout"]["fold_count"])
    gate0_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate0"
        / config["validation"]["gate0"]["artifact_version"]
    )
    if radiance_variant not in {"strict", "broad"}:
        raise ValueError("Radiance variant must be 'strict' or 'broad'")
    artifact_version = (
        PHYSICS_BUFFERED_VERSION
        if radiance_variant == "strict"
        else BROAD_PHYSICS_BUFFERED_VERSION
    )
    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "heldout"
        / artifact_version
    )
    output_root.mkdir(parents=True, exist_ok=True)
    buffers = (*SENSITIVITY_BUFFERS_M, PRIMARY_BUFFER_M)
    all_predictions = []
    summary_rows = []
    gain_rows = []
    retention_rows = []
    radiance_sources: dict[str, dict[str, Any]] = {}
    for city_id in config["cities"]["selected_city_ids"]:
        tables = {
            proxy: _load_proxy_table(gate0_root, city_id, proxy=proxy)
            for proxy in ("built_form_primary", "s2_only_ablation")
        }
        if radiance_variant == "broad":
            input_config = config["outputs"]["day2_inputs"]
            bundle_path = (
                resolve_project_path(input_config["root"])
                / city_id
                / input_config["earth_engine_bundle_filename"]
            )
            radiance_sources[city_id] = _file_record(bundle_path)
            tables = {
                proxy: _replace_radiance_from_bundle(table, bundle_path, band=6)
                for proxy, table in tables.items()
            }
        common_ids = set(tables["built_form_primary"]["coarse_cell_id"]) & set(
            tables["s2_only_ablation"]["coarse_cell_id"]
        )
        for proxy_name, table in tables.items():
            table = table[table["coarse_cell_id"].isin(common_ids)].copy()
            for buffer_m in buffers:
                predictions = heldout_predictions(
                    table,
                    fold_count=fold_count,
                    neighbor_count=NEIGHBOR_COUNT,
                    buffer_m=buffer_m,
                    maximum_neighbor_distance_m=MAXIMUM_NEIGHBOR_DISTANCE_M,
                )
                predictions["city_id"] = city_id
                predictions["proxy"] = proxy_name
                predictions["buffer_m"] = buffer_m
                predictions["buffer_role"] = (
                    "primary" if buffer_m == PRIMARY_BUFFER_M else "sensitivity"
                )
                all_predictions.append(predictions)
                summary_rows.extend(
                    {
                        **row,
                        "buffer_m": buffer_m,
                        "buffer_role": predictions["buffer_role"].iloc[0],
                    }
                    for row in _summaries(
                        predictions, city_id=city_id, proxy=proxy_name
                    )
                )
                gain_rows.extend(
                    _gain_summaries(
                        predictions,
                        city_id=city_id,
                        proxy=proxy_name,
                        buffer_m=buffer_m,
                    )
                )
                retention_rows.extend(
                    _retention_summaries(
                        predictions,
                        city_id=city_id,
                        proxy=proxy_name,
                        buffer_m=buffer_m,
                    )
                )

    outputs = {
        "predictions": output_root / "predictions.csv",
        "summary": output_root / "summary.csv",
        "gain_summary": output_root / "gain_summary.csv",
        "sample_retention": output_root / "sample_retention.csv",
    }
    pd.concat(all_predictions, ignore_index=True).to_csv(
        outputs["predictions"], index=False
    )
    pd.DataFrame(summary_rows).to_csv(outputs["summary"], index=False)
    pd.DataFrame(gain_rows).to_csv(outputs["gain_summary"], index=False)
    pd.DataFrame(retention_rows).to_csv(outputs["sample_retention"], index=False)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifact_version": artifact_version,
        "config_sha256": disaggregation_config_sha256(config_path),
        "decision_id": "HELDOUT-001",
        "radiance_variant": radiance_variant,
        "radiance_contract": (
            "strict MQF-0 median with at least 10 retained observations"
            if radiance_variant == "strict"
            else "broad MQF-0/1 median with at least 5 retained observations"
        ),
        "evaluation_cohort": (
            "frozen common Gate 0 native-cell cohort; broad radiance sampled at "
            "the registered native-cell centroids"
        ),
        "radiance_sources": radiance_sources,
        "method_class": (
            "physics_buffered_native_cell_structural_gain_validation; "
            "still_coarse_analogue_not_remove_before_fine_grid_convolution"
        ),
        "fold_assignment": "sorted_5km_block_id_round_robin",
        "primary_training_buffer_m": PRIMARY_BUFFER_M,
        "sensitivity_training_buffers_m": list(SENSITIVITY_BUFFERS_M),
        "primary_buffer_rationale": (
            "four-sigma truncated support radius of registered "
            "1500 m-FWHM Gaussian"
        ),
        "gain_strata": ["<0.8", "0.8-1.25", ">=1.25"],
        "neighbor_count": NEIGHBOR_COUNT,
        "maximum_neighbor_distance_m": MAXIMUM_NEIGHBOR_DISTANCE_M,
        "neighbors_only_baseline": "inverse_distance_squared",
        "outputs": {name: _file_record(path) for name, path in outputs.items()},
        "limitations": [
            "larger buffers disproportionately retain spatial-block interiors",
            "buffer rows are distance sensitivities, not exchangeable random samples",
            "native-cell proxy gain remains a coarse analogue of the fine-grid operator",
            "a separate remove-before-convolution run is required for the strongest leakage claim",
            (
                "broad-only cells absent from the frozen strict Gate 0 cohort are not "
                "added; this isolates radiance-contract sensitivity on identical targets"
            ),
        ],
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def heldout_predictions(
    table: pd.DataFrame,
    *,
    fold_count: int,
    neighbor_count: int,
    buffer_m: float,
    maximum_neighbor_distance_m: float,
) -> pd.DataFrame:
    required = {
        "coarse_cell_id",
        "block_id",
        "x_m",
        "y_m",
        "proxy_mean",
        "vnp_median_corrected_ntl",
    }
    missing = required - set(table)
    if missing:
        raise ValueError(f"Held-out table missing columns: {sorted(missing)}")
    data = table.copy().reset_index(drop=True)
    blocks = sorted(data["block_id"].astype(str).unique())
    fold_by_block = {block: index % fold_count for index, block in enumerate(blocks)}
    data["fold"] = data["block_id"].astype(str).map(fold_by_block).astype(int)
    coordinates = data[["x_m", "y_m"]].to_numpy(dtype=np.float64)
    radiance = data["vnp_median_corrected_ntl"].to_numpy(dtype=np.float64)
    proxy = data["proxy_mean"].to_numpy(dtype=np.float64)
    output_rows = []
    for fold in range(fold_count):
        test_index = np.flatnonzero(data["fold"].to_numpy() == fold)
        train_index = np.flatnonzero(
            (data["fold"].to_numpy() != fold)
            & np.isfinite(radiance)
            & np.isfinite(proxy)
            & (proxy >= 0)
        )
        tree = cKDTree(coordinates[train_index])
        query_count = min(len(train_index), max(neighbor_count * 24, 288))
        distances, local_indices = tree.query(
            coordinates[test_index],
            k=query_count,
            distance_upper_bound=maximum_neighbor_distance_m,
        )
        distances = np.atleast_2d(distances)
        local_indices = np.atleast_2d(local_indices)
        if len(test_index) == 1:
            distances = distances.reshape(1, -1)
            local_indices = local_indices.reshape(1, -1)
        for row_number, target_index in enumerate(test_index):
            eligible = (
                np.isfinite(distances[row_number])
                & (distances[row_number] > buffer_m)
                & (local_indices[row_number] < len(train_index))
            )
            retained_distances = distances[row_number][eligible][:neighbor_count]
            retained_local = local_indices[row_number][eligible][:neighbor_count]
            retained = train_index[retained_local]
            if len(retained) < neighbor_count:
                baseline = structural = neighbor_proxy = np.nan
            else:
                weights = 1.0 / np.square(retained_distances)
                weights /= weights.sum()
                baseline = float(np.sum(weights * radiance[retained]))
                neighbor_proxy = float(np.sum(weights * proxy[retained]))
                structural = (
                    baseline * proxy[target_index] / neighbor_proxy
                    if np.isfinite(proxy[target_index]) and neighbor_proxy > 0
                    else np.nan
                )
            output_rows.append(
                {
                    "coarse_cell_id": data.iloc[target_index]["coarse_cell_id"],
                    "block_id": data.iloc[target_index]["block_id"],
                    "fold": fold,
                    "x_m": coordinates[target_index, 0],
                    "y_m": coordinates[target_index, 1],
                    "observed_radiance": radiance[target_index],
                    "proxy_mean": proxy[target_index],
                    "neighbors_only_prediction": baseline,
                    "structural_prediction": structural,
                    "training_neighbor_proxy_mean": neighbor_proxy,
                    "retained_neighbor_count": len(retained),
                    "nearest_retained_neighbor_distance_m": (
                        float(retained_distances[0]) if len(retained_distances) else None
                    ),
                    "distance_to_block_edge_m": _distance_to_block_edge(
                        coordinates[target_index],
                        str(data.iloc[target_index]["block_id"]),
                    ),
                }
            )
    result = pd.DataFrame(output_rows)
    result["allocation_gain"] = (
        result["structural_prediction"] / result["neighbors_only_prediction"]
    )
    result["gain_stratum"] = pd.cut(
        result["allocation_gain"],
        [-np.inf, 0.8, 1.25, np.inf],
        right=False,
        labels=["<0.8", "0.8-1.25", ">=1.25"],
    )
    finite_observed = np.isfinite(result["observed_radiance"])
    result["radiance_decile"] = pd.NA
    if finite_observed.any():
        result.loc[finite_observed, "radiance_decile"] = pd.qcut(
            result.loc[finite_observed, "observed_radiance"],
            10,
            labels=False,
            duplicates="drop",
        ).astype("Int64")
    return result


def _distance_to_block_edge(coordinate: np.ndarray, block_id: str) -> float:
    block_x, block_y = (int(value) for value in block_id.split("_"))
    west = block_x * 5_000.0
    south = block_y * 5_000.0
    x, y = coordinate
    return float(min(x - west, west + 5_000.0 - x, y - south, south + 5_000.0 - y))


def _gain_summaries(
    predictions: pd.DataFrame,
    *,
    city_id: str,
    proxy: str,
    buffer_m: float,
) -> list[dict[str, Any]]:
    rows = []
    for stratum, group in predictions.groupby("gain_stratum", observed=True):
        observed = group["observed_radiance"].to_numpy(dtype=np.float64)
        baseline = group["neighbors_only_prediction"].to_numpy(dtype=np.float64)
        structural = group["structural_prediction"].to_numpy(dtype=np.float64)
        valid = np.isfinite(observed) & np.isfinite(baseline) & np.isfinite(structural)
        baseline_error = np.abs(baseline[valid] - observed[valid])
        structural_error = np.abs(structural[valid] - observed[valid])
        rows.append(
            {
                "city_id": city_id,
                "proxy": proxy,
                "buffer_m": buffer_m,
                "buffer_role": "primary"
                if buffer_m == PRIMARY_BUFFER_M
                else "sensitivity",
                "gain_stratum": str(stratum),
                "sample_count": int(valid.sum()),
                "mean_allocation_gain": float(
                    group.loc[valid, "allocation_gain"].mean()
                ),
                "neighbors_only_mae": float(baseline_error.mean())
                if valid.any()
                else None,
                "structural_mae": float(structural_error.mean())
                if valid.any()
                else None,
                "structural_minus_neighbors_absolute_error": float(
                    (structural_error - baseline_error).mean()
                )
                if valid.any()
                else None,
            }
        )
    return rows


def _retention_summaries(
    predictions: pd.DataFrame,
    *,
    city_id: str,
    proxy: str,
    buffer_m: float,
) -> list[dict[str, Any]]:
    rows = []
    for fold, group in [("all", predictions), *predictions.groupby("fold")]:
        retained = group["structural_prediction"].notna()
        rows.append(
            {
                "city_id": city_id,
                "proxy": proxy,
                "buffer_m": buffer_m,
                "buffer_role": "primary"
                if buffer_m == PRIMARY_BUFFER_M
                else "sensitivity",
                "fold": fold,
                "target_count": len(group),
                "retained_target_count": int(retained.sum()),
                "retained_target_fraction": float(retained.mean()),
                "median_nearest_neighbor_distance_m": float(
                    group.loc[retained, "nearest_retained_neighbor_distance_m"].median()
                )
                if retained.any()
                else None,
                "median_distance_to_block_edge_m": float(
                    group.loc[retained, "distance_to_block_edge_m"].median()
                )
                if retained.any()
                else None,
            }
        )
    return rows


def _load_proxy_table(root: Path, city_id: str, *, proxy: str) -> pd.DataFrame:
    suffix = "built_form" if proxy == "built_form_primary" else "s2_only"
    path = root / f"{city_id}_{suffix}_samples.csv"
    return pd.read_csv(
        path,
        usecols=[
            "coarse_cell_id",
            "block_id",
            "x_m",
            "y_m",
            "proxy_mean",
            "vnp_median_corrected_ntl",
        ],
    )


def _replace_radiance_from_bundle(
    table: pd.DataFrame,
    bundle_path: Path,
    *,
    band: int,
) -> pd.DataFrame:
    """Replace target radiance by nearest-grid samples at registered centroids."""

    result = table.copy()
    coordinates = result[["x_m", "y_m"]].itertuples(index=False, name=None)
    with rasterio.open(bundle_path) as dataset:
        values = np.asarray(
            [sample[0] for sample in dataset.sample(coordinates, indexes=band)],
            dtype=np.float64,
        )
    if not np.isfinite(values).all():
        raise ValueError(f"Broad radiance is incomplete at held-out cells: {bundle_path}")
    result["vnp_median_corrected_ntl"] = values
    return result


def _summaries(predictions: pd.DataFrame, *, city_id: str, proxy: str) -> list[dict[str, Any]]:
    records = []
    for method in ("neighbors_only_prediction", "structural_prediction"):
        for fold, decile, group in _summary_groups(predictions):
            observed = group["observed_radiance"].to_numpy(dtype=np.float64)
            predicted = group[method].to_numpy(dtype=np.float64)
            valid = np.isfinite(observed) & np.isfinite(predicted)
            error = predicted[valid] - observed[valid]
            records.append(
                {
                    "city_id": city_id,
                    "proxy": proxy,
                    "method": method,
                    "fold": fold,
                    "radiance_decile": decile,
                    "sample_count": int(error.size),
                    "bias": float(error.mean()) if error.size else None,
                    "mae": float(np.abs(error).mean()) if error.size else None,
                    "rmse": (float(np.sqrt(np.square(error).mean())) if error.size else None),
                    "spearman": (
                        float(
                            pd.Series(observed[valid]).corr(
                                pd.Series(predicted[valid]), method="spearman"
                            )
                        )
                        if error.size > 1
                        else None
                    ),
                }
            )
    return records


def _summary_groups(predictions: pd.DataFrame):
    yield "all", "all", predictions
    for fold, group in predictions.groupby("fold"):
        yield int(fold), "all", group
    for decile, group in predictions.groupby("radiance_decile", observed=True):
        yield "all", int(decile), group


def _file_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Rerun the preserved 500 m screening analysis",
    )
    parser.add_argument(
        "--radiance-variant",
        choices=("strict", "broad"),
        default="strict",
        help="Radiance authority for the physics-buffered run",
    )
    args = parser.parse_args(argv)
    runner = run_heldout_preflight if args.preflight else run_physics_buffered_heldout
    if args.preflight:
        print(runner(args.config))
    else:
        print(runner(args.config, radiance_variant=args.radiance_variant))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
