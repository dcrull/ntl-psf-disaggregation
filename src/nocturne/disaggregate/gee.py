from __future__ import annotations

import os
from typing import Any


def initialize_earth_engine(
    *, project: str | None = None, project_env: str = "NTL_PSF_EE_PROJECT"
):
    """Initialize Earth Engine for the configured Cloud project.

    Authentication remains an explicit user action: run ``ee.Authenticate()`` or
    ``earthengine authenticate`` before calling this function.
    """

    import ee

    resolved_project = project or os.environ.get(project_env)
    if not resolved_project:
        raise RuntimeError(
            f"Set {project_env} to the registered Google Cloud / Earth Engine project ID"
        )
    ee.Initialize(project=resolved_project)
    return ee


def initialize_earth_engine_from_config(config: dict[str, Any]):
    earth_engine = config["earth_engine"]
    ee = initialize_earth_engine(
        project=earth_engine.get("project"),
        project_env=earth_engine.get("project_env", "NTL_PSF_EE_PROJECT"),
    )
    ee.data.setDeadline(float(earth_engine["interactive_request_deadline_ms"]))
    return ee


def build_s2_composite(ee, *, region, config: dict[str, Any], target_grid=None):
    sources = config["sources"]
    window = config["date_window"]
    s2_config = sources["sentinel2"]
    cloud_config = s2_config["cloud_score"]
    qa_band = cloud_config["qa_band"]
    threshold = float(cloud_config["clear_threshold"])
    excluded_scl = list(s2_config["scl_excluded_classes"])
    bands = list(s2_config["bands"])
    continuous_resampling = config["grid"]["continuous_resampling"]["method"]

    cloud_score = (
        ee.ImageCollection(cloud_config["collection"])
        .filterBounds(region)
        .filterDate(window["start"], window["end_exclusive"])
    )
    collection = (
        ee.ImageCollection(s2_config["collection"])
        .filterBounds(region)
        .filterDate(window["start"], window["end_exclusive"])
        .linkCollection(cloud_score, [qa_band])
    )

    def mask_image(image):
        clear = image.select(qa_band).gte(threshold)
        scl = image.select("SCL")
        valid_scl = ee.Image.constant(1)
        for class_value in excluded_scl:
            valid_scl = valid_scl.And(scl.neq(class_value))
        common_band_mask = image.select(bands).mask().reduce(ee.Reducer.min())
        common_valid = clear.And(valid_scl).And(common_band_mask)
        common_valid_observation = (
            ee.Image.constant(1)
            .updateMask(common_valid)
            .rename("s2_common_valid_observation")
        )
        return image.updateMask(common_valid).addBands(common_valid_observation)

    target_projection = _target_projection(
        ee,
        target_grid=target_grid,
        fallback=ee.Image(collection.first()).select(bands[0]).projection(),
    )
    reflectance_scale = float(s2_config.get("reflectance_scale", 1.0))
    masked = collection.map(mask_image)

    def project_image(image):
        projected_bands = [
            _reproject_continuous(
                image.select(band).multiply(reflectance_scale),
                projection=target_projection,
                method=continuous_resampling,
            ).rename(band)
            for band in bands
        ]
        projected = ee.Image(projected_bands[0]).addBands(projected_bands[1:])
        projected_cloud_score = _reproject_continuous(
            image.select(qa_band),
            projection=target_projection,
            method=continuous_resampling,
        ).rename(qa_band)
        projected_observation = _reproject_categorical_nearest(
            image.select("s2_common_valid_observation"),
            projection=target_projection,
        )
        return (
            ee.Image(
                projected.addBands(
                    [projected_cloud_score, projected_observation]
                ).copyProperties(image, ["DATATAKE_IDENTIFIER", "system:time_start"])
            )
            .set("nocturne:source_index", image.get("system:index"))
            .clip(region)
        )

    projected = masked.map(project_image)
    datatake_identifiers = projected.aggregate_array("DATATAKE_IDENTIFIER").distinct()

    def mosaic_datatake(identifier):
        matching = projected.filter(
            ee.Filter.eq("DATATAKE_IDENTIFIER", identifier)
        ).sort("nocturne:source_index")
        return matching.mosaic().set(
            {
                "DATATAKE_IDENTIFIER": identifier,
                "system:time_start": matching.aggregate_min("system:time_start"),
            }
        )

    mosaicked = ee.ImageCollection.fromImages(datatake_identifiers.map(mosaic_datatake))
    median_bands = [
        mosaicked.select(band).median().reproject(target_projection).rename(band)
        for band in bands
    ]
    median = ee.Image(median_bands[0]).addBands(median_bands[1:])
    cloud_score_median = (
        mosaicked.select(qa_band)
        .median()
        .reproject(target_projection)
        .rename("s2_cloud_score_median")
    )
    count = _reproject_categorical_nearest(
        mosaicked.select("s2_common_valid_observation").count(),
        projection=target_projection,
    ).rename("s2_common_valid_observation_count")
    minimum_count = int(s2_config["minimum_common_valid_observations"])
    sufficient_support = count.gte(minimum_count).rename(
        "s2_sufficient_observation_support"
    )
    valid_continuous = median.addBands(cloud_score_median).updateMask(
        sufficient_support
    )
    return (
        valid_continuous.addBands(
            [
                count,
                count.rename("s2_valid_observation_count"),
                sufficient_support,
            ]
        )
        .set(
            {
                "nocturne:composite_method": s2_config["composite_method"],
                "nocturne:continuous_resampling": continuous_resampling,
                "nocturne:categorical_resampling": (
                    config["grid"]["categorical_resampling"]["method"]
                ),
                "nocturne:minimum_common_valid_observations": minimum_count,
                "nocturne:datatake_mosaic_count": datatake_identifiers.size(),
                "nocturne:swir_effective_resolution_m": (
                    s2_config["effective_resolution_m"]["swir_and_swir_indices"]
                ),
            }
        )
        .clip(region)
    )


