# Fork-form structural allocation sprint

## Purpose

This four-day tactical sprint tests whether a static, 10 m structural proxy can
allocate coarse VNP46A2 nighttime radiance more plausibly within a VIIRS
neighborhood while preserving VIIRS as the only radiometric authority.

The primary method uses the algebraic form of the training-free convolution
calibration in Fork et al. (2026), *Estimating high-resolution albedo for urban
applications*:

- paper: https://www.nature.com/articles/s41467-026-73436-y
- accompanying code: https://doi.org/10.7910/DVN/7T7QDH

Fork et al. use corresponding high- and low-resolution reflectance bands: the
high-resolution image already measures the same underlying quantity and carries
plausible subpixel reflectance detail, while Sentinel-2 supplies the
low-resolution radiometric constraint.

This sprint makes a materially weaker, cross-quantity substitution:

- `l` is VNP46A2 corrected nighttime radiance, reprojected onto the 10 m working
  grid;
- `h` is a dimensionless, nonnegative 10 m allocation proxy derived from
  daytime reflectance, land cover, buildings, and roads; and
- `L_tilde` is a locally normalized allocation of VIIRS radiance on a 10 m
  working grid.

For kernel `k`,

$$
\widetilde{L}(x,t)
=
\frac{\left[k \otimes l(\cdot,t)\right](x)}
{\max\left(\left[k \otimes h\right](x), \epsilon\right)}
h(x).
$$

The implementation is therefore a **Fork-form normalized-convolution
allocation**, not a transfer of radiometric calibration from S2 to NTL.
Sentinel-2 never supplies nighttime radiance, and the resulting 10 m values are
not independently calibrated NTL measurements.

### Scientific assumption and claim boundary

The cross-quantity substitution introduces the hypothesis

$$
L_{\mathrm{true}}(x,t) \propto h_{\mathrm{structure}}(x)
$$

within an allocation-kernel neighborhood. The method does not establish that
this proportionality holds. It only constructs one of infinitely many
high-resolution fields compatible with the coarse observation.

The output has radiance units because the arbitrary scale of `h` cancels in the
ratio. That dimensional consistency does not make `h` a radiance measurement or
make `L_tilde` radiometrically validated at 10 m.

This is an **analysis-only observation product**. It is not the canonical
radiance field `L(x,t)` or canonical state `phi`: it consumes observed VIIRS
radiance as an input and inherits the observation conditions in that radiance.
The strongest claim available without independent high-resolution nighttime
imagery is:

> The method produces a locally normalized, structurally informed allocation of
> observed VIIRS radiance whose behavior may be more plausible than declared
> null allocations under specific negative controls.

### Terminology contract

| Use | Meaning | Do not substitute |
| --- | --- | --- |
| **Fork convolution calibration** | The original same-quantity reflectance method in Fork et al. | A description of our S2-to-NTL semantics |
| **Fork-form normalized-convolution allocation** | Our reuse of the equation with a cross-quantity structural proxy | Radiometric calibration transfer |
| **Structural allocation proxy, `h`** | A dimensionless hypothesis about relative within-neighborhood allocation | High-resolution NTL, emitted radiance, or ground truth |
| **Locally normalized radiance allocation, `L_tilde`** | A high-resolution-shaped redistribution of an observed VIIRS radiance field under the declared operator | Conserved physical energy, calibrated 10 m NTL, canonical `L`, or super-resolved truth |
| **Allocation kernel, `k`** | A declared neighborhood-support assumption used by the algorithm | Measured, fitted, or recovered VIIRS PSF |
| **Independent nighttime reference** | SDGSAT/ISS/aerial data with documented calibration and registration limits | Ground truth unless those limits justify the term |

Code, figures, artifact metadata, the research note, the narrative notebook, and
the public blog must follow this contract.

## Locked sprint decisions

| Decision | Choice |
| --- | --- |
| Cities | New York City and Delhi |
| Pilot center date | 2024-03-01 |
| Pilot interval | 2024-01-11 inclusive through 2024-04-20 exclusive (100 days) |
| Low-resolution authority | Daily VNP46A2 corrected NTL plus a 100-day median |
| Analysis support | Exact 50 km square in each city's projected UTM grid |
| High-resolution grid | Explicit 10 m UTM working grid; 10 m sampling is not 10 m independent radiometry |
| Preregistered conservative VNP QA | Strict MQF-0, clear/probably-clear, snow/shadow/cirrus-free observations with minimum count 10 |
| Final spatial-reporting VNP QA | Broad MQF-0/1 median with minimum count 5; selected after Gate 2 for coverage, not performance |
| Implementation | Python using the Earth Engine Python API |
| Primary operator | Fork-form locally normalized radiance allocation |
| Learned parameters | None |
| Structural variants | direct/null, uniform allocation, built-form primary, S2-only ablation |
| Independent nighttime reference | Outside this sprint implementation; SDGSAT work is user-owned and does not gate the sprint |
| Public deliverables | Reproducible research note, detailed narrative notebook, and companion blog |

The interval is fixed before inspecting results. It spans a mostly leaf-off
period in New York and the dry/pre-monsoon period in Delhi. It may be changed
only if the Day 1 coverage gate fails; any replacement window and the reason for
changing it must be recorded.

## Relationship to Nocturne V1

The sprint isolates the spatial image-formation term that the current
VNP46A2 forward operator does not implement. It can feed later Nocturne work in
four ways:

1. a tested normalized-convolution allocation implementation;
2. an allocation-kernel sensitivity curve that can inform, but does not identify,
   the future VIIRS PSF/MTF term;
3. a structural allocation proxy that can be evaluated as a prior for a future
   trainable field; and
4. a radiance-authority-with-insufficient-support diagnostic for the residual
   layer.

It does **not** normalize lunar, cloud, snow, aerosol, or viewing conditions.
Daily condition stratification is therefore an artifact-propagation and
non-inferiority audit, not evidence that the canonical decisive test has been
passed.

## Experiment contract

### Analysis decision traceability

No material analytical choice may remain implicit in code. Before a choice is
used to produce or select a downstream result, record it in
`docs/psf-disaggregation-decisions.md` with:

- a stable decision ID and status;
- the exact assumption and implementation, including thresholds and formulas;
- which source, proxy, operator, mask, or metric it affects;
- the alternatives retained for sensitivity analysis;
- the rationale and expected failure modes;
- the evidence that may justify changing it;
- the artifacts that must be regenerated after a change; and
- the date and author of the decision.

This applies at minimum to masks and soft weights, quality thresholds,
reprojection/resampling, proxy floors and normalization, building/road weights,
kernel support, denominator guards, exclusions, and validation thresholds.
Configuration keys and artifact metadata must reference the corresponding
decision ID. A downstream metric may motivate a review, but it must not silently
change an upstream choice. Any post-result change creates a new decision entry,
increments the affected artifact version, and reruns every dependent result.

### Spatial extents and grids

Use the existing city manifest centers and an exact 50 km square in each city's
UTM CRS. Snap the center to the nearest 10 m grid point, yielding exactly
5000-by-5000 cells. Use a 1000 m source-query halo and crop final statistics to
the square. This efficient fixed support is not a functional-urban-area
definition; a versioned urban-boundary-plus-buffer analysis is future work.

All inputs must be aligned to the explicit projected grid before the operator
runs. Every resampling or aggregation operation must be named in configuration,
artifact metadata, and the methods write-up. “Earth Engine default” is not an
acceptable recorded method.

Record:

- CRS, affine transform, bounds, width, and height;
- the VNP46A2 source projection and resampling method;
- the valid-data mask for every source;
- the exact kernel normalization and boundary mode; and
- pixel area, because a 10 m pixel is not constant-area in EPSG:4326.

Use bilinear resampling for continuous S2 bands. Use nearest-neighbor
reprojection for quality flags, categorical masks, observation counts, and the
30 m JRC temporal-occurrence prior. Record and compare nearest-neighbor and
bilinear VNP radiance reprojection in a sensitivity check. Neither VNP method
creates independent 10 m radiometry.

