from nocturne.disaggregate.sensitivity import (
    configuration_metrics,
    proxy_comparisons,
    water_comparisons,
)


def _record(proxy: str, mae: float, water: str = "combined_soft") -> dict:
    return {
        "configuration": {
            "name": f"{proxy}_{water}",
            "kind": "stationary",
            "proxy": proxy,
            "water_variant": water,
            "kernel_name": "gaussian",
            "fwhm_m": 750.0,
            "radiance_contract": "strict",
        },
        "metrics": {
            "pixel_count": 100,
            "valid_output_mask_pixel_count": 90,
            "operator_consistency_sample_count": 80,
            "operator_consistency_mae": mae,
            "operator_consistency_rmse": mae + 1,
            "operator_consistency_bias": 0.1,
            "boundary_mask_pixel_count": 10,
            "invalid_radiance_neighborhood_mask_pixel_count": 5,
            "invalid_proxy_neighborhood_mask_pixel_count": 4,
            "denominator_floor_mask_pixel_count": 3,
            "insufficient_proxy_support_mask_pixel_count": 2,
        },
    }


def test_configuration_and_proxy_tables() -> None:
    manifest = {
        "cities": [
            {
                "city_id": "city",
                "configurations": [
                    _record("built_form_primary", 2.0),
                    _record("s2_only_ablation", 2.5),
                ],
            }
        ]
    }
    rows = configuration_metrics(manifest)
    assert rows[0]["valid_output_fraction"] == 0.9
    assert rows[0]["boundary_fraction"] == 0.1
    comparison = proxy_comparisons(rows)
    assert comparison[0]["s2_minus_built_mae"] == 0.5

    second_kernel = [dict(row, fwhm_m=1000.0) for row in rows]
    assert len(proxy_comparisons(rows + second_kernel)) == 2


def test_water_table_is_limited_to_circular_comparisons() -> None:
    record = _record("built_form_primary", 2.0)
    record["configuration"]["kernel_name"] = "circular_mean_reference"
    record["metrics"]["water_comparison_to_no_water"] = {
        "comparison_pixel_count": 90,
        "mean_allocation_difference": -0.1,
        "mean_absolute_allocation_difference": 0.4,
        "persistent_water_pixel_count": 20,
        "persistent_water_mean_allocation_difference": -0.2,
    }
    rows = water_comparisons(
        {"cities": [{"city_id": "city", "configurations": [record]}]}
    )
    assert rows == [
        {
            "city_id": "city",
            "proxy": "built_form_primary",
            "water_variant": "combined_soft",
            "comparison_pixel_count": 90,
            "mean_allocation_difference": -0.1,
            "mean_absolute_allocation_difference": 0.4,
            "persistent_water_pixel_count": 20,
            "persistent_water_mean_allocation_difference": -0.2,
        }
    ]
