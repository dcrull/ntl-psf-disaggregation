**Figure — Fork-form normalized-convolution allocation.**
$\widetilde{L}(x)$ is the locally normalized radiance allocation at fine-grid
location $x$; $\rho(x)$ is a nonnegative structural allocation proxy normalized
to mean one; $l$ is the observed coarse VIIRS radiance field; $k$ is the declared
allocation kernel; $\otimes$ denotes convolution; and $\varepsilon>0$ is a small
denominator floor used for numerical stability. The kernel is a declared support
assumption—not a recovered VIIRS point-spread function—and $\widetilde{L}$ is an
allocation rather than independently observed 10 m radiance.

**Alt text:** Equation showing fine-grid allocated radiance as the structural
proxy at a location multiplied by locally convolved coarse VIIRS radiance and
divided by the locally convolved structural proxy, subject to a small denominator
floor. A caption defines every symbol and states that the kernel and fine-grid
allocation are assumptions, not measured PSF and radiance.
