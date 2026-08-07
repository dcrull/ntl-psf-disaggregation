from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from nocturne.preview.paths import resolve_project_path

REQUIRED_SECTIONS = {
    "experiment",
    "cities",
    "date_window",
    "grid",
    "earth_engine",
    "sources",
    "allocation_proxies",
    "kernels",
    "validation",
    "outputs",
}


def load_disaggregation_config(config_path: str | Path) -> dict[str, Any]:
    path = resolve_project_path(config_path, must_exist=True)
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise TypeError(f"Disaggregation config must be a mapping: {path}")
    validate_disaggregation_config(config)
    return config


def disaggregation_config_sha256(config_path: str | Path) -> str:
    path = resolve_project_path(config_path, must_exist=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_disaggregation_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_SECTIONS - set(config)
    if missing:
        raise ValueError(f"Disaggregation config is missing sections: {sorted(missing)}")

    window = config["date_window"]
    start = date.fromisoformat(window["start"])
    end_exclusive = date.fromisoformat(window["end_exclusive"])
    center = date.fromisoformat(window["center"])
    if end_exclusive <= start:
        raise ValueError("date_window.end_exclusive must be after date_window.start")
    if not start <= center < end_exclusive:
        raise ValueError("date_window.center must fall inside the half-open date window")
    if (end_exclusive - start).days != 100:
        raise ValueError("The locked pilot date window must contain exactly 100 days")

    selected_city_ids = config["cities"].get("selected_city_ids", [])
    if selected_city_ids != ["usa_new_york", "india_delhi"]:
        raise ValueError("The locked pilot cities must be NYC followed by Delhi")

    geometry = config["cities"]["analysis_geometry"]
    if geometry["type"] != "projected_square":
        raise ValueError("The sprint analysis geometry must be a projected square")
    if float(geometry["side_length_km"]) != 50.0:
        raise ValueError("The locked sprint analysis square must be exactly 50 km per side")
    if float(geometry["source_halo_m"]) < 500:
        raise ValueError("Source inputs must cover at least one nominal coarse-cell halo")
    if int(config["earth_engine"]["interactive_request_deadline_ms"]) < 1:
        raise ValueError("Earth Engine interactive request deadline must be positive")
    export = config["earth_engine"]["export"]
    edge_inset_m = float(export["region_edge_inset_m"])
    if not 0 < edge_inset_m < int(config["grid"]["resolution_m"]) / 2:
        raise ValueError(
            "Earth Engine export edge inset must be positive and less than half a pixel"
        )

    grid = config["grid"]
    if int(grid["resolution_m"]) != 10:
        raise ValueError("The locked working-grid resolution is 10 m")
    if grid["crs_strategy"] != "per_city_utm":
        raise ValueError("The sprint requires an explicit projected per-city UTM grid")
    if grid["continuous_resampling"]["method"] != "bilinear":
        raise ValueError("Continuous sprint rasters must declare bilinear resampling")
    if grid["categorical_resampling"]["method"] != "nearest":
        raise ValueError("Categorical sprint rasters must declare nearest resampling")

    sentinel2 = config["sources"]["sentinel2"]
    cloud_score = sentinel2["cloud_score"]
    threshold = float(cloud_score["clear_threshold"])
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("Cloud Score+ clear_threshold must be in [0, 1]")
    if (
        sentinel2["composite_method"]
        != "index_of_bandwise_temporal_medians_after_datatake_mosaic"
    ):
        raise ValueError("The primary S2 composite method must be explicitly locked")
    if int(sentinel2["minimum_common_valid_observations"]) < 1:
        raise ValueError("S2 minimum common valid observations must be positive")

    vnp = config["sources"]["vnp46a2"]
    quality_contracts = vnp.get("quality_contracts", {})
    if set(quality_contracts) != {"primary", "broad_sensitivity"}:
        raise ValueError("VNP QA must define primary and broad_sensitivity contracts")
    if quality_contracts["primary"]["mandatory_quality_values"] != [0]:
        raise ValueError("The strict primary VNP QA contract must use MQF 0 only")
    for name, contract in quality_contracts.items():
        if int(contract["minimum_valid_observations"]) < 1:
            raise ValueError(f"VNP QA contract {name} needs a positive observation minimum")
        if not contract["cloud_detection_values"]:
            raise ValueError(f"VNP QA contract {name} needs allowed cloud states")
    broad_scope = quality_contracts["broad_sensitivity"]["downstream_analysis"]
    expected_broad_scope = {
        "mode": "targeted_reference_configuration",
        "include_in_full_factorial": False,
        "city_ids": ["usa_new_york"],
        "allocation_proxy": "built_form_primary",
        "kernel": "circular_mean_reference",
        "water_variant": "combined_soft",
        "purpose": "quantify_effect_of_strict_qa_support_gap",
    }
    if broad_scope != expected_broad_scope:
        raise ValueError(
            "Broad VNP QA must remain a targeted New York reference-configuration "
            "check outside the full factorial"
        )
    gap_filled = vnp["gap_filled_sensitivity"]
    maximum_age = int(gap_filled["maximum_retrieval_age_days"])
    if maximum_age != 30:
        raise ValueError("The versioned Day 2 gap-filled sensitivity must use 30 days")
    declared_ages = [int(value) for value in gap_filled["retrieval_age_sensitivities_days"]]
    if maximum_age not in declared_ages:
        raise ValueError("Primary gap-filled retrieval age must be a declared sensitivity")
    if declared_ages != sorted(set(declared_ages)) or declared_ages[0] < 0:
        raise ValueError("Gap-filled retrieval-age sensitivities must be unique and sorted")
    if int(gap_filled["minimum_recent_days"]) < 1:
        raise ValueError("Gap-filled sensitivity needs a positive recent-day minimum")
    if gap_filled["automatic_primary_replacement"]:
        raise ValueError("Gap-filled sensitivity cannot automatically replace corrected radiance")
    if gap_filled["repeated_daily_values_are_independent_retrievals"]:
        raise ValueError("Gap-filled carried-forward days cannot be treated as independent retrievals")

    variants = set(config["allocation_proxies"].get("variants", []))
    required_variants = {
        "direct_upsample",
        "uniform_normalized_convolution",
        "built_form_primary",
        "s2_only_ablation",
    }
    if variants != required_variants:
        raise ValueError(
            f"Allocation-proxy variants must be exactly {sorted(required_variants)}"
        )

    built = config["allocation_proxies"]["built_form"]
    if abs(float(built["building_weight"]) + float(built["road_weight"]) - 1.0) > 1e-9:
        raise ValueError("Built-form building and road weights must sum to one")
    if built["rasterization"] != {
        "decision_id": "OVERTURE-RASTER-001",
        "source_crs": "EPSG:4326",
        "building_fraction": {
            "method": "binary_union_subpixel_center_sampling",
            "subpixel_resolution_m": 2,
            "cutout_sensitivity_resolution_m": 1,
            "overlap_policy": "union",
            "invalid_geometry_policy": "make_valid_then_polygon_parts",
        },
        "weighted_road_length": {
            "method": "segmentized_midpoint_length_allocation",
            "maximum_segment_length_m": 1,
            "cutout_sensitivity_maximum_segment_length_m": 0.5,
            "overlap_policy": "additive_centerline_length",
            "assumed_road_width_m": None,
            "length_conservation_relative_tolerance": 0.0001,
        },
        "cutout_sensitivity": {
            "size_m": 1000,
            "selection_method": "nonradiance_aligned_block_extremes",
            "roles": [
                "dense_building",
                "sparse_built",
                "water_adjacent_infrastructure",
            ],
            "sparse_minimum_infrastructure_fraction": 0.05,
            "uses_vnp_radiance": False,
            "retain_full_sensitivity_rasters": False,
        },
        "output_overview_resampling": "nearest",
    }:
        raise ValueError("Overture rasterization must match OVERTURE-RASTER-001")
    if built["unlisted_road_class_policy"] != "error":
        raise ValueError("Unlisted road classes must fail rather than receive a silent weight")
    if float(built["road_density_saturation_m_per_km2"]) <= 0:
        raise ValueError("Road-density saturation must be positive")

    water = config["validation"]["water_handling"]
    required_water_variants = {
        "no_water_prior",
        "persistent_only_soft",
        "spectral_only_soft",
        "combined_soft",
        "combined_hard_persistent_sensitivity_only",
        "soft_with_mapped_infrastructure_override",
    }
    if set(water["variants"]) != required_water_variants:
        raise ValueError("The complete factorial water-variant contract is required")
    if water["primary_variant"] != "combined_soft":
        raise ValueError("The locked S2 water primary must be combined_soft")
    if not 0.0 <= float(water["proxy_floor"]) < 1.0:
        raise ValueError("The structural proxy floor must be in [0, 1)")

    gate0 = config["validation"]["gate0"]
    if float(gate0["aggregation_halo_m"]) < 500:
        raise ValueError("Gate 0 halo must cover at least one nominal VIIRS pixel width")
    coarse_support = float(gate0["minimum_s2_coarse_support_fraction"])
    if not 0.0 < coarse_support <= 1.0:
        raise ValueError("Gate 0 S2 coarse support fraction must be in (0, 1]")
    if int(gate0["interactive_chunk_attempts"]) < 1:
        raise ValueError("Gate 0 interactive chunk attempts must be positive")

    gate1 = config["validation"]["gate1"]
    support_fraction = float(gate1["minimum_valid_kernel_support_fraction"])
    if not 0.0 < support_fraction <= 1.0:
        raise ValueError("Gate 1 minimum valid kernel support must be in (0, 1]")
    if float(gate1["support_fraction_tolerance"]) <= 0:
        raise ValueError("Gate 1 support-fraction tolerance must be positive")
    if gate1["edge_padding"] != "constant_invalid":
        raise ValueError("Gate 1 must expose raster edges as constant-invalid support")
    if (
        gate1["proxy_normalization"]
        != config["allocation_proxies"]["common_normalization"]
    ):
        raise ValueError("Gate 1 must use the declared common proxy normalization")
    if gate1["denominator_epsilon_reference"] != "normalized_proxy_mean":
        raise ValueError("The relative denominator epsilon must reference normalized mean one")
    if (
        gate1["negative_radiance_policy"]
        != "retain_in_numerator_then_clip_negative_output_after_recording"
    ):
        raise ValueError("Gate 1 negative-radiance handling must remain explicit")
    if gate1["output_nodata"] != "nan":
        raise ValueError("Gate 1 in-memory nodata must be NaN")

    native_footprints = [
        sensitivity
        for sensitivity in config["kernels"]["sensitivities"]
        if sensitivity["type"] == "native_vnp_footprint"
    ]
    if len(native_footprints) != 1 or native_footprints[0].get("priority") != "major":
        raise ValueError("The actual VNP source footprint must be one major kernel sensitivity")
    gaussian = [
        sensitivity
        for sensitivity in config["kernels"]["sensitivities"]
        if sensitivity["type"] == "gaussian"
    ]
    if len(gaussian) != 1:
        raise ValueError("Exactly one named Gaussian kernel sensitivity is required")
    if gaussian[0].get("parameter") != "fwhm_m":
        raise ValueError("Gaussian sensitivity widths must be named as FWHM")
    if float(gaussian[0].get("truncate_sigma", 0)) < 3.0:
        raise ValueError("Gaussian kernels must retain at least three sigma of support")

    day2_inputs = config["outputs"]["day2_inputs"]
    if len(day2_inputs["earth_engine_bands"]) != len(
        set(day2_inputs["earth_engine_bands"])
    ):
        raise ValueError("Day 2 Earth Engine bundle band names must be unique")
    if len(day2_inputs["overture_bands"]) != len(set(day2_inputs["overture_bands"])):
        raise ValueError("Day 2 Overture bundle band names must be unique")
    required_ee_bands = {
        "vnp_median_corrected_radiance",
        "vnp_valid_observation_count",
        "vnp_source_observation_count",
        "vnp_quality_rejected_observation_count",
        "vnp_quality_retained_fraction",
        "vnp_broad_median_corrected_radiance",
        "vnp_broad_valid_observation_count",
        "vnp_gap_filled_recent7d_median_radiance",
        "vnp_gap_filled_recent7d_day_count",
        "vnp_gap_filled_recent30d_median_radiance",
        "vnp_gap_filled_recent30d_day_count",
        "vnp_gap_filled_recent90d_median_radiance",
        "vnp_gap_filled_recent90d_day_count",
        "vnp_gap_filled_source_observation_count",
        "vnp_fresh_high_quality_retrieval_count",
        "vnp_latest_high_quality_retrieval_days_median",
        "vnp_latest_high_quality_retrieval_days_p90",
        "s2_base_proxy_unwatered_unfloored",
        "s2_spectral_water_weight",
        "persistent_water_weight",
        "persistent_water_mask",
    }
    if not required_ee_bands.issubset(day2_inputs["earth_engine_bands"]):
        raise ValueError("Day 2 Earth Engine bundle omits required operator inputs")
    required_overture_bands = {
        "built_form_base_proxy_unwatered_unfloored",
        "mapped_infrastructure_mask",
    }
    if not required_overture_bands.issubset(day2_inputs["overture_bands"]):
        raise ValueError("Day 2 Overture bundle omits required operator inputs")
