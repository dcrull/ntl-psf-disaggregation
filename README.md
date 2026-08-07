# NTL PSF disaggregation

This repository contains the code and reproducibility record for the PSF-aware,
locally normalized structural allocation sprint conducted over New York and Delhi.

The extraction preserves the final v2 implementation under the original
`nocturne.disaggregate` Python namespace. Renaming the import namespace is deferred
until an equivalence test can be run against the closed v2 products.

## Included

- The tiled, resumable full-city executor and allocation operators.
- Acquisition, proxy construction, validation, sensitivity, and reporting modules.
- The frozen scientific experiment contract in `configs/psf_disaggregation.yaml`,
  with private runtime identity redacted from the public copy.
- Unit and integration tests for the disaggregation workflow.
- The method overview, decision register, review hub, and final results record.
- Compact diagnostic figures and artifact manifests currently referenced by the docs.
- The public narrative notebook, with separately reusable figures under
  `notebooks/figures/`.

Large source rasters and full-city outputs are intentionally not included. Compact
evidence is versioned under `artifacts/`; its manifests retain the original
runtime-relative `outputs/psf_disaggregation/...` paths and hashes for the omitted
products. Each user retrieves the source data and generates and stores the large
products locally; this project will not distribute those rasters through GitHub.

## Documentation

- [Review status and reading order](docs/psf-disaggregation-status.md)
- [Final evidence synthesis](docs/psf-disaggregation-results.md)
- [Method and experiment contract](docs/psf-disaggregation.md)
- [Analysis decision register](docs/psf-disaggregation-decisions.md)
- [Narrative notebook](notebooks/psf_disaggregation_writeup.ipynb)
- [Compact artifact package](artifacts/README.md)
- [Data licenses, retrieval, and redistribution](docs/data-licenses.md)
- [Citation metadata](CITATION.cff)

## Local setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
```

Earth Engine, Overture, and notebook dependencies are optional extras:

```bash
.venv/bin/python -m pip install -e '.[earth-engine,overture,notebooks]'
```

## Fresh-clone reproduction check

The following commands exercise configuration loading, projected grid generation,
the self-contained synthetic allocation operator, and COG raster output without
private credentials or omitted source rasters:

```bash
.venv/bin/python -m nocturne.disaggregate.grids \
  configs/psf_disaggregation.yaml
.venv/bin/python -m nocturne.disaggregate.gate1 \
  configs/psf_disaggregation.yaml --synthetic-only
.venv/bin/python -m nocturne.disaggregate.day2 \
  configs/psf_disaggregation.yaml
```

The synthetic Gate 1 run writes inspectable rasters beneath
`outputs/psf_disaggregation/validation/gate1/synthetic_cog_bundle/`. The Day 2
audit is also expected to succeed in a fresh clone, but its manifest reports
`ready_for_two_city_operator_run: false` until the user supplies the documented
10 m Earth Engine and Overture input bundles. Empirical city workflows require
those locally ingested rasters; Earth Engine workflows additionally require the
private runtime settings below.

Earth Engine runs require private runtime settings. Export them in the shell;
do not write their values into the committed configuration:

```bash
export NTL_PSF_EE_PROJECT='<your-earth-engine-cloud-project>'
export NTL_PSF_EE_DRIVE_FOLDER='<your-google-drive-export-folder>'
```

The code resolves both values at runtime. Public collection identifiers remain
in the configuration because they identify datasets, not accounts.

The privacy-redacted public YAML is intentionally byte-different from the frozen
runtime YAML used for the closed v2 outputs. Existing artifact manifests retain
the original configuration hash as provenance; it is not recomputed or rewritten
to claim that the public redacted file generated those products.

## Publication status

This is the initial public repository release. The analytical v2 closeout and
fresh-clone software reproduction check are complete. Large-raster distribution
is intentionally out of scope; an optional archival DOI and the remaining
presentation review are recorded in the
[review status](docs/psf-disaggregation-status.md).

## License

The software in this repository is available under the
[BSD 3-Clause License](LICENSE). Data and derived artifacts remain subject to
their respective source licenses and attribution requirements, documented in
[Data licenses, retrieval, and redistribution](docs/data-licenses.md).

## Citation

If you use this software, cite the repository using the metadata in
[`CITATION.cff`](CITATION.cff). Repository and archive identifiers can be added
there after the public remote and any Zenodo record are created.