### VNP46A2 products

Retain the daily stack throughout the 100-day interval:

- `DNB_BRDF_Corrected_NTL`;
- `Gap_Filled_DNB_BRDF_Corrected_NTL`;
- `DNB_Lunar_Irradiance`;
- `Latest_High_Quality_Retrieval`;
- `Mandatory_Quality_Flag`;
- `QF_Cloud_Mask`; and
- `Snow_Flag`.

Decode `QF_Cloud_Mask` into its categorical bit fields before analysis. Build the
100-day primary median from MQF-0, nighttime, confident/probably-clear,
medium/high cloud-mask-quality, shadow-free, cirrus-free, snow-free corrected
observations. Require at least ten retained observations. Store the raw source
count, retained count, rejected count, retained fraction, and sufficient-support
mask.

Retain a declared broader diagnostic admitting MQF 1 and requiring at least
five observations. It remains explicit because the Earth Engine catalog and
the October 2024 NASA Collection 2 guide disagree about MQF 1 and later values.

The v1 Day 2 visual audit found native corrected-radiance coverage depressions
over lower and central Manhattan. Exact-grid checks show that this occurs
before Nocturne convolution or JRC water weighting and is associated with the
VNP product's own coarse land/water background and retrieval availability.
Lower Manhattan has 10 native corrected observations and 8 strict retained
observations; Midtown has 23/21; Central Park has 48/41. The JRC occurrence at
all three named points is zero and its allocation weight is one.

Preserve the strict corrected-radiance median as the Gate 0 and daily-condition
authority and as a conservative-quality spatial sensitivity. Export source,
retained, rejected, and
retained-fraction fields plus the broad-QA composite. After the completed v1
analysis, `VNP-COVERAGE-002` selects broad QA for final spatial demonstration
reporting because the strict support mask dilates under convolution.
Retain gap-filled radiance only as an explicitly labeled sensitivity with
maximum latest-high-quality-retrieval ages of 7, 30, and 90 days. Thirty days
is the named recent threshold and requires at least ten represented days.
Export fresh-retrieval count and median/P90 retrieval age. Repeated daily
gap-filled values may carry one retrieval forward and are not independent
observations.

The named-site audit demonstrates material sensitivity: Lower Manhattan is
approximately 137 under broad corrected radiance versus 529 under the
recent-30-day gap-filled field; Midtown is approximately 619 versus 865.
Neither visual brightness nor coverage alone selects the gap-filled field, and
it cannot silently replace the primary.

The v2 core-square audit finds that broad QA adds only 0.117 percentage points
of New York coverage, or 2.93 km², while strict and broad radiance on their
common support correlate at 0.9975. Both contracts cover 100% of the Delhi
core. The original v1 decision limited broad QA to one targeted New York
comparison. The versioned v2 reporting refresh supersedes only that spatial
reporting role: it adds broad direct, uniform, and built-form/no-water products
for both cities without reopening the full proxy/kernel/water factorial or
rewriting strict artifacts.

### Sentinel-2 composite

Build bandwise Sentinel-2 SR Harmonized medians over the same fixed interval.
Join and mask with Cloud Score+ following the referenced method as closely as
its public description permits. Also mask snow and invalid reflectance, require
common valid support across all retained bands, and mask the continuous
composite where fewer than five common observations exist.

Explicitly bilinearly reproject every continuous source band to the locked UTM
grid, mosaic overlapping MGRS tiles sharing a `DATATAKE_IDENTIFIER`, and only
then compute temporal medians and indices. Reproject SCL, masks, and counts with
nearest neighbor. B11/B12 and indices that depend on them retain an effective
resolution of 20 m even though they are sampled on the 10 m working grid.
Retain
`index_of_bandwise_temporal_medians_after_datatake_mosaic` as the primary
composite definition and compare it with per-datatake-index medians if time
permits.

Retain at least:

- B2, B3, B4, B8, B11, and B12 surface reflectance;
- NDVI;
- NDBI;
- MNDWI or an equivalent water indicator;
- the Cloud Score+ clear score; and
- valid-observation count.

The composite is a static structural covariate, not nighttime radiance.

### Structural allocation proxies

Every allocation proxy must be nonnegative, finite, on the same 10 m grid, and
normalized to a common arbitrary scale over finite analysis support before use.
Water is not excluded from normalization merely because it is water. The
Fork-form operator is invariant to a global positive rescaling of `h` except
where numerical floors intervene; nevertheless, record the normalization
support and pre/post-normalization summaries so variants remain auditable.

1. **Direct upsample null** — reprojected VNP radiance with no structural
   allocation. This is the visual and numerical no-disaggregation baseline.
2. **Uniform normalized-convolution null** — `h(x) = 1` on valid land. Under the
   equation this generally returns `k ⊗ l`, not exactly the direct upsample.
   Keep both baselines so smoothing is not mistaken for structural skill.
3. **Built-form primary proxy** — Overture building footprints plus Overture
   weighted road-segment density, with declared water and land-cover weights.
   Overture road segments retain class information and draw substantially on
   OpenStreetMap while allowing buildings and roads to be pinned to one
   reproducible Overture release. The sprint release is explicitly a
   **contemporary structural proxy used to allocate 2024 radiance**, not a
   reconstruction of 2024 built form. This is the
   conceptually strongest sprint proxy because buildings and roads encode where
   urban lighting infrastructure can occur. Use the same construction in both
   cities. If Overture access becomes the Day 1 bottleneck, use direct OSM
   buildings and roads as the declared fallback rather than mixing sources
   across cities.
4. **Sentinel-2-only ablation** — a preregistered monotone combination of
   built-up, low-vegetation, and non-water evidence. It tests how much allocation
   can be obtained from daytime spectral context alone; it is not an
   uncalibrated NTL image and is not presumed to be the preferred proxy.

Freeze proxy formulas only after the corrected Day 1 Gate 0; do not tune them
against downstream validation figures. The original Gate 0 is exploratory v0.

Keep buildings and roads as separate intermediate rasters even if they are
combined in the final `h`. This makes the attribution inspectable.

For the 10 m structure bundles, estimate building-footprint coverage from the
binary union of Overture polygons sampled on a 2 m subpixel grid and averaged
over each 5-by-5 block. Allocate class-weighted road-centerline length after
segmentizing lines to at most 1 m and assigning each short segment's exact
length to its midpoint pixel. Do not assume a road width. The building method
is an area approximation with 0.04 fraction increments; the road method must
conserve weighted length within `0.0001` relative error before float32
accumulation. Compare 2 m versus 1 m building sampling and 1 m versus 0.5 m
road segmentization on representative cutouts. These are explicit
rasterization sensitivities, not hidden resampling.

For corrected coarse Gate 0, intersect Overture geometry with actual native VNP
cell polygons. Divide building area by actual projected cell area. Express
weighted road length in metres per square kilometre and use the same fixed
20,000 m/km² saturation in both cities. Explicitly configure every observed
road class and fail if a new class appears; do not silently apply a default.
Record the 70/30 building-road weights, square-root building transform, and
`0.05` floor as preliminary heuristic assumptions.

Pin Overture release `2026-07-22.0` and record input checksums and source
bounding boxes. A checkpointed 2024-03-01 OSM-attic comparison was initiated
under `OSM-HISTORY-001`, then deferred after 547 New York extraction tiles;
Delhi was not started. The preserved checkpoints can support future work, but
OSM-only history versus multi-source Overture would remain a combined
source-coverage/vintage sensitivity rather than a clean temporal experiment.

### Water handling

Water is an allocation assumption, not an invalid observation. Never mask,
zero, or discard VNP radiance solely because its footprint intersects water.
Do not make water pixels output nodata solely because they are water.

