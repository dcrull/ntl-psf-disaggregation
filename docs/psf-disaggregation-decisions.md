# PSF disaggregation analysis decision register

This register provides a strict line of sight from analytical assumptions to
configuration, implementation, and regenerated artifacts. It is part of the
experiment contract in `docs/psf-disaggregation.md`.

## Active register

| ID | Decision | Status | Configuration / implementation | Dependent artifacts |
| --- | --- | --- | --- | --- |
| AOI-001 | Use an exact 50 km projected square per city, centered on the manifest point snapped to the 10 m grid | Fixed for sprint efficiency | `cities.analysis_geometry`; `CityGridSpec` | Every input query, raster, Gate 0 sample, allocation, and validation |
| VNP-QA-001 | Use MQF 0, clear/probably-clear, adequate cloud-mask quality, nighttime, shadow/cirrus-free, snow-free corrected radiance with at least 10 observations | Preserved for Gate 0, the daily-condition audit, and conservative spatial sensitivity; final spatial reporting and held-out radiance superseded by VNP-COVERAGE-002 and HELDOUT-BROAD-001 | `sources.vnp46a2.quality_contracts`; `build_vnp_daily_collection` | VNP median, daily stack, Gate 0, strict allocations, targeted New York QA check |
| VNP-COVERAGE-001 | Preserve strict corrected radiance as primary; expose native coverage, broad QA, and age-bounded gap-filled fields in the versioned source bundle | Historical v1 decision preserved; spatial reporting role superseded by VNP-COVERAGE-002 | `sources.vnp46a2.gap_filled_sensitivity`; `build_vnp_gap_filled_sensitivity`; `vnp_coverage.py`; `source_preview.py` | Day 2 source bundles, coverage audit, targeted empirical check, research note |
| VNP-COVERAGE-002 | Use the broad-QA median for the final spatial demonstration while retaining strict v1 as immutable conservative sensitivity and Gate 0/daily authority | Accepted 2026-08-03; coverage-driven, not performance-tuned | `broad_reporting.py`; v2 manifest and selection | Final QGIS rasters, baselines, results synthesis |
| VNP-DAILY-001 | Retain the strict-QA 100-day series on a compact aligned 500 m grid with date-matched condition stacks; stream daily reprojection instead of materializing a 10 m×100 stack | Complete and audited 2026-07-30 | `daily_vnp.py`; Gate 2 readiness and audit summary | Observation-condition propagation |
| OBS-COND-001 | Test daily condition propagation on common complete support with direct, uniform, and built-form/no-water coarse reference analogues; treat reductions from direct as smoothing | Complete; bounded non-amplification pass 2026-07-30 | `observation_conditions.py`; v1 manifest and review | Gate 2 claim and limitations |
| DAY3-CLASSIFICATION-001 | Classify the sprint as a bounded method result with useful negative findings; preserve built form/no-water/circular reference as reporting primary with direct and uniform baselines | Accepted 2026-07-30 | Day 3 closeout manifest; results synthesis | Research note, blog, figures, claim language |
| RESAMPLE-001 | Bilinear for continuous S2 bands; nearest for categorical masks, counts, and the 30 m JRC occurrence prior; declare every reprojection | Fixed; VNP radiance sensitivity retained | `grid`; S2/water builders; artifact metadata | S2 composites, indices, water prior, proxies, exports |
| S2-COMPOSITE-001 | Mosaic overlapping MGRS tiles from the same Sentinel-2 datatake on the locked grid, then compute indices from bandwise temporal medians with common multispectral support | Primary fixed after a live seam diagnostic; alternate composite retained as future sensitivity | `sources.sentinel2`; `build_s2_composite` | S2 layers and S2-only proxy |
| S2-SUPPORT-001 | Require at least 90% fine-pixel S2 support within a native VIIRS footprint before that cell enters S2-only Gate 0 metrics | Fixed after a post-v2 partial-support audit | `validation.gate0.minimum_s2_coarse_support_fraction`; Gate 0 sampler/metrics | S2-only Gate 0 samples, metrics, and figures |
| PROXY-FORMULA-001 | Use fully configured proxy breakpoints, floor, transforms, weights, and road-class weights; fail on unlisted road classes | Fixed for corrected Gate 0; heuristic | `allocation_proxies`; proxy builders | Gate 0 and every structural allocation |
| OVERTURE-001 | Treat pinned Overture 2026-07-22.0 as a contemporary structural proxy used to allocate 2024 radiance | Fixed for preliminary sprint; historical source/vintage sensitivity deferred | `allocation_proxies.built_form`; Overture state files | Built-form proxy and comparisons |
| OSM-HISTORY-001 | Use a 2024-03-01 OSM attic snapshot to test sensitivity to structural vintage while retaining the OSM-versus-Overture source-coverage confound | Deferred 2026-07-30; 547 New York checkpoints preserved, Delhi not started, no result selected | `historical_osm.py`; `historical_proxy.py`; snapshot manifests | Historical structural bundles, comparison table, difference maps |
| OVERTURE-RASTER-001 | Estimate 10 m building coverage from a binary-union 2 m subpixel grid; allocate weighted road-centerline length after segmentizing to at most 1 m, with no assumed road width | Fixed for full extents; 1 m building and 0.5 m road cutout checks required | `allocation_proxies.built_form.rasterization`; `overture_bundle.py` | Day 2 Overture structure bundles and built-form allocations |
| KERNEL-001 | Preserve the literal Fork-form 500 m-radius circle as reference and treat the actual native VNP cell polygon as a major sensitivity | Fixed | `kernels` | Day 2 allocations and kernel comparisons |
| KERNEL-HALO-001 | Retain the 1000 m source halo for the reference run; invalidate edge support that is incomplete for wider Gaussian sensitivities | Fixed for this sprint; larger-halo refresh is future work | `cities.analysis_geometry.source_halo_m`; kernel metadata; Gate 1 halo audit | Gaussian sensitivity valid masks, maps, and metrics |
| OPERATOR-NUMERICS-001 | Require full declared kernel support, constant-invalid edges, mean-one proxy normalization, relative denominator guards, and recorded negative-value clipping | Fixed before empirical Day 2 runs | `validation.gate1`; `operator.py` | Every allocation, diagnostic COG, Gate 1 result, and downstream validation |
| CONSERVATION-001 | Call the Fork-form output locally normalized unless measured operator-consistency error supports stronger language | Fixed before operator implementation | `validation.operator_interpretation`; operator diagnostics | Code, figures, research note, blog |
| GATE0-001 | Preserve exploratory v0, tile-seamed v1, and pre-coarse-support v2; write the current support-aware result as `v3_qa_grid_halo_datatake_support` | Fixed | `validation.gate0.artifact_version`; Gate 0 runner | Gate 0 samples, summaries, maps, proxy decision |
| GATE0-MONOTONICITY-001 | Distinguish a monotone proxy formula from an empirically monotone proxy–radiance relationship; add shape/tail diagnostics to future Gate 0 rules | Rule gap accepted 2026-07-30; no retrospective proxy retuning | Gate 0 diagnostics and future acceptance rules | Proxy screening, limitations, future reruns |
| HELDOUT-001 | Use a 2550 m PSF-support exclusion as the native-cell held-out primary, with 1500 m and 2000 m sensitivities; retain the 500 m result as preflight only | Native-cell run complete 2026-07-30; fine-grid remove-before-convolution extension optional | `heldout.py`; v2 manifest | Held-out predictions, gain/distance sensitivities, final validation figures |
| HELDOUT-BROAD-001 | Repeat HELDOUT-001 with broad-QA radiance on the identical frozen cell cohort and fold assignment | Complete 2026-08-03; overall built-form benefit and gain asymmetry preserved | `heldout.py`; broad v3 manifest; v2 closeout | Final broad-QA evidence classification and write-up |
| ARTIFACT-PROVENANCE-001 | Record and quarantine four Gate 0 PNGs filed under v3 whose displayed metrics came from v0; regenerate figures from saved version-matched artifacts | Defect recorded; numerical decisions unaffected | Gate 0 artifact directory; Day 3 figure regeneration | Figure provenance and write-up |
| WATER-001 | Treat water as a tested allocation prior; never invalidate VNP solely because its footprint intersects water | Preregistered combined-soft primary preserved; superseded for reporting after completed factorial | `validation.water_handling`; water/proxy builders | All proxy rasters, allocations, Gate 1 coastline results, Gate 2 shoreline results |
| WATER-002 | Use no-water-prior as the post–Gate 2 reporting primary; retain water weighting only as sensitivity analysis | Accepted 2026-07-30 | Machine-readable primary-selection record; frozen configuration deliberately unchanged | Headline tables, figures, research note, and blog |
| WATER-INLAND-001 | Compare no-water allocated/direct regional-sum ratios over mapped water and the existing radiance-blind inland low-proxy control | Complete 2026-08-02; supports a general low-proxy rather than water-specific interpretation | `day4_inland_ratio.py`; Day 4 manifest and tables | Water interpretation, results synthesis, future counterfactual design |
| FINE-GAIN-001 | Deliver the exact proxy-only fine-grid gain and validated warning stratum as a companion COG without rewriting frozen products | Complete 2026-08-02 | `fine_grid_gain.py`; `trust_indicators.tif`; gain manifest | QGIS review, product trust diagnostics, writing |
| WINDOW-001 | Use the fixed 100-day interval from 2024-01-11 through 2024-04-20 exclusive | Fixed | `date_window` | All S2 and VNP composites, daily stacks, allocations, validation |
| CLOUD-001 | Use Cloud Score+ `cs_cdf >= 0.60` plus declared SCL exclusions | Fixed for sprint; report coverage | `sources.sentinel2.cloud_score`; `sources.sentinel2.scl_excluded_classes` | S2 composite, indices, S2-only proxy, coverage diagnostics |
| PROXY-001 | Re-freeze the declared built-form primary and S2-only ablation after support-aware Gate 0 v3; retain all water and scale sensitivities without target-driven retuning | Fixed for Day 2 | `allocation_proxies`; proxy builders; v3 Gate 0 summaries | All structural allocations and proxy comparisons |
| NORMALIZATION-001 | Normalize each proxy to mean one over its finite analysis support; do not define support as land-only | Fixed before full allocation | `allocation_proxies.common_normalization`; proxy builders | Proxy rasters, denominator diagnostics, allocations |
| GRID-001 | Use explicit, aligned 10 m per-city UTM grids | Fixed | `grid`; city-grid manifest | Every raster and spatial validation |
| GRID-EXPORT-001 | Inset the Earth Engine selection region by 0.01 m while retaining the exact transform and dimensions, preventing numerical edge slivers from adding a row or column | Fixed for versioned v2 exports | `earth_engine.export.region_edge_inset_m`; `ee_export.py` | Day 2 Earth Engine source bundles and input audit |

