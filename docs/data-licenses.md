# Data licenses, retrieval, and redistribution

Last reviewed: 2026-08-07

This document records the upstream terms that apply to the data used by this
repository and identifies what is, and is not, redistributed here. It is a
practical compliance record, not legal advice. Upstream license text and service
terms control if they differ from this summary.

The repository's [BSD 3-Clause License](../LICENSE) covers project-authored
software and documentation. It does **not** relicense third-party observations,
map databases, or imagery. For project-authored analytical artifacts, BSD terms
apply only to the original selection, organization, analysis, and presentation;
the source notices below must remain with any artifact that incorporates an
upstream source.

## Source register

| Source | Use in this experiment | Version or time pin | Data terms | Required credit / action |
|---|---|---|---|---|
| NASA VIIRS Black Marble VNP46A2 | Radiometric authority and QA bands | Collection 2; 2024-01-11 inclusive to 2024-04-20 exclusive | NASA-led mission data are CC0 unless specifically marked otherwise. The VNP46A2 catalog asks authors to cite the dataset. | Cite VNP46A2.002 and acknowledge NASA; do not imply NASA endorsement. |
| Copernicus Sentinel-2 | Surface-reflectance inputs to the structural proxy | `COPERNICUS/S2_SR_HARMONIZED`; same 100-day window | Free, full, and open use under the Copernicus Sentinel Data Legal Notice, including reproduction, distribution, adaptation, and combination. | Modified outputs must say `Contains modified Copernicus Sentinel data 2024`. |
| Google Cloud Score+ | Sentinel-2 clear-observation QA | `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` | CC BY 4.0 | Credit Google Earth Engine and cite Pasquarella et al. (2023). Indicate that the QA data were modified/combined. |
| OpenStreetMap | Historical structural sensitivity and an upstream contributor to Overture | Attic snapshot requested at `2024-03-01T00:00:00Z` | Open Database License 1.0 (ODbL) | Display `© OpenStreetMap contributors`, make the ODbL clear, and apply ODbL share-alike to a publicly used Derivative Database. |
| Overture Maps | Building coverage, transportation segments, mapped infrastructure, and validation water | Structures `2026-07-22.0`; water `2026-06-17.0` | Base, Buildings, and Transportation themes are ODbL. Individual upstream source notices listed by Overture also apply. | Use `© OpenStreetMap contributors, Overture Maps Foundation`, link the ODbL, and retain relevant Overture source notices. |
| JRC Global Surface Water | Internal persistent-water occurrence prior; inactive in the reporting-primary no-water configuration | v1.4, 1984–2021 occurrence | Copernicus Programme data, free of charge and without use restriction; acknowledgement and citation required. | For a published map, use `Source: EC JRC/Google`; cite Pekel et al. (2016). |

## Source-specific details

### NASA VIIRS VNP46A2 Collection 2

The exact Earth Engine collection is `NASA/VIIRS/002/VNP46A2`. The experiment
uses `DNB_BRDF_Corrected_NTL`, its gap-filled counterpart for declared
sensitivities, lunar irradiance, retrieval-age, mandatory-quality, cloud-mask,
and snow bands. The date and QA contracts are frozen in
[`configs/psf_disaggregation.yaml`](../configs/psf_disaggregation.yaml).

NASA's current Earthdata guidance says NASA-led mission data are CC0 unless a
specific restriction is shown, asks users to acknowledge NASA, and prohibits an
implication of endorsement. The VNP46A2 catalog additionally requests dataset
citation for publications and derived work.

Use these citations:

- VNP46A2.002 dataset DOI: <https://doi.org/10.5067/VIIRS/VNP46A2.002>
- Román, M. O., et al. (2018), *NASA's Black Marble nighttime lights product
  suite*, *Remote Sensing of Environment*, 210, 113–143.
  <https://doi.org/10.1016/j.rse.2018.03.017>