The preregistered primary was a **soft proxy weight**, not a binary mask. JRC
occurrence is a 30 m temporal frequency derived from 1984–2021 Landsat, not a
10 m spatial fraction or a contemporaneous 2024 observation. Where JRC has no
valid-observation support, retain a neutral allocation weight and a support-gap
diagnostic. Otherwise, occurrence is converted to

$$
w_{\mathrm{water}} =
1 - \operatorname{clip}\left(
\frac{\mathrm{occurrence}}{90}, 0, 1
\right),
$$

then multiplied into the raw structural proxy before applying the existing
`0.05` proxy floor. The S2-only ablation also contains a separate MNDWI-derived
spectral-water weight. Thus persistent water receives weak but nonzero
allocation support, while the original VNP authority remains present in the
numerator and all operator-consistency diagnostics.

The S2-only proxy contains two separable water components: the persistent JRC
prior and the MNDWI spectral prior. Run the same proxy and kernel under these
preregistered factorial variants:

1. **no water prior** — neither JRC nor MNDWI suppression;
2. **persistent only** — soft JRC occurrence weight without MNDWI suppression;
3. **spectral only** — MNDWI suppression without JRC weighting;
4. **combined soft** — the preregistered primary using both components;
5. **combined hard-persistent sensitivity** — MNDWI plus `w_water = 0` above
   the declared JRC occurrence threshold,
   sensitivity-only and never eligible to become the headline result solely
   because it reduces allocated-water radiance; and
6. **soft weight with mapped-infrastructure override** — retain soft water
   weighting but restore proxy support where mapped buildings or road/bridge
   segments intersect water, as a sensitivity for ports, bridges, and
   waterfront infrastructure.

No water variant may replace the preregistered primary automatically. A change
requires a new decision-ledger entry made after reviewing the complete
shoreline test—not just the allocated-water-radiance metric—and requires regeneration of all
dependent allocations and validations.

After the complete Gate 2 shoreline review, `WATER-002` selects **no water
prior** as the post-review reporting primary. The frozen configuration retains
`combined_soft` so the preregistration and completed artifact hashes remain
unchanged. The already-completed no-water products are selected directly;
future headline tables and figures must use them and label all water-weighted
outputs as sensitivities. This is an evidence-based reporting change, not a
claim that combined-soft was disproven.

### Allocation kernels

The reference operator preserves the literal Fork equation and substitutes a normalized
circular averaging kernel whose radius is one nominal coarse-pixel width
(500 m). It is a provenance choice, not the native footprint or a measured
VIIRS PSF.

Treat the following as allocation sensitivity variants, not as recovered or
equivalent definitions of the VIIRS PSF:

- the actual aligned native 15-arcsecond VNP cell polygon as a **major
  sensitivity**;
- Gaussian kernels with explicitly named `sigma` or FWHM; and
- widths of 750 m, 1000 m, and 1500 m under that named convention.

Never use the unqualified word `width` in configuration or output metadata.
The true effective response includes the sensor footprint, scan geometry,
geolocation, and VNP gridding. No comparison in this sprint identifies those
components separately or estimates a physical PSF.

### Numerical guards and residuals

Use:

- normalized kernels;
- an explicit denominator epsilon;
- nonnegativity clipping after recording pre-clip diagnostics;
- a valid-support fraction;
- edge padding documented in metadata; and
- a denominator-instability mask.

Write three different diagnostics and do not conflate them:

1. **operator-consistency error**: `l - k ⊗ L_tilde`, evaluated only where the discrete
   operator makes the comparison valid;
2. **radiance-authority share with insufficient proxy support**: positive
   VIIRS authority where `k ⊗ h` is below the supported threshold; and
3. **proxy disagreement**: differences among S2-only, built-form, and uniform
   allocations.

Exact equality is not assumed: the Fork-form local gain varies spatially, so a
second aggregation does not algebraically have to reproduce the source field.
Epsilon floors, boundaries, reprojection, and invalid masks add further
differences. Call the output **locally normalized** unless measured
operator-consistency error is small enough for a separately declared stronger
term. Do not describe radiance sums as physical flux or emitted energy.

## Validation gates

### Gate 0 — proxy and alignment, Day 1

Run this before implementing the complete export pipeline.

For each city and each nonuniform structural proxy:

- aggregate `h` to the VIIRS support;
- compute citywide and spatial-block Spearman correlations with median VNP;
- repeat after removing the broad radial distance-to-center trend;
- inspect water, airport, industrial, dense-residential, and low-light areas;
- report S2 valid-observation coverage; and
- report the fraction of land-eligible coarse cells with insufficient proxy
  support, the separately excluded persistent-water fraction, and the share of
  VNP radiance falling in insufficient-support cells.

Decision rule:

- **go**: positive spatial-block and detrended association, adequate coverage,
  and no obvious systematic allocation to water/cloud gaps;
- **revise once**: broad citywide association exists but the detrended/block
  result or visual audit fails; or
- **stop/prune the proxy**: the revised proxy still fails.

Do not select a proxy solely because it maximizes correlation with VNP. The
purpose is to reject a nonsensical allocation hypothesis, not train one on the
target. Passing Gate 0 shows coarse association and alignment only; it does not
validate the within-pixel nighttime allocation.

#### Exploratory Gate 0 v0 and corrected rerun

The first Gate 0 run found positive associations for both proxies, but it is
retained as **exploratory v0**, not as the final freeze. It used unfiltered VNP
radiance values, chunk-clipped S2 aggregation, nominal 500-by-500-m cell areas,
and centroid-allocated Overture geometry. Its water-support definition was also
revised after the initial New York result. These are traceable development
findings, not confirmatory results.

| Proxy | City | Citywide Spearman | 5 km block Spearman | Radially detrended Spearman | Insufficient land cells | VNP radiance in insufficient cells | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Built-form primary | New York | 0.802 | 0.830 | 0.727 | 3.01% | 3.59% | Go |
| Built-form primary | Delhi | 0.755 | 0.902 | 0.716 | 3.24% | 0.66% | Go |
| S2-only ablation | New York | 0.774 | 0.823 | 0.717 | 0.00% | 2.00% | Go |
| S2-only ablation | Delhi | 0.440 | 0.571 | 0.497 | 0.03% | <0.01% | Go |

In exploratory v0, the New York analysis rectangle was 23.69%
persistent-water-excluded coarse
cells; those cells are reported separately rather than incorrectly treated as
unsupported land. The coarse maps show the intended suppression of open water
in the saved rendering. That visual check could not rule out partial internal
chunk-footprint aggregation. Airport, port, and other bright-but-sparsely-built areas
remain a named visual-audit risk: open paved or industrial lighting can be
bright at night without much mapped building area. That limitation is carried
forward rather than tuned away using VNP.

Corrected Gate 0 uses strict `VNP-QA-001`, the exact 50 km UTM square, a 1000 m
processing halo around every interactive chunk, deterministic core ownership,
same-datatake mosaicking of overlapping Sentinel-2 MGRS tiles on the locked
grid, actual native VNP polygons/areas, and exact Overture intersections with
those polygons. Re-freeze the proxy only after reviewing that rerun.

The authoritative Gate 0 artifacts are the v3 files under
`outputs/psf_disaggregation/validation/gate0/`. The first corrected attempt
under `v1_qa_grid_halo/` is superseded because the Delhi map exposed a major
Sentinel-2 MGRS-tile seam; its metrics cannot support the proxy decision. The
datatake-corrected v2 attempt is also superseded and is not retained in the
final v2 working artifact set.

V2 is also superseded as a proxy-freeze basis. Its area-weighted S2 mean could
use a partially supported native footprint because masked 10 m pixels do not
enter the reducer denominator. V3 records the mean of the binary fine-pixel
support mask on each actual native VNP footprint and requires at least 90%
supported area before that cell enters S2-only metrics. This criterion does not
apply to the built-form proxy.

Current corrected artifacts are written under
`outputs/psf_disaggregation/validation/gate0/v3_qa_grid_halo_datatake_support/`.

Corrected v3 results:

