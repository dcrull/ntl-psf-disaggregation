"""Gate 2 sensitivity summaries derived from completed full-city artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from nocturne.disaggregate.config import disaggregation_config_sha256, load_disaggregation_config
from nocturne.preview.paths import resolve_project_path

SENSITIVITY_VERSION = "v1_full_city_sensitivity"


def run_sensitivity_summary(config_path: str | Path) -> Path:
    """Create registered comparison tables without recomputing any raster."""

    config_path = Path(config_path)
    config = load_disaggregation_config(config_path)
    raster_root = (
        resolve_project_path(config["outputs"]["rasters"]) / "full_city" / "v1_resumable_tiled"
    )
    source_path = raster_root / "artifact_manifest.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    expected_hash = disaggregation_config_sha256(config_path)
    if source.get("complete") is not True or source.get("config_sha256") != expected_hash:
        raise ValueError("Full-city manifest is incomplete or belongs to another configuration")

    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "sensitivity"
        / SENSITIVITY_VERSION
    )
    output_root.mkdir(parents=True, exist_ok=True)
    configuration_rows = configuration_metrics(source)
    kernel_rows = [
        row
        for row in configuration_rows
        if row["kind"] == "stationary"
        and row["water_variant"] == "combined_soft"
        and row["radiance_contract"] == "strict"
    ]
    proxy_rows = proxy_comparisons(kernel_rows)
    water_rows = water_comparisons(source)

    paths = {
        "configuration_metrics": output_root / "configuration_metrics.csv",
        "kernel_sensitivity": output_root / "kernel_sensitivity.csv",
        "proxy_comparison": output_root / "proxy_comparison.csv",
        "water_sensitivity": output_root / "water_sensitivity.csv",
    }
    _write_csv(paths["configuration_metrics"], configuration_rows)
    _write_csv(paths["kernel_sensitivity"], kernel_rows)
    _write_csv(paths["proxy_comparison"], proxy_rows)
    _write_csv(paths["water_sensitivity"], water_rows)
    figure_path = output_root / "kernel_sensitivity.png"
    _plot_kernel_sensitivity(kernel_rows, figure_path)

    artifacts = {name: _file_record(path) for name, path in paths.items()}
    artifacts["kernel_sensitivity_figure"] = _file_record(figure_path)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifact_version": SENSITIVITY_VERSION,
        "config_sha256": expected_hash,
        "source_manifest": _file_record(source_path),
        "source_configuration_count": len(configuration_rows),
        "artifacts": artifacts,
        "interpretation_contract": [
            "operator consistency is reconstruction error, not independent validation",
            "native-footprint rows use native-cell diagnostics and are not ranked with stationary kernels",
            "water differences are relative to each proxy's no-water circular reference",
        ],
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def configuration_metrics(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten full-city configuration metrics into stable tabular rows."""

    rows = []
    for city in manifest["cities"]:
        for record in city["configurations"]:
            spec = record["configuration"]
            metrics = record["metrics"]
            count = metrics["pixel_count"]
            rows.append(
                {
                    "city_id": city["city_id"],
                    "configuration": spec["name"],
                    "kind": spec["kind"],
                    "proxy": spec.get("proxy"),
                    "water_variant": spec.get("water_variant"),
                    "kernel_name": spec.get("kernel_name"),
                    "fwhm_m": spec.get("fwhm_m"),
                    "radiance_contract": spec["radiance_contract"],
                    "pixel_count": count,
                    "valid_output_fraction": metrics["valid_output_mask_pixel_count"] / count,
                    "operator_consistency_sample_count": metrics[
                        "operator_consistency_sample_count"
                    ],
                    "operator_consistency_mae": metrics.get("operator_consistency_mae"),
                    "operator_consistency_rmse": metrics.get("operator_consistency_rmse"),
                    "operator_consistency_bias": metrics.get("operator_consistency_bias"),
                    "boundary_fraction": metrics["boundary_mask_pixel_count"] / count,
                    "invalid_radiance_neighborhood_fraction": metrics[
                        "invalid_radiance_neighborhood_mask_pixel_count"
                    ]
                    / count,
                    "invalid_proxy_neighborhood_fraction": metrics[
                        "invalid_proxy_neighborhood_mask_pixel_count"
                    ]
                    / count,
                    "denominator_floor_fraction": metrics[
                        "denominator_floor_mask_pixel_count"
                    ]
                    / count,
                    "insufficient_proxy_support_fraction": metrics[
                        "insufficient_proxy_support_mask_pixel_count"
                    ]
                    / count,
                }
            )
    return rows


