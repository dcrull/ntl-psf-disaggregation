# PSF disaggregation review hub

Last updated: 2026-08-07 — standalone-repository cleanup complete

This page is the short entry point for continuous review and eventual writing.
The full experiment contract is in `psf-disaggregation.md`; the authoritative
assumption and choice history is in `psf-disaggregation-decisions.md`.
Machine-readable manifests and tables remain authoritative for numerical
results.

In the standalone repository, compact evidence is stored below
`artifacts/outputs/psf_disaggregation/`. Paths beginning with
`outputs/psf_disaggregation/` denote the complete external runtime artifact tree,
including the large rasters intentionally omitted from Git.

## Current position

The two-city demonstration has completed Days 1–3, Gate 1, the principal
Gate 2 validation suites, the full-city sensitivity summary, and publication
packaging through analytical closeout. Gate 1 and the Day 3 analytical phase
are closed. The post–Gate 2 reporting primary is now the coverage-complete
broad-QA, circular-reference built-form allocation with **no water prior**.
Broad direct upsampling and
uniform normalized convolution remain required baselines. The strict v1
products are immutable conservative quality sensitivities, and every
water-weighted result remains a sensitivity.

The broad reporting package is under
`outputs/psf_disaggregation/rasters/full_city/v2_broad_qa_reporting/`. The
three primary/baseline configurations in each city—six COGs total—have complete
support and zero invalid radiance neighborhoods. The New York S2-only v2
sensitivity also has zero radiance-neighborhood gaps; its remaining invalid
area is the unchanged S2 proxy-
support mask. The selection is coverage-driven: broad QA fills 29,269 New
York input pixels whose strict retained count was below ten, preventing their
dilation to 177,594 missing output pixels.

The broad-QA physics-buffered held-out rerun and compact v2 analytical
closeout are complete. Built form improves overall MAE/RMSE in both cities at
2550 m and preserves the gain asymmetry. It improves 5/5 New York folds and
4/5 Delhi folds; the lone adverse Delhi fold changes MAE by +0.044. The v2
closeout is under
`outputs/psf_disaggregation/validation/gate2/closeout/v2_broad_qa_reporting/`.

This choice is deliberately conservative. The source VNP observation remains
the radiometric authority, while mapped structure only allocates that
coarse-scale observation. The analysis does not identify the true 10 m origin
of light and must not be described as super-resolved truth or calibrated 10 m
nighttime radiance.

## Publication and packaging status

The analytical sprint and Day 4 evidence synthesis are complete. The consolidated
results are in `psf-disaggregation-results.md`; the detailed narrative notebook is
`../notebooks/psf_disaggregation_writeup.ipynb`; and the public blog is
<https://daynan.com/at-the-edge/measuring-lights-at-night/>. The final compact
machine-readable classification and review are under
`../artifacts/outputs/psf_disaggregation/validation/gate2/closeout/v2_broad_qa_reporting/`.
The v1 closeout remains an explicitly historical strict-QA snapshot.

### Closeout flags

- The machine-readable v2 closeout still records final user presentation review
  of the two broad-QA built-form COGs as open. This does not block analytical
  closeout, but it should be explicitly accepted before public release.
- Data-license confirmation, citation metadata, and the local-only large-raster
  policy are complete. Fresh-clone reproduction remains on
  `publication-checklist.md`; source and derived-artifact terms are in
  `data-licenses.md`.
- Several superseded, ignored working-output directories are not retained in
  the compact v2 workspace. Their results are recorded in the overview and
  decision ledger, while the accepted galleries are checksummed under
  `docs/figures/psf-disaggregation/`.
- The standalone test, Ruff, notebook-hygiene, file-size, Markdown-link, and
  compact-artifact checksum checks are the repository closeout gates.

The additional allocated-versus-direct test is complete under
`outputs/psf_disaggregation/validation/gate2/day4_allocated_direct_ratio/`.
Mapped water does not have a larger reduction than the existing matched inland
low-proxy control in either city or proxy. This favors a general low-proxy
reallocation interpretation over a water-specific effect, subject to the
control-selection caveat documented in its manifest and interpretation file.