| Proxy | City | S2 support exclusion | Citywide Spearman | 5 km block Spearman | Radially detrended Spearman | Insufficient land cells | VNP radiance in insufficient cells | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Built-form primary | New York | n/a | 0.812 | 0.826 | 0.744 | 1.48% | 2.68% | Go |
| Built-form primary | Delhi | n/a | 0.761 | 0.901 | 0.733 | 1.69% | 0.34% | Go |
| S2-only ablation | New York | 2.43% (372/15,335) | 0.783 | 0.811 | 0.730 | 0.00% | 1.99% | Go |
| S2-only ablation | Delhi | 0.00% (0/13,280) | 0.438 | 0.576 | 0.499 | 0.03% | <0.01% | Go |

Both declared proxies are therefore frozen for Day 2 without target-driven
retuning. These results establish plausible coarse association and alignment
only; they are not evidence that either proxy identifies the true within-cell
nighttime radiance pattern.

The Gate 0 go rule did not test whether the empirical proxy-to-radiance
relationship was monotone across proxy bins or in the bright tail. The phrase
“monotone combination” in the S2-only definition describes the construction of
the proxy, not its empirical relationship with VNP. A mound-shaped association
could pass the positive citywide/block/detrended thresholds while
misallocating the bright tail. `GATE0-MONOTONICITY-001` records this as a rule
gap; future runs must preregister binned shape and upper-tail diagnostics. No
retrospective threshold or proxy change is made here.

Four Gate 0 PNGs filed beneath the v3 directory carried v0 metric annotations.
The approximately 0.006 differences do not alter a go decision, but those PNGs
are not version-matched evidence. Under `ARTIFACT-PROVENANCE-001`, the v3
CSV/JSON summaries are authoritative and publication figures must be
regenerated from saved, checksum-recorded v3 artifacts.

The v3 runner checkpoints each completed interactive chunk with the complete
configuration hash and rejects malformed, mismatched, or stale checkpoints. A
five-minute request deadline and three bounded attempts prevent a single Earth
Engine request from blocking the run indefinitely. These settings change
execution reliability, not the analytical graph.

### Gate 1 — operator invariants, Day 2

For synthetic rasters and a small real-data cutout, verify:

- uniform and constant-field behavior;
- nonnegativity;
- nodata propagation;
- denominator-floor behavior;
- kernel normalization;
- boundary behavior;
- deterministic results; and
- operator-consistency error away from invalid support and boundaries.

Add a synthetic coastline fixture with bright land directly abutting water.
For every water variant, verify that VNP authority remains in the calculation,
report operator-consistency error, and quantify any transfer from water to adjacent
land. Hard masking is expected to move allocation and is not considered a
successful invariant merely because water values become zero.

The direct upsample and uniform normalized-convolution baselines must remain
distinct in tests and figures.

The deterministic synthetic coastline run now passes these software-level
checks: nonnegative valid outputs, distinct direct and uniform baselines,
preserved positive VIIRS authority over water, changed adjacent-land allocation
under the hard-water sensitivity, and execution of all six declared water
variants. It writes numerical summaries, inspectable figures, arrays, and a
17-layer diagnostic COG bundle under
`outputs/psf_disaggregation/validation/gate1/`.

The empirical preflight now adds three radiance-blind 1 km reporting cores per
city: dense building, sparse built, and water-adjacent infrastructure. The
operator is evaluated on a larger window before cropping, and the cores are
selected far enough from the source boundary to give the largest declared
Gaussian complete geometric support. Both proxies, all six water variants, the
circular reference, the Gaussian sensitivities, actual projected native-cell
area overlaps, direct and uniform nulls, and the targeted New York broad-QA
configuration are represented. Proxy normalizers are calculated over the
complete 50 km analysis square, not independently inside each cutout.

All circular-reference cores have complete strict-QA output support, with no
denominator-floor, denominator-instability, or negative-preclip events.
Scale-normalized operator-consistency MAE for the two structural proxies ranges
from 6.45% to 23.83% of mean absolute source radiance. This is empirical
evidence for the already-declared **locally normalized**, non-conserving
terminology; it is not independent fine-scale validation. The actual
native-cell area-overlap sensitivity has cell-level normalized consistency MAE
from 0.42% to 0.68%, while still retaining the recorded finite-grid
reaggregation error rather than being called exact conservation.

Strict-QA holes in the processing neighborhood—not cutout geometry—leave no
complete support for the 1000 m and 1500 m Gaussian kernels in the New York
dense core and for the 1500 m kernel in the New York water-adjacent core.
Those outputs remain nodata and are explicitly labeled in the gallery; broad
QA is not promoted to replace them. The accepted, checksummed results are
preserved under
`docs/figures/psf-disaggregation/empirical-cutout-galleries-v1/`.

The user completed the two-city visual audit on 2026-07-29 and found no
obvious anomaly in the accepted plots. This closes the empirical cutout
preflight only; it does not select a proxy or water variant and does not replace
the later independent shoreline and held-out validation. A checksummed
blog/research-note snapshot is preserved under
`docs/figures/psf-disaggregation/empirical-cutout-galleries-v1/`.

The kernel-support audit also found that the existing 1000 m source halo fully
supports the reference and representative native-cell kernels but not the
four-sigma Gaussian sensitivities. Their incomplete 50 km-square edge widths
are 280 m, 700 m, and 1550 m for 750 m, 1000 m, and 1500 m FWHM,
respectively. Those strips are invalid for the associated sensitivity; they
must not be padded or silently treated as complete support.

The resumable Linux full-city run completed on 2026-07-29. Its checksummed
manifest contains all 23 New York and 22 Delhi configurations. All 45 COGs and
metrics sidecars pass checksum, grid, band-description, and COG-layout
verification. Machine closeout found no denominator-floor, denominator-
instability, or negative-preclip event in a stationary run; exact expected
Gaussian boundary counts; pixel-exact direct baselines; and no evidence of a
512-pixel executor seam. The numerical and machine-assisted visual pre-review
is recorded in
`outputs/psf_disaggregation/validation/gate1/full_city_machine_closeout.md`.
The user completed final inspection of the full-city COGs on 2026-07-29 and
found no visual issue.
Gate 1 is therefore closed as an execution, integrity, and operator-invariant
gate. During review, the user identified a remaining interpretation risk:
because the water prior creates a sharper and more systematic low-proxy
boundary than many inland low-structure surfaces, it may shift waterfront
radiance landward even when some observed light originates from ports,
bridges, vessels, or waterfront structures. This is not treated as a Gate 1
implementation failure or as resolved evidence. Gate 2 must compare shoreline
transfer against both no-water variants and analogous inland hard-boundary
negative controls.

### Gate 2 — negative controls without independent high-resolution NTL, Day 3

#### Water-handling and shoreline-sensitivity test

Run every preregistered water variant with otherwise identical proxy, kernel,
grid, VNP input, and numerical guards. Use the 30 m JRC temporal-occurrence
prior on the 10 m working grid without calling it 10 m fractional water.
Evaluate against a separate current/reference water layer or manually audited
shorelines so the validation is not wholly circular. Compare:

- direct VNP upsample;
- uniform normalized-convolution output;
- S2-only output; and
- S2 + built-form output.

Report:

- allocated radiance over the declared water reference and its share of total
  allocated radiance;
- operator-consistency error and insufficient-support radiance-authority share;
- change in adjacent-land allocation relative to the no-water-prior variant;
- statistics in shoreline-distance bands of 0–100 m, 100–500 m, 500–1500 m,
  and beyond 1500 m;
- results separately for mapped waterfront buildings, ports, bridges/roads,
  and ordinary shoreline;
- the fraction of observed VNP authority whose footprint intersects water; and
- maps of the difference between each water variant and no water prior.

Show at least one New York coastal/Hudson/harbor example and the corresponding
Delhi river/water example. Inspect known bright waterfront infrastructure
separately from open water. A lower water fraction is a useful negative-control
result, but it can be achieved by hard-coding a zero water proxy and therefore
is not proof of correct land allocation. A variant that reduces allocated-water
radiance while producing compensating shoreline inflation, increased
insufficient-support radiance authority, or worse operator consistency is not
an improvement.

