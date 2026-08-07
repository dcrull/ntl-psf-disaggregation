# Gate 2 observation-condition propagation review

Final-v2 role: this strict-QA daily result is inherited conservative sensitivity
evidence. No broad-QA daily stack was created, and this review must not be
relabeled as broad-QA validation.

Status: pass as a 500 m daily coarse-operator audit.

The audit applies direct, uniform circular convolution, and the frozen
built-form/no-water structural analogue to each strict-QA day. All comparisons
use identical observations with complete center-plus-four-cardinal-cell
support. Associations are computed after within-cell centering of log1p output
and each condition.

## Support

| City | Mean direct daily support | Mean complete-kernel support | Median complete-kernel support |
| --- | ---: | ---: | ---: |
| New York | 0.335 | 0.263 | 0.087 |
| Delhi | 0.589 | 0.529 | 0.710 |

Strict daily coverage, especially in New York, is itself the dominant
propagation constraint. Some days have no complete support. This is not filled
or locally renormalized.

## Condition association

The largest descriptive association is with lunar irradiance:

| City | Direct R² | Uniform R² | Built-form R² | Built minus uniform |
| --- | ---: | ---: | ---: | ---: |
| New York | 0.00251 | 0.00663 | 0.00666 | +0.00003 |
| Delhi | 0.00176 | 0.00382 | 0.00384 | +0.00002 |

Cloud-detection and cloud-mask-quality R² values remain below 0.00060 for all
methods. Built-form differences from uniform are below 0.00001 for those
fields.

Mean absolute within-cell log residual is:

| City | Direct | Uniform | Built form |
| --- | ---: | ---: | ---: |
| New York | 0.24790 | 0.17602 | 0.17548 |
| Delhi | 0.22212 | 0.16119 | 0.16023 |

Built form does not materially amplify observation-condition association or
temporal variability relative to uniform. Reductions from direct are attributed
to spatial smoothing and cannot be described as observation-condition
correction.

MQF, snow, and retrieval age are all zero on strict retained pixels. They
verify the strict-QA contract but are not estimable within-sample effects.

## Claim boundary

This is a daily 500 m analogue of the reference operator, not regeneration of
100 full 10 m allocation fields. It tests whether the frozen structural gain
adds condition sensitivity beyond the uniform operator on common support. It
does not establish causal observation-condition effects or validate the
fine-scale allocation.