def build_s2_indices(ee, *, region, config: dict[str, Any], target_grid=None):
    composite = build_s2_composite(
        ee,
        region=region,
        config=config,
        target_grid=target_grid,
    )
    ndvi = _normalized_difference(
        composite,
        first_band="B8",
        second_band="B4",
        output_band="s2_ndvi",
    )
    ndbi = _normalized_difference(
        composite,
        first_band="B11",
        second_band="B8",
        output_band="s2_ndbi",
    )
    mndwi = _normalized_difference(
        composite,
        first_band="B3",
        second_band="B11",
        output_band="s2_mndwi",
    )
    return composite.addBands([ndvi, ndbi, mndwi])


def build_s2_allocation_components(
    ee,
    *,
    region,
    config: dict[str, Any],
    indices=None,
    target_grid=None,
):
    """Return separable S2 evidence and water weights before floor/normalization."""

    if indices is None:
        indices = build_s2_indices(
            ee,
            region=region,
            config=config,
            target_grid=target_grid,
        )
    proxy_config = config["allocation_proxies"]["s2_only"]
    ndbi_scale = proxy_config["ndbi_unit_scale"]
    ndvi_scale = proxy_config["ndvi_vegetation_unit_scale"]
    mndwi_scale = proxy_config["mndwi_water_unit_scale"]
    built_evidence = (
        indices.select("s2_ndbi")
        .unitScale(float(ndbi_scale["minimum"]), float(ndbi_scale["maximum"]))
        .clamp(0, 1)
        .rename("s2_built_evidence")
    )
    vegetation_weight = (
        ee.Image(1)
        .subtract(
            indices.select("s2_ndvi")
            .unitScale(float(ndvi_scale["minimum"]), float(ndvi_scale["maximum"]))
            .clamp(0, 1)
        )
        .rename("s2_low_vegetation_weight")
    )
    spectral_water_weight = (
        ee.Image(1)
        .subtract(
            indices.select("s2_mndwi")
            .unitScale(float(mndwi_scale["minimum"]), float(mndwi_scale["maximum"]))
            .clamp(0, 1)
        )
        .rename("s2_spectral_water_weight")
    )
    base_proxy = built_evidence.multiply(vegetation_weight).rename(
        "s2_base_proxy_unwatered_unfloored"
    )
    return base_proxy.addBands(
        [
            built_evidence,
            vegetation_weight,
            spectral_water_weight,
            indices.select("s2_common_valid_observation_count"),
            indices.select("s2_sufficient_observation_support"),
        ]
    )


