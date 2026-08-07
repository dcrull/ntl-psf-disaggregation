"""Run synthetic Gate 1 invariants and write the Day 2 visual inspection bundle."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely import affinity

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from rasterio.transform import from_origin

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.export import (
    AllocationArtifactIdentity,
    write_allocation_cog_bundle,
)
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.disaggregate.kernels import (
    AllocationKernel,
    kernel_from_config,
)
from nocturne.disaggregate.operator import (
    AllocationResult,
    apply_fork_form_allocation,
    direct_upsample_baseline,
    summarize_allocation_result,
    uniform_normalized_convolution_baseline,
)
from nocturne.disaggregate.validate import water_allocation_metrics
from nocturne.disaggregate.water import WATER_VARIANTS, build_water_proxy_variant
from nocturne.preview.paths import resolve_project_path


def run_gate1(config_path: str | Path) -> list[Path]:
    config = load_disaggregation_config(config_path)
    output_root = resolve_project_path(config["outputs"]["validation"]) / "gate1"
    output_root.mkdir(parents=True, exist_ok=True)
    fixture = synthetic_coastline_fixture()
    reference_kernel = kernel_from_config(config, kernel_type="circular_mean")
    operator_kwargs = _operator_kwargs(config)

    direct = direct_upsample_baseline(fixture["radiance"])
    uniform = uniform_normalized_convolution_baseline(
        fixture["radiance"],
        kernel=reference_kernel,
        **operator_kwargs,
    )
    variant_results: dict[str, AllocationResult] = {}
    variant_proxies: dict[str, np.ndarray] = {}
    rows: list[dict[str, Any]] = []
    no_water_allocation: np.ndarray | None = None
    for variant in WATER_VARIANTS:
        water_proxy = build_water_proxy_variant(
            fixture["base_proxy"],
            variant=variant,
            persistent_water_weight=fixture["persistent_water_weight"],
            spectral_water_weight=fixture["spectral_water_weight"],
            persistent_water_mask=fixture["persistent_water_mask"],
            mapped_infrastructure_mask=fixture["mapped_infrastructure_mask"],
            proxy_floor=float(config["validation"]["water_handling"]["proxy_floor"]),
        )
        result = apply_fork_form_allocation(
            fixture["radiance"],
            water_proxy.proxy,
            kernel=reference_kernel,
            **operator_kwargs,
        )
        variant_results[variant] = result
        variant_proxies[variant] = water_proxy.proxy
        if variant == "no_water_prior":
            no_water_allocation = result.allocation
        summary = summarize_allocation_result(
            result,
            source_radiance=fixture["radiance"],
            insufficient_proxy_threshold=float(
                config["validation"]["gate0"]["insufficient_proxy_mean_threshold"]
            ),
        )
        summary.update(
            {
                "method": variant,
                "method_class": "water_variant",
                "gate": "gate1_synthetic_coastline",
            }
        )
        rows.append(summary)
    if no_water_allocation is None:
        raise AssertionError("The required no-water reference was not run")

    for row in rows:
        variant = row["method"]
        row.update(
            water_allocation_metrics(
                variant_results[variant].allocation,
                source_radiance=fixture["radiance"],
                water_reference_mask=fixture["water_mask"],
                adjacent_land_mask=fixture["adjacent_land_mask"],
                reference_allocation=(
                    None if variant == "no_water_prior" else no_water_allocation
                ),
            )
        )
    summary_table = pd.DataFrame(rows)
    summary_csv = output_root / "synthetic_coastline_gate1_summary.csv"
    summary_table.to_csv(summary_csv, index=False)

    representative_kernels = _representative_kernel_set(config_path, config)
    payload = {
        "schema_version": 1,
        "experiment_id": config["experiment"]["id"],
        "contract_version": config["experiment"]["contract_version"],
        "config_sha256": disaggregation_config_sha256(config_path),
        "gate": "Gate 1",
        "fixture": {
            "name": "bright_land_adjacent_water",
            "shape": list(fixture["radiance"].shape),
            "resolution_m": config["grid"]["resolution_m"],
            "interpretation": (
                "synthetic operator invariant and shoreline-transfer fixture; "
                "not empirical city evidence"
            ),
        },
        "reference_kernel": reference_kernel.to_metadata(),
        "representative_kernel_set": {
            name: kernel.to_metadata()
            for name, kernel in representative_kernels.items()
        },
        "kernel_halo_audit": _kernel_halo_audit(
            config=config,
            kernels=representative_kernels,
        ),
        "water_variant_results": rows,
        "gate1_checks": _gate1_checks(
            fixture=fixture,
            direct=direct,
            uniform=uniform,
            variants=variant_results,
        ),
    }
    summary_json = output_root / "synthetic_coastline_gate1_summary.json"
    summary_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    npz_path = output_root / "synthetic_coastline_gate1_arrays.npz"
    np.savez_compressed(
        npz_path,
        source_radiance=fixture["radiance"].astype(np.float32),
        base_proxy=fixture["base_proxy"].astype(np.float32),
        water_mask=fixture["water_mask"],
        persistent_water_mask=fixture["persistent_water_mask"],
        adjacent_land_mask=fixture["adjacent_land_mask"],
        mapped_infrastructure_mask=fixture["mapped_infrastructure_mask"],
        direct_upsample=direct,
        uniform_normalized_convolution=uniform.allocation,
        **{
            f"allocation_{variant}": result.allocation
            for variant, result in variant_results.items()
        },
        **{
            f"proxy_{variant}": proxy.astype(np.float32)
            for variant, proxy in variant_proxies.items()
        },
    )

    coastline_figure = output_root / "synthetic_coastline_gate1.png"
    _write_coastline_figure(
        fixture=fixture,
        direct=direct,
        uniform=uniform,
        variants=variant_results,
        output_path=coastline_figure,
    )
    kernel_figure = output_root / "allocation_kernel_supports.png"
    _write_kernel_figure(representative_kernels, output_path=kernel_figure)
    synthetic_cog_paths = write_allocation_cog_bundle(
        variant_results["combined_soft"],
        output_directory=output_root / "synthetic_cog_bundle",
        identity=AllocationArtifactIdentity(
            city_id="synthetic_gate1",
            interval_start=config["date_window"]["start"],
            interval_end_exclusive=config["date_window"]["end_exclusive"],
            allocation_proxy="synthetic_structural_proxy",
            water_variant="combined_soft",
            kernel_type=reference_kernel.kernel_type,
            kernel_parameter_name=reference_kernel.parameter_name,
            kernel_parameter_value=reference_kernel.parameter_value,
            vnp_resampling="nearest",
            config_sha256=disaggregation_config_sha256(config_path),
        ),
        crs="EPSG:32618",
        transform=from_origin(
            0,
            fixture["radiance"].shape[0] * float(config["grid"]["resolution_m"]),
            float(config["grid"]["resolution_m"]),
            float(config["grid"]["resolution_m"]),
        ),
        extra_metadata={
            "fixture": "synthetic_bright_land_adjacent_water",
            "synthetic_georeferencing": (
                "local metre grid encoded in EPSG:32618 for software inspection; "
                "not an empirical location"
            ),
        },
    )
    index_path = output_root / "index.html"
    index_path.write_text(
        _gate1_index(
            figure_names=[coastline_figure.name, kernel_figure.name],
            checks=payload["gate1_checks"],
        ),
        encoding="utf-8",
    )
    return [
        summary_csv,
        summary_json,
        npz_path,
        coastline_figure,
        kernel_figure,
        index_path,
        *synthetic_cog_paths,
    ]


def synthetic_coastline_fixture(size: int = 401) -> dict[str, np.ndarray]:
    """Create a deterministic bright-land/adjacent-water operator fixture."""

    if size < 201 or size % 2 == 0:
        raise ValueError("Synthetic coastline size must be odd and at least 201")
    rows, columns = np.indices((size, size))
    center = (size - 1) / 2.0
    coast_column = center + 16.0 * np.sin((rows - center) / 43.0)
    signed_coast_distance_pixels = columns - coast_column
    water = signed_coast_distance_pixels >= 0
    adjacent_land = (~water) & (signed_coast_distance_pixels >= -10)

    block_size = 25
    block_rows = (rows // block_size) * block_size + block_size / 2.0
    block_columns = (columns // block_size) * block_size + block_size / 2.0
    broad_city = 20.0 * np.exp(
        -((block_rows - center) ** 2 + (block_columns - (center - 55)) ** 2)
        / (2 * 90.0**2)
    )
    port = 16.0 * np.exp(
        -((block_rows - (center + 65)) ** 2 + (block_columns - center) ** 2)
        / (2 * 34.0**2)
    )
    radiance = 1.5 + broad_city + port
    radiance += np.where(water, 2.5, 0.0)

    structure = 0.08 + 0.75 * np.exp(
        -((rows - center) ** 2 + (columns - (center - 62)) ** 2)
        / (2 * 75.0**2)
    )
    structure += 0.22 * (np.mod(rows + 2 * columns, 53) <= 2)
    structure += 0.26 * np.exp(
        -((rows - (center + 65)) ** 2 + (columns - (center - 8)) ** 2)
        / (2 * 24.0**2)
    )
    structure = np.clip(structure, 0, 1)

    bridge = (
        (np.abs(rows - (center - 45)) <= 3)
        & (signed_coast_distance_pixels >= -18)
        & (signed_coast_distance_pixels <= 18)
    )
    mapped_port = (
        (rows - (center + 65)) ** 2 + (columns - center) ** 2 <= 18.0**2
    )
    infrastructure = bridge | mapped_port
    synthetic_occurrence = np.where(
        water,
        np.clip(35.0 + 2.5 * signed_coast_distance_pixels, 0.0, 100.0),
        0.0,
    )
    persistent_weight = 1.0 - np.clip(synthetic_occurrence / 90.0, 0.0, 1.0)
    persistent_mask = synthetic_occurrence >= 90.0
    spectral_weight = np.where(water, 0.15, 1.0)
    return {
        "radiance": radiance.astype(np.float32),
        "base_proxy": structure.astype(np.float32),
        "water_mask": water,
        "persistent_water_mask": persistent_mask,
        "adjacent_land_mask": adjacent_land,
        "mapped_infrastructure_mask": infrastructure,
        "persistent_water_weight": persistent_weight.astype(np.float32),
        "spectral_water_weight": spectral_weight.astype(np.float32),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Gate 1 synthetic operator invariants and visual diagnostics."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    for path in run_gate1(args.config):
        print(path)
    return 0


def _operator_kwargs(config: dict[str, Any]) -> dict[str, float]:
    gate1 = config["validation"]["gate1"]
    return {
        "denominator_epsilon_relative": float(
            config["allocation_proxies"]["denominator_epsilon_relative"]
        ),
        "denominator_instability_threshold_relative": float(
            config["validation"]["gate0"]["insufficient_proxy_mean_threshold"]
        ),
        "minimum_valid_support_fraction": float(
            gate1["minimum_valid_kernel_support_fraction"]
        ),
        "support_fraction_tolerance": float(gate1["support_fraction_tolerance"]),
    }


def _representative_kernel_set(
    config_path: str | Path,
    config: dict[str, Any],
) -> dict[str, AllocationKernel]:
    kernels: dict[str, AllocationKernel] = {
        "Fork-form reference · 500 m radius": kernel_from_config(
            config,
            kernel_type="circular_mean",
        )
    }
    grids = {grid.city_id: grid for grid in build_city_grid_specs(config_path)}
    gate0_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate0"
        / config["validation"]["gate0"]["artifact_version"]
    )
    for city_id in config["cities"]["selected_city_ids"]:
        samples_path = gate0_root / f"{city_id}_s2_only_samples.csv"
        if not samples_path.exists():
            raise FileNotFoundError(
                f"Gate 1 native-footprint preview requires corrected Gate 0: {samples_path}"
            )
        samples = pd.read_csv(
            samples_path,
            usecols=[
                "coarse_cell_id",
                "coarse_cell_polygon_wkt",
                "radius_m",
            ],
        )
        row = samples.loc[samples["radius_m"].idxmin()]
        polygon_wgs84 = shapely.from_wkt(row["coarse_cell_polygon_wkt"])
        transformer = Transformer.from_crs(
            "EPSG:4326",
            grids[city_id].crs,
            always_xy=True,
        )
        polygon_projected = shapely.transform(
            polygon_wgs84,
            transformer.transform,
            interleaved=False,
        )
        centroid = shapely.centroid(polygon_projected)
        local = affinity.translate(
            polygon_projected,
            xoff=-float(shapely.get_x(centroid)),
            yoff=-float(shapely.get_y(centroid)),
        )
        kernels[f"{city_id} · representative native cell"] = kernel_from_config(
            config,
            kernel_type="native_vnp_footprint",
            footprint=local,
            footprint_id=str(row["coarse_cell_id"]),
        )
    gaussian = next(
        item
        for item in config["kernels"]["sensitivities"]
        if item["type"] == "gaussian"
    )
    for fwhm_m in gaussian["values"]:
        kernels[f"Gaussian · FWHM {fwhm_m} m"] = kernel_from_config(
            config,
            kernel_type="gaussian",
            fwhm_m=float(fwhm_m),
        )
    return kernels


def _gate1_checks(
    *,
    fixture: dict[str, np.ndarray],
    direct: np.ndarray,
    uniform: AllocationResult,
    variants: dict[str, AllocationResult],
) -> dict[str, bool]:
    all_allocations = [uniform.allocation] + [
        result.allocation for result in variants.values()
    ]
    authority = fixture["radiance"]
    return {
        "all_outputs_nonnegative_on_valid_support": all(
            bool(np.nanmin(allocation) >= 0) for allocation in all_allocations
        ),
        "direct_and_uniform_are_distinct": bool(
            not np.allclose(
                direct[uniform.valid_output_mask],
                uniform.allocation[uniform.valid_output_mask],
            )
        ),
        "every_water_variant_retains_positive_water_authority": all(
            float(np.maximum(authority[fixture["water_mask"]], 0).sum()) > 0
            for _ in variants
        ),
        "hard_sensitivity_changes_adjacent_land": bool(
            np.nansum(
                np.abs(
                    variants[
                        "combined_hard_persistent_sensitivity_only"
                    ].allocation[fixture["adjacent_land_mask"]]
                    - variants["no_water_prior"].allocation[
                        fixture["adjacent_land_mask"]
                    ]
                )
            )
            > 0
        ),
        "all_declared_water_variants_ran": set(variants) == set(WATER_VARIANTS),
    }


def _kernel_halo_audit(
    *,
    config: dict[str, Any],
    kernels: dict[str, AllocationKernel],
) -> dict[str, Any]:
    available_halo_m = float(config["cities"]["analysis_geometry"]["source_halo_m"])
    rows = []
    for name, kernel in kernels.items():
        required_halo_m = max(kernel.halo_rows, kernel.halo_columns) * kernel.resolution_m
        rows.append(
            {
                "kernel": name,
                "required_halo_m": required_halo_m,
                "available_source_halo_m": available_halo_m,
                "full_analysis_square_support": required_halo_m <= available_halo_m,
                "additional_invalid_edge_width_m": max(
                    required_halo_m - available_halo_m,
                    0.0,
                ),
            }
        )
    return {
        "policy": (
            "retain the declared 1 km source halo for the reference run; mark "
            "incomplete sensitivity support invalid rather than padding with data"
        ),
        "kernels": rows,
    }


def _write_coastline_figure(
    *,
    fixture: dict[str, np.ndarray],
    direct: np.ndarray,
    uniform: AllocationResult,
    variants: dict[str, AllocationResult],
    output_path: Path,
) -> None:
    no_water = variants["no_water_prior"].allocation
    combined = variants["combined_soft"].allocation
    hard = variants["combined_hard_persistent_sensitivity_only"].allocation
    override = variants["soft_with_mapped_infrastructure_override"].allocation
    difference = hard - no_water
    panels = [
        ("Source VNP radiance authority", fixture["radiance"], "magma", None),
        ("Structural base proxy", fixture["base_proxy"], "viridis", None),
        ("Persistent-water weight", fixture["persistent_water_weight"], "Blues_r", None),
        ("Direct upsample null", direct, "magma", None),
        ("Uniform normalized-convolution null", uniform.allocation, "magma", None),
        ("No-water-prior allocation", no_water, "magma", None),
        ("Combined-soft primary", combined, "magma", None),
        ("Hard-persistent sensitivity", hard, "magma", None),
        ("Infrastructure-override sensitivity", override, "magma", None),
        (
            "Combined-soft operator-consistency error",
            variants["combined_soft"].operator_consistency_error,
            "RdBu_r",
            "centered",
        ),
        (
            "Combined-soft valid kernel support",
            variants["combined_soft"].radiance_support_fraction,
            "viridis",
            None,
        ),
        ("Hard minus no-water allocation", difference, "RdBu_r", "centered"),
    ]
    figure, axes = plt.subplots(3, 4, figsize=(18, 13), constrained_layout=True)
    for axis, (title, values, cmap, scaling) in zip(axes.flat, panels, strict=True):
        finite = np.asarray(values)[np.isfinite(values)]
        if finite.size:
            if scaling == "centered":
                limit = float(np.percentile(np.abs(finite), 98))
                norm = TwoSlopeNorm(vmin=-max(limit, 1e-9), vcenter=0, vmax=max(limit, 1e-9))
                image = axis.imshow(values, cmap=cmap, norm=norm)
            else:
                low, high = np.percentile(finite, [2, 98])
                if np.isclose(low, high):
                    high = low + 1
                image = axis.imshow(values, cmap=cmap, vmin=low, vmax=high)
            figure.colorbar(image, ax=axis, fraction=0.046, pad=0.02)
        axis.contour(
            fixture["water_mask"],
            levels=[0.5],
            colors=["#22D3EE"],
            linewidths=0.8,
        )
        axis.contour(
            fixture["mapped_infrastructure_mask"],
            levels=[0.5],
            colors=["#FDE047"],
            linewidths=0.7,
        )
        axis.set_title(title, fontsize=10)
        axis.set_xticks([])
        axis.set_yticks([])
    figure.suptitle(
        "Gate 1 synthetic coastline — cyan: water boundary; yellow: mapped infrastructure",
        fontsize=15,
        fontweight="bold",
    )
    figure.savefig(output_path, dpi=170)
    plt.close(figure)


def _write_kernel_figure(
    kernels: dict[str, AllocationKernel],
    *,
    output_path: Path,
) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(15, 9), constrained_layout=True)
    for axis, (name, kernel) in zip(axes.flat, kernels.items(), strict=True):
        weights = np.where(kernel.weights > 0, kernel.weights, np.nan)
        image = axis.imshow(weights, cmap="magma")
        axis.set_title(
            f"{name}\n{kernel.weights.shape[1]}×{kernel.weights.shape[0]} cells",
            fontsize=10,
        )
        axis.set_xticks([])
        axis.set_yticks([])
        figure.colorbar(image, ax=axis, fraction=0.046, pad=0.02)
    figure.suptitle(
        "Declared allocation supports — algorithmic sensitivities, not recovered PSFs",
        fontsize=15,
        fontweight="bold",
    )
    figure.savefig(output_path, dpi=170)
    plt.close(figure)


def _gate1_index(*, figure_names: list[str], checks: dict[str, bool]) -> str:
    cards = "\n".join(
        f'<figure><img src="{html.escape(name)}"><figcaption>{html.escape(name)}</figcaption></figure>'
        for name in figure_names
    )
    checks_html = "\n".join(
        f"<li><strong>{'PASS' if passed else 'FAIL'}</strong> — "
        f"{html.escape(name.replace('_', ' '))}</li>"
        for name, passed in checks.items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nocturne allocation — Gate 1</title>
<style>
body {{ margin: 2rem; color: #202124; background: #f8f9fa; font: 15px system-ui; }}
main {{ display: grid; grid-template-columns: 1fr; gap: 1.2rem; }}
figure {{ margin: 0; padding: .8rem; background: white; border: 1px solid #dadce0; }}
figcaption {{ margin-top: .6rem; font-weight: 650; }}
img {{ display: block; width: 100%; height: auto; background: #eee; }}
li {{ margin: .35rem 0; }}
</style>
</head>
<body>
<h1>Day 2 · Gate 1 operator inspection</h1>
<p>These are synthetic invariants and support visualizations, not empirical
city results or independent fine-scale validation. Water changes only the
structural proxy; the source VIIRS radiance authority remains present.</p>
<h2>Automated checks</h2>
<ul>{checks_html}</ul>
<main>{cards}</main>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
