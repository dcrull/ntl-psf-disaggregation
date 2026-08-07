from __future__ import annotations

import numpy as np
import pandas as pd


def decode_qf_cloud_mask(values) -> pd.DataFrame:
    """Decode the VNP46A2 QF_Cloud_Mask bit field.

    Missing inputs remain missing in every decoded output. Bit definitions follow
    the NASA/VIIRS/002/VNP46A2 Earth Engine data catalog.
    """

    numeric = pd.to_numeric(pd.Series(values), errors="coerce")
    valid = numeric.notna()
    encoded = numeric.fillna(0).to_numpy(dtype=np.uint16)

    decoded = pd.DataFrame(
        {
            "qf_day_night": encoded & 0b1,
            "qf_land_water_background": (encoded >> 1) & 0b111,
            "qf_cloud_mask_quality": (encoded >> 4) & 0b11,
            "qf_cloud_detection": (encoded >> 6) & 0b11,
            "qf_shadow_detected": (encoded >> 8) & 0b1,
            "qf_cirrus_detected": (encoded >> 9) & 0b1,
            "qf_snow_ice_surface": (encoded >> 10) & 0b1,
        }
    )
    decoded.loc[~valid.to_numpy(), :] = pd.NA
    return decoded.astype("UInt8")


def evaluate_vnp_quality_contract(
    mandatory_quality,
    qf_cloud_mask,
    snow_flag,
    *,
    contract: dict,
) -> pd.Series:
    """Evaluate the configured VNP contract outside Earth Engine for tests/audits."""

    mandatory = pd.to_numeric(pd.Series(mandatory_quality), errors="coerce")
    cloud_numeric = pd.to_numeric(pd.Series(qf_cloud_mask), errors="coerce")
    snow = pd.to_numeric(pd.Series(snow_flag), errors="coerce")
    decoded = decode_qf_cloud_mask(cloud_numeric)
    valid_input = mandatory.notna() & cloud_numeric.notna() & snow.notna()

    valid = mandatory.isin(contract["mandatory_quality_values"])
    valid &= decoded["qf_cloud_detection"].isin(contract["cloud_detection_values"])
    valid &= decoded["qf_cloud_mask_quality"] >= int(
        contract["minimum_cloud_mask_quality"]
    )
    if contract["require_night"]:
        valid &= decoded["qf_day_night"] == 0
    if contract["exclude_shadow"]:
        valid &= decoded["qf_shadow_detected"] == 0
    if contract["exclude_cirrus"]:
        valid &= decoded["qf_cirrus_detected"] == 0
    if contract["require_snow_free"]:
        valid &= (snow == 0) & (decoded["qf_snow_ice_surface"] == 0)
    return (valid & valid_input).astype(bool)
