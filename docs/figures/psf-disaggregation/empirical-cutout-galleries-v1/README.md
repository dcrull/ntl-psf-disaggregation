# PSF disaggregation empirical cutout galleries v1

This directory is the durable, versionable snapshot of the Day 2 empirical
operator-preflight gallery accepted by visual inspection on 2026-07-29. It is
preserved for the reproducible research note, narrative notebook, and blog.

Open `index.html` to view the dense-building, sparse-built, and
water-adjacent-infrastructure reporting cores for New York and Delhi. Each
figure compares the strict-QA VIIRS radiance input, direct and uniform nulls,
built-form and S2 allocations, selected water treatments, the actual
native-cell polygon sensitivity, and proxy disagreement.

The cutouts were selected from Overture structure and JRC water occurrence
without using VIIRS radiance. Every displayed 1 km core was evaluated with the
complete declared processing halo before cropping. Panels labeled “No complete
strict-QA support” are intentionally nodata; strict-QA neighborhood gaps were
not filled or silently renormalized.

These figures are **operator and input diagnostics**, not independent
fine-resolution nighttime-radiance validation. Panel-specific percentile
stretches and `log1p` display transforms aid inspection but do not modify the
saved arrays or COGs. The JRC layer is an internal allocation prior and cannot
serve as an independent water reference.

`summary.json` and `metrics.csv` preserve the numerical and provenance record
for the 129-run diagnostic matrix. `manifest.json` records snapshot hashes; its
source artifact-manifest hash links this reduced blog snapshot to the complete
81-file live package, including the COGs and compressed arrays.

Regenerate the complete live package with:

```bash
.venv/bin/python -m nocturne.disaggregate.empirical_cutouts \
  configs/psf_disaggregation.yaml
```
