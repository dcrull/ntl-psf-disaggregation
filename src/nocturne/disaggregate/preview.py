from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.experiment.manifest import build_experiment_manifest, load_experiment_config
from nocturne.preview.paths import resolve_project_path


def write_visual_previews(config_path: str | Path) -> list[Path]:
    config = load_disaggregation_config(config_path)
    cities = _load_pilot_cities(config)
    grids = {grid.city_id: grid for grid in build_city_grid_specs(config_path)}
    output_root = resolve_project_path(config["outputs"]["previews"])
    output_root.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    city_sections = []
    gate_root = (
        resolve_project_path(config["outputs"]["validation"])
        / "gate0"
        / config["validation"]["gate0"]["artifact_version"]
    )
    for city in cities.itertuples(index=False):
        figures = [
            (
                "corrected Gate 0 — built-form primary",
                gate_root / f"{city.city_id}_built_form_gate0.png",
            ),
            (
                "corrected Gate 0 — S2-only ablation",
                gate_root / f"{city.city_id}_s2_only_gate0.png",
            ),
        ]
        missing = [path for _, path in figures if not path.exists()]
        if missing:
            raise FileNotFoundError(
                f"Run both corrected Gate 0 proxies before the preview bundle: {missing}"
            )
        city_sections.append(
            (
                city.city,
                city.city_id,
                [
                    (
                        name,
                        Path("..") / path.relative_to(output_root.parent),
                    )
                    for name, path in figures
                ],
            )
        )

    index_path = output_root / "index.html"
    index_path.write_text(_preview_index(city_sections), encoding="utf-8")
    written.append(index_path)

    script_path = output_root / "gee_inspector.js"
    script_path.write_text(
        _gee_inspector_script(config, cities, grids),
        encoding="utf-8",
    )
    written.append(script_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the durable Day 1 inspection bundle.")
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    for path in write_visual_previews(args.config):
        print(path)
    return 0


def _preview_index(city_sections) -> str:
    sections = []
    for city, city_id, images in city_sections:
        cards = "\n".join(
            (
                '<figure><figcaption>'
                f"{html.escape(name)}</figcaption>"
                f'<img src="{html.escape(str(path))}" loading="lazy"></figure>'
            )
            for name, path in images
        )
        sections.append(f"<h2>{html.escape(city)} ({html.escape(city_id)})</h2><main>{cards}</main>")
    inspection_note = """<p>The figures below are the corrected, versioned
Gate 0 artifacts generated from actual native VIIRS cell supports. They test
coarse association and alignment only, not within-cell nighttime allocation.
For interactive RGB, NDVI, NDBI, MNDWI, water, QA, and proxy layers, paste
<code>gee_inspector.js</code> into the Earth Engine Code Editor.</p>"""
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nocturne allocation — Day 1 previews</title>
<style>
body { margin: 2rem; color: #202124; background: #f8f9fa; font: 15px system-ui; }
main { display: grid; grid-template-columns: repeat(auto-fit,minmax(360px,1fr)); gap: 1rem; }
figure { margin: 0; padding: .8rem; background: white; border: 1px solid #dadce0; }
figcaption { margin-bottom: .6rem; font-weight: 650; }
img { display: block; width: 100%; height: auto; background: #eee; }
code { background: #eee; padding: .1rem .3rem; }
</style>
</head>
<body>
<h1>Day 1 validation and inspection bundle</h1>
""" + inspection_note + "\n" + "\n".join(sections) + """
</body>
</html>
"""


def _gee_inspector_script(config, cities, grids) -> str:
    city_entries = ",\n".join(
        (
            f"  {city.city_id!r}: "
            f"{{name: {city.city!r}, ring: "
            f"{json.dumps([list(point) for point in grids[city.city_id].analysis_wgs84_ring])}, "
            f"crs: {grids[city.city_id].crs!r}, "
            f"transform: {json.dumps(list(grids[city.city_id].transform))}}}"
        )
        for city in cities.itertuples(index=False)
    )
    window = config["date_window"]
    threshold = config["sources"]["sentinel2"]["cloud_score"]["clear_threshold"]
    minimum_s2 = config["sources"]["sentinel2"]["minimum_common_valid_observations"]
    primary_vnp = config["sources"]["vnp46a2"]["quality_contracts"]["primary"]
    primary_vnp_json = json.dumps(primary_vnp)
    proxy = config["allocation_proxies"]["s2_only"]
    floor = config["validation"]["water_handling"]["proxy_floor"]
    return f"""// Nocturne Day 1 inspector — paste into code.earthengine.google.com
// S2 is a structural allocation proxy, not high-resolution nighttime radiance.
// RESAMPLE-001: continuous S2 bands -> bilinear; categorical masks/counts -> nearest.
// S2-COMPOSITE-001: overlapping MGRS tiles are mosaicked once per datatake.
// VNP-QA-001: the displayed VNP median uses the strict primary quality contract.
var cities = {{
{city_entries}
}};
var selected = cities.usa_new_york;  // change to cities.india_delhi
var region = ee.Geometry.Polygon([selected.ring], 'EPSG:4326', false);
var targetProjection = ee.Projection(selected.crs, selected.transform);
var start = {window["start"]!r};
var endExclusive = {window["end_exclusive"]!r};
var cloudThreshold = {threshold};
var minimumS2Observations = {minimum_s2};

var cloudScore = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED');
var s2Source = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(region)
  .filterDate(start, endExclusive)
  .linkCollection(cloudScore, ['cs_cdf'])
  .map(function(image) {{
    var scl = image.select('SCL');
    var validScl = scl.neq(1).and(scl.neq(3)).and(scl.neq(8))
      .and(scl.neq(9)).and(scl.neq(10)).and(scl.neq(11));
    var bands = image.select(['B2','B3','B4','B8','B11','B12']);
    var commonBandMask = bands.mask().reduce(ee.Reducer.min());
    var commonValid = image.select('cs_cdf').gte(cloudThreshold)
      .and(validScl).and(commonBandMask);
    var observation = ee.Image.constant(1).updateMask(commonValid)
      .rename('s2_common_valid_observation');
    return image.updateMask(commonValid).addBands(observation);
  }});
var s2Projected = s2Source.map(function(image) {{
  function projectBand(name) {{
    return image.select(name).multiply(0.0001)
      .resample('bilinear').reproject(targetProjection).rename(name);
  }}
  var continuous = projectBand('B2').addBands([
    projectBand('B3'), projectBand('B4'), projectBand('B8'),
    projectBand('B11'), projectBand('B12'),
    image.select('cs_cdf').resample('bilinear')
      .reproject(targetProjection).rename('cs_cdf')
  ]);
  var observation = image.select('s2_common_valid_observation')
    .reproject(targetProjection);
  return continuous.addBands(observation)
    .copyProperties(image, ['DATATAKE_IDENTIFIER', 'system:time_start'])
    .set('nocturne:source_index', image.get('system:index'));
}});
var datatakes = s2Projected.aggregate_array('DATATAKE_IDENTIFIER').distinct();
var s2 = ee.ImageCollection.fromImages(datatakes.map(function(identifier) {{
  var matching = s2Projected.filter(
    ee.Filter.eq('DATATAKE_IDENTIFIER', identifier)
  ).sort('nocturne:source_index');
  return matching.mosaic().set({{
    'DATATAKE_IDENTIFIER': identifier,
    'system:time_start': matching.aggregate_min('system:time_start')
  }});
}}));
function medianBand(name) {{
  return s2.select(name).median().reproject(targetProjection).rename(name);
}}
var composite = medianBand('B2').addBands([
  medianBand('B3'), medianBand('B4'), medianBand('B8'),
  medianBand('B11'), medianBand('B12')
]);
var s2Count = s2.select('s2_common_valid_observation').count()
  .reproject(targetProjection).rename('s2_common_valid_observation_count');
composite = composite.updateMask(s2Count.gte(minimumS2Observations));
var ndvi = composite.normalizedDifference(['B8','B4']).rename('s2_ndvi');
var ndbi = composite.normalizedDifference(['B11','B8']).rename('s2_ndbi');
var mndwi = composite.normalizedDifference(['B3','B11']).rename('s2_mndwi');
var waterOccurrence = ee.Image('JRC/GSW1_4/GlobalSurfaceWater')
  .select('occurrence').unmask(0).reproject(targetProjection);
var waterValid = ee.Image('JRC/GSW1_4/Metadata').select('valid_obs')
  .unmask(0).reproject(targetProjection).gt(0);
var waterWeight = ee.Image(1).subtract(waterOccurrence.divide(90).clamp(0, 1))
  .where(waterValid.not(), 1);
var builtEvidence = ndbi.unitScale(
  {proxy["ndbi_unit_scale"]["minimum"]}, {proxy["ndbi_unit_scale"]["maximum"]}
).clamp(0, 1);
var vegetationWeight = ee.Image(1).subtract(ndvi.unitScale(
  {proxy["ndvi_vegetation_unit_scale"]["minimum"]},
  {proxy["ndvi_vegetation_unit_scale"]["maximum"]}
).clamp(0, 1));
var spectralWaterWeight = ee.Image(1).subtract(mndwi.unitScale(
  {proxy["mndwi_water_unit_scale"]["minimum"]},
  {proxy["mndwi_water_unit_scale"]["maximum"]}
).clamp(0, 1));
var proxy = ee.Image({floor}).add(
  builtEvidence.multiply(vegetationWeight).multiply(spectralWaterWeight)
    .multiply(waterWeight).multiply({1.0 - float(floor)})
).rename('proxy_s2_only_ablation');

var vnpSource = ee.ImageCollection('NASA/VIIRS/002/VNP46A2')
  .filterBounds(region).filterDate(start, endExclusive);
function applyVnpQa(image) {{
  var cloud = image.select('QF_Cloud_Mask').toUint16();
  var cloudQuality = cloud.rightShift(4).bitwiseAnd(3);
  var cloudDetection = cloud.rightShift(6).bitwiseAnd(3);
  var allowedCloud = cloudDetection.eq(0).or(cloudDetection.eq(1));
  var valid = image.select('Mandatory_Quality_Flag').eq(0)
    .and(cloud.bitwiseAnd(1).eq(0))
    .and(cloudQuality.gte({primary_vnp["minimum_cloud_mask_quality"]}))
    .and(allowedCloud)
    .and(cloud.rightShift(8).bitwiseAnd(1).eq(0))
    .and(cloud.rightShift(9).bitwiseAnd(1).eq(0))
    .and(cloud.rightShift(10).bitwiseAnd(1).eq(0))
    .and(image.select('Snow_Flag').eq(0));
  return image.updateMask(valid);
}}
var vnp = vnpSource.map(applyVnpQa);
var vnpMedian = vnp.select('DNB_BRDF_Corrected_NTL').median();
var vnpCount = vnp.select('DNB_BRDF_Corrected_NTL').count();
var vnpSourceCount = vnpSource.select('DNB_BRDF_Corrected_NTL').count();
vnpMedian = vnpMedian.updateMask(vnpCount.gte(
  {primary_vnp["minimum_valid_observations"]}
));
var vnpRetainedFraction = vnpCount.divide(vnpSourceCount.max(1));

Map.centerObject(region, 10);
Map.addLayer(composite, {{bands:['B4','B3','B2'], min:0, max:0.3, gamma:1.2}}, 'S2 RGB');
Map.addLayer(ndvi, {{min:-0.3,max:0.8,palette:['7f3b08','f7f7f7','1b7837']}}, 'S2 NDVI', false);
Map.addLayer(ndbi, {{min:-0.4,max:0.4,palette:['2166ac','f7f7f7','b2182b']}}, 'S2 NDBI', false);
Map.addLayer(mndwi, {{min:-0.5,max:0.5,palette:['8c510a','f6e8c3','01665e']}}, 'S2 MNDWI', false);
Map.addLayer(waterWeight, {{min:0,max:1,palette:['2166ac','f7f7f7']}}, 'Persistent-water weight', false);
Map.addLayer(waterValid, {{min:0,max:1,palette:['b2182b','f7f7f7']}}, 'JRC observation support', false);
Map.addLayer(proxy, {{min:{floor},max:1,palette:['fff7bc','fec44f','d95f0e','7f0000']}}, 'S2-only allocation proxy (raw)');
Map.addLayer(s2Count, {{min:0,max:40,palette:['67001f','f7f7f7','053061']}}, 'S2 valid-observation count', false);
Map.addLayer(vnpMedian.add(1).log(), {{min:0,max:5.5,palette:['000004','51127c','b73779','fcfdbf']}}, 'VNP strict-QA median log1p', false);
Map.addLayer(vnpCount, {{min:0,max:100,palette:['67001f','f7f7f7','053061']}}, 'VNP strict-QA observation count', false);
Map.addLayer(vnpRetainedFraction, {{min:0,max:1,palette:['b2182b','f7f7f7','2166ac']}}, 'VNP QA-retained fraction', false);
Map.addLayer(region, {{color:'white'}}, selected.name + ' AOI', false);
print('S2 source tile count', s2Source.size());
print('S2 datatake mosaic count', s2.size());
print('VNP source image count', vnpSource.size());
print('VNP-QA-001 primary contract', {primary_vnp_json});
print('RESAMPLE-001', 'continuous=bilinear; categorical=nearest');
"""


def _load_pilot_cities(config):
    source_config = load_experiment_config(config["cities"]["source_config"])
    _, cities = build_experiment_manifest(source_config)
    selected = cities[cities["city_id"].isin(config["cities"]["selected_city_ids"])].copy()
    by_id = selected.set_index("city_id")
    return by_id.loc[config["cities"]["selected_city_ids"]].reset_index()


if __name__ == "__main__":
    raise SystemExit(main())