def build_s2_only_allocation_proxy(
    ee,
    *,
    region,
    config: dict[str, Any],
    indices=None,
    normalize: bool = True,
    target_grid=None,
    water_variant: str | None = None,
):
    """Build the preregistered S2-only cross-quantity ablation.

    This is a dimensionless structural allocation proxy, not high-resolution NTL.
    """

    if indices is None:
        indices = build_s2_indices(
            ee,
            region=region,
            config=config,
            target_grid=target_grid,
        )
    components = build_s2_allocation_components(
        ee,
        region=region,
        config=config,
        indices=indices,
        target_grid=target_grid,
    )
    spectral_water_weight = components.select("s2_spectral_water_weight")
    selected_water_variant = (
        water_variant or config["validation"]["water_handling"]["primary_variant"]
    )
    use_persistent, use_spectral, persistent_mode = _s2_water_components(
        selected_water_variant
    )
    persistent_water_weight = build_persistent_water_weight(
        ee,
        region=region,
        config=config,
        target_grid=target_grid,
        mode=persistent_mode if use_persistent else "none",
    )
    raw = components.select("s2_base_proxy_unwatered_unfloored")
    if use_spectral:
        raw = raw.multiply(spectral_water_weight)
    if use_persistent:
        raw = raw.multiply(persistent_water_weight)
    floor = float(config["validation"]["water_handling"]["proxy_floor"])
    proxy = (
        ee.Image(floor)
        .add(raw.multiply(1.0 - floor))
        .rename("proxy_s2_only_ablation")
        .set(
            {
                "nocturne:water_variant": selected_water_variant,
                "nocturne:proxy_floor": floor,
            }
        )
    )
    if normalize:
        return _normalize_proxy_mean_one(
            ee,
            proxy,
            region=region,
            target_grid=target_grid,
        )
    return proxy


def build_persistent_water_layers(
    ee,
    *,
    region,
    config: dict[str, Any],
    target_grid=None,
    mode: str = "soft",
):
    source = config["sources"]["water"]
    if mode not in {"none", "soft", "hard"}:
        raise ValueError(f"Unsupported persistent-water mode: {mode}")
    target_projection = _target_projection(
        ee,
        target_grid=target_grid,
        fallback=ee.Image(source["collection"]).select(source["band"]).projection(),
    )
    occurrence = _reproject_categorical_nearest(
        ee.Image(source["collection"]).select(source["band"]).unmask(0),
        projection=target_projection,
    ).rename("persistent_water_occurrence_percent")
    valid_observations = _reproject_categorical_nearest(
        ee.Image(source["metadata_collection"])
        .select(source["valid_observations_band"])
        .unmask(0),
        projection=target_projection,
    ).rename("persistent_water_valid_observation_count")
    observation_support = valid_observations.gt(0).rename(
        "persistent_water_observation_support"
    )
    threshold = float(source["persistent_occurrence_threshold"])
    if mode == "none":
        weight = ee.Image(1)
    elif mode == "hard":
        weight = occurrence.lt(threshold)
    else:
        weight = ee.Image(1).subtract(occurrence.divide(threshold).clamp(0, 1))
    weight = (
        weight.where(observation_support.Not(), 1)
        .rename("persistent_water_weight")
        .set(
            {
                "nocturne:water_semantics": "30 m temporal occurrence prior, 1984-2021",
                "nocturne:water_resampling": source["resampling_method"],
                "nocturne:persistent_water_mode": mode,
            }
        )
    )
    return occurrence.addBands([valid_observations, observation_support, weight]).clip(
        region
    )


def build_persistent_water_weight(
    ee,
    *,
    region,
    config: dict[str, Any],
    target_grid=None,
    mode: str = "soft",
):
    return build_persistent_water_layers(
        ee,
        region=region,
        config=config,
        target_grid=target_grid,
        mode=mode,
    ).select("persistent_water_weight")


def build_vnp_source_collection(ee, *, region, config: dict[str, Any]):
    source = config["sources"]["vnp46a2"]
    window = config["date_window"]
    return (
        ee.ImageCollection(source["collection"])
        .filterBounds(region)
        .filterDate(window["start"], window["end_exclusive"])
        .select(list(source["retained_bands"]))
    )


def build_vnp_daily_collection(
    ee,
    *,
    region,
    config: dict[str, Any],
    quality_variant: str = "primary",
):
    source = config["sources"]["vnp46a2"]
    contract = source["quality_contracts"][quality_variant]
    return build_vnp_source_collection(ee, region=region, config=config).map(
        lambda image: _apply_vnp_quality_contract(ee, image, contract=contract)
    )


