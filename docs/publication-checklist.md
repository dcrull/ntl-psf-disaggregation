# Pre-publication checklist

The analytical v2 closeout is complete. The remaining work is release engineering
and distribution, not additional model selection or validation.

- [x] Add the BSD 3-Clause code license. Completed 2026-08-07.
- [x] Add `CITATION.cff`. Completed 2026-08-07.
- [ ] Optionally archive tagged releases with Zenodo and add the resulting DOI to
  `CITATION.cff`.
- [x] Document licenses and retrieval terms for VIIRS, Sentinel-2, Cloud Score+,
  OSM, Overture, JRC, and redistributed derived sample data in
  `docs/data-licenses.md`. Completed 2026-08-07.
- [x] Fix the large-raster policy: source and product rasters are user-ingested or
  generated and stored locally; they are not published to GitHub or distributed
  by this project. Existing manifests and checksums remain the provenance record.
  Completed 2026-08-07.
- [x] Run a credential and privacy scan, including Earth Engine identifiers,
  usernames, absolute paths, bucket names, and private hostnames. Private
  runtime identifiers and notebook execution state were removed; the
  commit-eligible tree contains no high-confidence secret findings. Completed
  2026-08-07.
- [ ] Set the intended public Git author name and email before the first commit.
- [ ] Verify the documented setup, test, and representative reproduction
  commands from a fresh clone.
- [ ] Add a tiny synthetic or redistributable fixture if a fresh-clone workflow
  should exercise raster I/O without locally ingested source data.
- [ ] Complete and record presentation review of the two broad-QA built-form
  reporting COGs; this is the one review item still open in the frozen v2
  closeout manifest.
- [x] Reconcile the narrative notebook with the frozen artifact record: New York's
  S2 spatial ablation is broad-QA while Delhi's remains strict-v1; the code license
  is BSD-3-Clause; and the large COGs are generated and retained locally rather
  than committed to Git. Corrected 2026-08-07.
- [x] Confirm that the public narrative notebook policy is intentional: the
  notebook is distributed without code-cell outputs or execution counts, and
  the hygiene hook preserves that policy on commit. Completed 2026-08-07.
- [ ] Keep demonstrated findings, limitations, and deferred work separated as
  defined in `psf-disaggregation-results.md`.

The original `nocturne.disaggregate` import namespace is intentionally retained
for equivalence with the closed products. Renaming it is optional future package
work, not a release blocker.
