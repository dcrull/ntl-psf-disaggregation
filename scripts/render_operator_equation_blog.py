from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

parser = argparse.ArgumentParser(description="Render the blog-ready PSF operator equation.")
parser.add_argument(
    "--output-dir",
    type=Path,
    default=Path(__file__).resolve().parents[1] / "docs" / "figures",
)
args = parser.parse_args()

OUT_DIR = args.output_dir
OUT_DIR.mkdir(parents=True, exist_ok=True)

INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#74736f"
BLUE = "#2a78d6"
PALE_BLUE = "#eef5fd"
LINE = "#d8d7d2"
WHITE = "#ffffff"

mpl.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 12,
        "text.color": INK,
        "axes.facecolor": WHITE,
        "figure.facecolor": WHITE,
        "svg.fonttype": "path",
    }
)


fig = plt.figure(figsize=(12, 6.75), dpi=180)
ax = fig.add_axes((0, 0, 1, 1))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")

# Eyebrow and title
ax.text(
    0.07,
    0.91,
    "PSF-AWARE NIGHTTIME-LIGHT DISAGGREGATION",
    color=BLUE,
    fontsize=9.5,
    fontweight="bold",
    va="center",
    ha="left",
)
ax.text(
    0.07,
    0.848,
    "Fork-form normalized-convolution allocation",
    color=INK,
    fontsize=21,
    fontweight="bold",
    va="center",
    ha="left",
)

# Main equation panel
panel = FancyBboxPatch(
    (0.07, 0.59),
    0.86,
    0.18,
    boxstyle="round,pad=0.012,rounding_size=0.012",
    linewidth=1.1,
    edgecolor="#c7d9ef",
    facecolor=PALE_BLUE,
)
ax.add_patch(panel)
equation = (
    r"$\widetilde{L}(x)"
    r"\;=\;"
    r"\rho(x)\,"
    r"\dfrac{[k\,\otimes\,l](x)}"
    r"{\max\!\left([k\,\otimes\,\rho](x),\,\varepsilon\right)}$"
)
ax.text(0.5, 0.68, equation, fontsize=28, ha="center", va="center", color=INK)

# Plain-language reading
ax.text(
    0.07,
    0.525,
    "Read it as a local share:",
    fontsize=11.5,
    fontweight="bold",
    color=INK,
    ha="left",
    va="center",
)
ax.text(
    0.305,
    0.525,
    "smooth the observed radiance over the declared kernel, then distribute it in proportion to structure.",
    fontsize=11.5,
    color=INK_2,
    ha="left",
    va="center",
)

ax.plot([0.07, 0.93], [0.47, 0.47], color=LINE, lw=1)

# Caption and symbol definitions
ax.text(0.07, 0.423, "CAPTION / SYMBOLS", fontsize=9.5, fontweight="bold", color=BLUE)
caption_lines = [
    (r"$\widetilde{L}(x)$", "locally normalized radiance allocation at fine-grid location x;"),
    (r"$\rho(x)$", "nonnegative structural allocation proxy, normalized to mean one;"),
    (r"$l$", "observed coarse VIIRS radiance field;"),
    (r"$k$", "declared allocation kernel;  ⊗ denotes convolution;"),
    (r"$\varepsilon > 0$", "small denominator floor used for numerical stability."),
]

y = 0.374
for symbol, definition in caption_lines:
    ax.text(0.075, y, symbol, fontsize=12.2, color=INK, ha="left", va="center")
    x_def = 0.19
    ax.text(x_def, y, definition, fontsize=10.9, color=INK_2, ha="left", va="center")
    y -= 0.047

# Scientific guardrail
note = FancyBboxPatch(
    (0.07, 0.075),
    0.86,
    0.075,
    boxstyle="round,pad=0.009,rounding_size=0.008",
    linewidth=0,
    facecolor="#f4f3f0",
)
ax.add_patch(note)
ax.text(
    0.087,
    0.1125,
    "Interpretation guardrail",
    fontsize=9.8,
    fontweight="bold",
    color=INK,
    ha="left",
    va="center",
)
ax.text(
    0.315,
    0.1125,
    "The kernel is a declared support assumption—not a recovered VIIRS PSF—and the output is an allocation, not observed 10 m radiance.",
    fontsize=9.0,
    color=MUTED,
    ha="left",
    va="center",
)

for suffix in ("svg", "png"):
    fig.savefig(
        OUT_DIR / f"operator-kernel-equation.{suffix}",
        dpi=180,
        facecolor=WHITE,
        bbox_inches=None,
        metadata={"Title": "Fork-form normalized-convolution allocation equation"},
    )

plt.close(fig)
