# Compact sprint artifacts

This directory preserves the small, reviewable evidence files referenced by the
v2 closeout: input manifests, selection records, held-out summaries, observation-
condition results, shoreline and matched-inland summaries, gain metadata, closeout
classification, and selected diagnostic figures.

The source-relative path begins below `artifacts/`, for example:

```text
artifacts/outputs/psf_disaggregation/validation/gate2/
```

Paths stored *inside* the copied manifests intentionally retain their original
runtime root, `outputs/psf_disaggregation/...`. In this repository, prepend
`artifacts/` when the referenced compact file is included. References to omitted
rasters and row-level tables remain provenance records. They resolve only when a
user has locally ingested or regenerated those files at the recorded runtime path;
there is no project-hosted external raster archive.

Large full-city rasters, held-out row-level `predictions.csv` files, raw OSM data,
and the 16 MB historical v1 tile manifest are deliberately omitted. The compact
v2 full-city artifact manifest is included because it records the final product
paths and hashes without embedding the raster products themselves.

The 2026-08-07 cleanup audit verified every manifest `path`/`sha256` pair whose
target is included in this compact package; all verifiable references matched.

These compact files are analytical summaries and produced figures, not a source-
data archive. Their source attribution and redistribution conditions are recorded
in [`docs/data-licenses.md`](../docs/data-licenses.md). In particular, standalone
reuse of a map or diagnostic figure must retain the relevant VIIRS, modified
Copernicus Sentinel, Cloud Score+, Overture/OpenStreetMap, and JRC credits.