def proxy_comparisons(kernel_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair built-form and S2-only results under identical kernels."""

    pairs: dict[tuple[str, str, float | None], dict[str, dict[str, Any]]] = {}
    for row in kernel_rows:
        key = (row["city_id"], row["kernel_name"], row["fwhm_m"])
        pairs.setdefault(key, {})[row["proxy"]] = row
    output = []
    for (city_id, kernel_name, fwhm_m), pair in sorted(
        pairs.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or 0)
    ):
        if set(pair) != {"built_form_primary", "s2_only_ablation"}:
            continue
        built = pair["built_form_primary"]
        s2 = pair["s2_only_ablation"]
        output.append(
            {
                "city_id": city_id,
                "kernel_name": kernel_name,
                "fwhm_m": fwhm_m,
                "built_form_operator_consistency_mae": built["operator_consistency_mae"],
                "s2_only_operator_consistency_mae": s2["operator_consistency_mae"],
                "s2_minus_built_mae": (
                    s2["operator_consistency_mae"] - built["operator_consistency_mae"]
                ),
                "built_form_valid_output_fraction": built["valid_output_fraction"],
                "s2_only_valid_output_fraction": s2["valid_output_fraction"],
                "s2_minus_built_valid_fraction": (
                    s2["valid_output_fraction"] - built["valid_output_fraction"]
                ),
            }
        )
    return output


def water_comparisons(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract circular-kernel water-prior perturbations."""

    rows = []
    for city in manifest["cities"]:
        for record in city["configurations"]:
            spec = record["configuration"]
            comparison = record["metrics"].get("water_comparison_to_no_water")
            if spec.get("kernel_name") != "circular_mean_reference" or comparison is None:
                continue
            rows.append(
                {
                    "city_id": city["city_id"],
                    "proxy": spec.get("proxy"),
                    "water_variant": spec.get("water_variant"),
                    "comparison_pixel_count": comparison["comparison_pixel_count"],
                    "mean_allocation_difference": comparison["mean_allocation_difference"],
                    "mean_absolute_allocation_difference": comparison[
                        "mean_absolute_allocation_difference"
                    ],
                    "persistent_water_pixel_count": comparison["persistent_water_pixel_count"],
                    "persistent_water_mean_allocation_difference": comparison[
                        "persistent_water_mean_allocation_difference"
                    ],
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows available for {path.name}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot_kernel_sensitivity(rows: list[dict[str, Any]], path: Path) -> None:
    stationary = [row for row in rows if row["fwhm_m"] is not None]
    cities = sorted({row["city_id"] for row in stationary})
    figure, axes = plt.subplots(len(cities), 2, figsize=(10, 4 * len(cities)), squeeze=False)
    for row_index, city_id in enumerate(cities):
        city_rows = [row for row in stationary if row["city_id"] == city_id]
        for proxy, marker in (("built_form_primary", "o"), ("s2_only_ablation", "s")):
            proxy_rows = sorted(
                (row for row in city_rows if row["proxy"] == proxy),
                key=lambda row: row["fwhm_m"],
            )
            label = proxy.replace("_", " ")
            axes[row_index, 0].plot(
                [row["fwhm_m"] for row in proxy_rows],
                [row["operator_consistency_mae"] for row in proxy_rows],
                marker=marker,
                label=label,
            )
            axes[row_index, 1].plot(
                [row["fwhm_m"] for row in proxy_rows],
                [row["valid_output_fraction"] for row in proxy_rows],
                marker=marker,
                label=label,
            )
        axes[row_index, 0].set_ylabel(f"{city_id}\nconsistency MAE")
        axes[row_index, 1].set_ylabel("valid-output fraction")
        for axis in axes[row_index]:
            axis.set_xlabel("Gaussian FWHM (m)")
            axis.grid(alpha=0.25)
            axis.legend()
    figure.suptitle("Gate 2 full-city kernel sensitivity (combined-soft, strict contract)")
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _file_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "sha256": digest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    print(run_sensitivity_summary(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
