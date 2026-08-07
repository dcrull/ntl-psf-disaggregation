# PSF disaggregation method-input galleries v1

This directory is the durable, versionable snapshot of the Day 2 input
inspection galleries accepted on 2026-07-29. It is preserved for the
reproducible research note, narrative notebook, and blog.

Open `index.html` to view all six panels:

- New York and Delhi Earth Engine source-bundle overviews;
- New York and Delhi VNP retrieval/coverage diagnostics; and
- New York and Delhi Overture structural-proxy overviews.

These are **method and input-diagnostic figures**, not allocation results or
independent validation. The overview arrays use display-only downsampling,
`log1p` for the radiance panels, and panel-specific percentile stretches.
Those operations do not alter the source COGs, but they also mean brightness
must not be compared quantitatively between panels from the images alone.

This historical v1 gallery uses the strict-QA VNP median. The final spatial
reporting products use the later broad-QA corrected median for coverage, while
strict QA remains the Gate 0/daily authority and conservative spatial sensitivity.
Gap-filled panels remain labeled diagnostics and are not headline measurements.
The Overture base is an unwatered, unfloored contemporary structural proxy used
to allocate 2024 radiance.

The exact source checksums, grid checks, display contract, and snapshot file
checksums are recorded in `source_bundle_inspection.json` and `manifest.json`.
Regenerate the live galleries from the audited source artifacts with:

```bash
.venv/bin/python -m nocturne.disaggregate.source_preview \
  configs/psf_disaggregation.yaml \
  --input-root drafts
```
