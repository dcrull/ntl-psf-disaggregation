"""Check or strip execution state from tracked Jupyter notebooks."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def tracked_notebooks() -> list[Path]:
    """Return tracked notebooks when the caller did not provide paths."""

    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.ipynb"],
        check=True,
        capture_output=True,
    )
    return [Path(value) for value in result.stdout.decode().split("\0") if value]


def strip_execution_state(notebook: dict[str, object]) -> bool:
    """Remove code-cell outputs and execution counts in place."""

    changed = False
    for cell in notebook.get("cells", []):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        if cell.get("outputs"):
            cell["outputs"] = []
            changed = True
        if cell.get("execution_count") is not None:
            cell["execution_count"] = None
            changed = True
    return changed


def process(path: Path, *, fix: bool) -> bool:
    """Return whether a notebook contains execution state; optionally strip it."""

    notebook = json.loads(path.read_text(encoding="utf-8"))
    changed = strip_execution_state(notebook)
    if changed and fix:
        path.write_text(
            json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if execution state exists")
    mode.add_argument("--fix", action="store_true", help="Strip execution state in place")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()

    paths = args.paths or tracked_notebooks()
    dirty: list[Path] = []
    for path in paths:
        if path.suffix != ".ipynb" or not path.exists():
            continue
        if process(path, fix=args.fix):
            dirty.append(path)

    if args.fix:
        for path in dirty:
            print(f"stripped notebook execution state: {path}")
        return 0
    if dirty:
        print("Notebook outputs or execution counts must be stripped:")
        for path in dirty:
            print(f"  {path}")
        print("Run: python3 scripts/notebook_hygiene.py --fix")
        return 1
    print(f"Notebook hygiene passed for {len(paths)} tracked notebook(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
