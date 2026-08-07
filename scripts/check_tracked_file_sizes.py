"""Reject tracked or proposed files above a configurable size limit."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

DEFAULT_MAX_MIB = 25.0


def tracked_files() -> list[Path]:
    """Return files tracked by the current Git index."""

    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [Path(value) for value in result.stdout.decode().split("\0") if value]


def oversized_files(paths: list[Path], *, maximum_bytes: int) -> tuple[int, list[tuple[int, Path]]]:
    """Return the checked-file count and files larger than ``maximum_bytes``."""

    oversized: list[tuple[int, Path]] = []
    checked = 0
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        checked += 1
        size = path.stat().st_size
        if size > maximum_bytes:
            oversized.append((size, path))
    return checked, oversized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-mib", type=float, default=DEFAULT_MAX_MIB)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    if args.max_mib <= 0:
        parser.error("--max-mib must be positive")

    paths = args.paths or tracked_files()
    maximum_bytes = round(args.max_mib * 1024 * 1024)
    checked, oversized = oversized_files(paths, maximum_bytes=maximum_bytes)

    if oversized:
        print(f"Files exceed the {args.max_mib:g} MiB ordinary-Git limit:")
        for size, path in sorted(oversized, reverse=True):
            print(f"  {size / 1024 / 1024:.2f} MiB  {path}")
        print("Store generated data outside Git or explicitly configure Git LFS.")
        return 1
    print(f"File-size hygiene passed for {checked} file(s); limit={args.max_mib:g} MiB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
