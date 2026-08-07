from __future__ import annotations

from copy import deepcopy

import pytest

from nocturne.disaggregate.config import (
    load_disaggregation_config,
    validate_disaggregation_config,
)
from nocturne.disaggregate.ee_export import resolve_drive_folder


def test_locked_config_is_valid() -> None:
    config = load_disaggregation_config("configs/psf_disaggregation.yaml")
    assert config["date_window"]["center"] == "2024-03-01"
    assert config["cities"]["selected_city_ids"] == ["usa_new_york", "india_delhi"]
    assert config["earth_engine"]["project"] is None
    assert config["earth_engine"]["project_env"] == "NTL_PSF_EE_PROJECT"
    assert config["earth_engine"]["export"]["drive_folder"] is None
    assert (
        config["earth_engine"]["export"]["drive_folder_env"]
        == "NTL_PSF_EE_DRIVE_FOLDER"
    )
    assert config["earth_engine"]["export"]["region_edge_inset_m"] == 0.01
    assert config["experiment"]["contract_version"] == "integrity_v3"
    assert config["cities"]["analysis_geometry"] == {
        "decision_id": "AOI-001",
        "type": "projected_square",
        "side_length_km": 50.0,
        "center_snap_to_grid": True,
        "source_halo_m": 1000,
    }
    assert config["sources"]["vnp46a2"]["quality_contracts"]["primary"][
        "mandatory_quality_values"
    ] == [0]
    assert config["sources"]["vnp46a2"]["quality_contracts"]["broad_sensitivity"][
        "downstream_analysis"
    ] == {
        "mode": "targeted_reference_configuration",
        "include_in_full_factorial": False,
        "city_ids": ["usa_new_york"],
        "allocation_proxy": "built_form_primary",
        "kernel": "circular_mean_reference",
        "water_variant": "combined_soft",
        "purpose": "quantify_effect_of_strict_qa_support_gap",
    }
    assert config["grid"]["continuous_resampling"]["method"] == "bilinear"
    assert config["grid"]["categorical_resampling"]["method"] == "nearest"
    assert (
        config["sources"]["sentinel2"]["composite_method"]
        == "index_of_bandwise_temporal_medians_after_datatake_mosaic"
    )
    assert (
        config["validation"]["gate0"]["artifact_version"]
        == "v3_qa_grid_halo_datatake_support"
    )
    assert set(config["allocation_proxies"]["variants"]) == {
        "direct_upsample",
        "uniform_normalized_convolution",
        "built_form_primary",
        "s2_only_ablation",
    }
    assert config["allocation_proxies"]["built_form"]["rasterization"] == {
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
    }
    assert config["validation"]["gate1"] == {
        "decision_id": "OPERATOR-NUMERICS-001",
        "minimum_valid_kernel_support_fraction": 1.0,
        "support_fraction_tolerance": 0.000001,
        "edge_padding": "constant_invalid",
        "proxy_normalization": "mean_one_over_finite_analysis_support",
        "denominator_epsilon_reference": "normalized_proxy_mean",
        "negative_radiance_policy": (
            "retain_in_numerator_then_clip_negative_output_after_recording"
        ),
        "output_nodata": "nan",
    }
    assert config["kernels"]["sensitivities"][1]["truncate_sigma"] == 4.0
    assert config["outputs"]["day2_inputs"]["earth_engine_bundle_filename"] == (
        "ee_source_bundle.tif"
    )
    assert (
        "vnp_median_corrected_radiance"
        in config["outputs"]["day2_inputs"]["earth_engine_bands"]
    )
    assert (
        config["outputs"]["day2_inputs"]["artifact_version"]
        == "v2_vnp_coverage_diagnostics"
    )
    assert config["sources"]["vnp46a2"]["gap_filled_sensitivity"] == {
        "decision_id": "VNP-COVERAGE-001",
        "description": (
            "Recent gap-filled radiance sensitivity; never a silent replacement "
            "for corrected radiance."
        ),
        "maximum_retrieval_age_days": 30,
        "retrieval_age_sensitivities_days": [7, 30, 90],
        "minimum_recent_days": 10,
        "automatic_primary_replacement": False,
        "repeated_daily_values_are_independent_retrievals": False,
    }


def test_drive_folder_is_resolved_from_private_environment(monkeypatch) -> None:
    monkeypatch.setenv("NTL_PSF_EE_DRIVE_FOLDER", "local-private-folder")
    assert (
        resolve_drive_folder(
            {"drive_folder": None, "drive_folder_env": "NTL_PSF_EE_DRIVE_FOLDER"}
        )
        == "local-private-folder"
    )


def test_date_window_must_be_exactly_100_days() -> None:
    config = load_disaggregation_config("configs/psf_disaggregation.yaml")
    changed = deepcopy(config)
    changed["date_window"]["end_exclusive"] = "2024-04-19"
    with pytest.raises(ValueError, match="exactly 100 days"):
        validate_disaggregation_config(changed)