## AOI-001 — fixed 50 km projected square

For this preliminary sprint, an exact 50 km square is more efficient and more
reproducible than sourcing, versioning, and harmonizing jurisdictional or
morphological urban boundaries. For each city, transform the manifest center to
the local UTM CRS, snap it to the nearest 10 m grid point, and use a
5000-by-5000-cell analysis grid. Source queries include a 1000 m halo; final
statistics crop to the square. The square is a fixed comparison support, not a
claim that it matches the functional urban area. Urban-boundary-plus-buffer
support remains future work.

## VNP-QA-001 — corrected-radiance quality contract

The primary VNP field retains only:

- `Mandatory_Quality_Flag == 0`;
- nighttime observations;
- confident-clear or probably-clear cloud detection;
- cloud-mask quality of medium or high;
- no shadow or cirrus flag;
- no snow in either VNP snow indicator; and
- pixels with at least ten retained observations in the 100-day interval.

The broader sensitivity admits MQF 1, lowers cloud-mask quality to low, and
requires at least five observations. This sensitivity is explicit because the
Earth Engine catalog and the October 2024 NASA Collection 2 guide disagree
about MQF 1 and omit/differ on later values. Preserve raw source counts,
quality-retained counts, rejected counts, and retained fractions. Quality flags
are always nearest-neighbor categorical data.

The v2 core-square audit found 99.883% strict coverage and 100% broad coverage
in New York, a broad-only gain of 0.117 percentage points or 2.93 km². On
common support, strict and broad radiance have Pearson correlation 0.9975,
means of 44.70 and 43.58, and mean absolute difference 1.47. Delhi has 100%
coverage under both contracts. Because the broad field is nearly redundant
citywide and a full radiance-variant factorial would materially expand the
operator workload, it remains in the immutable source bundle but is excluded
from the full factorial. Run it only once for New York using the built-form
primary, circular reference kernel, and combined-soft water configuration to
quantify the effect of the strict-support gap. Do not run a downstream broad-QA
allocation for Delhi.

## VNP-COVERAGE-001 — native retrieval gaps and gap-filled sensitivities

Visual inspection of the v1 New York source bundle found depressed corrected
radiance observation counts over central and lower Manhattan. This cannot be a
Nocturne water-convolution artifact: the count is produced before the operator,
and JRC water occurrence is zero with allocation weight one at the named land
sites.

The exact-grid audit records:

| Site | Native corrected count | Strict retained count | Broad retained count | Gap-filled day count | Median/P90 retrieval age | Native VNP background |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Lower Manhattan | 10 | 8 | 9 | 99 | 8/20 days | sea water |
| Midtown | 23 | 21 | 22 | 99 | 2/9 days | sea water |
| Central Park | 48 | 41 | 45 | 99 | 1/3 days | coastal |
| Queens | 57 | 38 | 44 | 99 | 0/3 days | land, no desert |

These background labels are decoded from the native VNP
`QF_Cloud_Mask`; they are not derived from the Nocturne JRC layer. Their
association with retrieval availability is an upstream product limitation, but
the available flags do not establish the complete causal branch.

Under the historical v1 contract, the strict MQF-0 corrected-radiance median
with at least ten observations remained primary. The v2 source bundle additionally
contains:

- corrected source count, strict retained/rejected counts, and retained
  fraction;
- the declared broad corrected-radiance median and retained count;
- gap-filled medians and represented-day counts with maximum retrieval ages of
  7, 30, and 90 days;
- count of days reporting a fresh high-quality retrieval; and
- median and 90th-percentile latest-high-quality-retrieval age.

The 30-day threshold is the named recent sensitivity and requires at least ten
represented days. Seven and ninety days bracket it. Carried-forward daily
values are not independent radiance retrievals, so their day count must never
be interpreted as effective sample size. No gap-filled variant can replace a
corrected-radiance field automatically. `VNP-COVERAGE-002` later superseded only
the final spatial-reporting role with the broad corrected median; strict QA remains
the Gate 0/daily authority and conservative spatial sensitivity.

The named-site audit also shows that gap filling materially changes radiance:
Lower Manhattan is approximately 137 under broad corrected radiance versus 529
under the 30-day gap-filled sensitivity; Midtown is approximately 619 versus
865. These are reasons to compare and label the fields, not reasons to select
the visually brighter one.

## VNP-COVERAGE-002 — coverage-complete demonstration reporting

Accepted on 2026-08-03 after direct inspection confirmed that all nine New
York strict-input gaps contain 5–9 retained observations and are masked only
by the ten-observation threshold. The original 29,269 missing 10 m pixels
dilate to 177,594 missing pixels under complete circular-kernel support.

Use the broad corrected median, which admits MQF 0/1 and requires five retained
observations, for the final demonstration rasters. It supplies complete support
for direct, uniform, and built-form/no-water outputs in both cities. On common
support, broad and strict direct radiance correlate at 0.99746 in New York and
0.99928 in Delhi. Preserve strict v1 as the immutable conservative-quality
spatial sensitivity and as authority for the frozen Gate 0 cohort and the
daily-condition audit. The final held-out result is the later broad-QA v3 rerun
on that identical cohort. Do not describe MQF 1 as equivalent in quality to
MQF 0, and do not promote age-based gap filling.

The reporting change is motivated solely by spatial completeness and mask
dilation. It does not select a proxy, kernel, or water treatment from improved
performance and therefore does not reopen those frozen choices.

## VNP-DAILY-001 — compact audited daily stack

The live Earth Engine catalog contains exactly 100 unique daily VNP46A2 images
from 2024-01-11 through 2024-04-19. Preserve strict-QA corrected radiance and
date-matched lunar irradiance, latest-retrieval age, decoded cloud detection,
decoded cloud-mask quality, mandatory-quality flag, and snow flag.

Store each variable as a 100-band COG on a 100-by-100, 500 m projected grid
aligned to the 10 m analysis origin and 50 km extent. This retains the
native-scale information needed for daily propagation while avoiding roughly
10 GB per city of repeated 10 m values. Reproject one day at a time during the
operator audit. Every file records date-qualified band descriptions and a
checksum.

Both cities pass the Gate 2 date, band, grid, metadata, and COG audit. Daily
valid fractions are 0.335367 in New York and 0.588984 in Delhi; median valid
counts are 35 and 59. Daily-stack medians agree with the frozen Day 2 median
after nearest alignment to MAE 0.207 in New York and 0.145 in Delhi. Rare
boundary maxima reflect the different order of median formation and projected
nearest sampling, not a date or QA-contract mismatch.

Within strict-QA retained pixels, MQF is zero, snow is absent, and latest
high-quality retrieval age is zero by construction. Retain those layers as
contract evidence, but do not claim within-sample observation-condition
effects for invariant fields. Lunar irradiance, cloud detection, and
cloud-mask quality remain available for propagation analysis.

## OBS-COND-001 — daily observation-condition propagation

Apply direct, uniform circular convolution, and built-form/no-water structural
allocation to each strict-QA day on the compact 500 m grid. Require complete
center-plus-four-cardinal-cell daily support and compare all methods on the
same observations. Estimate descriptive lunar, cloud-detection, and
cloud-mask-quality associations after within-cell centering of log1p output and
condition. Treat MQF, snow, and retrieval age as invariant contract checks.

The audit passes its bounded non-amplification rule. Built-form condition R²
differs from uniform by less than 0.00004 in both cities, and built-form mean
absolute within-cell log variability is slightly lower than uniform
(0.17548 versus 0.17602 in New York; 0.16023 versus 0.16119 in Delhi).
Reductions relative to direct are smoothing and must not be described as
observation-condition correction.

Mean complete daily kernel support is 0.263 in New York and 0.529 in Delhi;
medians are 0.087 and 0.710. Strict daily support, particularly in New York,
is a larger limitation than incremental structural amplification. Preserve
zero-support days and incomplete neighborhoods as invalid rather than filling
or locally renormalizing them.

This is a 500 m daily coarse analogue. It does not regenerate or validate 100
full-resolution 10 m allocation fields and does not establish causal condition
effects.

## GRID-EXPORT-001 — deterministic Earth Engine selection edges

The v1 New York export reopened at the expected 5200-by-5200 source-halo shape.
Delhi reopened at 5201-by-5201 despite the correct 10 m affine origin because a
numerical region-edge sliver selected one extra eastern column and southern
row. Delhi v1 is quarantined from the operator.

Versioned v2 exports inset only the Earth Engine selection geometry by 0.01 m
on each side while retaining the exact projected transform and expected
5200-by-5200 dimensions. This is an export-selection guard, not resampling,
cropping of the 50 km analysis square, or a change to its coordinates. The
local input audit still rejects any shape, transform, CRS, or band-order
mismatch.

## OVERTURE-RASTER-001 — fine-grid structural rasterization

