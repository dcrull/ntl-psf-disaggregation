"""Audit propagation of strict-QA daily observation conditions through allocation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from scipy.ndimage import convolve

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.preview.paths import resolve_project_path

VERSION = "v1_daily_coarse_operator"
CONDITIONS = ("lunar_irradiance", "cloud_detection", "cloud_mask_quality")


def run_observation_condition_audit(config_path: str | Path) -> Path:
    """Apply the reference operator daily and summarize condition propagation."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    input_root = (
        resolve_project_path(config["outputs"]["root"])
        / "inputs"
        / "gate2_daily_vnp"
    )
    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "observation_conditions"
        / VERSION
    )
    output_root.mkdir(parents=True, exist_ok=True)
    rows = []
    daily_rows = []
    invariant_rows = []
    for city_id in config["cities"]["selected_city_ids"]:
        city_input = input_root / city_id
        radiance = _read_stack(city_input / "daily_vnp_stack.tif")
        conditions = {
            name: _read_stack(city_input / f"daily_{name}.tif")
            for name in CONDITIONS
        }
        invariants = {
            name: _read_stack(city_input / f"daily_{name}.tif")
            for name in (
                "mandatory_quality_flag",
                "snow_flag",
                "retrieval_age_days",
            )
        }
        proxy = _coarse_proxy(config, city_id)
        methods, complete_support = apply_daily_coarse_operator(radiance, proxy)
        common = complete_support & np.isfinite(methods["direct"])
        for method, values in methods.items():
            method_values = np.where(common, values, np.nan)
            rows.extend(
                _condition_rows(
                    city_id,
                    method=method,
                    values=method_values,
                    conditions=conditions,
                )
            )
            temporal = _within_cell_log_residual(method_values)
            rows.append(
                {
                    "city_id": city_id,
                    "method": method,
                    "condition": "overall_temporal_variability",
                    "sample_count": int(np.isfinite(temporal).sum()),
                    "within_cell_correlation": None,
                    "within_cell_r_squared": None,
                    "mean_absolute_within_cell_log_residual": float(
                        np.nanmean(np.abs(temporal))
                    ),
                }
            )
        for day in range(radiance.shape[0]):
            daily_rows.append(
                {
                    "city_id": city_id,
                    "day_index": day,
                    "direct_valid_fraction": float(np.isfinite(radiance[day]).mean()),
                    "complete_kernel_support_fraction": float(
                        complete_support[day].mean()
                    ),
                }
            )
        for name, values in invariants.items():
            valid_values = values[np.isfinite(values)]
            invariant_rows.append(
                {
                    "city_id": city_id,
                    "condition": name,
                    "sample_count": int(valid_values.size),
                    "minimum": float(valid_values.min()),
                    "maximum": float(valid_values.max()),
                    "unique_values": json.dumps(
                        np.unique(valid_values).astype(float).tolist()
                    ),
                    "estimable_within_strict_qa": bool(
                        np.unique(valid_values).size > 1
                    ),
                }
            )
        _plot_city(
            city_id,
            methods=methods,
            common=common,
            conditions=conditions,
            output_path=output_root / f"{city_id}_observation_conditions.png",
        )

    paths = {
        "condition_summary": output_root / "condition_summary.csv",
        "daily_support": output_root / "daily_support.csv",
        "invariant_conditions": output_root / "invariant_conditions.csv",
    }
    _write_csv(paths["condition_summary"], rows)
    _write_csv(paths["daily_support"], daily_rows)
    _write_csv(paths["invariant_conditions"], invariant_rows)
    manifest_path = output_root / "manifest.json"
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifact_version": VERSION,
        "config_sha256": disaggregation_config_sha256(config_path),
        "method_class": "500m_daily_coarse_analogue_of_reference_operator",
        "kernel": "500m-radius circle on 500m grid: center plus four cardinal cells",
        "proxy": "built_form_primary_no_water_prior_with_0.05_floor",
        "comparison_support": (
            "identical observations with complete five-cell daily radiance support"
        ),
        "condition_estimator": (
            "Pearson correlation after within-cell centering of log1p output "
            "and condition; r-squared is univariate descriptive association"
        ),
        "pass_rule": (
            "structural condition r-squared and temporal variability must not "
            "materially exceed both direct and uniform on common support"
        ),
        "outputs": {name: _file_record(path) for name, path in paths.items()},
        "limitations": [
            "coarse daily operator audit does not reproduce the 10m output field",
            "strict daily QA can sharply reduce complete kernel support",
            "condition associations are descriptive and not causal",
            "MQF, snow, and retrieval age are invariant on strict retained pixels",
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def apply_daily_coarse_operator(
    radiance: np.ndarray, proxy: np.ndarray
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Apply direct, uniform, and structural reference analogues."""

    if radiance.ndim != 3 or proxy.shape != radiance.shape[1:]:
        raise ValueError("Daily radiance and proxy shapes are incompatible")
    kernel = np.asarray(
        [[0.0, 1.0, 0.0], [1.0, 1.0, 1.0], [0.0, 1.0, 0.0]],
        dtype=np.float64,
    )
    kernel /= kernel.sum()
    valid = np.isfinite(radiance)
    filled = np.where(valid, radiance, 0.0)
    support = convolve(
        valid.astype(np.float64),
        kernel[None, :, :],
        mode="constant",
        cval=0.0,
    )
    complete = support >= 1.0 - 1e-9
    numerator = convolve(
        filled,
        kernel[None, :, :],
        mode="constant",
        cval=0.0,
    )
    proxy = np.maximum(proxy.astype(np.float64), 0.05)
    denominator = convolve(
        proxy,
        kernel,
        mode="constant",
        cval=np.nan,
    )
    uniform = np.where(complete, numerator, np.nan)
    structural = np.where(
        denominator[None, :, :] > 1e-6,
        proxy[None, :, :] * numerator / denominator[None, :, :],
        np.nan,
    )
    structural = np.where(complete, structural, np.nan)
    return {
        "direct": radiance.astype(np.float64, copy=False),
        "uniform": uniform,
        "built_form_no_water": structural,
    }, complete


def _condition_rows(
    city_id: str,
    *,
    method: str,
    values: np.ndarray,
    conditions: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    output_residual = _within_cell_log_residual(values)
    rows = []
    for name, condition in conditions.items():
        condition_residual = _within_cell_residual(condition)
        valid = np.isfinite(output_residual) & np.isfinite(condition_residual)
        correlation = (
            float(np.corrcoef(output_residual[valid], condition_residual[valid])[0, 1])
            if valid.sum() > 1
            and np.std(output_residual[valid]) > 0
            and np.std(condition_residual[valid]) > 0
            else None
        )
        rows.append(
            {
                "city_id": city_id,
                "method": method,
                "condition": name,
                "sample_count": int(valid.sum()),
                "within_cell_correlation": correlation,
                "within_cell_r_squared": correlation**2
                if correlation is not None
                else None,
                "mean_absolute_within_cell_log_residual": float(
                    np.nanmean(np.abs(output_residual))
                ),
            }
        )
    return rows


def _within_cell_log_residual(values: np.ndarray) -> np.ndarray:
    return _within_cell_residual(np.log1p(np.maximum(values, 0)))


def _within_cell_residual(values: np.ndarray) -> np.ndarray:
    median = np.nanmedian(values, axis=0)
    return values - median[None, :, :]


def _coarse_proxy(config: dict[str, Any], city_id: str) -> np.ndarray:
    input_config = config["outputs"]["day2_inputs"]
    path = (
        resolve_project_path(input_config["root"])
        / city_id
        / input_config["overture_bundle_filename"]
    )
    with rasterio.open(path) as dataset:
        bands = {name: index for index, name in enumerate(dataset.descriptions, 1)}
        proxy = dataset.read(
            bands["built_form_base_proxy_unwatered_unfloored"]
        ).astype(np.float64)
    trim = (proxy.shape[0] - 5000) // 2
    core = proxy[trim : trim + 5000, trim : trim + 5000]
    return core.reshape(100, 50, 100, 50).mean(axis=(1, 3))


def _read_stack(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return dataset.read(masked=True).filled(np.nan).astype(np.float64)


def _plot_city(
    city_id: str,
    *,
    methods: dict[str, np.ndarray],
    common: np.ndarray,
    conditions: dict[str, np.ndarray],
    output_path: Path,
) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(13, 7), constrained_layout=True)
    colors = {"direct": "black", "uniform": "#4c78a8", "built_form_no_water": "#e45756"}
    for axis, condition_name in zip(axes[0], CONDITIONS):
        condition = conditions[condition_name]
        sample = common & np.isfinite(condition)
        for method, values in methods.items():
            residual = _within_cell_log_residual(np.where(common, values, np.nan))
            axis.hexbin(
                condition[sample],
                residual[sample],
                gridsize=45,
                mincnt=1,
                alpha=0.25,
                color=colors[method],
                label=method,
            )
        axis.set(xlabel=condition_name.replace("_", " "), ylabel="within-cell log residual")
    direct_fraction = np.isfinite(methods["direct"]).mean(axis=(1, 2))
    complete_fraction = common.mean(axis=(1, 2))
    axes[1, 0].plot(direct_fraction, label="direct daily support")
    axes[1, 0].plot(complete_fraction, label="complete kernel support")
    axes[1, 0].set(xlabel="day index", ylabel="valid fraction")
    axes[1, 0].legend()
    for method, values in methods.items():
        residual = _within_cell_log_residual(np.where(common, values, np.nan))
        axes[1, 1].hist(
            residual[np.isfinite(residual)],
            bins=80,
            density=True,
            histtype="step",
            label=method,
            color=colors[method],
        )
    axes[1, 1].set(xlabel="within-cell log residual", ylabel="density")
    axes[1, 1].legend()
    axes[1, 2].axis("off")
    axes[0, 0].legend()
    figure.suptitle(f"{city_id}: strict-QA observation-condition propagation")
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _file_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    print(run_observation_condition_audit(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
