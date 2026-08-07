# Broad-QA v2 analytical closeout

Classification: **coverage-complete bounded method result**.

## Experiment contract

**Objective.** Test whether a static fine-grid structural proxy can allocate coarse VNP46A2 radiance more plausibly than declared null allocations while VNP46A2 remains the only radiometric authority.

**Primary estimand.** Native-cell broad-QA held-out prediction error on the frozen Gate 0 cohort, using the preregistered 2550 m four-sigma PSF-support exclusion. This is a coarse structural-gain analogue; it is not independent validation of the 10 m field.

**Frozen method.** Built-form proxy, no water prior, circular-mean reference kernel, direct upsample and uniform normalized convolution as mandatory spatial baselines, and neighbors-only inverse-distance-squared interpolation as the held-out baseline.

**Sensitivity controls.** S2-only proxy ablation; 1500 m and 2000 m buffer rows; strict-versus-broad QA comparison; water-weighted variants and matched inland low-proxy regions; and the inherited strict-QA daily observation-condition audit.

The final 10 m COG is therefore a structurally allocated observation product, not observed or calibrated 10 m nighttime radiance.

## Physics-buffered held-out result

| City | Proxy | Neighbor MAE | Structural MAE | Neighbor RMSE | Structural RMSE | Improved folds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| india_delhi | built_form_primary | 13.493 | 12.147 | 19.615 | 18.660 | 4/5 |
| india_delhi | s2_only_ablation | 13.493 | 13.655 | 19.615 | 20.256 | 2/5 |
| usa_new_york | built_form_primary | 18.717 | 16.100 | 30.433 | 28.199 | 5/5 |
| usa_new_york | s2_only_ablation | 18.717 | 15.787 | 30.433 | 27.539 | 5/5 |

Built form improves overall MAE and RMSE in both cities. Delhi improves in 4/5 folds; the single adverse fold changes MAE by +0.044.

Gain below 0.8 remains favorable and gain at or above 1.25 remains adverse in every city-by-proxy comparison.

## Coverage sensitivity

- usa_new_york: strict/broad common-support r = 0.99746; newly filled pixels = 29,269.
- india_delhi: strict/broad common-support r = 0.99928; newly filled pixels = 0.

The strict daily observation-condition result remains inherited conservative sensitivity evidence, not broad-QA daily validation.

## Spatial-product scope

Broad-QA direct, uniform, and built-form/no-water products are complete in both cities. The New York S2-only ablation was also regenerated under broad QA, but retains an explicit S2 proxy-support mask. Delhi's S2-only spatial raster remains strict-v1; the two displayed S2 city rasters therefore must not be treated as a radiance-contract-matched cross-city comparison.

Analytical closeout is complete. User visual review of the two v2 primary COGs remains the final presentation check.
