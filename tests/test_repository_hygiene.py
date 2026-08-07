from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_notebook_hygiene_check_and_fix(tmp_path) -> None:
    notebook_path = tmp_path / "dirty.ipynb"
    notebook_path.write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["keep me"]},
                    {
                        "cell_type": "code",
                        "execution_count": 7,
                        "outputs": [{"output_type": "stream", "text": ["remove me"]}],
                        "source": ["print('keep source')"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    command = [sys.executable, str(ROOT / "scripts" / "notebook_hygiene.py")]

    check = subprocess.run([*command, "--check", str(notebook_path)], check=False)
    assert check.returncode == 1
    subprocess.run([*command, "--fix", str(notebook_path)], check=True)

    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    assert notebook["cells"][0] == {"cell_type": "markdown", "source": ["keep me"]}
    assert notebook["cells"][1]["execution_count"] is None
    assert notebook["cells"][1]["outputs"] == []
    assert notebook["cells"][1]["source"] == ["print('keep source')"]
    subprocess.run([*command, "--check", str(notebook_path)], check=True)


def test_file_size_hygiene_uses_strict_limit(tmp_path) -> None:
    at_limit = tmp_path / "at-limit.bin"
    over_limit = tmp_path / "over-limit.bin"
    at_limit.write_bytes(b"1234")
    over_limit.write_bytes(b"12345")
    command = [
        sys.executable,
        str(ROOT / "scripts" / "check_tracked_file_sizes.py"),
        "--max-mib",
        str(4 / 1024 / 1024),
    ]

    result = subprocess.run(
        [*command, str(at_limit), str(over_limit)],
        check=False,
    )

    assert result.returncode == 1
    subprocess.run([*command, str(at_limit)], check=True)