The 10 m building layer is an estimated footprint-coverage fraction, not a
binary building-presence mask. Reproject Overture polygons to the city UTM
grid, repair invalid geometry, retain polygon parts, rasterize their binary
union by 2 m cell-center sampling, then average each 5-by-5 subpixel block.
Overlapping polygons cannot double-count coverage. The resulting fraction has
increments of 0.04. This is a controlled approximation rather than an exact
polygon/pixel intersection; compare it with 1 m sampling on representative
dense, sparse, and waterfront cutouts before the empirical operator run.

The road layer represents configured class-weighted centerline length, not road
area. Reproject and clip road lines to the source grid, segmentize them to at
most 1 m, and allocate each short segment's exact length to the 10 m pixel
containing its midpoint. Add overlapping centerline lengths and assume no road
width. Require citywide weighted-length conservation within `0.0001` relative
error before float32 accumulation, and compare the result with 0.5 m
segmentization on representative cutouts.

Keep `building_fraction` and `weighted_road_density_normalized` as separate
bands. Combine them into the unwatered, unfloored structural base using the
frozen 70/30 and square-root formula. Export a separate mapped-infrastructure
mask for the water-override sensitivity. COG overviews use nearest-neighbor
resampling because one band is categorical; overviews are display aids and do
not alter base-resolution values.

The preregistered finer-rasterization check passed on 2026-07-29. For each
city, 1 km dense-building, sparse-built, and water-adjacent-infrastructure
cutouts were selected from building fraction, mapped infrastructure, and JRC
water only; VNP radiance was not used for selection. Comparing 2 m with 1 m
building sampling changed total sampled building area by no more than 0.67%
across the six cutouts. Comparing at-most-1 m with at-most-0.5 m road
segmentization produced correlations of 0.9979 or greater. Visual inspection
found differences localized to polygon and line edges, without a coherent
spatial artifact. Retain the 2 m building and 1 m road primary for this sprint;
the finer versions remain a documented sensitivity rather than silently
replacing the analysis inputs.

## RESAMPLE-001 and S2-COMPOSITE-001

Every resampling operation must appear in configuration, artifact metadata, and
the methods write-up. Current primary operations are:

| Source/layer | From | To | Method | Consequence |
| --- | --- | --- | --- | --- |
| S2 reflectance and Cloud Score+ | Native band/MGRS grids | Locked 10 m UTM grid | Bilinear, followed by a same-datatake tile mosaic | B11/B12-derived products retain an effective resolution of 20 m; overlapping tiles count once per acquisition |
| S2 SCL, common-valid mask, and observation counts | Native categorical grids | Locked 10 m UTM grid | Nearest | No fractional class invention |
| JRC occurrence and valid-observation support | 30 m Landsat-derived grid | Locked 10 m UTM grid | Nearest | The result remains a 30 m temporal prior, not 10 m fractional water |
| S2 proxy for Gate 0 | Locked 10 m UTM grid | Native VNP grid | Area-weighted mean via `reduceResolution` | Full native footprint support requires the query halo |
| S2 sufficient-support mask for Gate 0 | Locked 10 m binary support | Native VNP grid | Area-weighted mean via `reduceResolution` | Produces an explicit supported-area fraction; S2 metrics require at least 0.90 |
| VNP radiance for Day 2 | Native 15-arcsecond grid | Locked 10 m UTM grid | Nearest primary; bilinear sensitivity | Neither method creates independent 10 m radiometry |

The primary S2 composite first reprojects every tile to the locked grid and
mosaics all tiles with the same `DATATAKE_IDENTIFIER`. It then computes the
index of bandwise temporal medians, requires common support across
B2/B3/B4/B8/B11/B12, and masks the continuous composite where fewer than five
datatakes have common observations. The first input tile never defines the
working projection, and overlapping MGRS tiles do not count as separate
observations.

## PROXY-FORMULA-001 and OVERTURE-001

The preliminary proxy remains heuristic but must behave identically across
cities:

- intersect Overture geometry with actual native VNP cell polygons for Gate 0;
- divide building area by each cell's actual projected area;
- express weighted road length in metres per square kilometre and normalize it
  against one fixed 20,000 m/km² saturation in both cities;
- use the configured 70/30 building-road mixture and square-root building
  transform;
- explicitly list every observed road class and fail on a new class; and
- consume the configured `0.05` proxy floor rather than duplicating it in code.

The pinned Overture release is a **contemporary structural proxy used to
allocate 2024 radiance**. It is not a reconstruction of built form as of the
VNP window. A 2024 OSM snapshot sensitivity was initiated under
`OSM-HISTORY-001` and then deferred with checkpoints preserved. If completed,
it could help bound the temporal-mismatch concern, but it could not isolate
temporal change from differences between OSM-only and Overture-conflated
coverage.

## OSM-HISTORY-001 — historical structural sensitivity

Use OpenStreetMap attic state at `2024-03-01T00:00:00Z`, within the locked
analysis window, to retrieve building-tagged ways and relations and
highway-tagged ways over the same source extent. The extractor uses adaptive,
nonoverlapping bounding-box tiles and preserves every successful raw response
as a checkpoint. Consolidated features are deduplicated by OSM element type
and ID.

Rasterize historical features on the same grid and with the same building
sampling, eligible road classes and weights, road-density saturation, 70/30
mixture, and square-root building transform used for the contemporary primary.
Compare component layers and the combined unwatered/unfloored proxy before any
downstream allocation comparison. Record totals, nonzero coverage, mean
absolute and root-mean-square differences, correlation, and mapped
differences.

This is not a clean temporal experiment. Contemporary Overture building
coverage is conflated from multiple providers, whereas the historical layer is
OSM-only; OSM database state is also not independently verified construction
date. Interpret differences as a **combined source-coverage and vintage
sensitivity**. Do not tune the historical proxy against VNP radiance or
automatically replace the reporting primary from this comparison.

The extraction was deferred on 2026-07-30 after 547 New York tile checkpoints;
Delhi was not started and no comparison result was produced. The partial
artifacts are retained solely as resumable inputs for optional future work.

## KERNEL-001 and CONSERVATION-001

The literal Fork-form circular mean with 500 m radius remains the reference
operator for provenance. The actual native 15-arcsecond VNP cell polygon is a
major sensitivity because “500 m” is a nominal product label, not a fixed
500-by-500-m footprint.

The Fork-form equation is locally normalized but does not algebraically ensure
that applying the aggregation operator again exactly reproduces the source
radiance everywhere. Report **operator-consistency error** and
**radiance-authority share with insufficient proxy support**. Do not use
“conserved,” “physical flux,” or “emission” for the sprint output unless a
separate definition and measured evidence justify it.

## KERNEL-HALO-001 — sensitivity support at analysis edges

