# PSF disaggregation sprint results

Last updated: 2026-08-07

## Final evidence classification

**Bounded method result with useful negative findings.**

The sprint demonstrates a reproducible and inspectable way to allocate coarse
corrected VNP46A2 radiance using fine structural proxies while preserving the
coarse observation as radiometric authority. It does not recover observed or
calibrated 10 m nighttime radiance, physical emissions, or the VIIRS
point-spread function.

The final demonstration reporting primary is:

- coverage-complete broad-QA corrected VNP46A2 median;
- built-form structural proxy;
- no water prior;
- circular-mean reference kernel; and
- direct upsample plus uniform normalized convolution as mandatory baselines.

The strict-QA v1 products remain immutable conservative quality sensitivities.
Strict QA remains the authority for the frozen Gate 0 cohort and the completed
daily-condition audit; the final held-out result was rerun with broad-QA
radiance on that identical cohort. Broad QA is selected for the displayed
spatial product because all pixels have at least five retained observations and
the strict input's 0.117% New York support mask dilates to 0.710% under
complete-kernel support. This is a coverage decision, not performance-based
retuning. Broad QA admits MQF 1 and lower cloud-mask quality, so completeness
does not imply equal quality at every pixel.

No water prior is a post–Gate 2 reporting decision, not the preregistered water
primary. All water-weighted outputs remain visible sensitivities.

## Experiment objective, controls, and outcome

**Objective.** Test whether a static 10 m structural proxy can allocate coarse
corrected VNP46A2 radiance more plausibly than declared null allocations while
preserving VNP46A2 as the only radiometric authority.

**Primary comparison.** On the frozen native-cell Gate 0 cohort, compare the
frozen structural-gain predictor with neighbors-only inverse-distance-squared
interpolation under a 2550 m four-sigma PSF-support exclusion. The 1500 m and
2000 m rows are distance sensitivities, not exchangeable replicate samples.

**Spatial controls.** Direct upsampling and uniform normalized convolution are
mandatory nulls; S2-only is a proxy ablation; strict QA is a conservative
radiance sensitivity; water variants and matched inland low-proxy areas test
allocation assumptions. The daily strict-QA analysis checks condition
amplification relative to uniform smoothing.

**Outcome.** The evidence supports a reproducible, bounded structural-allocation
method result. It does not independently validate the fine-grid values or show
that structural upweighting recovers true lighting magnitude.

## Demonstrated findings

### Physics-buffered held-out cells

At the preregistered 2550 m primary buffer:

| City | Proxy | Neighbor MAE | Structural MAE | Neighbor RMSE | Structural RMSE | Improved folds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| New York | Built form | 18.717 | 16.100 | 30.433 | 28.199 | 5/5 |
| New York | S2 only | 18.717 | 15.787 | 30.433 | 27.539 | 5/5 |
| Delhi | Built form | 13.493 | 12.147 | 19.615 | 18.660 | 4/5 |
| Delhi | S2 only | 13.493 | 13.655 | 19.615 | 20.256 | 2/5 |

These are the broad-QA rerun results on the identical frozen native-cell
cohort. Built form improves overall error and rank association in both cities.
It improves MAE in all five New York folds and four Delhi folds; the adverse
Delhi fold differs by only +0.044 radiance units. New York
S2-only has lower MAE/RMSE than built form, but Delhi S2-only is negative.
Built form remains primary because changing proxy choice from held-out results
would violate the frozen no-retuning rule.

The native-cell test uses the same eligible neighbors for both methods and
retains all targets at 1500, 2000, and 2550 m. It is a coarse structural-gain
analogue, not the stronger optional remove-before-fine-grid-convolution test.

### Allocation-gain asymmetry

Mean structural-minus-neighbor absolute-error change at 2550 m:

| City | Proxy | Gain <0.8 | Gain 0.8–1.25 | Gain ≥1.25 |
| --- | --- | ---: | ---: | ---: |
| New York | Built form | -10.253 | -0.169 | +2.127 |
| New York | S2 only | -10.941 | -0.275 | +0.501 |
| Delhi | Built form | -5.956 | +0.459 | +2.113 |
| Delhi | S2 only | -3.482 | +0.730 | +3.407 |

The proxy-only gain diagnostic confirms a measured limitation: structural
downweighting helps, whereas strong upweighting hurts in all four comparisons.
Built form constrains where light can occur but does not measure its magnitude.