def build_vnp_median(
    ee,
    *,
    region,
    config: dict[str, Any],
    quality_variant: str = "primary",
):
    source = config["sources"]["vnp46a2"]
    target_band = source["target_band"]
    source_daily = build_vnp_source_collection(ee, region=region, config=config)
    daily = build_vnp_daily_collection(
        ee,
        region=region,
        config=config,
        quality_variant=quality_variant,
    )
    contract = source["quality_contracts"][quality_variant]
    base_projection = ee.Image(source_daily.first()).select(target_band).projection()
    valid_count = (
        daily.select(target_band)
        .count()
        .rename("vnp_valid_observation_count")
        .setDefaultProjection(base_projection)
    )
    source_count = (
        source_daily.select(target_band)
        .count()
        .rename("vnp_source_observation_count")
        .setDefaultProjection(base_projection)
    )
    sufficient_support = valid_count.gte(
        int(contract["minimum_valid_observations"])
    ).rename("vnp_sufficient_observation_support")
    median = (
        daily.select(target_band)
        .median()
        .rename("vnp_median_corrected_ntl")
        .setDefaultProjection(base_projection)
        .updateMask(sufficient_support)
    )
    rejected_count = source_count.subtract(valid_count).rename(
        "vnp_quality_rejected_observation_count"
    )
    valid_fraction = valid_count.divide(source_count.max(1)).rename(
        "vnp_quality_retained_fraction"
    )
    return (
        median.addBands(
            [
                valid_count,
                source_count,
                rejected_count,
                valid_fraction,
                sufficient_support,
            ]
        )
        .set(
            {
                "nocturne:vnp_quality_variant": quality_variant,
                "nocturne:vnp_minimum_valid_observations": (
                    contract["minimum_valid_observations"]
                ),
                "nocturne:vnp_mandatory_quality_values": ",".join(
                    str(value) for value in contract["mandatory_quality_values"]
                ),
            }
        )
        .clip(region)
    )


def build_vnp_gap_filled_sensitivity(
    ee,
    *,
    region,
    config: dict[str, Any],
    maximum_age_days: int | None = None,
):
    """Build an explicitly age-bounded gap-filled sensitivity and diagnostics.

    Gap-filled daily values may carry one high-quality retrieval forward across
    multiple days. Their day count is therefore coverage of represented days,
    not a count of independent radiance retrievals.
    """

    source_config = config["sources"]["vnp46a2"]
    sensitivity = source_config["gap_filled_sensitivity"]
    gap_band = source_config["fallback_band"]
    age_band = "Latest_High_Quality_Retrieval"
    resolved_maximum_age_days = int(
        sensitivity["maximum_retrieval_age_days"]
        if maximum_age_days is None
        else maximum_age_days
    )
    declared_ages = {
        int(value) for value in sensitivity["retrieval_age_sensitivities_days"]
    }
    if resolved_maximum_age_days not in declared_ages:
        raise ValueError(
            f"Undeclared gap-filled retrieval-age sensitivity: {resolved_maximum_age_days}"
        )
    minimum_recent_days = int(sensitivity["minimum_recent_days"])
    recent_prefix = f"vnp_gap_filled_recent{resolved_maximum_age_days}d"
    source = build_vnp_source_collection(ee, region=region, config=config)
    base_projection = ee.Image(source.first()).select(gap_band).projection()

    def mask_to_recent_retrieval(image):
        return (
            image.select(gap_band)
            .updateMask(image.select(age_band).lte(resolved_maximum_age_days))
            .rename(f"{recent_prefix}_daily_radiance")
        )

    recent = source.map(mask_to_recent_retrieval)
    source_count = (
        source.select(gap_band)
        .count()
        .rename("vnp_gap_filled_source_observation_count")
        .setDefaultProjection(base_projection)
    )
    recent_day_count = (
        recent.count()
        .rename(f"{recent_prefix}_day_count")
        .setDefaultProjection(base_projection)
    )
    recent_median = (
        recent.median()
        .rename(f"{recent_prefix}_median_radiance")
        .setDefaultProjection(base_projection)
        .updateMask(recent_day_count.gte(minimum_recent_days))
    )
    fresh_retrieval_count = (
        source.select(age_band)
        .map(
            lambda image: image.eq(0).rename(
                "vnp_fresh_high_quality_retrieval_indicator"
            )
        )
        .sum()
        .rename("vnp_fresh_high_quality_retrieval_count")
        .setDefaultProjection(base_projection)
    )
    age_median = (
        source.select(age_band)
        .median()
        .rename("vnp_latest_high_quality_retrieval_days_median")
        .setDefaultProjection(base_projection)
    )
    age_p90 = (
        source.select(age_band)
        .reduce(ee.Reducer.percentile([90]))
        .rename("vnp_latest_high_quality_retrieval_days_p90")
        .setDefaultProjection(base_projection)
    )
    return (
        recent_median.addBands(
            [
                source_count,
                recent_day_count,
                fresh_retrieval_count,
                age_median,
                age_p90,
            ]
        )
        .set(
            {
                "nocturne:vnp_gap_filled_sensitivity": True,
                "nocturne:maximum_retrieval_age_days": resolved_maximum_age_days,
                "nocturne:minimum_recent_days": minimum_recent_days,
                "nocturne:repeated_days_are_independent_retrievals": False,
                "nocturne:automatic_primary_replacement": False,
            }
        )
        .clip(region)
    )


