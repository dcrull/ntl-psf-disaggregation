from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the repository root for editable/local preview workflows."""

    for start in (Path.cwd(), Path(__file__).resolve()):
        for candidate in (start, *start.parents):
            if (candidate / "assets").is_dir() and (candidate / "docs").is_dir():
                return candidate
    return Path.cwd()


def resolve_project_path(path: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve a path against cwd first, then the repository root."""

    path = Path(path).expanduser()
    if path.is_absolute():
        return path
    if path.exists():
        return path

    rooted = project_root() / path
    if must_exist and not rooted.exists():
        raise FileNotFoundError(f"Could not find {path!s} relative to cwd or {project_root()!s}")
    return rooted