The exact fine-grid analogue,
`rho(x) / max((k tensor rho)(x), denominator_epsilon)`, is now delivered as a
radiance-blind companion COG beside each reporting-primary raster; `rho` here
is the normalized structural proxy `h` used in the method overview. Band 1 is
continuous gain. Band 2 is the validated warning stratum: 1 for gain below
0.8, 2 for 0.8 to below 1.25, and 3 for gain at or above 1.25. The coarse
held-out result supports these as interpretable warning ranges, but does not
calibrate pixel-level error probabilities.

### Water and waterfronts

Water weighting causes material, proxy-dependent redistribution near mapped
shorelines. The S2-only combined-soft variant moves radiance from mapped water
toward adjacent land in both cities; built form does not reproduce that pattern
uniformly. Mapped infrastructure strata show especially large changes around
buildings, roads, bridges, and piers/quays, but cannot identify the true origin
of waterfront radiance.

No independent nighttime reference establishes that this redistribution is
more accurate. The simpler no-water-prior variant is therefore the reporting
primary. This does not disprove water weighting.

### Day 4 water-versus-inland direct-radiance ratio

The no-water reporting allocations were compared with the direct-radiance
baseline over mapped water and the existing radiance-blind matched inland
low-proxy control. The metric is the ratio of regional allocated-radiance sum
to positive direct-radiance sum on common finite support; reduction is one
minus that ratio.

| City | Proxy | Water reduction | Inland reduction | Water minus inland |
| --- | --- | ---: | ---: | ---: |
| New York | Built form | 39.3% | 81.0% | -41.7 pp |
| New York | S2 only | 6.8% | 68.6% | -61.7 pp |
| Delhi | Built form | 52.8% | 55.2% | -2.4 pp |
| Delhi | S2 only | -19.0% | 70.5% | -89.5 pp |

Water does not show the larger reduction in either city or proxy. For the
reporting-primary built-form proxy, the inland reduction is much larger in New
York and similar but slightly larger in Delhi. This supports the more general
description that structural allocation relocates radiance away from low-proxy
regions; the observed effect is not water-specific in this comparison.

The control is not a distribution-matched counterfactual. It selects the
lowest proxy-valued inland pixels more than 1500 m from mapped water, targets
the mapped-water pixel count, and caps selection at 10% of eligible inland
support. Thus the result is descriptive and cannot establish that allocation
over mapped water—or inland—is independently more accurate.

### Observation-condition propagation

The 100-day strict-QA stack contains exactly the locked dates and passes its
grid, band, metadata, and checksum audit. In the daily 500 m operator audit,
built form changes lunar/cloud R² by less than 0.00004 relative to uniform and
has slightly lower temporal variability:

| City | Direct | Uniform | Built form |
| --- | ---: | ---: | ---: |
| New York | 0.24790 | 0.17602 | 0.17548 |
| Delhi | 0.22212 | 0.16119 | 0.16023 |

This passes the bounded non-amplification rule. Reductions from direct are
smoothing, not observation-condition correction. Mean complete daily kernel
support is only 0.263 in New York and 0.529 in Delhi, making strict daily
coverage the larger limitation.

### Coverage-complete reporting refresh

All broad direct, uniform, and built-form/no-water COGs have complete 25
million-pixel support in both cities and zero invalid radiance neighborhoods.
On strict/broad common support, radiance correlations are 0.99746 in New York
and 0.99928 in Delhi. Broad QA fills 29,269 New York pixels and no Delhi pixels.

The built-form allocated/direct water-minus-inland reduction remains negative:
-41.4 percentage points in New York and -2.4 points in Delhi, preserving the
Day 4 conclusion that the effect is general low-proxy reallocation rather than
water-specific. The strict daily observation-condition audit is retained as a
conservative sensitivity; no broad daily stack is fabricated from the
composite.

The New York S2-only/no-water ablation was also regenerated under broad QA.
Its radiance-neighborhood gaps fall from 177,594 to zero. Its remaining
1,209,492 invalid pixels are the unchanged S2 proxy-neighborhood support mask,
not missing VNP radiance, so the ablation must not be described as spatially
complete in the same sense as built form. Delhi's displayed S2-only ablation
remains the strict-v1 raster. Consequently, the New York and Delhi S2 maps do
not share a radiance contract and must not be used as a like-for-like cross-city
spatial comparison. The broad-QA held-out S2 table above is comparable across
cities because it was rerun from the same broad radiance contract and frozen
cohort.

### Kernel and reconstruction diagnostics

