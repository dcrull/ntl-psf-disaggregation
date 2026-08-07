"""Regenerate version-matched Gate 0 figures from saved v3 artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.gate0 import (
    _gate0_output_root,
    _gate_analysis_samples,
    _load_pilot_cities,
    _write_gate_figure,
)


def regenerate_gate0_figures(config_path: str | Path) -> Path:
    """Replace four stale PNGs and record exact table/sample provenance."""

    config = load_disaggregation_config(config_path)
    output_root = _gate0_output_root(config)
    cities = _load_pilot_cities(config)
    specs = (
        (
            "built_form",
            "built_form_primary",
            "Overture built-form allocation proxy",
        ),
        ("s2_only", "s2_only_ablation", "S2-only allocation proxy"),
    )
    records = []
    for suffix, proxy, label in specs:
        summary_path = output_root / f"{suffix}_gate0_summary.csv"
        summary = pd.read_csv(summary_path).set_index("city_id")
        for city in cities.itertuples(index=False):
            sample_path = output_root / f"{city.city_id}_{suffix}_samples.csv"
            output_path = output_root / f"{city.city_id}_{suffix}_gate0.png"
            samples = pd.read_csv(sample_path)
            metrics = summary.loc[city.city_id].to_dict()
            _write_gate_figure(
                _gate_analysis_samples(
                    samples,
                    allocation_proxy=proxy,
                    config=config,
                ),
                city=city,
                allocation_label=label,
                metrics=metrics,
                output_path=output_path,
            )
            records.append(
                {
                    "city_id": city.city_id,
                    "allocation_proxy": proxy,
                    "sample_path": str(sample_path),
                    "sample_sha256": _sha256(sample_path),
                    "summary_path": str(summary_path),
                    "summary_sha256": _sha256(summary_path),
                    "displayed_citywide_spearman": float(
                        metrics["citywide_spearman"]
                    ),
                    "displayed_block_spearman": float(
                        metrics["block_mean_spearman"]
                    ),
                    "figure_path": str(output_path),
                    "figure_sha256": _sha256(output_path),
                }
            )
    manifest_path = output_root / "gate0_figure_regeneration.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at_utc": datetime.now(UTC).isoformat(),
                "artifact_version": config["validation"]["gate0"]["artifact_version"],
                "defect_closed": "ARTIFACT-PROVENANCE-001",
                "source_policy": "saved v3 samples and v3 summary tables only",
                "figures": records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    args = parser.parse_args(argv)
    print(regenerate_gate0_figures(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