### Deferred historical structural-proxy comparison

A checkpointed extraction of OpenStreetMap attic data at
`2024-03-01T00:00:00Z` was started and then intentionally stopped to prioritize
the higher-value Day 3 validation suites. It retrieves
building-tagged ways/relations and highway-tagged ways over the same source
extent used by the primary analysis. Successful tiles are immutable
checkpoints, so a future run can resume without repeating them. New York
checkpoints are preserved; Delhi was not started.

Completion requires, for each city:

- `inputs/osm_2024_snapshot/<city>/manifest.json`;
- `buildings.parquet` and `segments.parquet`;
- an OSM structural bundle rasterized with the same 2 m building sampling,
  road weights, 70/30 mixture, and transformations as the primary proxy; and
- a proxy-comparison table and mapped current-minus-historical differences.

This comparison answers whether the structural allocation is sensitive to a
plausible 2024 OSM snapshot. It does **not** isolate time cleanly: the primary
uses contemporary Overture, whose building coverage includes sources beyond
OSM, while the historical layer is OSM-only. Report it as a combined
source-coverage and vintage sensitivity.

### Gate 2 completion and optional extensions

- [Completed] Run five native-cell folds with the PSF-derived 2550 m primary
  training exclusion and 1500 m/2000 m sensitivities, identical eligible
  neighbors, gain strata, and sample-composition reporting. All targets
  retained sufficient neighbors. In the final broad-QA rerun, built form
  improves overall MAE/RMSE in both cities and fold MAE in 5/5 New York and
  4/5 Delhi folds; Delhi S2-only remains negative overall. The strict-v1 run
  improved 5/5 folds in each city.
- [Optional stronger extension] Remove held-out radiance before fine-grid
  reprojection/convolution and reaggregate to exact native polygons. The
  completed physics-buffered run remains a coarse structural-gain analogue,
  not this stronger operator-level test.
- [Completed] Build and audit the retained strict-QA 100-day daily VNP stack.
  Both cities have compact aligned 500 m, 100-band radiance COGs and six
  date-matched condition COGs. The formal Gate 2 readiness audit passes.
- [Completed] Run observation-condition propagation from the audited daily
  stack. Built form adds less than 0.00004 condition R² relative to uniform and
  has slightly lower temporal variability; it passes the bounded
  non-amplification rule. Reductions from direct are labeled smoothing.
  Under strict QA, lunar irradiance, cloud detection, and cloud-mask quality vary;
  MQF, snow, and retrieval age are constant by construction and serve as
  contract evidence rather than usable within-sample strata.
- [Completed] Consolidate publication figures, headline metrics, source hashes,
  and the final machine-readable evidence classification.
- Optionally compare a calibrated and aligned SDGSAT-1 scene as an independent
  high-resolution reference; this remains non-gating.

## Accepted findings to carry into writing

1. The allocation operator is locally normalized, but reconstruction
   consistency is an internal diagnostic rather than independent validation.
2. Full-city signed residuals appear broadly balanced at city scale, but local
   structure-conditioned errors remain plausible and untested at sufficient
   depth for a general absence-of-bias claim.
3. Water weighting causes material, proxy-dependent redistribution near
   mapped shorelines. The analysis cannot establish that this movement is more
   accurate, so no water prior is the reporting primary.
4. Contemporary mapped structure is temporally mismatched with the 2024 VNP
   window. A historical OSM sensitivity could help bound that concern but was
   deferred because OSM-versus-Overture source coverage prevents a clean
   temporal comparison.
5. Wider kernels trade greater invalid edge/support area for worse
   reconstruction consistency in these runs; this does not identify the true
   sensor response.
6. Radiance-blind allocation-gain asymmetry persists under the primary 2550 m
   buffer in all four city×proxy combinations: downweighting below gain 0.8
   substantially reduces error, while upweighting at or above 1.25 increases
   it.
