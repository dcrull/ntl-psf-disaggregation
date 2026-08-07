# Migration record

This directory was extracted from the private Nocturne working repository as a
clean, non-history-preserving candidate for a standalone public repository.

## Provenance boundary

- Original Nocturne files were copied, not deleted or moved.
- `configs/psf_disaggregation.yaml` is byte-identical to the closed v2 config so
  its recorded SHA-256 remains valid.
- The broader Nocturne candidate-city workbook and first-experiment configuration
  were not copied. They are replaced here by a minimal two-city registry and a
  compatibility config at the same relative path.
- `src/nocturne/preview` and `src/nocturne/experiment` contain only the small
  dependency closure required by the copied sprint implementation.
- Full input and output rasters, caches, credentials, and private Git history are
  excluded.
- Two `local_expected_path` values in the copied Earth Engine export manifest were
  changed from a personal absolute path to the equivalent repository-relative path.
  Dataset identifiers, task identifiers, export descriptions, and hashes were not
  changed.

## Intentional migration-only change

The copied city loader accepts CSV registries in addition to Excel workbooks. This
allows the standalone tree to carry only the New York and Delhi coordinates needed
by the sprint without exposing the broader internal candidate workbook.

## Migration closeout

The standalone dependency boundary, documentation links, compact evidence package,
test suite, and repository-hygiene checks have been audited. The original
`nocturne.disaggregate` namespace is intentionally retained to preserve equivalence
with the closed v2 products. Remaining release tasks are tracked in
`docs/publication-checklist.md`.
