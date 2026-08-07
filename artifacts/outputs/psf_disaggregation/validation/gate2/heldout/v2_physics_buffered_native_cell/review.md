# Gate 2 physics-buffered native-cell held-out review

Historical scope: this is the strict-QA v2 held-out result. The final held-out
evidence is the broad-QA v3 rerun on the identical frozen cohort, summarized in
`outputs/psf_disaggregation/validation/gate2/closeout/v2_broad_qa_reporting/review.md`.

Status: complete under `HELDOUT-001` as native-cell structural-gain
validation. This remains a coarse analogue of the fine-grid operator; it is not
the separate remove-before-convolution experiment.

## Design

Five deterministic spatial-block folds use twelve inverse-distance-squared
training neighbors within 10 km. Training-cell centers must be farther than
1500 m, 2000 m, or 2550 m from each target. The 2550 m primary is the
registered four-sigma support radius of the widest 1500 m-FWHM Gaussian.
Neighbors-only and structural predictions use identical eligible cells.

All targets retained twelve eligible neighbors at every buffer. The primary
median nearest-neighbor distance is 2554 m in New York and 2613 m in Delhi.
Because the buffer changes eligible neighbors rather than selecting a far-cell
target subset, target/block-interior composition is unchanged in this run.
Results across buffers nevertheless compare different training neighborhoods.

## Primary 2550 m results

| City | Proxy | Neighbor MAE | Structural MAE | Neighbor RMSE | Structural RMSE | Neighbor Spearman | Structural Spearman | Improved folds |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| New York | Built form | 19.701 | 16.995 | 31.920 | 29.823 | 0.763 | 0.874 | 5/5 |
| New York | S2 only | 19.701 | 16.643 | 31.920 | 28.963 | 0.763 | 0.853 | 5/5 |
| Delhi | Built form | 13.728 | 12.270 | 19.960 | 18.925 | 0.788 | 0.859 | 5/5 |
| Delhi | S2 only | 13.728 | 13.840 | 19.960 | 20.532 | 0.788 | 0.803 | 2/5 |

Built form improves overall MAE, RMSE, and rank correlation in both cities and
improves MAE in every fold. S2-only remains mixed: it improves New York but
worsens Delhi MAE/RMSE. In New York, S2-only has lower error than built form,
while built form has higher rank correlation. This tension does not change the
frozen proxy selection.

## Allocation-gain asymmetry

Mean structural-minus-neighbors absolute-error change at 2550 m is:

| City | Proxy | Gain <0.8 | Gain 0.8–1.25 | Gain ≥1.25 |
| --- | --- | ---: | ---: | ---: |
| New York | Built form | -10.886 | -0.155 | +2.511 |
| New York | S2 only | -11.536 | -0.278 | +0.641 |
| Delhi | Built form | -6.160 | +0.471 | +1.957 |
| Delhi | S2 only | -3.608 | +0.716 | +3.372 |

The preregistered asymmetry persists under the physics-set buffer:
downweighting helps substantially, neutral gain is near neutral or mildly
harmful, and strong upweighting is harmful in all four comparisons. This is a
measured limitation of the structural-gain formulation, not a generic caveat.

## Interpretation

Increasing the buffer weakens the neighbors-only baseline, but the built-form
advantage persists at 1500 m, 2000 m, and 2550 m in both cities. This is
evidence that the comparison is not driven solely by immediately adjacent VNP
cells. It does not independently validate the fine-scale allocation or remove
all spatial autocorrelation.

The strongest leakage test would remove held-out radiance before constructing
and convolving a fine-grid field, then reaggregate to exact native polygons.
That extension remains distinct and should be undertaken only if the demo
requires a fine-grid validation claim stronger than this bounded native-cell
result.
