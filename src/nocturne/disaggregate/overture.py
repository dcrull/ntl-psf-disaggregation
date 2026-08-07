from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from nocturne.disaggregate.config import load_disaggregation_config
from nocturne.disaggregate.grids import build_city_grid_specs
from nocturne.preview.paths import resolve_project_path

SOURCE_SPECS = (
    ("building", "buildings", "buildings.parquet"),
    ("segment", "transportation", "segments.parquet"),
)


def refresh_overture_inputs(
    config_path: str | Path,
    *,
    selected_city_ids: list[str] | None = None,
) -> list[Path]:
    """Download the pinned Overture release for each exact source envelope."""

    config = load_disaggregation_config(config_path)
    built = config["allocation_proxies"]["built_form"]
    release = str(built["overture_release"])
    output_root = resolve_project_path(built["overture_input_root"])
    grids = build_city_grid_specs(config_path)
    requested = set(selected_city_ids or config["cities"]["selected_city_ids"])
    unknown = requested - {grid.city_id for grid in grids}
    if unknown:
        raise ValueError(f"Unknown city IDs: {sorted(unknown)}")

    overture_cli = Path(sys.executable).with_name("overturemaps")
    if not overture_cli.exists():
        raise FileNotFoundError(
            f"Expected the Overture CLI beside the active Python: {overture_cli}"
        )

    written: list[Path] = []
    for grid in grids:
        if grid.city_id not in requested:
            continue
        city_root = output_root / grid.city_id
        city_root.mkdir(parents=True, exist_ok=True)
        bbox = tuple(map(float, grid.source_wgs84_bounds))
        bbox_argument = ",".join(f"{value:.12f}" for value in bbox)
        for overture_type, theme, filename in SOURCE_SPECS:
            output_path = city_root / filename
            temporary_path = city_root / f".{filename}.download"
            command = [
                str(overture_cli),
                "download",
                "--bbox",
                bbox_argument,
                "-f",
                "geoparquet",
                "--output",
                str(temporary_path),
                "--type",
                overture_type,
                "--release",
                release,
                "--connect_timeout",
                "30",
                "--request_timeout",
                "300",
            ]
            for attempt in range(1, 4):
                _remove_temporary_download(temporary_path)
                try:
                    subprocess.run(command, check=True)
                    break
                except subprocess.CalledProcessError:
                    if attempt == 3:
                        raise
                    print(
                        f"{grid.city_id}: {overture_type} download attempt "
                        f"{attempt}/3 failed; retrying",
                        flush=True,
                    )
            _validate_download(temporary_path)

            state = {
                "last_release": release,
                "last_run": datetime.now(UTC).isoformat(),
                "theme": theme,
                "type": overture_type,
                "bbox": {
                    "xmin": bbox[0],
                    "ymin": bbox[1],
                    "xmax": bbox[2],
                    "ymax": bbox[3],
                },
                "backend": "geoparquet",
                "output": str(output_path.resolve()),
                "command": command,
                "analysis_geometry": "exact_50_km_projected_square_plus_source_halo",
                "source_halo_m": config["cities"]["analysis_geometry"]["source_halo_m"],
            }
            temporary_state = city_root / f".{filename}.state.download"
            temporary_state.write_text(
                json.dumps(state, indent=2) + "\n",
                encoding="utf-8",
            )
            cli_state = Path(f"{temporary_path}.state")
            if cli_state.exists():
                cli_state.unlink()
            os.replace(temporary_path, output_path)
            os.replace(temporary_state, Path(f"{output_path}.state"))
            written.extend([output_path, Path(f"{output_path}.state")])
            print(
                f"{grid.city_id}: refreshed {overture_type} from Overture {release}",
                flush=True,
            )
    return written


def _validate_download(path: Path) -> None:
    parquet = pq.ParquetFile(path)
    if parquet.metadata.num_rows < 1:
        raise ValueError(f"Overture download is empty: {path}")
    if "geometry" not in parquet.schema_arrow.names:
        raise ValueError(f"Overture download lacks geometry: {path}")


def _remove_temporary_download(path: Path) -> None:
    for temporary in (path, Path(f"{path}.state")):
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh pinned Overture inputs for exact city source envelopes."
    )
    parser.add_argument("config", nargs="?", default="configs/psf_disaggregation.yaml")
    parser.add_argument(
        "--city",
        action="append",
        dest="city_ids",
        help="Refresh one city ID; repeat for multiple cities. Defaults to all pilots.",
    )
    args = parser.parse_args(argv)
    for path in refresh_overture_inputs(args.config, selected_city_ids=args.city_ids):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