7. New York S2-only has lower final held-out MAE/RMSE than built form, while
   built form has higher rank association and is consistent across both
   cities. Built form remains primary because changing it from held-out
   results would be prohibited retuning; the tension must still be reported.
8. Gate 0 lacked an empirical monotonicity/bright-tail criterion. “Monotone”
   described proxy construction only. This is a recorded rule limitation for
   future screening.
9. The daily coarse-operator audit finds no material structural amplification
   of lunar/cloud associations or temporal variability beyond uniform
   smoothing. New York's low complete daily kernel support is the larger
   limitation.
10. The Day 4 allocated/direct regional-sum ratio does not show a larger
    reduction over mapped water than over the existing inland low-proxy
    control. The result is descriptive because that control is area-targeted
    and low-proxy-selected, not distribution-matched by proxy or urban context.
11. The reporting products now have versioned companion `trust_indicators.tif`
    COGs containing continuous fine-grid allocation gain and the three
    validated gain strata. Existing product COGs and hashes were not modified;
    coarse gain validation transfers interpretation, not pixel-error
    calibration.
12. Broad-QA primary and baseline reporting products have complete support in
    both cities. Strict v1 remains the Gate 0/daily-condition authority and
    conservative-quality spatial sensitivity; the final held-out result is the
    broad-v3 rerun on the frozen strict cohort. The broad switch is not evidence
    that MQF 1 equals MQF 0 in quality.
13. Only the New York S2 spatial ablation was regenerated under broad QA. The
    Delhi S2 map remains strict-v1, so those two displayed S2 maps are not a
    radiance-contract-matched cross-city comparison. The broad held-out S2
    comparison is matched across cities.

## Known artifact defect

Four PNGs under the v3 Gate 0 directory carried v0 metric annotations. The
differences were approximately 0.006 and do not change the proxy decisions,
but the original PNGs were not version-matched evidence. This defect is closed:
all four figures were regenerated from v3 samples and summaries, with source
and output hashes in `gate0_figure_regeneration.json`.

## Review order

For a fast audit, read in this order:

1. This status page.
2. `psf-disaggregation-results.md` for the final objective, controls, outcomes,
   and evidence boundaries.
3. `psf-disaggregation-decisions.md`, especially `VNP-COVERAGE-002`,
   `HELDOUT-BROAD-001`, `WATER-002`, and `FINE-GAIN-001`.
4. The Day 3 status and interpretation in `psf-disaggregation.md`.
5. The preserved method-input and empirical-cutout galleries under
   `docs/figures/psf-disaggregation/`.
6. Bundled machine-readable selection, sensitivity, and comparison evidence under
   `../artifacts/outputs/psf_disaggregation/validation/`.

## Writing guardrails

Use:

- “structural allocation”;
- “locally normalized disaggregation”;
- “operator-consistency” or “reconstruction-consistency error”;
- “reporting primary” and “sensitivity”; and
- “combined source/vintage sensitivity” for the historical OSM comparison.

Avoid:

- “10 m observed radiance”;
- “radiometrically calibrated 10 m NTL”;
- “recovered emissions”;
- “validated water correction”; and
- treating a lower reconstruction error as proof of more accurate fine-scale
  allocation.

## Artifact anchors

- Final reporting-primary selection:
  `artifacts/outputs/psf_disaggregation/validation/gate2/primary_selection/v2_broad_qa_reporting/selection.json`
- Final reporting COGs:
  `outputs/psf_disaggregation/rasters/full_city/v2_broad_qa_reporting/`
- Historical strict-v1 selection and full-city sensitivities:
  `artifacts/outputs/psf_disaggregation/validation/gate2/primary_selection/v1_post_gate2/selection.json`
  and `outputs/psf_disaggregation/rasters/full_city/v1_resumable_tiled/`
- Bundled Gate 2 validation evidence:
  `artifacts/outputs/psf_disaggregation/validation/gate2/`
- Historical OSM inputs:
  `outputs/psf_disaggregation/inputs/osm_2024_snapshot/`
- Historical comparison, when complete:
  `outputs/psf_disaggregation/validation/structural_vintage/v1_osm_2024/`