- Official terms: [NASA Earthdata Data Use and Citation
  Guidance](https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance)
  and the [VNP46A2 Earth Engine catalog
  entry](https://developers.google.com/earth-engine/datasets/catalog/NASA_VIIRS_002_VNP46A2).

Suggested credit: `Contains modified NASA VIIRS VNP46A2 Collection 2 data
(2024), accessed through Google Earth Engine.`

### Sentinel-2 and Cloud Score+

The reflectance collection is `COPERNICUS/S2_SR_HARMONIZED`. The project applies
quality masking, same-datatake mosaicking, temporal compositing, reprojection,
indices, and proxy formulas, so every exported raster and figure is modified
Sentinel data rather than an unaltered scene.

The [Copernicus Sentinel Data Legal
Notice](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice)
permits lawful reproduction, distribution, communication, adaptation, and
combination. It requires this source notice for modified data:

`Contains modified Copernicus Sentinel data 2024`

Cloud screening also uses `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED`. The
[Earth Engine catalog entry](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_CLOUD_SCORE_PLUS_V1_S2_HARMONIZED)
licenses Cloud Score+ under CC BY 4.0 and gives the preferred paper citation:
Pasquarella, V. J., Brown, C. F., Czerwinski, W., and Rucklidge, W. J. (2023),
<https://doi.org/10.1109/CVPRW59228.2023.00206>.

Suggested combined credit: `Contains modified Copernicus Sentinel data 2024.
Cloud-quality data: Google Earth Engine Cloud Score+, CC BY 4.0.`

### OpenStreetMap

OpenStreetMap data are licensed under the ODbL 1.0. Copying and adapting the
database is permitted with attribution; a publicly used Derivative Database is
subject to ODbL share-alike. A rendered figure is normally a Produced Work and
does not itself have to use ODbL, but it still needs visible attribution. See the
[OSM copyright page](https://www.openstreetmap.org/copyright) and the
[OSMF attribution guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines).

The historical comparison code queried OSM attic data through
`https://overpass.kumi.systems/api/interpreter`, using adaptive bounding-box
tiles and the timestamp `2024-03-01T00:00:00Z`. This is a community-operated
Overpass instance, not a guaranteed archival distribution channel. Its capacity
and current operating policy apply at retrieval time. The extraction was
intentionally deferred after the New York checkpoints; no consolidated OSM
snapshot or historical-proxy result is distributed in this repository.

If that work is resumed, run:

```bash
python -m nocturne.disaggregate.historical_osm \
  configs/psf_disaggregation.yaml
```

Retain the generated snapshot manifest, source endpoint, timestamp, bounds, and
hashes. If a consolidated or derived database is published, distribute it under
ODbL-compatible terms and include the ODbL text or a direct link in its metadata.

Required credit: `© OpenStreetMap contributors` with a link to
<https://www.openstreetmap.org/copyright>.

### Overture Maps

The structural input uses the Buildings `building` type and Transportation
`segment` type from release `2026-07-22.0`. The independent mapped-water
reference uses the Base `water` type from release `2026-06-17.0`. Overture's
[attribution register](https://docs.overturemaps.org/attribution/) lists all
three themes as ODbL and identifies their contributing sources. Buildings may
also include Esri Community Maps, Microsoft Global ML Building Footprints,
Google Open Buildings, and other sources; transportation includes OSM and
TomTom; base includes OSM and other listed sources. The release-specific
attribution register is authoritative.

The project retrieves city-bounded GeoParquet extracts with the Overture Python
CLI. The reproducible wrapper is:

```bash
python -m nocturne.disaggregate.overture \
  configs/psf_disaggregation.yaml
```

It records the release, exact source bounding box, CLI command, backend, and
output path in sidecar state files. The water reference was read from:

```text
s3://overturemaps-us-west-2/release/2026-06-17.0/theme=base/type=water/
```

Overture publishes GeoParquet on public Amazon S3 and Microsoft Azure paths;
its [catalog access guide](https://docs.overturemaps.org/getting-data/cloud-sources/)
describes CLI, DuckDB, and bulk retrieval. Its
[release policy](https://docs.overturemaps.org/release-calendar/) keeps raw
release files publicly available for at most 60 days. Consequently, a pinned
release path is reproducible only while retained. Anyone archiving a release for
long-term reproduction must preserve its ODbL license and source notices rather
than treating the archive as BSD-licensed project data.

Required map/figure credit: `© OpenStreetMap contributors, Overture Maps
Foundation` with links to <https://www.openstreetmap.org/copyright> and the
[Overture attribution register](https://docs.overturemaps.org/attribution/).

For research references, Overture also recommends: `Overture Maps Foundation,
overturemaps.org`, with the access date.

### JRC Global Surface Water

The internal water prior uses the `occurrence` band from
`JRC/GSW1_4/GlobalSurfaceWater` and the `valid_obs` support band from
`JRC/GSW1_4/Metadata`. It is transformed and resampled, and it is not active in
the selected reporting primary. The independent Gate 2 water reference is
Overture, not JRC.

The [JRC catalog terms](https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater)
require acknowledgement, the source article, and `Source: EC JRC/Google` on a
published map. Cite Pekel, J.-F., Cottam, A., Gorelick, N., and Belward, A. S.
(2016), <https://doi.org/10.1038/nature20584>.

## Retrieval platform terms

Google Earth Engine is the access and processing platform for VIIRS,
Sentinel-2, Cloud Score+, and JRC data; it is not a replacement license for
those datasets. Reproduction requires an Earth Engine-enabled Google Cloud
project and compliance with the current [Earth Engine terms](https://earthengine.google.com/terms/)
and [per-project and per-user quotas](https://developers.google.com/earth-engine/guides/usage).
The Google Cloud project and Google Drive export folder are private runtime
settings supplied through `NTL_PSF_EE_PROJECT` and
`NTL_PSF_EE_DRIVE_FOLDER`. Their values are not committed. No credentials,
tokens, or private Earth Engine assets are redistributed here.

The collection IDs, date filters, bands, quality rules, and export grid are in
[`configs/psf_disaggregation.yaml`](../configs/psf_disaggregation.yaml).
Exported-product metadata are preserved in
[`artifacts/outputs/psf_disaggregation/manifests/day2_earth_engine_exports.json`](../artifacts/outputs/psf_disaggregation/manifests/day2_earth_engine_exports.json).
Account-specific task IDs and the Drive folder are redacted from that public
manifest. Do not repeat the exports merely to inspect the closed v2 record.

The public configuration is byte-different from the private-runtime file used to
create the closed outputs. Frozen artifact manifests retain the original
configuration hash. This is an explicit privacy redaction of runtime identity,
not a claim that the redacted file has the same checksum.

## What this repository redistributes

| Material | Location | Classification and terms |
|---|---|---|
| Project code and documentation | `src/`, `tests/`, `docs/`, configuration and repository metadata | Project-authored material under BSD-3-Clause; quoted or linked upstream material remains under its source terms. |
| Two-city registry | `assets/sprint_cities.csv` | Project-authored factual registry. BSD applies to the project's selection and presentation; no third-party raster or map features are embedded. |
| Manifests and aggregate analytical tables | `artifacts/` | Project-authored provenance and summary outputs. They contain hashes, paths, experiment settings, and aggregate metrics, not a substitute copy of an upstream raster or map database. BSD applies to original project content; source citations still travel with reuse. |
| Diagnostic maps and figures | `docs/figures/`, `notebooks/figures/`, and PNGs below `artifacts/` | Produced works combining project analysis with VIIRS, Sentinel-2, Overture/OSM, and sometimes JRC. Figure design is project-authored, but upstream attribution remains mandatory. Reuse the credit block below. |
| Narrative notebook | `notebooks/psf_disaggregation_writeup.ipynb` | Project-authored narrative and code under BSD-3-Clause. Its displayed outputs are derived works and retain the source notices below. |

The repository does **not** redistribute raw VIIRS scenes, Sentinel-2 scenes,
Cloud Score+ rasters, JRC rasters, Overture or OSM feature extracts, complete
Earth Engine export bundles, full-city output COGs, daily VNP stacks, or
row-level held-out prediction tables. Manifests may name those omitted files and
record their hashes for provenance. Users retrieve or generate these large files
and store them in their local `outputs/` tree. The project does not publish them
to GitHub and does not promise a separate hosted raster archive.

The compact tables and images are analytical summaries, not source-data
archives. This classification does not waive ODbL: if a future sample exposes a
substantial extract or can be used to reconstruct a source database, treat it as
a database distribution, perform a new license review, and provide ODbL terms
and the source data or transformation offer where required.

## Copy-ready attribution

Use this block in the notebook, a paper's data statement, and the description of
any independently redistributed figure:

> Nighttime radiance contains modified NASA VIIRS VNP46A2 Collection 2 data
> (2024), DOI: 10.5067/VIIRS/VNP46A2.002, accessed through Google Earth Engine.
> Contains modified Copernicus Sentinel data 2024. Cloud-quality data: Google
> Earth Engine Cloud Score+, CC BY 4.0. Map and structural data: © OpenStreetMap
> contributors, Overture Maps Foundation; ODbL 1.0. Persistent-water data, where
> shown: Source: EC JRC/Google.

For a standalone static image, place the relevant shortened credit adjacent to
the image or in its caption; a link only in repository documentation may not be
sufficient. If an image does not use a listed source, omit that source rather
than claiming it contributed.

## Before adding or publishing more data

1. Record the exact product ID, release, retrieval date, spatial bounds, service,
   query, and checksum in a manifest.
2. Review the license for the exact product and release, including subordinate
   Overture source notices.
3. Determine whether the output is source data, a Derivative Database, a
   Produced Work, or a genuinely aggregate analytical result.
4. Put source attribution next to maps and figures and in the data directory for
   database-like distributions.
5. Never assume the repository's BSD license applies to third-party data.
6. Keep large source and product rasters local. If a downstream user independently
   publishes any of them, that user must confirm redistribution rights and retain
   every required notice.