#### Leakage-safe held-out coarse pixels

Create spatially separated coarse-pixel folds. For a held-out fold:

1. remove its VNP values before reprojection or convolution;
2. estimate the local allocation gain only from the retained neighborhood;
3. produce the high-resolution allocation;
4. reaggregate it to the held-out coarse support; and
5. compare the predicted coarse value with the untouched observation.

Compare all proxies with a neighbors-only spatial interpolation baseline. Buffer
held-out folds by the declared PSF support so the held-out signal cannot enter
through nearby observed cells. Under `HELDOUT-001`, use **2550 m as the primary
exclusion buffer**: this is the registered four-sigma truncation radius for the
widest 1500 m-FWHM Gaussian sensitivity, rather than an arbitrary round
distance. Also run 1500 m and 2000 m buffer sensitivities. For a 1500 m-FWHM
Gaussian, 2000 m is approximately 3.14 sigma and its radial response is below
1% of peak, making it a useful practical bracket rather than the strict
primary.

Use the identical eligible training cells for the neighbors-only and
structural predictions. Report MAE, RMSE, bias, Spearman correlation,
performance by radiance decile, retained target count, retained-neighbor
count, nearest retained-neighbor distance, and the spatial distribution of
retained targets for every buffer. The increasingly distant subsets are not
random subsamples: they disproportionately retain block interiors. Treat
differences across buffers as evidence of distance dependence, not as clean
re-estimates from equivalent samples. If structural variants do not beat
spatial interpolation, record the negative result.

Preregister allocation-gain strata below `0.8`, `0.8–1.25`, and at least
`1.25`, where gain is target proxy divided by the weighted training-neighbor
proxy. This diagnostic is radiance-blind. Within each stratum report both
method errors and structural-minus-neighbors absolute-error change. The 500 m
preflight showed a consistent asymmetry across all four city×proxy
combinations: large error reductions below 0.8 and error increases at or above
1.25. The final PSF-buffered run must test whether that measured limitation
persists rather than assuming it does.

#### Observation-condition propagation

Apply the frozen proxy/operator to the retained daily VNP stack and stratify
output variability by decoded cloud state, lunar irradiance, snow, retrieval
age, and mandatory quality.

The pass condition is non-inferiority: disaggregation should not materially
amplify observation-condition sensitivity relative to the uniform/direct
baselines. Any apparent reduction must be labeled as smoothing unless it
survives matched clean-sample comparisons. This operator has no mechanism for
observation normalization.

### External nighttime reference (separate workstream)

SDGSAT discovery and preparation are user-owned and outside this sprint
implementation. If an independent nighttime reference is later joined to these
artifacts, record acquisition time, calibration status, cloud cover,
georegistration method and uncertainty, and license before using it. Treat it
as an independent reference with stated limitations unless its calibration and
alignment support a stronger label. Its availability does not gate this sprint.

## Four-day execution plan

### Visual inspection loop

Visualization is a required daily diagnostic, not a presentation step deferred
to the end.

- **Day 1:** generate the local corrected Gate 0 gallery and the matching Earth
  Engine Code Editor inspector. In Earth Engine, check RGB, NDVI, NDBI, MNDWI,
  persistent-water weight, S2-only allocation proxy, median VNP, and VNP
  observation count in both cities. Inspect the saved Gate 0 maps beside the
  numerical table.
- **Day 2:** inspect georeferenced cutouts and full-city COGs locally in
  QGIS/rasterio, including operator-consistency error, valid support,
  denominator instability, insufficient-support radiance-authority share,
  water-variant differences, and shoreline distance bands. Use temporary Earth
  Engine assets only when browser-side
  comparison materially helps; record the asset ID and source artifact
  checksum.
- **Day 3:** regenerate validation maps and figures from saved artifacts, with
  direct and uniform nulls visible beside every structural result.
- **Day 4:** build research-note and blog figures from the same artifact
  manifest, not from manually styled one-off exports.

For Day 1, run:

```bash
python -m nocturne.disaggregate.grids configs/psf_disaggregation.yaml
python -m nocturne.disaggregate.smoke configs/psf_disaggregation.yaml
python -m nocturne.disaggregate.overture configs/psf_disaggregation.yaml
python -m nocturne.disaggregate.gate0 configs/psf_disaggregation.yaml
python -m nocturne.disaggregate.built configs/psf_disaggregation.yaml
python -m nocturne.disaggregate.preview configs/psf_disaggregation.yaml
```

The Overture refresh downloads the pinned release for the exact 50 km source
envelope plus halo, validates each GeoParquet, and atomically replaces the
prior input only after validation.

The preview command regenerates the local corrected Gate 0 gallery and Earth
Engine inspection script under `outputs/psf_disaggregation/previews/`; those
ephemeral files are not part of the final v2 package. To inspect the same
live-derived layers in Earth Engine, paste the regenerated `gee_inspector.js`
into the Earth Engine Code Editor and change the `selected` city near the top
of the script. These are
computed directly from public catalog collections; they are not imported
assets. A file in Google Drive is only an export, while an Earth Engine asset
has an `ee.Image` asset ID and appears under the Code Editor **Assets** tab.
Whenever the pipeline creates either, the daily log must state the Drive folder
or exact asset ID and identify the corresponding local artifact.

For the current Day 2 synthetic inspection, run:

```bash
python -m nocturne.disaggregate.gate1 configs/psf_disaggregation.yaml
python -m nocturne.disaggregate.day2 configs/psf_disaggregation.yaml
```

To build the real 10 m Overture structure bundles before the input audit, run:

```bash
python -m nocturne.disaggregate.overture_bundle configs/psf_disaggregation.yaml
```

The first command regenerates a browser gallery and individual COGs beneath
`gate1/synthetic_cog_bundle/`; open `allocation.tif`,
`operator_consistency_error.tif`, and the support/mask layers in QGIS to
inspect their grid and nodata behavior. Their EPSG:32618 coordinates are an
explicitly labeled synthetic metre grid, not a real New York location.

The second command writes
`outputs/psf_disaggregation/manifests/day2_input_audit.json`. It checks both
city bundles for the exact CRS, 10 m affine transform, 5200-by-5200 source-halo
shape, band count/order, and checksum before a real-data operator run is
allowed.

Run the georeferenced empirical preflight with:

```bash
python -m nocturne.disaggregate.empirical_cutouts \
  configs/psf_disaggregation.yaml
```

Open
`docs/figures/psf-disaggregation/empirical-cutout-galleries-v1/index.html`
for the preserved two-city gallery. A fresh empirical-cutout run regenerates
the larger working directory with key 10 m QGIS COGs, compressed arrays, exact
run metadata, and the complete 129-row diagnostic matrix.

To reproduce the native VNP coverage diagnosis, run:

```bash
python -m nocturne.disaggregate.vnp_coverage configs/psf_disaggregation.yaml
```

The named-site CSV and JSON are regenerated beneath the ignored diagnostics
output tree; the final values are recorded in this overview and in
`psf-disaggregation-decisions.md`. After downloading the versioned v2 bundles, run
`python -m nocturne.disaggregate.source_preview` to produce the main source
gallery and a separate 16-panel VNP coverage/retrieval-age comparison.

### Day 1 — environment, data, allocation proxies, and Gate 0

1. Create or select a Google Cloud project, register it for Earth Engine, and
   authenticate the Python client.
2. Use Google Drive for initial Earth Engine exports; it requires less setup
   than provisioning a Cloud Storage bucket. Record the Cloud project ID and
   Drive folder in local/user configuration, never in committed credentials.
3. Add a sprint configuration containing cities, fixed dates, source asset IDs,
   grid definitions, masks, export settings, and allocation-proxy variants.