The 1000 m source halo fully supports the 500 m-radius circular reference and
the representative New York and Delhi native-footprint kernels inspected at
Gate 1. It does not fully support the declared four-sigma Gaussian truncations:

| Gaussian FWHM | Declared support radius | Additional invalid edge width inside the 50 km square |
| ---: | ---: | ---: |
| 750 m | 1280 m | 280 m |
| 1000 m | 1700 m | 700 m |
| 1500 m | 2550 m | 1550 m |

For this sprint, keep the efficient 1000 m source halo and mark the affected
edge strips invalid for each sensitivity. Do not pad, reflect, wrap, or silently
renormalize incomplete neighborhoods into valid support. The reference result
therefore retains the full analysis square, while Gaussian summary metrics use
their smaller, explicitly valid interiors. A future refresh with at least a
2550 m halo is required if all Gaussian sensitivities must cover the complete
50 km square.

The empirical cutout preflight separates geometric support from data support.
Its six reporting cores were selected without VNP radiance and placed far
enough inside the available source rasters for complete 2550 m geometric
support. Nevertheless, strict-QA radiance gaps inside the kernel neighborhood
invalidated the 1000 m and 1500 m Gaussian outputs for the New York dense core
and the 1500 m output for the New York water-adjacent core. Retain those
all-nodata results as support diagnostics. Do not fill, locally renormalize, or
promote broad QA to make the sensitivity visually complete.

## HELDOUT-001 — PSF-derived held-out exclusion

Removing a target VNP record is necessary but insufficient for physical
leakage control. A nearby VNP observation can include radiance originating
within the held-out support because the effective spatial response extends
beyond nominal native-cell boundaries. The completed 500 m-buffer run is
therefore a coarse screening preflight, not a physically leakage-safe result.

For the final five-fold evaluation, remove held-out VNP values before
reprojection or convolution and exclude training-cell centers within **2550
m** of each target. This primary distance is the registered four-sigma
truncation radius of the widest declared 1500 m-FWHM Gaussian. It ties the
exclusion to the experiment's PSF family rather than to a convenient round
number. Run 1500 m and 2000 m sensitivities as practical brackets. For a 1500
m-FWHM Gaussian, 2000 m is approximately 3.14 sigma and the radial response is
below 1% of peak; it is not a strict zero-contribution boundary.

Use exactly the same eligible training cells for neighbors-only and structural
predictions. For every buffer, record retained targets, retained neighbors,
nearest retained-neighbor distance, spatial/block position, and error metrics.
Also stratify error change by the radiance-blind allocation gain
`target_proxy / weighted_training_neighbor_proxy`, with preregistered bins
below `0.8`, `0.8–1.25`, and at least `1.25`, alongside radiance decile. Report
both method errors and `absolute_error_structural - absolute_error_neighbors`
within each gain stratum.
Larger-buffer targets disproportionately represent block interiors, so
buffer-specific rows diagnose distance dependence and sample attrition rather
than providing directly exchangeable estimates. Do not headline a
greater-than-1500 m subset as though it were a random subsample.

The 500 m preflight motivated this diagnostic but cannot validate it. Across
all four city×proxy combinations, mean absolute-error change was negative
below gain 0.8 and positive at gain 1.25 or above:

| City | Proxy | Gain <0.8 | Gain 0.8–1.25 | Gain ≥1.25 |
| --- | --- | ---: | ---: | ---: |
| New York | Built form | -6.302 | -0.163 | +3.620 |
| New York | S2 only | -7.513 | -0.117 | +0.178 |
| Delhi | Built form | -3.742 | +0.506 | +3.800 |
| Delhi | S2 only | -2.301 | +0.722 | +4.342 |

Because gain is calculated from proxy values and training-neighbor geometry
without target radiance, it is legitimate to preregister this stratification
before the final fold run. The observed asymmetry supports a measured
limitation: structural downweighting tends to help, while strong upweighting
tends to hurt. It does not establish the same result under the final,
PSF-buffered sample.

The completed strict v2 run retained all targets and twelve neighbors at every
buffer. At the 2550 m primary, built form improved MAE/RMSE from
19.701/31.920 to 16.995/29.823 in New York and from 13.728/19.960 to
12.270/18.925 in Delhi, with MAE improvement in 5/5 folds in each city.
S2-only improved New York to 16.643/28.963 but worsened Delhi to
13.840/20.532 and improved only 2/5 Delhi folds. Gain asymmetry persisted in
all four comparisons. This completes the native-cell physics-buffered
diagnostic; a remove-before-fine-grid-convolution evaluation remains a
stronger optional extension and must not be implied by these results.

The broad-QA v3 rerun holds the strict Gate 0 cohort and every fold/neighborhood
choice fixed, changing only sampled radiance. Built form improves overall
MAE/RMSE from 18.717/30.433 to 16.100/28.199 in New York and from
13.493/19.615 to 12.147/18.660 in Delhi. It improves 5/5 New York and 4/5 Delhi
folds; the single adverse Delhi fold is +0.044 MAE. Gain below 0.8 remains
favorable and gain at or above 1.25 adverse in all four city-by-proxy results.

## OPERATOR-NUMERICS-001 — numerical and mask contract

The pure-array operator:

- normalizes each nonnegative proxy to mean one over finite declared analysis
  support, including water;
- uses a unit-mass allocation kernel and constant-invalid exterior padding;
- requires 100% radiance, proxy, and geometric kernel support within a
  tolerance of `1e-6`;
- defines epsilon as `1e-6` times the normalized proxy mean and records a
  separate denominator-instability mask at the Gate 0 insufficient-proxy
  threshold;
- retains finite negative VNP radiance in the numerator, records negative
  source and pre-clip output masks, then clips the reported allocation to zero;
- represents invalid in-memory outputs with `NaN`; and
- computes operator-consistency error only where the second aggregation also
  has complete valid support.

Water variants can modify only the proxy. The water module accepts no radiance
argument, preventing a proxy sensitivity from silently masking the VIIRS
radiometric authority. Direct upsample and uniform normalized convolution are
separate baselines and remain distinct in tests and figures.

## GATE0-001 — result versioning

The original Gate 0 remains under the unversioned `gate0/` path as exploratory
v0. It used unfiltered VNP values, partial internal chunk footprints, approximate
500 m cell areas, and centroid-allocated Overture geometry. It must not support
the final proxy freeze.

The first QA/grid/halo-corrected attempt remains beneath
`gate0/v1_qa_grid_halo/` but is **superseded**. Its New York result was
plausible, while its Delhi proxy map exposed a large MGRS-tile discontinuity.
The source collection represented overlapping tiles from one Sentinel-2
datatake as separate observations and reduced them before imposing a stable
mosaic. Those results must not support the proxy freeze.

