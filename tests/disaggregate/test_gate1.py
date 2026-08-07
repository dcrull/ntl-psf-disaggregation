from __future__ import annotations

import json
from pathlib import Path

import rasterio

from nocturne.disaggregate.gate1 import main

ROOT = Path(__file__).parents[2]


def test_synthetic_only_cli_runs_without_gate0_artifacts(
    tmp_path,
    monkeypatch,
) -> None:
    # Make the temporary directory an independent project root for output
    # resolution while reading only the committed public configuration.
    (tmp_path / "assets").mkdir()
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)

    config_path = ROOT / "configs" / "psf_disaggregation.yaml"
    assert main([str(config_path), "--synthetic-only"]) == 0

    gate1_root = tmp_path / "outputs" / "psf_disaggregation" / "validation" / "gate1"
    summary_path = gate1_root / "synthetic_coastline_gate1_summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert payload["run_mode"] == "synthetic_only"
    assert payload["native_vnp_footprints_included"] is False
    assert len(payload["representative_kernel_set"]) == 4
    assert all(payload["gate1_checks"].values())
    assert not (gate1_root.parent / "gate0").exists()

    allocation_path = gate1_root / "synthetic_cog_bundle" / "allocation.tif"
    with rasterio.open(allocation_path) as dataset:
        assert dataset.shape == (401, 401)
        assert dataset.crs.to_string() == "EPSG:32618"
        assert dataset.descriptions == ("allocation",)
        assert dataset.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