4. Implement or scaffold Python modules for:
   - Earth Engine initialization;
   - per-city grids;
   - S2/Cloud Score+ compositing;
   - daily and median VNP preparation;
   - quality-bit decoding;
   - building/road raster preparation; and
   - allocation-proxy construction.
5. Generate the local source/proxy gallery and Earth Engine Code Editor
   inspector, then preview small Gate 0 rasters and summary tables before
   starting full-resolution exports.
6. Preserve exploratory Gate 0 v0, then rerun Gate 0 with strict VNP QA,
   50 km square grids, 1000 m chunk halos, actual native VNP polygons/areas,
   and exact Overture intersections.
7. Freeze accepted proxy formulas only from the corrected result.
8. Keep SDGSAT discovery/preparation in the separate user-owned workstream; do
   not spend sprint implementation time on it or gate Day 1 on it.

Day 1 definition of done:

- authenticated Earth Engine Python smoke test;
- both city AOIs and 10 m grid metadata;
- fixed-window S2 and VNP previews;
- retained daily VNP design confirmed;
- the built-form primary, S2-only ablation, uniform null, and direct null;
- versioned corrected Gate 0 table and maps;
- written go/revise/stop decision for each proxy; and
- queued exports needed for Day 2.

### Day 2 — Fork-form operator, tests, and COG artifacts

1. Implement the Fork-form locally normalized radiance-allocation operator as
   pure array/raster functions independent of Earth Engine.
2. Add the circular reference, actual native VNP footprint as a major
   sensitivity, and named Gaussian sensitivity kernels.
3. Add epsilon, valid-support, boundary, and nonnegativity diagnostics.
4. Write focused unit tests and synthetic fixtures for Gate 1, including the
   bright-land/adjacent-water coastline fixture and all water variants.
5. Run the operator on small cutouts, then both city extents.
6. Export georeferenced 10 m Cloud-Optimized GeoTIFFs and machine-readable
   metadata.
7. Write operator-consistency, insufficient-support-radiance, and
   proxy-disagreement layers.

Day 2 definition of done:

- Gate 1 tests pass;
- all outputs identify city, interval, allocation proxy, kernel type, and kernel
  parameter;
- operator-consistency error is quantified and stronger agreement terminology
  is not asserted;
- water-variant differences and adjacent-land transfer are quantified;
- two-city reference outputs exist; and
- failures near masks, edges, and low denominators are visible as diagnostics.

Current Day 2 status (2026-07-29):

- [x] Pure-array Fork-form operator and distinct direct/uniform baselines.
- [x] Circular reference, exact-overlap native-footprint implementation, and
      explicitly named Gaussian FWHM sensitivities.
- [x] Full-support, boundary, denominator, negative-value, and
      operator-consistency diagnostics.
- [x] All six water variants, with water prevented from changing the VIIRS
      radiance input.
- [x] Deterministic synthetic coastline Gate 1 run, figures, arrays, summaries,
      and diagnostic COGs.
- [x] Unit and integration tests for kernels, operator behavior, water
      variants, grid locking, bundle auditing, and COG export.
- [x] Exact Earth Engine export graph and manifest contract for each expanded
      5200-by-5200 city grid.
- [x] Submit the v1 Earth Engine tasks to the configured private Drive folder.
      Account-specific task and folder identifiers are removed from the public
      repository. Delhi v1 is quarantined because it reopened at 5201-by-5201.
- [x] Diagnose native Manhattan corrected-radiance coverage, preserve strict
      QA as the then-current validation authority, and implement broad-QA plus 7/30/90-day
      gap-filled and retrieval-age diagnostics in versioned v2.
- [x] Prepare and live-validate the v2 Earth Engine graph with unique Drive
      filenames and the deterministic export-edge guard.
- [x] Submit and complete the revised v2 payloads in Drive. Account-specific
      task identifiers are removed from the public repository.
- [x] Download the versioned v2 bundles to `drafts/`, validate their CRS,
      5200-by-5200 shape, transform, band order, and COG layout, and generate
      the two-city source and VNP diagnostic galleries.
- [x] Build both 10 m Overture structure bundles under
      `OVERTURE-RASTER-001`, record source/output checksums and building/road
      metrics, and generate the two-city structural galleries.
- [x] Place each Earth Engine output at the expected local path and pass the
      exact two-city `day2_input_audit.json`; all four source bundles are valid.
- [x] Preserve the accepted six-panel input/method gallery as
      `docs/figures/psf-disaggregation/method-input-galleries-v1/` with source
      and snapshot checksums for the research note and blog.
- [x] Run the preregistered, radiance-blind 1 m building and 0.5 m road
      rasterization checks on dense, sparse, and water-adjacent 1 km cutouts
      in both cities. Retain the 2 m building and 1 m road primary: sampled
      building-area changes were at most 0.67% and road-layer correlations
      were at least 0.9979; visual differences were confined to footprint and
      centerline edges. The result is retained in this experiment record; its
      standalone ignored working directory is not part of the final v2 package.
- [x] Run six radiance-blind empirical cutouts with the direct and uniform
      nulls, both proxy families, all six circular-reference water variants,
      all declared Gaussian sensitivities, actual projected native-cell
      overlaps, and the targeted New York broad-QA configuration. Preserve the
      129-row metrics matrix, compressed arrays, 66 georeferenced COGs, and
      local inspection gallery.
- [x] Complete the user visual audit with no obvious anomaly and preserve the
      accepted empirical gallery, numerical summaries, and checksums under
      `docs/figures/psf-disaggregation/empirical-cutout-galleries-v1/`.
- [x] Run both strict-QA full-city extents with every declared
      operator/proxy/water sensitivity and the single targeted New York
      broad-QA reference configuration.
- [x] Resume this item on the higher-memory Linux server using the temporary
      Linux handoff instructions; complete the 23/22 matrices and checksum-valid
      artifact manifest. The temporary handoff file is not part of final v2
      documentation.
- [x] Complete Gate 1 with real-data results and inspect the two-city COGs;
      no visual issue was found, and the waterfront-boundary concern is carried
      explicitly into Gate 2.

### Day 3 — validation and figures

1. Run the full factorial water-handling and shoreline-sensitivity test using a
   separately declared current/reference water layer and preregistered
   shoreline-distance bands.
2. Run leakage-safe spatial held-out folds against neighbors-only interpolation.
3. Run the daily observation-condition propagation audit.
4. Produce kernel/proxy sensitivity tables.
5. Generate publication-ready figures:
   - direct versus disaggregated coastal/river maps;
   - allocated-water-radiance comparison;
   - held-out performance by method;
   - kernel sensitivity curve; and
   - insufficient-support-radiance/failure map.
6. Decide whether the result supports a positive claim, a bounded-method claim,
   or a useful negative result.

Current Day 3 status (2026-07-30):

- [x] Close Gate 1 and freeze its 23/22 full-city artifact manifest as the
      input authority for Gate 2.
- [x] Implement and test common shoreline-distance and matched inland
      low-proxy boundary metrics using the preregistered 0–100 m, 100–500 m,
      500–1500 m, and greater-than-1500 m bands.
- [x] Add a Gate 2 readiness audit that rejects missing provenance, grid
      mismatches, the internal JRC prior mislabeled as independent validation,
      and the old 2021 preview granules substituted for the 2024 daily stack.
- [x] Acquire and prepare a separately documented current/reference water mask
      for both cities at
      `outputs/psf_disaggregation/inputs/gate2_water_reference/<city>/`.
      The pinned Overture `2026-06-17.0` areal-water features are independent
      of the JRC prior but primarily OSM-derived; line-only waterways are not
      buffered and pools/wastewater are excluded.
- [x] Run the saved-output shoreline and matched inland low-proxy boundary
      factorial after both reference masks passed the readiness audit.
- [x] Add mutually exclusive mapped waterfront-infrastructure strata (pier or
      quay, bridge, building, road, and ordinary shoreline) over mapped water
      and adjacent 0–100 m land, plus two-city difference-map panels for every
      registered water variant versus its matching no-water result.