The datatake-mosaicked v2 result remains beneath
`gate0/v2_qa_grid_halo_datatake/`. A post-result audit found that area-weighted
means can otherwise use a partially supported S2 footprint because masked fine
pixels do not enter the reducer denominator. V2 is therefore preserved as
superseded rather than silently overwritten.

Current corrected artifacts are written beneath
`gate0/v3_qa_grid_halo_datatake_support/`. They require at least 90% supported
fine-pixel area before a native cell enters S2-only metrics and include config
hashes, QA counts, actual native cell polygons/areas, datatake counts, the
supported-area fraction, and declared resampling metadata. The built-form
metric does not use S2 coverage.

V3 excludes 372 of 15,335 New York native cells (2.43%) from S2-only metrics
and excludes none of 13,280 Delhi cells. Both proxies pass in both cities. The
built-form citywide/block/detrended Spearman correlations are
0.812/0.826/0.744 in New York and 0.761/0.901/0.733 in Delhi. The S2-only
correlations are 0.783/0.811/0.730 in New York and 0.438/0.576/0.499 in Delhi.
Compared with v2, the support-aware New York S2 result changes only modestly;
Delhi is unchanged. These are coarse association and alignment diagnostics,
not within-cell validation. The declared formulas are frozen for Day 2 without
tuning them to these values.

`GATE0-MONOTONICITY-001` records a gap in that acceptance rule. “Monotone” in
the S2 proxy description means its formula combines inputs monotonically; it
does not mean observed coarse radiance increases monotonically with proxy
value. Gate 0 required positive citywide, block, and detrended association, so
a mound-shaped relationship or bright-tail reversal could pass. Delhi S2-only
exposes why this matters. Future Gate 0 runs must add radiance-blind proxy-bin
shape and upper-tail diagnostics, with the rule fixed before examining target
outcomes. This gap is documented without retrospectively rejecting or
retuning the frozen proxy.

`ARTIFACT-PROVENANCE-001` records a closed figure defect. Four PNGs originally
filed under `gate0/v3_qa_grid_halo_datatake_support/` displayed v0 metric
annotations even though the directory and adjacent tables identify v3.
Differences were approximately 0.006 and did not change any proxy decision. All
four figures were regenerated from saved v3 artifacts; source and output hashes
are recorded in `gate0_figure_regeneration.json`. The v3 CSV/JSON summaries remain
the numerical authority.

Interactive chunks are checkpointed with the full configuration hash and
accepted only when city, chunk bounds, chunk number, hash, and recorded row
count all match. Checkpointing and the bounded request deadline affect
execution reliability only; they do not alter the analytical graph.

## WATER-001 — water handling

### Status

Combined-soft was the preregistered S2-only primary used to construct the
complete factorial. After the complete Gate 2 review it is superseded for
reporting by WATER-002, while the frozen configuration and completed artifacts
retain the original label and hash.

### Assumption

Persistent water is generally less plausible structural support for fixed urban
lighting than built land, but observed VIIRS radiance over or near water may
represent waterfront structures, bridges, ports, vessels, atmospheric spread,
geolocation uncertainty, or the sensor footprint. Water therefore cannot be
treated as intrinsically invalid VNP data.

### Exact current implementation

- VNP radiance is retained over water and remains in the allocation numerator.
- JRC occurrence is a 30 m temporal frequency derived from 1984–2021, not a
  10 m spatial water fraction or a 2024 observation.
- JRC occurrence is unmasked to zero only where JRC valid-observation support
  exists; where support is absent the allocation weight is neutral and the
  support gap is retained as a diagnostic.
- The proxy water weight is
  `1 - clip(occurrence / 90, 0, 1)`.
- The raw structural proxy is multiplied by that weight.
- The final proxy retains a `0.05` floor, so persistent water is weakly
  supported rather than assigned output nodata.
- The S2-only proxy also applies a separate MNDWI-derived spectral-water
  weight.

### Preregistered alternatives

1. No persistent or spectral water prior.
2. Persistent-occurrence soft weight only.
3. MNDWI spectral weight only.
4. Combined soft occurrence and spectral weights.
5. Combined spectral weight plus a hard persistent-water mask,
   sensitivity-only.
6. Soft occurrence weight with mapped building and road/bridge support restored
   over water.

All variants keep the same VNP input, grid, structural proxy components,
kernel, and numerical guards.

### Required evidence

Compare water allocation, operator-consistency error, insufficient-support
radiance-authority share, and
adjacent-land transfer in 0–100 m, 100–500 m, 500–1500 m, and greater-than-1500
m shoreline bands. Include mapped ports, waterfront buildings, bridges/roads,
ordinary shoreline, New York harbor/Hudson examples, and a Delhi river example.
Publish difference maps relative to no suppression.

### Decision rule

No automatic winner is selected. In particular, lower water allocation alone
cannot justify a change. Review the primary if it causes material shoreline
inflation, suppresses mapped waterfront infrastructure, increases
insufficient-support radiance authority, or worsens operator consistency.
Replacing the primary requires a
new ledger entry stating the evidence and regenerating every dependent
artifact.

### Change history

| Date | Change | Author |
| --- | --- | --- |
| 2026-07-27 | Recorded the existing soft-weight behavior and preregistered the shoreline sensitivity suite before the full allocation run | Codex, at user direction |

## WATER-002 — post-Gate 2 reporting primary

### Status

Accepted on 2026-07-30. `no_water_prior` became the reporting water choice for
both structural proxies under the strict radiance contract and circular-
reference kernel. `VNP-COVERAGE-002` subsequently carries that unchanged water
choice into the final broad-QA built-form product. Combined-soft and all other
water variants remain sensitivity analyses.

### Evidence and rationale

Gate 2 found material, proxy-dependent redistribution at mapped water,
shorelines, and waterfront infrastructure. It did not provide independent
fine-scale nighttime truth showing that this redistribution is more accurate.
Water weighting therefore adds an origin assumption—light observed near water
should preferentially be placed on land—that the VNP observation does not
establish and that is not applied consistently to other low-proxy boundaries.

The simpler no-water allocation preserves the corrected VNP observation as
radiometric authority while allowing the structural proxy to allocate within
the declared kernel. This is a bounded methodological choice, not evidence
that water-weighted allocation is false in every location.

### Provenance policy