Wider Gaussian kernels produce worse operator-consistency error and narrower
valid interiors. For built form, MAE increases from 6.29 to 10.21 in New York
and from 4.47 to 7.31 in Delhi between 750 and 1500 m FWHM. Valid-output
fractions fall from 0.952 to 0.809 and from 0.978 to 0.880. These are internal
operator diagnostics, not identification of the true sensor response.

## Limitations

- The fine grid is a structural allocation of coarse VNP46A2 radiance, not an
  observed, calibrated, or independently validated 10 m nighttime-light
  measurement.
- The held-out comparison validates a coarse structural-gain analogue. It does
  not validate the exact fine-grid allocation or identify a physical VIIRS PSF.
- Structural gain is asymmetric: downweighting generally helps, while strong
  upweighting hurts. Built form constrains plausible locations but does not
  measure lighting magnitude.
- The water-versus-inland analysis is descriptive. Its low-proxy inland control
  is not a distribution-matched counterfactual, and no independent nighttime
  reference validates waterfront allocation.
- Broad QA closes the reporting-primary VNP coverage gaps by admitting lower
  quality observations. The New York S2-only ablation retains a separate proxy
  support mask, and the displayed Delhi S2-only raster remains strict-v1.
- Strict daily complete-kernel support is limited, especially in New York, and
  reductions in lunar/cloud association relative to direct upsampling reflect
  smoothing rather than causal correction.
- The two-city demonstration does not establish geographic generality. The
  reporting built-form source is also temporally mismatched with 2024 radiance,
  because the reproducible Overture release postdates the observation window.

## Supported claims

- The workflow reproducibly generates fine-grid structural allocations and
  exposes support, denominator, boundary, and reconstruction diagnostics.
- Physics-buffered native-cell evidence supports built form over
  neighbors-only interpolation in both demonstration cities.
- The frozen built-form gain does not materially amplify the tested daily
  observation-condition associations beyond uniform smoothing.
- Water handling is a consequential allocation assumption that must remain
  visible as sensitivity analysis.

## Unsupported claims

- observed, calibrated, or true 10 m nighttime radiance;
- recovered emissions or conserved physical flux;
- recovered VIIRS PSF;
- validated water correction;
- causal correction of lunar/cloud effects; or
- independent fine-scale accuracy without a calibrated high-resolution
  nighttime reference.

## Deferred work

- calibrated and aligned SDGSAT-1 comparison, if suitable data become
  available;
- remove-before-fine-grid-convolution held-out evaluation;
- historical OSM versus Overture sensitivity, whose preserved checkpoints are
  confounded by source coverage; and
- deeper spatial residual attribution and autocorrelation.

## Review artifacts

- [Historical strict-v1 Day 3 summary and classification](../artifacts/outputs/psf_disaggregation/validation/gate2/closeout/v1_bounded_method_closeout/)
- [Historical strict-v1 physics-buffered held-out review](../artifacts/outputs/psf_disaggregation/validation/gate2/heldout/v2_physics_buffered_native_cell/review.md)
- [Final broad-QA physics-buffered held-out manifest](../artifacts/outputs/psf_disaggregation/validation/gate2/heldout/v3_physics_buffered_native_cell_broad_qa/manifest.json)
- [Observation-condition review](../artifacts/outputs/psf_disaggregation/validation/gate2/observation_conditions/v1_daily_coarse_operator/review.md)
- [Waterfront analysis](../artifacts/outputs/psf_disaggregation/validation/gate2/shoreline/v1_overture_mapped_water/)
- [Day 4 water-versus-inland ratio](../artifacts/outputs/psf_disaggregation/validation/gate2/day4_allocated_direct_ratio/v1_existing_matched_inland_control/)
- [Version-matched Gate 0 figure manifest](../artifacts/outputs/psf_disaggregation/validation/gate0/v3_qa_grid_halo_datatake_support/gate0_figure_regeneration.json)
- [Historical strict-v1 water selection](../artifacts/outputs/psf_disaggregation/validation/gate2/primary_selection/v1_post_gate2/selection.json)
- [Broad-QA reporting selection](../artifacts/outputs/psf_disaggregation/validation/gate2/primary_selection/v2_broad_qa_reporting/selection.json)
- [Broad-QA product audit](../artifacts/outputs/psf_disaggregation/validation/gate2/broad_reporting/v1_coverage_and_water_inland/manifest.json)
- [Broad-QA v2 closeout](../artifacts/outputs/psf_disaggregation/validation/gate2/closeout/v2_broad_qa_reporting/review.md)
- [Fine-grid gain manifest](../artifacts/outputs/psf_disaggregation/validation/gate2/fine_grid_gain/v1_reporting_primary/manifest.json)
