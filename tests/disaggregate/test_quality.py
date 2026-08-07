from __future__ import annotations

import pandas as pd

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.quality import (
    decode_qf_cloud_mask,
    evaluate_vnp_quality_contract,
)


def test_decode_qf_cloud_mask_fields() -> None:
    value = 1 | (5 << 1) | (3 << 4) | (2 << 6) | (1 << 8) | (1 << 9) | (1 << 10)
    decoded = decode_qf_cloud_mask([value]).iloc[0]
    assert decoded.to_dict() == {
        "qf_day_night": 1,
        "qf_land_water_background": 5,
        "qf_cloud_mask_quality": 3,
        "qf_cloud_detection": 2,
        "qf_shadow_detected": 1,
        "qf_cirrus_detected": 1,
        "qf_snow_ice_surface": 1,
    }


def test_decode_qf_cloud_mask_preserves_missing_values() -> None:
    decoded = decode_qf_cloud_mask([None])
    assert decoded.isna().all(axis=None)
    assert all(dtype == pd.UInt8Dtype() for dtype in decoded.dtypes)


def test_primary_vnp_quality_contract_is_strict() -> None:
    config = load_disaggregation_config("configs/psf_disaggregation.yaml")
    primary = config["sources"]["vnp46a2"]["quality_contracts"]["primary"]
    high_quality_clear = 3 << 4
    probably_clear = (3 << 4) | (1 << 6)
    cloudy = (3 << 4) | (3 << 6)
    mask = evaluate_vnp_quality_contract(
        mandatory_quality=[0, 0, 1, 0, 0],
        qf_cloud_mask=[
            high_quality_clear,
            probably_clear,
            high_quality_clear,
            cloudy,
            high_quality_clear,
        ],
        snow_flag=[0, 0, 0, 0, 1],
        contract=primary,
    )
    assert mask.tolist() == [True, True, False, False, False]


def test_broad_vnp_quality_contract_retains_mqf_one() -> None:
    config = load_disaggregation_config("configs/psf_disaggregation.yaml")
    broad = config["sources"]["vnp46a2"]["quality_contracts"]["broad_sensitivity"]
    clear = 2 << 4
    mask = evaluate_vnp_quality_contract(
        mandatory_quality=[0, 1, 3],
        qf_cloud_mask=[clear, clear, clear],
        snow_flag=[0, 0, 0],
        contract=broad,
    )
    assert mask.tolist() == [True, True, False]