Do not edit the frozen `primary_variant: combined_soft` configuration or
completed manifests. They record the preregistration under configuration hash
`9a033823...718a`. Select the already-completed no-water COGs in future
headline tables and figures, label the change as post–Gate 2, and retain direct
and uniform baselines. The historical strict-v1 selection record is
`outputs/psf_disaggregation/validation/gate2/primary_selection/v1_post_gate2/selection.json`.
The final broad-QA selection record is
`outputs/psf_disaggregation/validation/gate2/primary_selection/v2_broad_qa_reporting/selection.json`.
The standalone repository carries compact copies of both records below the same
relative paths under `artifacts/`.

## Project change history

| Date | Change | Author |
| --- | --- | --- |
| 2026-07-27 | Superseded corrected Gate 0 v1 after a Delhi MGRS-tile seam exposed pre-mosaic temporal reduction; required same-datatake mosaicking and a versioned v2 rerun | Codex, at user direction |
| 2026-07-28 | Superseded v2 after auditing partial fine-pixel support inside coarse S2 means; required a 0.90 supported-area threshold and versioned v3 rerun | Codex, at user direction |
| 2026-07-28 | Updated the Draw.io and native Miro layer to the integrity-v3 terminology contract; removed SDGSAT from the sprint layer because it is a separate user-owned workstream | Codex, at user direction |
| 2026-07-28 | Fixed the Day 2 numerical contract and recorded the narrower valid interiors required by Gaussian supports larger than the existing 1000 m source halo | Codex, at user direction |
| 2026-07-28 | Submitted the two aligned Day 2 Earth Engine source bundles to the configured Drive folder after explicit user authorization; recorded task IDs, band order, transforms, and resampling semantics in the export manifest | Codex, at user direction |
| 2026-07-28 | Preserved the strict corrected-radiance primary after diagnosing native Manhattan retrieval gaps; added broad and 7/30/90-day gap-filled sensitivities, retrieval-age diagnostics, and a reproducible named-site audit under VNP-COVERAGE-001 | Codex, at user direction |
| 2026-07-28 | Quarantined the 5201-by-5201 Delhi v1 export and added a 0.01 m export-selection inset for deterministic v2 grid dimensions without resampling | Codex, at user direction |
| 2026-07-28 | Kept strict QA as the only full-city radiance primary; excluded broad QA from the factorial and retained one targeted New York reference check after the v2 audit found only 2.93 km² of added coverage | Codex, at user direction |
| 2026-07-28 | Fixed OVERTURE-RASTER-001 before empirical allocation, built both 10 m structure bundles, and passed the exact four-bundle Day 2 input audit | Codex, at user direction |
| 2026-07-29 | Accepted both two-city input galleries, preserved a checksummed copy for the research note and blog, and retained the OVERTURE-RASTER-001 primary after its radiance-blind finer-rasterization sensitivity showed only edge-localized differences | Codex, at user direction |
| 2026-07-29 | Completed six radiance-blind empirical Gate 1 cutouts with citywide proxy normalization, the full circular-reference water factorial, Gaussian and actual-native-cell sensitivities, and a targeted New York broad-QA diagnostic; retained strict-QA support failures as nodata | Codex, at user direction |
| 2026-07-29 | Closed the empirical cutout visual preflight after the user found no obvious anomaly; preserved a reduced checksummed gallery for the research note and blog without treating visual acceptance as proxy selection or independent validation | Codex, at user direction |
| 2026-07-29 | Completed the resumable Linux full-city 23/22 matrices and machine closeout: all 45 COGs and sidecars passed checksums and grid/layout validation, direct baselines matched source pixels exactly, registered Gaussian invalid edges were retained, and no executor tile seam was detected; final user COG review remains open | Codex, at user direction |
| 2026-07-29 | Closed Gate 1 after user visual review found no issue; carried forward the concern that a sharp water prior may move waterfront-origin radiance landward more systematically than analogous inland low-proxy boundaries, requiring explicit Gate 2 shoreline and inland-boundary negative controls | Codex, at user direction |
| 2026-07-29 | Started Day 3 with common shoreline-distance and matched inland-boundary metrics plus an explicit Gate 2 readiness audit; blocked independent shoreline and observation-condition claims until a documented external water reference and the retained 2024 daily VNP stack exist | Codex, at user direction |
| 2026-07-29 | Ran a fixed five-fold, 500 m-buffered native-cell held-out preflight before the final fine-grid fold implementation; both New York proxy analogues improved overall MAE, Delhi built form was mixed, and Delhi S2-only worsened MAE/RMSE, so no proxy was selected and the negative result was retained | Codex, at user direction |
| 2026-07-29 | Interpreted held-out residuals as broadly sign-balanced at city scale but not proven spatially random; retained possible road, waterway, development-edge, suburban-patch, and radiance-decile conditioning as future work and moved on within the demo sprint | Codex, at user direction |
| 2026-07-29 | Generated checksummed full-city configuration, kernel, proxy, and internal-water-prior sensitivity tables and a kernel curve from the frozen 45-configuration manifest; retained them as reconstruction/support diagnostics rather than independent validation | Codex, at user direction |
| 2026-07-29 | Prepared pinned Overture 2026-06-17 areal-water references for both cities and ran the saved-output shoreline factorial; found a clear water-to-adjacent-land shift for S2-only combined-soft but not built form, so retained the waterfront concern as proxy-dependent and bounded rather than universal | Codex, at user direction |
| 2026-07-30 | Added mapped pier/quay, bridge, building, road, and ordinary-shoreline strata plus all-variant difference-map plates; retained sparse Delhi pier/quay results as non-interpretable and treated all strata as redistribution diagnostics rather than origin truth | Codex, at user direction |
| 2026-07-30 | Selected no-water-prior as the post–Gate 2 reporting primary because water weighting imposed an unvalidated, proxy-dependent origin assumption; preserved combined-soft as the preregistered configuration and retained every water-weighted output as a sensitivity | Codex, at user direction |
| 2026-07-30 | Started a checkpointed 2024-03-01 OSM-attic structural sensitivity for both cities; required identical rasterization and formula choices where comparable and classified it as combined source-coverage/vintage sensitivity rather than clean temporal validation | Codex, at user direction |
| 2026-07-30 | Reclassified the 500 m held-out run as preflight because nearby VNP cells can contain PSF-mediated target signal; set 2550 m, the four-sigma support of the widest registered 1500 m-FWHM Gaussian, as the final primary exclusion with 1500 m and 2000 m sensitivities and mandatory sample-composition reporting | Codex, at user direction |
| 2026-07-30 | Preregistered radiance-blind allocation-gain strata (<0.8, 0.8–1.25, and ≥1.25) for the final held-out run after the preflight showed consistent downweighting benefit and upweighting harm across all city×proxy combinations | Codex, at user direction |
| 2026-07-30 | Recorded the New York preflight tension: S2-only beat built form on overall MAE/RMSE and improved MAE in 5/5 rather than 4/5 folds; preserved built form as primary because changing proxy from held-out outcomes would violate PROXY-001 | Codex, at user direction |
| 2026-07-30 | Recorded the missing Gate 0 empirical-monotonicity criterion and quarantined four v3-directory PNGs whose annotations used v0 metrics; retained v3 CSV/JSON summaries as authority and required version-matched regeneration | Codex, at user direction |
| 2026-07-30 | Completed the HELDOUT-001 native-cell run at 1500/2000/2550 m; built form improved MAE/RMSE in both cities and every primary-buffer fold, Delhi S2-only remained negative, and gain asymmetry persisted. Retained remove-before-fine-grid-convolution as a stronger optional extension | Codex, at user direction |
| 2026-07-30 | Built and audited compact two-city strict-QA daily VNP packages with 100 dates and six date-matched condition stacks; replaced an implied 10 m×100 materialization with aligned 500 m storage and daily streaming semantics without changing radiance authority | Codex, at user direction |
| 2026-07-30 | Completed the daily coarse-operator observation-condition audit; built form added less than 0.00004 condition R² relative to uniform and did not amplify temporal variability. Classified reductions from direct as smoothing and retained low New York daily support as the dominant limitation | Codex, at user direction |
| 2026-07-30 | Closed ARTIFACT-PROVENANCE-001 by regenerating all four Gate 0 figures exclusively from saved v3 samples and v3 summaries and recording source/output hashes | Codex, at user direction |
| 2026-07-30 | Closed Day 3 as a bounded method result with useful negative findings; consolidated checksummed tables/figures and fixed supported, unsupported, and deferred claim language in a machine-readable classification | Codex, at user direction |
| 2026-07-30 | Deferred OSM-HISTORY-001 after 547 New York extraction checkpoints, with Delhi not started and no result selected; preserved resumability while prioritizing held-out and observation-condition evidence because OSM-versus-Overture differences remain source-confounded | Codex, at user direction |
| 2026-08-02 | Compared reporting-primary allocated/direct regional-sum ratios over mapped water and the existing radiance-blind inland low-proxy controls; found no city×proxy case with a larger water reduction and classified the effect as general low-proxy reallocation, while explicitly retaining the non-distribution-matched control limitation | Codex, at user direction |
| 2026-08-02 | Added proxy-only fine-grid allocation gain and validated gain-stratum companion COGs for both reporting-primary products; preserved frozen product hashes and limited threshold interpretation to warning strata rather than pixel-error calibration | Codex, at user direction |
| 2026-08-03 | Selected the broad-QA median for final demonstration reporting after confirming that the strict ten-observation mask dilated from 29,269 input pixels to 177,594 output pixels; generated complete-coverage direct, uniform, built-form/no-water and gain COGs for both cities while preserving strict v1 as Gate 0/daily authority and conservative spatial sensitivity | Codex, at user direction |
| 2026-08-03 | Repeated the physics-buffered held-out analysis with broad-QA radiance on the identical frozen cohort; built form improved overall MAE/RMSE in both cities, improved 5/5 New York and 4/5 Delhi folds, and retained favorable low-gain/adverse high-gain asymmetry in all four city-by-proxy comparisons | Codex, at user direction |
| 2026-08-03 | Closed v2 analytically as a coverage-complete bounded method result; joined coverage, broad held-out, operator, water/inland, gain, and inherited strict daily-condition evidence while leaving user visual inspection as the final presentation check | Codex, at user direction |
| 2026-08-03 | Added the New York broad-QA S2-only/no-water ablation and its proxy-specific gain companion; eliminated all 177,594 radiance-neighborhood gaps while retaining 1,209,492 explicitly labeled S2 proxy-support invalid pixels | Codex, at user direction |