- [x] Run a fixed native-cell held-out preflight with five spatial-block
      folds, a 500 m training buffer, and a common neighbors-only baseline.
      New York improves under both coarse structural analogues; Delhi built
      form is mixed and Delhi S2-only is worse. Retain this as screening, not
      the final fine-grid fold result. Because a nearby VNP observation may
      contain PSF-mediated signal from the target support, do not describe the
      500 m run as physically leakage-safe or use it for a headline claim.
- [x] Run five physics-buffered native-cell folds under `HELDOUT-001` using a
      2550 m primary exclusion and 1500 m/2000 m sensitivities, identical
      eligible neighbors, radiance-decile and gain strata, and
      sample-composition reporting. All targets retained twelve neighbors.
      Built form improves MAE/RMSE in both cities and MAE in 5/5 folds per
      city; Delhi S2-only remains worse overall.
- [ ] Optional stronger extension: remove held-out radiance before fine-grid
      reprojection/convolution, produce the allocation, and reaggregate to
      exact native polygons. The completed native-cell gain test is explicitly
      a coarse operator analogue and does not satisfy this stronger claim.
- [x] Build the retained strict-QA 100-day VNP stack at
      `outputs/psf_disaggregation/inputs/gate2_daily_vnp/<city>/`; do not use
      the unrelated 2021 preview cache. Retain it on a compact 100-by-100,
      500 m projected grid aligned to the analysis origin/extent rather than
      duplicating native-scale values over a 5000-by-5000 fine grid. Each city
      has 100 strict-radiance bands and six date-matched condition stacks.
      Dates, QA metadata, CRS, transform, band descriptions, COG layout, and
      hashes pass the Gate 2 audit.
- [x] Run observation-condition propagation from the audited daily package
      as a 500 m daily coarse-operator audit on identical complete-support
      observations. Built form differs from uniform condition R² by less than
      0.00004 in both cities and has slightly lower within-cell temporal
      variability, satisfying the bounded non-amplification rule. Attribute
      reductions from direct to smoothing, not condition correction.
      Lunar irradiance, cloud detection, and cloud-mask quality vary within
      strict-QA support. MQF, snow, and retrieval age are constant on retained
      pixels by construction and must be reported as contract checks rather
      than presented as estimable within-strict-sample effects.
- [x] Generate reproducible full-city configuration, kernel, proxy, and
      internal-water-prior sensitivity tables plus the kernel curve from the
      frozen 45-configuration manifest. These quantify reconstruction
      consistency and allocation perturbation; they are not independent
      validation.
- [x] Generate the held-out preflight residual maps.
- [x] Generate the consolidated Day 3 evidence figure, headline table,
      checksummed artifact index, and version-matched Gate 0 figures.
- [ ] Optionally join a calibrated, aligned SDGSAT-1 scene as an independent
      high-resolution benchmark without making availability a Gate 2 blocker.
- [ ] Deferred, non-gating: complete the checkpointed 2024-03-01 OSM-attic
      extraction, rasterize it with the unchanged structural formula, and
      compare its component and combined proxies with contemporary Overture.
      Interpret this only as a combined source-coverage/vintage sensitivity.

The held-out preflight residual signs appear broadly balanced at city scale,
with no obvious large-scale gradient or seam and only small overall signed
bias. This is not evidence that residuals are spatially independent. Local
conditioning by roads, waterways, development edges, suburban patchiness, and
radiance decile remains plausible. Deeper residual-autocorrelation and
structure-attribution analysis is documented as future work rather than added
to the demo sprint.

The same preflight contains two results that must remain visible without
driving post-result proxy selection. First, allocation-gain error change is
monotone in the same direction across all four city×proxy combinations:
structural downweighting below gain 0.8 substantially reduces MAE, whereas
upweighting at or above 1.25 increases it. Second, in New York the S2-only
ablation has lower overall MAE (14.137 versus 14.889) and RMSE (24.483 versus
26.479) than built form and improves fold MAE in 5/5 folds versus 4/5. Built
form remains the reporting primary because switching proxies based on
held-out performance would violate `PROXY-001`; the tension is evidence to
report, not a tuning instruction.

The strict-v1 `HELDOUT-001` physics-buffered run confirms the substantive pattern at
the 2550 m primary distance. New York built form reduces MAE from 19.701 to
16.995 and RMSE from 31.920 to 29.823; New York S2-only reduces them to 16.643
and 28.963. Delhi built form reduces MAE from 13.728 to 12.270 and RMSE from
19.960 to 18.925, while Delhi S2-only worsens them to 13.840 and 20.532. Built
form improves MAE in all five folds in both cities; S2-only does so in all five
New York folds but only two Delhi folds. The preregistered gain asymmetry also
persists in all four comparisons. These results support a bounded structural
allocation claim, not validation of the fine-grid radiance field.

The coverage-complete broad-QA rerun uses the identical cell cohort, folds,
neighbors, and buffers. New York built form reduces MAE from 18.717 to 16.100
and RMSE from 30.433 to 28.199; Delhi built form reduces MAE from 13.493 to
12.147 and RMSE from 19.615 to 18.660. Fold MAE improves in 5/5 New York and
4/5 Delhi folds; the adverse Delhi fold changes MAE by only +0.044. S2-only
remains favorable in New York and negative overall in Delhi. Low-gain benefit
and high-gain harm persist in all four comparisons.

The external mapped-water factorial gives a bounded, proxy-dependent version
of the waterfront concern. Relative to no water prior, New York S2-only
combined-soft reduces mapped-water allocation by 3.406 radiance units per
water pixel on average and increases allocation within 100 m on adjacent land
by 2.651. Delhi shows the same direction at smaller magnitude (-2.687 and
+0.364). The built-form primary does not show the same pattern: New York
mapped-water allocation increases slightly (+0.066) while adjacent land falls
(-0.469), and Delhi changes are near zero. Corresponding inland low-proxy
controls are much smaller and do not reproduce a uniform water-like response.
This supports documenting a proxy-dependent shoreline redistribution risk; it
does not establish that lower allocation over mapped water is more accurate.
The reference is independent of JRC but shares OpenStreetMap provenance with
parts of the built-form ecosystem, so it is not fully source-independent of
that proxy.

The infrastructure strata sharpen that interpretation. For New York
combined-soft built form, the largest mean reductions over mapped water occur
at mapped buildings (-85.67), roads (-38.25), bridges (-33.26), and piers or
quays (-9.98), while ordinary mapped-water pixels increase slightly (+0.26).
For S2-only, mapped-water reductions occur across every stratum, including
ordinary shoreline (-3.26), while adjacent buildings, roads, bridges, and
ordinary shoreline increase. Delhi contains almost no mapped pier/quay sample
in this support, so that stratum is reported but must not be interpreted.
These strata describe where the registered prior reallocates the saved output;
they still cannot determine whether the displaced radiance originated on
water, at waterfront infrastructure, or on adjacent land.

Accordingly, the final spatial-reporting primary is now the coverage-complete
broad-QA, circular-reference structural allocation with **no water prior**. This
preserves corrected VNP as radiometric authority while avoiding dilation of
the strict ten-observation support mask. The immutable strict v1 remains the
Gate 0 cohort authority, the daily-condition authority, and the
conservative-quality spatial sensitivity. The final native-cell held-out
result is the broad-QA v3 rerun on that frozen cohort. The choice also
avoids imposing a water-specific origin assumption that Gate 2 cannot
validate. Broad direct upsample and uniform normalized convolution remain
required baselines. Combined-soft and every other water-weighted output remain
visible as sensitivity analyses and negative controls. The frozen
configuration and original manifests continue to identify combined-soft as
the preregistered primary; they are not rewritten.

