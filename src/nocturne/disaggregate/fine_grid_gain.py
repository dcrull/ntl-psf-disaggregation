"""Build proxy-only fine-grid allocation-gain companion COGs."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.shutil import copy as rio_copy
from rasterio.windows import Window

from nocturne.disaggregate.config import (
    disaggregation_config_sha256,
    load_disaggregation_config,
)
from nocturne.disaggregate.empirical_cutouts import (
    _operator_kwargs,
    _read_processing_inputs,
)
from nocturne.disaggregate.export import sha256_file
from nocturne.disaggregate.full_city import (
    DEFAULT_TILE_PIXELS,
    FULL_CITY_VERSION,
    expanded_window,
    iter_core_windows,
)
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.disaggregate.kernels import kernel_from_config
from nocturne.disaggregate.operator import (
    allocation_gain_from_components,
    apply_fork_form_allocation,
)
from nocturne.disaggregate.water import build_water_proxy_variant
from nocturne.preview.paths import resolve_project_path

VERSION = "v1_reporting_primary"
CONFIGURATIONS = {
    "built_form_primary": "built_form_primary__no_water_prior__circular_mean_reference",
    "s2_only_ablation": "s2_only_ablation__no_water_prior__circular_mean_reference",
}
BANDS = ("fine_grid_allocation_gain", "validated_gain_stratum")


def run_fine_grid_gain(
    config_path: str | Path,
    *,
    tile_pixels: int = DEFAULT_TILE_PIXELS,
    proxy: str = "built_form_primary",
    only_city: str | None = None,
) -> Path:
    """Generate companion gain COGs without modifying frozen product COGs."""

    config_path = Path(config_path)
    if proxy not in CONFIGURATIONS:
        raise ValueError(f"Unsupported gain proxy: {proxy}")
    configuration = CONFIGURATIONS[proxy]
    config = load_disaggregation_config(config_path)
    config_hash = disaggregation_config_sha256(config_path)
    raster_root = (
        resolve_project_path(config["outputs"]["rasters"])
        / "full_city"
        / FULL_CITY_VERSION
    )
    full_manifest_path = raster_root / "artifact_manifest.json"
    full_manifest = json.loads(full_manifest_path.read_text(encoding="utf-8"))
    if full_manifest.get("complete") is not True:
        raise ValueError("Full-city artifact manifest is incomplete")
    if full_manifest.get("config_sha256") != config_hash:
        raise ValueError("Full-city artifacts belong to another configuration")

    grids = {grid.city_id: grid for grid in build_city_grid_specs(config_path)}
    records: list[dict[str, Any]] = []
    for city in full_manifest["cities"]:
        city_id = city["city_id"]
        if only_city is not None and city_id != only_city:
            continue
        grid = grids[city_id]
        primary = next(
            record
            for record in city["configurations"]
            if record["configuration"]["name"] == configuration
        )
        product_path = Path(primary["path"])
        output_path = product_path.parent / "trust_indicators.tif"
        input_root = resolve_project_path(config["outputs"]["day2_inputs"]["root"])
        input_config = config["outputs"]["day2_inputs"]
        ee_path = input_root / city_id / input_config["earth_engine_bundle_filename"]
        overture_path = input_root / city_id / input_config["overture_bundle_filename"]
        _build_city_gain(
            config,
            grid=grid,
            ee_path=ee_path,
            overture_path=overture_path,
            normalization_divisor=float(primary["normalization"]["mean"]),
            output_path=output_path,
            config_hash=config_hash,
            tile_pixels=tile_pixels,
            proxy=proxy,
            configuration=configuration,
        )
        records.append(
            {
                "city_id": city_id,
                "configuration": configuration,
                "product_path": str(product_path),
                "product_sha256": primary["sha256"],
                "gain_path": str(output_path),
                "gain_sha256": sha256_file(output_path),
                "band_descriptions": list(BANDS),
            }
        )

    version = "v1_reporting_primary" if proxy == "built_form_primary" else "v1_s2_only_ablation"
    output_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate2"
        / "fine_grid_gain"
        / version
    )
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "artifact_version": version,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config_sha256": config_hash,
        "source_manifest": {
            "path": str(full_manifest_path),
            "sha256": sha256_file(full_manifest_path),
        },
        "formula": "rho(x) / max((k tensor rho)(x), denominator_epsilon)",
        "radiance_blind": True,
        "support_contract": (
            "finite normalized proxy and convolved proxy with complete declared "
            "proxy and geometric kernel support; independent of radiance availability"
        ),
        "stratum_codes": {
            "1": "gain_below_0.8; coarse held-out evidence consistently favorable",
            "2": "gain_0.8_to_below_1.25; near-neutral range",
            "3": "gain_at_or_above_1.25; coarse held-out error increased in all four comparisons",
        },
        "interpretation_limit": (
            "The thresholds transfer a validated coarse diagnostic to its exact "
            "fine-grid operator analogue; they do not constitute pixel-level error calibration."
        ),
        "frozen_products_modified": False,
        "proxy": proxy,
        "records": records,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _build_city_gain(
    config: dict[str, Any],
    *,
    grid: Any,
    ee_path: Path,
    overture_path: Path,
    normalization_divisor: float,
    output_path: Path,
    config_hash: str,
    tile_pixels: int,
    proxy: str,
    configuration: str,
) -> None:
    kernel = kernel_from_config(config, kernel_type="circular_mean")
    halo = 2 * max(int(kernel.halo_rows), int(kernel.halo_columns))
    source_halo = round(
        float(config["cities"]["analysis_geometry"]["source_halo_m"])
        / grid.resolution_m
    )
    analysis_window = Window(source_halo, source_halo, grid.width, grid.height)
    strict_minimum = int(
        config["sources"]["vnp46a2"]["quality_contracts"]["primary"][
            "minimum_valid_observations"
        ]
    )
    broad_minimum = int(
        config["sources"]["vnp46a2"]["quality_contracts"]["broad_sensitivity"]
        ["minimum_valid_observations"]
    )
    working = output_path.with_suffix(".working.tif")
    profile = {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": len(BANDS),
        "dtype": "float32",
        "crs": grid.crs,
        "transform": Affine(*grid.transform),
        "nodata": np.nan,
        "compress": "DEFLATE",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(working, "w", **profile) as destination:
        for index, name in enumerate(BANDS, start=1):
            destination.set_band_description(index, name)
        for core_local in iter_core_windows((grid.height, grid.width), tile_pixels):
            core_source = Window(
                analysis_window.col_off + core_local.col_off,
                analysis_window.row_off + core_local.row_off,
                core_local.width,
                core_local.height,
            )
            processing, crop = expanded_window(
                core_source,
                halo=halo,
                bounds_shape=(5200, 5200),
            )
            components, _ = _read_processing_inputs(
                ee_path,
                overture_path,
                window=processing,
                core_window=core_source,
                strict_minimum_observations=strict_minimum,
                broad_minimum_observations=broad_minimum,
            )
            proxy_values = build_water_proxy_variant(
                components[f"{proxy}_base"],
                variant="no_water_prior",
                persistent_water_weight=components["persistent_water_weight"],
                spectral_water_weight=components["spectral_water_weight"],
                persistent_water_mask=components["persistent_water_mask"],
                mapped_infrastructure_mask=components["mapped_infrastructure_mask"],
                proxy_floor=float(config["validation"]["water_handling"]["proxy_floor"]),
            ).proxy
            result = apply_fork_form_allocation(
                components["strict_radiance"],
                proxy_values,
                kernel=kernel,
                radiance_valid_mask=components["strict_valid_mask"],
                proxy_normalization_divisor=normalization_divisor,
                denominator_reference_mean_after_normalization=1.0,
                **_operator_kwargs(config),
            )
            operator = _operator_kwargs(config)
            proxy_valid = (
                np.isfinite(result.normalized_proxy)
                & np.isfinite(result.convolved_proxy)
                & (
                    result.proxy_support_fraction
                    >= operator["minimum_valid_support_fraction"]
                    - operator["support_fraction_tolerance"]
                )
                & (
                    result.geometric_support_fraction
                    >= operator["minimum_valid_support_fraction"]
                    - operator["support_fraction_tolerance"]
                )
            )
            gain = allocation_gain_from_components(
                result.normalized_proxy,
                result.convolved_proxy,
                valid_mask=proxy_valid,
                denominator_epsilon=result.denominator_epsilon,
            )[crop]
            strata = np.full(gain.shape, np.nan, dtype=np.float32)
            finite = np.isfinite(gain)
            strata[finite & (gain < 0.8)] = 1
            strata[finite & (gain >= 0.8) & (gain < 1.25)] = 2
            strata[finite & (gain >= 1.25)] = 3
            destination.write(gain, 1, window=core_local)
            destination.write(strata, 2, window=core_local)
        destination.update_tags(
            configuration=configuration,
            config_sha256=config_hash,
            formula="rho / max(k_tensor_rho, denominator_epsilon)",
            radiance_blind="true",
        )
    temporary = output_path.with_suffix(".tmp.tif")
    rio_copy(
        working,
        temporary,
        driver="COG",
        compress="DEFLATE",
        blocksize=512,
        # Preserve the integer semantics of Band 2 at reduced zoom levels.
        # Nearest is also acceptable for the diagnostic continuous Band 1.
        overview_resampling=Resampling.nearest.name,
        BIGTIFF="IF_SAFER",
    )
    temporary.replace(output_path)
    working.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "--proxy",
        choices=tuple(CONFIGURATIONS),
        default="built_form_primary",
    )
    parser.add_argument("--only-city")
    args = parser.parse_args()
    print(run_fine_grid_gain(args.config, proxy=args.proxy, only_city=args.only_city))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