def _normalized_difference(
    image, *, first_band: str, second_band: str, output_band: str
):
    return image.expression(
        "(first - second) / (first + second + 1e-6)",
        {
            "first": image.select(first_band),
            "second": image.select(second_band),
        },
    ).rename(output_band)


def _normalize_proxy_mean_one(ee, proxy, *, region, target_grid=None):
    reduction_arguments: dict[str, Any] = {
        "reducer": ee.Reducer.mean(),
        "geometry": region,
        "bestEffort": False,
        "maxPixels": 100_000_000,
    }
    if target_grid is None:
        reduction_arguments["scale"] = 100
    else:
        reduction_arguments["crs"] = target_grid.crs
        reduction_arguments["crsTransform"] = list(target_grid.transform)
    mean = ee.Number(
        proxy.reduceRegion(**reduction_arguments).get(proxy.bandNames().get(0))
    )
    normalized = ee.Image(proxy.divide(mean.max(1e-6)).copyProperties(proxy))
    return normalized.rename(proxy.bandNames())


def _apply_vnp_quality_contract(ee, image, *, contract: dict[str, Any]):
    mandatory_quality = image.select("Mandatory_Quality_Flag")
    mandatory_mask = _equals_any(
        ee,
        mandatory_quality,
        contract["mandatory_quality_values"],
    )
    cloud = image.select("QF_Cloud_Mask").toUint16()
    day_night = cloud.bitwiseAnd(1)
    cloud_mask_quality = cloud.rightShift(4).bitwiseAnd(3)
    cloud_detection = cloud.rightShift(6).bitwiseAnd(3)
    shadow = cloud.rightShift(8).bitwiseAnd(1)
    cirrus = cloud.rightShift(9).bitwiseAnd(1)
    qf_snow = cloud.rightShift(10).bitwiseAnd(1)

    valid = mandatory_mask.And(
        _equals_any(ee, cloud_detection, contract["cloud_detection_values"])
    ).And(cloud_mask_quality.gte(int(contract["minimum_cloud_mask_quality"])))
    if contract["require_night"]:
        valid = valid.And(day_night.eq(0))
    if contract["exclude_shadow"]:
        valid = valid.And(shadow.eq(0))
    if contract["exclude_cirrus"]:
        valid = valid.And(cirrus.eq(0))
    if contract["require_snow_free"]:
        valid = valid.And(image.select("Snow_Flag").eq(0)).And(qf_snow.eq(0))
    return image.updateMask(valid).set(
        "nocturne:vnp_quality_contract_applied",
        True,
    )


def _equals_any(ee, image, values):
    mask = ee.Image(0)
    for value in values:
        mask = mask.Or(image.eq(int(value)))
    return mask


def _target_projection(ee, *, target_grid, fallback):
    if target_grid is None:
        return fallback
    return ee.Projection(target_grid.crs, list(target_grid.transform))


def _reproject_continuous(image, *, projection, method: str):
    if method not in {"bilinear", "bicubic"}:
        raise ValueError(
            f"Continuous resampling must be bilinear or bicubic, got {method}"
        )
    return image.resample(method).reproject(projection)


def _reproject_categorical_nearest(image, *, projection):
    """Reproject without resample(); Earth Engine's declared nearest default is intentional."""

    return image.reproject(projection)


def _s2_water_components(variant: str) -> tuple[bool, bool, str]:
    variants = {
        "no_water_prior": (False, False, "none"),
        "persistent_only_soft": (True, False, "soft"),
        "spectral_only_soft": (False, True, "none"),
        "combined_soft": (True, True, "soft"),
        "combined_hard_persistent_sensitivity_only": (True, True, "hard"),
    }
    if variant == "soft_with_mapped_infrastructure_override":
        raise ValueError(
            "Mapped-infrastructure override applies to the built-form proxy, not S2-only"
        )
    try:
        return variants[variant]
    except KeyError as error:
        raise ValueError(f"Unsupported S2 water variant: {variant}") from error