The completed full-city sensitivity summary shows the expected support/error
tradeoff as Gaussian FWHM increases: from 750 m to 1500 m, consistency MAE
rises from 6.29 to 10.21 in New York and 4.47 to 7.31 in Delhi for built form,
while valid-output fraction falls from 0.952 to 0.809 and 0.978 to 0.880,
respectively. S2-only has lower circular-reference consistency MAE in both
cities, but loses substantially more valid support in New York. These are
operator diagnostics, not evidence that S2-only predicts true fine-scale
radiance better.

Day 3 definition of done:

- all three validation suites run reproducibly;
- no water-handling choice is selected from the allocated-water-radiance metric
  alone;
- no target-fold leakage within the completed native-cell held-out diagnostic;
- failure modes are mapped and quantified;
- every headline figure includes the direct and uniform baselines; and
- the claim is chosen from the evidence rather than fixed in advance.

Day 3 first closed on 2026-07-30 as a **bounded method result with useful
negative findings**. That strict-v1 machine-readable classification and summary
figure remain under
`outputs/psf_disaggregation/validation/gate2/closeout/v1_bounded_method_closeout/`;
the final broad-QA analytical closeout is under
`outputs/psf_disaggregation/validation/gate2/closeout/v2_broad_qa_reporting/`.
The writing-oriented synthesis is `docs/psf-disaggregation-results.md`.

### Day 4 — reproducible note and public narrative

The sprint produced two complementary artifacts:

1. **Research note** — method, data contract, operator, validation, results,
   limitations, exact reproduction commands, and artifact manifest.
2. **Public narrative** — problem, visual result, why local normalization is not
   correctness, and what failed or worked, published as the detailed notebook and
   accompanying blog post.

Title and frame the work as a cross-quantity adaptation with named failure
modes. “Fork-form” describes the equation and provenance, not equivalent data
semantics. Avoid calling the output “radiometrically calibrated 10 m NTL,”
“super-resolved truth,” “canonical radiance,” or a recovered physical PSF.

The analytical Day 4 definition of done was:

- a clean-run command sequence is documented;
- figures and tables are generated from saved artifacts;
- data/product citations and licenses are included;
- limitations include cross-quantity proxy error, non-identifiability, and
  structural-allocation bias;
- no credentials or private imagery are committed; and
- the research note, notebook, and blog make compatible, evidence-bounded claims.

## Final v2 repository anchors

```text
configs/psf_disaggregation.yaml
src/nocturne/disaggregate/
  operator.py              # locally normalized allocation and diagnostics
  full_city.py             # strict-v1 resumable tiled executor
  broad_reporting.py       # final broad-QA v2 reporting matrix
  broad_reporting_audit.py # coverage, COG, selection, and regional audit
  heldout.py               # strict-v2 and broad-v3 physics-buffered validation
  observation_conditions.py # strict daily coarse-operator audit
  fine_grid_gain.py        # proxy-only trust-indicator COGs
  v2_closeout.py           # final evidence classification and review
tests/disaggregate/
outputs/psf_disaggregation/
  manifests/
  rasters/
  validation/
artifacts/outputs/psf_disaggregation/  # compact Git-versioned evidence subset
docs/psf-disaggregation-results.md
docs/psf-disaggregation-status.md
docs/psf-disaggregation-decisions.md
notebooks/psf_disaggregation_writeup.ipynb
```

Large rasters and authenticated export state remain outside Git. Commit
configuration, code, small summary tables, figures appropriate for the repo, and
artifact manifests/checksums. Source licenses, retrieval constraints, and the
terms for redistributed compact artifacts are recorded in
`docs/data-licenses.md`. Users ingest source rasters and generate and retain large
product rasters locally under `outputs/`; the project does not publish them to
GitHub or maintain an external raster archive.

The research-note evidence synthesis is `docs/psf-disaggregation-results.md`.
The detailed public narrative is `notebooks/psf_disaggregation_writeup.ipynb`,
and the accompanying blog is
<https://daynan.com/at-the-edge/measuring-lights-at-night/>. Remaining repository
release tasks are tracked separately in `docs/publication-checklist.md`.

## Named failure modes

- **Cross-quantity proxy error:** daytime reflectance and mapped structure are
  not measurements of nighttime radiance.
- **Structural proxy error:** built form is only a constraint on where lighting
  can occur, not the observed radiance magnitude.
- **Dark but built / bright but unmapped:** the proxy misses operating patterns,
  temporary lights, ports, vehicles, and directional radiance patterns.
- **Kernel misspecification:** a circular stationary kernel is not the effective
  scan- and processing-dependent VIIRS response.
- **Coregistration error:** small spatial offsets become apparent at 10 m.
- **Temporal mismatch:** static structural inputs and the S2 composite cannot
  represent daily lighting change; the primary 2026 Overture structure also
  postdates the 2024 radiance window.
- **Historical-source confounding:** comparing a 2024 OSM-only snapshot with
  contemporary multi-source Overture mixes temporal change with differences in
  source coverage and conflation.
- **Denominator instability:** weak proxy support can create extreme ratios.
- **Boundary and mask leakage:** convolution near water, clouds, or AOI edges can
  violate the intended invariant.
- **Native retrieval-coverage bias:** corrected VNP availability and its coarse
  background class can remove important bright urban cells before Nocturne
  processing.
- **Gap-fill pseudoreplication:** carried-forward daily values can make temporal
  coverage appear larger than the number of independent high-quality
  retrievals.
- **Export-edge rounding:** numerical region boundaries can select a spurious
  row or column unless the reopened raster is checked against the exact grid.
- **Validation circularity:** low operator-consistency error is a construction
  diagnostic and is not independent evidence of the fine-scale pattern.
- **Water-test gaming:** excluding water improves the metric even if land
  allocation remains wrong.
- **Non-identifiability:** infinitely many high-resolution fields can agree with
  one coarse observation.

## Immediate Day 1 checklist

- [x] Create/register a Google Cloud project for Earth Engine.
- [x] Authenticate the Earth Engine Python API and run a one-pixel smoke test.
- [x] Confirm Google Drive as the initial export target and choose a folder.
- [x] Add `configs/psf_disaggregation.yaml`.
- [x] Add the `nocturne.disaggregate` package skeleton.
- [x] Define exact 50 km UTM squares and explicit resampling contracts.
- [x] Implement strict and broad VNP quality contracts.
- [x] Implement common-support S2 compositing with explicit reprojection and
      same-datatake MGRS mosaicking.
- [x] Decode VNP quality fields.
- [x] Preserve and label the original Gate 0 as exploratory v0.
- [x] Implement halo-safe chunk aggregation and native VNP polygons/areas.
- [x] Replace centroid/nominal-area Gate 0 built aggregation with exact
      geometry intersections and common cross-city scaling.
- [x] Refresh pinned Overture inputs to the exact square plus source halo.
- [x] Regenerate the catalog smoke test, corrected local Gate 0 gallery, and
      interactive Earth Engine inspector under the integrity-v3 contract.
- [x] Run support-aware Gate 0 v3 for both proxies, visually inspect it, and
      re-freeze the declared formulas without target-driven tuning.
- [x] Implement the direct and uniform nulls with the Day 2 operator.
- [x] Queue and preserve the v1 Earth Engine source-layer exports.
- [x] Submit and complete the v2 VNP-coverage/grid-corrected exports after
      explicit approval. The private execution record contained task IDs; the
      public manifest retains product metadata with those IDs redacted.
- [x] Exclude SDGSAT preparation from the sprint implementation; it is a
      separate user-owned workstream and remains non-gating.
- [x] Update the draft Draw.io/Miro sources to integrity-v3 terminology and
      remove SDGSAT from the sprint layer.
- [x] Create polished SVG and high-resolution PNG representations for manual
      placement on the existing Miro board.
- [ ] User: add the SVG (preferred) or PNG to the existing Miro board.
- [ ] Optional: import the native-shape version and save the item-ID manifest
      if Miro API authorization is configured later.
- [ ] Deferred, non-gating: resume the checkpointed 2024-03-01 OSM structural
      sensitivity and compare it with the contemporary Overture proxy;
      preserve its source-coverage confounding in every interpretation.
