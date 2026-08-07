"""Compact analytical closeout for coverage-complete broad-QA reporting."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.export import sha256_file
from nocturne.preview.paths import resolve_project_path

VERSION = "v2_broad_qa_reporting"


def run_v2_closeout(config_path: str | Path) -> Path:
    """Join v2 evidence without rewriting strict-v1 validation artifacts."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    config_hash = disaggregation_config_sha256(config_path)
    validation = resolve_project_path(config["outputs"]["validation"]) / "gate2"
    sources = {
        "reporting_selection": validation
        / "primary_selection"
        / "v2_broad_qa_reporting"
        / "selection.json",
        "broad_products": resolve_project_path(config["outputs"]["rasters"])
        / "full_city"
        / "v2_broad_qa_reporting"
        / "artifact_manifest.json",
        "broad_audit": validation
        / "broad_reporting"
        / "v1_coverage_and_water_inland"
        / "manifest.json",
        "broad_heldout": validation
        / "heldout"
        / "v3_physics_buffered_native_cell_broad_qa"
        / "manifest.json",
        "strict_observation_conditions": validation
        / "observation_conditions"
        / "v1_daily_coarse_operator"
        / "manifest.json",
    }
    for name, path in sources.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing v2 closeout source {name}: {path}")

    audit_root = sources["broad_audit"].parent
    heldout_root = sources["broad_heldout"].parent
    product_audit = pd.read_csv(audit_root / "product_audit.csv")
    strict_broad = pd.read_csv(audit_root / "strict_broad_comparison.csv")
    water = pd.read_csv(audit_root / "water_inland_ratio.csv")
    heldout = pd.read_csv(heldout_root / "summary.csv")
    gain = pd.read_csv(heldout_root / "gain_summary.csv")
    primary = heldout[
        (heldout["buffer_m"] == 2550)
        & (heldout["fold"].astype(str) == "all")
        & (heldout["radiance_decile"].astype(str) == "all")
    ]
    headline_rows = _headline_rows(
        product_audit=product_audit,
        strict_broad=strict_broad,
        water=water,
        heldout=heldout,
        primary=primary,
        gain=gain,
    )

    output_root = validation / "closeout" / VERSION
    output_root.mkdir(parents=True, exist_ok=True)
    headline_path = output_root / "headline_metrics.csv"
    _write_csv(headline_path, headline_rows)
    evidence_path = output_root / "evidence_classification.json"
    evidence = {
        "classification": "coverage_complete_bounded_method_result",
        "experiment_contract": {
            "objective": (
                "test whether a static fine-grid structural proxy can allocate "
                "coarse VNP46A2 radiance more plausibly than declared null "
                "allocations while VNP46A2 remains the radiometric authority"
            ),
            "primary_estimand": (
                "native-cell broad-QA held-out prediction error under the frozen "
                "2550 m PSF-support exclusion"
            ),
            "fine_grid_limit": (
                "the 10 m products are structurally allocated observation fields, "
                "not independently observed or calibrated 10 m radiance"
            ),
        },
        "reporting_primary": {
            "radiance": "broad_QA_corrected_VNP46A2_median_minimum_5",
            "proxy": "built_form_primary",
            "water_variant": "no_water_prior",
            "kernel": "circular_mean_reference",
            "required_baselines": ["broad_direct", "broad_uniform"],
        },
        "supported_claims": [
            "all v2 primary and baseline COGs have complete two-city spatial support",
            "the New York S2-only broad-QA sensitivity has zero radiance-neighborhood gaps; remaining invalid pixels are unchanged S2 proxy-support gaps",
            "on the frozen native-cell cohort, broad-QA built form improves overall MAE and RMSE in both cities at the 2550 m buffer",
            "the radiance-blind gain asymmetry persists under broad QA in all four city-by-proxy comparisons",
            "the broad water-versus-inland result remains consistent with general low-proxy reallocation rather than a water-specific effect",
        ],
        "mixed_findings": [
            "Delhi built form improves broad-QA MAE in 4 of 5 folds; fold 3 worsens by only 0.044 radiance units",
            "New York S2-only remains lower-error than built form, while Delhi S2-only remains negative overall",
            "broad QA removes support holes but admits MQF 1 and lower cloud-mask quality",
            "only the New York S2-only spatial raster was regenerated under broad QA; the Delhi S2-only spatial sensitivity remains strict-v1 and is not a like-for-like cross-city map comparison",
        ],
        "inherited_evidence": [
            "the daily observation-condition propagation audit remains strict-QA conservative sensitivity evidence and is not relabeled as broad-QA validation"
        ],
        "unsupported_claims": [
            "observed or calibrated 10 m nighttime radiance",
            "pixel-level accuracy from gain strata",
            "equivalent quality of MQF 0 and MQF 1",
            "broad-QA daily observation-condition correction",
            "validated water correction or recovered physical emissions",
        ],
        "remaining_review": ["user visual inspection of the two v2 built-form primary COGs"],
    }
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    review_path = output_root / "review.md"
    review_path.write_text(_review_markdown(primary, heldout, gain, strict_broad), encoding="utf-8")
    outputs = {
        "headline_metrics": headline_path,
        "evidence_classification": evidence_path,
        "review": review_path,
    }
    manifest = {
        "schema_version": 1,
        "artifact_version": VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config_sha256": config_hash,
        "classification": evidence["classification"],
        "sources": {
            name: {"path": str(path), "sha256": sha256_file(path)} for name, path in sources.items()
        },
        "outputs": {
            name: {"path": str(path), "sha256": sha256_file(path)} for name, path in outputs.items()
        },
        "analytical_closeout_complete": True,
        "visual_review_complete": False,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _headline_rows(**tables: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in tables["product_audit"].to_dict(orient="records"):
        rows.append(
            {
                "evidence_family": "coverage",
                "city_id": record["city_id"],
                "proxy": record["configuration"],
                "stratum": "all",
                "metric": "valid_fraction",
                "value": record["valid_fraction"],
            }
        )
    for record in tables["strict_broad"].to_dict(orient="records"):
        rows.append(
            {
                "evidence_family": "strict_broad",
                "city_id": record["city_id"],
                "proxy": "direct",
                "stratum": "common_support",
                "metric": "pearson",
                "value": record["pearson_on_common_support"],
            }
        )
    for record in tables["primary"].to_dict(orient="records"):
        rows.append(
            {
                "evidence_family": "heldout",
                "city_id": record["city_id"],
                "proxy": record["proxy"],
                "stratum": record["method"],
                "metric": "mae",
                "value": record["mae"],
            }
        )
    for record in tables["gain"][tables["gain"]["buffer_m"] == 2550].to_dict(orient="records"):
        rows.append(
            {
                "evidence_family": "gain",
                "city_id": record["city_id"],
                "proxy": record["proxy"],
                "stratum": record["gain_stratum"],
                "metric": "structural_minus_neighbor_absolute_error",
                "value": record["structural_minus_neighbors_absolute_error"],
            }
        )
    for record in tables["water"].to_dict(orient="records"):
        if record["region"] == "water_minus_inland_reduction":
            rows.append(
                {
                    "evidence_family": "water_inland",
                    "city_id": record["city_id"],
                    "proxy": "built_form_primary",
                    "stratum": "water_minus_inland",
                    "metric": "reduction_fraction_difference",
                    "value": record["reduction_fraction_vs_direct"],
                }
            )
    return rows


def _review_markdown(
    primary: pd.DataFrame,
    heldout: pd.DataFrame,
    gain: pd.DataFrame,
    strict_broad: pd.DataFrame,
) -> str:
    lines = [
        "# Broad-QA v2 analytical closeout",
        "",
        "Classification: **coverage-complete bounded method result**.",
        "",
        "## Experiment contract",
        "",
        "**Objective.** Test whether a static fine-grid structural proxy can allocate coarse VNP46A2 radiance more plausibly than declared null allocations while VNP46A2 remains the only radiometric authority.",
        "",
        "**Primary estimand.** Native-cell broad-QA held-out prediction error on the frozen Gate 0 cohort, using the preregistered 2550 m four-sigma PSF-support exclusion. This is a coarse structural-gain analogue; it is not independent validation of the 10 m field.",
        "",
        "**Frozen method.** Built-form proxy, no water prior, circular-mean reference kernel, direct upsample and uniform normalized convolution as mandatory spatial baselines, and neighbors-only inverse-distance-squared interpolation as the held-out baseline.",
        "",
        "**Sensitivity controls.** S2-only proxy ablation; 1500 m and 2000 m buffer rows; strict-versus-broad QA comparison; water-weighted variants and matched inland low-proxy regions; and the inherited strict-QA daily observation-condition audit.",
        "",
        "The final 10 m COG is therefore a structurally allocated observation product, not observed or calibrated 10 m nighttime radiance.",
        "",
        "## Physics-buffered held-out result",
        "",
        "| City | Proxy | Neighbor MAE | Structural MAE | Neighbor RMSE | Structural RMSE | Improved folds |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (city, proxy), group in primary.groupby(["city_id", "proxy"]):
        methods = group.set_index("method")
        neighbor = methods.loc["neighbors_only_prediction"]
        structural = methods.loc["structural_prediction"]
        fold_rows = heldout[
            (heldout["city_id"] == city)
            & (heldout["proxy"] == proxy)
            & (heldout["buffer_m"] == 2550)
            & (heldout["radiance_decile"].astype(str) == "all")
            & (heldout["fold"].astype(str) != "all")
        ]
        pivot = fold_rows.pivot(index="fold", columns="method", values="mae")
        improved = int((pivot["structural_prediction"] < pivot["neighbors_only_prediction"]).sum())
        lines.append(
            f"| {city} | {proxy} | {neighbor.mae:.3f} | {structural.mae:.3f} | "
            f"{neighbor.rmse:.3f} | {structural.rmse:.3f} | {improved}/5 |"
        )
    lines.extend(
        [
            "",
            "Built form improves overall MAE and RMSE in both cities. Delhi improves in 4/5 folds; the single adverse fold changes MAE by +0.044.",
            "",
            "Gain below 0.8 remains favorable and gain at or above 1.25 remains adverse in every city-by-proxy comparison.",
            "",
            "## Coverage sensitivity",
            "",
        ]
    )
    for row in strict_broad.to_dict(orient="records"):
        lines.append(
            f"- {row['city_id']}: strict/broad common-support r = "
            f"{row['pearson_on_common_support']:.5f}; newly filled pixels = "
            f"{int(row['newly_filled_pixel_count']):,}."
        )
    lines.extend(
        [
            "",
            "The strict daily observation-condition result remains inherited conservative sensitivity evidence, not broad-QA daily validation.",
            "",
            "## Spatial-product scope",
            "",
            "Broad-QA direct, uniform, and built-form/no-water products are complete in both cities. The New York S2-only ablation was also regenerated under broad QA, but retains an explicit S2 proxy-support mask. Delhi's S2-only spatial raster remains strict-v1; the two displayed S2 city rasters therefore must not be treated as a radiance-contract-matched cross-city comparison.",
            "",
            "Analytical closeout is complete. User visual review of the two v2 primary COGs remains the final presentation check.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    print(run_v2_closeout(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
