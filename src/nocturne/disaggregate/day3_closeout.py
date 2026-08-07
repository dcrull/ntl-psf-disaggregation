"""Build the Day 3 publication summary and evidence classification."""

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
import pandas as pd

from nocturne.disaggregate.config import disaggregation_config_sha256
from nocturne.preview.paths import resolve_project_path

VERSION = "v1_bounded_method_closeout"


def build_day3_closeout(config_path: str | Path) -> Path:
    """Consolidate saved Day 3 evidence without rerunning empirical analyses."""

    config_path = Path(config_path)
    validation = resolve_project_path("outputs/psf_disaggregation/validation")
    output_root = validation / "gate2" / "closeout" / VERSION
    output_root.mkdir(parents=True, exist_ok=True)
    sources = {
        "gate0_figures": validation
        / "gate0"
        / "v3_qa_grid_halo_datatake_support"
        / "gate0_figure_regeneration.json",
        "primary_selection": validation
        / "gate2"
        / "primary_selection"
        / "v1_post_gate2"
        / "selection.json",
        "shoreline": validation
        / "gate2"
        / "shoreline"
        / "v1_overture_mapped_water"
        / "manifest.json",
        "sensitivity": validation
        / "gate2"
        / "sensitivity"
        / "v1_full_city_sensitivity"
        / "manifest.json",
        "heldout": validation
        / "gate2"
        / "heldout"
        / "v2_physics_buffered_native_cell"
        / "manifest.json",
        "observation_conditions": validation
        / "gate2"
        / "observation_conditions"
        / "v1_daily_coarse_operator"
        / "manifest.json",
        "daily_vnp_audit": resolve_project_path(
            "outputs/psf_disaggregation/inputs/gate2_daily_vnp/audit_summary.json"
        ),
    }
    for name, path in sources.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing closeout source {name}: {path}")

    heldout_root = sources["heldout"].parent
    observation_root = sources["observation_conditions"].parent
    sensitivity_root = sources["sensitivity"].parent
    heldout = pd.read_csv(heldout_root / "summary.csv")
    gain = pd.read_csv(heldout_root / "gain_summary.csv")
    observation = pd.read_csv(observation_root / "condition_summary.csv")
    kernel = pd.read_csv(sensitivity_root / "kernel_sensitivity.csv")

    headline_rows = _headline_metrics(heldout, gain, observation, kernel)
    headline_path = output_root / "headline_metrics.csv"
    _write_csv(headline_path, headline_rows)
    figure_path = output_root / "day3_evidence_summary.png"
    _plot_summary(
        heldout=heldout,
        gain=gain,
        observation=observation,
        kernel=kernel,
        output_path=figure_path,
    )
    classification_path = output_root / "evidence_classification.json"
    classification = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "classification": "bounded_method_result_with_useful_negative_findings",
        "reporting_primary": {
            "radiance": "strict_QA_corrected_VNP46A2",
            "proxy": "built_form_primary",
            "water_variant": "no_water_prior",
            "kernel": "circular_mean_reference",
            "required_baselines": [
                "direct_upsample",
                "uniform_normalized_convolution",
            ],
        },
        "supported_claims": [
            (
                "The implementation produces reproducible, inspectable, "
                "locally normalized structural allocations with explicit "
                "support and consistency diagnostics."
            ),
            (
                "At the physics-set 2550 m held-out buffer, built form improves "
                "native-cell MAE and RMSE over neighbors-only interpolation in "
                "both cities and improves MAE in all five folds per city."
            ),
            (
                "Built form does not materially amplify daily lunar/cloud "
                "association or temporal variability beyond uniform smoothing "
                "in the 500 m daily operator audit."
            ),
            (
                "Water weighting causes proxy-dependent shoreline "
                "redistribution that cannot be validated as more accurate, "
                "supporting no water prior as the simpler reporting primary."
            ),
        ],
        "negative_or_mixed_findings": [
            (
                "Strong structural upweighting (gain >=1.25) increases held-out "
                "absolute error in all four city-by-proxy comparisons."
            ),
            (
                "Delhi S2-only worsens held-out MAE and RMSE at the primary "
                "buffer; New York S2-only has lower error than built form, "
                "showing proxy performance is city-dependent."
            ),
            (
                "Wider Gaussian kernels lose valid support and have worse "
                "operator-consistency error."
            ),
            (
                "Strict daily complete-kernel support is sparse in New York, "
                "with mean 0.263 and median 0.087."
            ),
        ],
        "unsupported_claims": [
            "recovered or observed 10 m nighttime radiance",
            "radiometrically calibrated super-resolution",
            "physical emission or flux conservation",
            "recovered VIIRS point-spread function",
            "validated water correction",
            "fine-scale accuracy without an independent high-resolution nighttime reference",
            "causal correction of lunar or cloud effects",
        ],
        "deferred_or_optional": [
            (
                "Independent calibrated SDGSAT-1 comparison, if a suitable "
                "aligned scene becomes available."
            ),
            (
                "Remove-before-fine-grid-convolution held-out evaluation for a "
                "stronger operator-level leakage claim."
            ),
            (
                "Historical OSM versus contemporary Overture sensitivity; "
                "checkpoints are preserved but the comparison is confounded by "
                "source coverage and was deprioritized."
            ),
        ],
    }
    classification_path.write_text(
        json.dumps(classification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path = output_root / "manifest.json"
    artifacts = {
        "headline_metrics": headline_path,
        "summary_figure": figure_path,
        "evidence_classification": classification_path,
    }
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifact_version": VERSION,
        "config_sha256": disaggregation_config_sha256(config_path),
        "classification": classification["classification"],
        "source_artifacts": {
            name: _file_record(path) for name, path in sources.items()
        },
        "outputs": {name: _file_record(path) for name, path in artifacts.items()},
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _headline_metrics(heldout, gain, observation, kernel) -> list[dict[str, Any]]:
    rows = []
    overall = heldout[
        (heldout["buffer_m"] == 2550)
        & (heldout["fold"].astype(str) == "all")
        & (heldout["radiance_decile"].astype(str) == "all")
    ]
    for record in overall.to_dict(orient="records"):
        rows.extend(
            [
                {
                    "evidence_family": "heldout_primary",
                    "city_id": record["city_id"],
                    "variant": f"{record['proxy']}:{record['method']}",
                    "metric": "mae",
                    "value": record["mae"],
                },
                {
                    "evidence_family": "heldout_primary",
                    "city_id": record["city_id"],
                    "variant": f"{record['proxy']}:{record['method']}",
                    "metric": "rmse",
                    "value": record["rmse"],
                },
            ]
        )
    for record in gain[gain["buffer_m"] == 2550].to_dict(orient="records"):
        rows.append(
            {
                "evidence_family": "allocation_gain",
                "city_id": record["city_id"],
                "variant": f"{record['proxy']}:{record['gain_stratum']}",
                "metric": "structural_minus_neighbors_absolute_error",
                "value": record["structural_minus_neighbors_absolute_error"],
            }
        )
    temporal = observation[
        observation["condition"] == "overall_temporal_variability"
    ]
    for record in temporal.to_dict(orient="records"):
        rows.append(
            {
                "evidence_family": "observation_conditions",
                "city_id": record["city_id"],
                "variant": record["method"],
                "metric": "mean_absolute_within_cell_log_residual",
                "value": record["mean_absolute_within_cell_log_residual"],
            }
        )
    gaussian = kernel[
        (kernel["proxy"] == "built_form_primary")
        & (kernel["kernel_name"] == "gaussian")
    ]
    for record in gaussian.to_dict(orient="records"):
        rows.extend(
            [
                {
                    "evidence_family": "kernel_sensitivity",
                    "city_id": record["city_id"],
                    "variant": f"gaussian_{int(record['fwhm_m'])}m",
                    "metric": "operator_consistency_mae",
                    "value": record["operator_consistency_mae"],
                },
                {
                    "evidence_family": "kernel_sensitivity",
                    "city_id": record["city_id"],
                    "variant": f"gaussian_{int(record['fwhm_m'])}m",
                    "metric": "valid_output_fraction",
                    "value": record["valid_output_fraction"],
                },
            ]
        )
    return rows


def _plot_summary(*, heldout, gain, observation, kernel, output_path: Path) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    overall = heldout[
        (heldout["buffer_m"] == 2550)
        & (heldout["fold"].astype(str) == "all")
        & (heldout["radiance_decile"].astype(str) == "all")
    ]
    methods = ("neighbors_only_prediction", "structural_prediction")
    positions = np.arange(4)
    combinations = [
        ("usa_new_york", "built_form_primary"),
        ("usa_new_york", "s2_only_ablation"),
        ("india_delhi", "built_form_primary"),
        ("india_delhi", "s2_only_ablation"),
    ]
    for offset, method in zip((-0.18, 0.18), methods):
        values = [
            overall[
                (overall.city_id == city)
                & (overall.proxy == proxy)
                & (overall.method == method)
            ].mae.iloc[0]
            for city, proxy in combinations
        ]
        axes[0, 0].bar(
            positions + offset,
            values,
            width=0.36,
            label=method.replace("_prediction", "").replace("_", " "),
        )
    axes[0, 0].set(
        title="Held-out MAE at 2550 m buffer",
        ylabel="MAE",
        xticks=positions,
        xticklabels=["NY built", "NY S2", "Delhi built", "Delhi S2"],
    )
    axes[0, 0].legend()

    primary_gain = gain[gain.buffer_m == 2550]
    strata = ["<0.8", "0.8-1.25", ">=1.25"]
    for (city, proxy), group in primary_gain.groupby(["city_id", "proxy"]):
        series = group.set_index("gain_stratum")[
            "structural_minus_neighbors_absolute_error"
        ]
        axes[0, 1].plot(
            strata,
            [series.loc[stratum] for stratum in strata],
            marker="o",
            label=f"{city.replace('_', ' ')} {proxy.replace('_', ' ')}",
        )
    axes[0, 1].axhline(0, color="black", linewidth=0.8)
    axes[0, 1].set(
        title="Allocation-gain error asymmetry",
        xlabel="allocation gain",
        ylabel="structural − neighbors absolute error",
    )
    axes[0, 1].legend(fontsize=7)

    temporal = observation[
        observation.condition == "overall_temporal_variability"
    ]
    width = 0.24
    for index, method in enumerate(("direct", "uniform", "built_form_no_water")):
        values = [
            temporal[
                (temporal.city_id == city) & (temporal.method == method)
            ].mean_absolute_within_cell_log_residual.iloc[0]
            for city in ("usa_new_york", "india_delhi")
        ]
        axes[1, 0].bar(
            np.arange(2) + (index - 1) * width,
            values,
            width=width,
            label=method.replace("_", " "),
        )
    axes[1, 0].set(
        title="Daily within-cell variability",
        ylabel="mean absolute log residual",
        xticks=np.arange(2),
        xticklabels=["New York", "Delhi"],
    )
    axes[1, 0].legend(fontsize=8)

    gaussian = kernel[
        (kernel.proxy == "built_form_primary") & (kernel.kernel_name == "gaussian")
    ]
    for city, group in gaussian.groupby("city_id"):
        group = group.sort_values("fwhm_m")
        axes[1, 1].plot(
            group.fwhm_m,
            group.operator_consistency_mae,
            marker="o",
            label=f"{city.replace('_', ' ')} MAE",
        )
    axes[1, 1].set(
        title="Kernel sensitivity",
        xlabel="Gaussian FWHM (m)",
        ylabel="operator-consistency MAE",
    )
    axes[1, 1].legend(fontsize=8)
    figure.suptitle("PSF disaggregation Day 3 evidence summary")
    figure.savefig(output_path, dpi=180)
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
    print(build_day3_closeout(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