## FINE-GAIN-001 — fine-grid trust indicator

The delivered gain is `rho(x) / max((k tensor rho)(x), epsilon)` under the
reporting-primary built-form, no-water, circular-reference operator; `rho` is
the normalized structural proxy `h` from the method overview. It uses complete
proxy/geometric kernel support and no radiance values. Band 1 stores
continuous gain; Band 2 stores 1 for gain below 0.8, 2 for 0.8 to below 1.25,
and 3 for gain at or above 1.25.

The coarse physics-buffered held-out results justify labeling Band 3 as a
failure-risk warning: error increased in the gain-at-or-above-1.25 stratum in
all four city-by-proxy comparisons. They do not prove that every fine pixel in
Band 3 is wrong or assign a pixel-level error probability. The COGs are
versioned companions to, not replacements for, the immutable reporting
products.

## WATER-INLAND-001 — allocated/direct regional comparison

Completed on 2026-08-02 without changing the reporting primary. The metric is
the ratio of allocated-radiance sum to nonnegative direct-radiance sum on
common finite support for mapped water and the existing radiance-blind inland
low-proxy control. In all four city-by-proxy comparisons, water reduction is
not larger than inland reduction. For built form, water minus inland reduction
is -41.7 percentage points in New York and -2.4 points in Delhi.

This does not support a water-specific allocation effect. It supports the
broader descriptive interpretation that the structural operator relocates
radiance away from low-proxy regions. It does not establish fine-scale
accuracy or validate the allocation as a water correction.

The reused control selects the lowest proxy-valued inland pixels more than
1500 m from mapped water. It targets mapped-water area but is capped at 10% of
eligible inland support. It is radiance-blind and reproducible, but not
distribution-matched on proxy value, morphology, direct radiance, or urban
context. A stronger causal contrast would require a preregistered matching
design; do not retroactively describe this result as one.

## NORMALIZATION-001 — proxy normalization support

Normalize each proxy to mean one over pixels where that proxy has finite valid
analysis support. Do not remove pixels from the normalization support merely
because they are classified as water. Record the pre-normalization mean, valid
pixel count, support mask checksum, and post-normalization mean.

A global positive rescaling of `h` cancels algebraically in the Fork-form
allocation except where denominator floors or finite-precision guards
intervene. The normalization is therefore for comparability and numerical
auditability, not a claim that proxy values have physical units. Gate 0 rank
statistics may use the unnormalized proxy but must record that fact.

This entry corrects the earlier configuration label
`mean_one_over_valid_land`, which did not match the implemented S2 region-mean
normalization. No completed Gate 0 rank result changes because Spearman
correlation is invariant to positive global scaling.

## New-decision template

Copy this section before making another material analytical choice.

```text
ID:
Status:
Assumption:
Exact implementation:
Affected components:
Alternatives retained:
Rationale:
Expected failure modes:
Evidence required for review:
Decision rule:
Artifacts to regenerate if changed:
Date and author:
```
