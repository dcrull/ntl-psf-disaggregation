# Notebooks

`psf_disaggregation_writeup.ipynb` is the public narrative notebook for the
closed v2 experiment. Reusable exported panels and the social-media wipe animation
are under `figures/`.

The repository hygiene hook strips code-cell outputs and execution counts before
commit. This keeps the versioned notebook reviewable; exported figures that form
part of the narrative record remain separate files. Run the notebook against the
external `outputs/psf_disaggregation/` artifact tree to regenerate computed cells.

The source licenses and copy-ready credit for the notebook and its reusable
figures are documented in [`docs/data-licenses.md`](../docs/data-licenses.md) and
[`figures/README.md`](figures/README.md).
