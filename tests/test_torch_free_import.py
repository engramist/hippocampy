"""
B387 — torch-free ingestion plane.

Importing campy.brain_daemon must leave zero torch/thinc/spacy entries in
sys.modules. Run as a real subprocess (not an in-process import) so an
already-imported torch/thinc/spacy from an earlier test in the same pytest
session can't produce a false pass — this has to reflect what a fresh
daemon process actually loads.
"""

from __future__ import annotations

import subprocess
import sys


def test_import_brain_daemon_leaves_no_torch_thinc_spacy_in_sys_modules():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import campy.brain_daemon, sys; "
            "print([m for m in sys.modules if m.split('.')[0] in "
            "('torch', 'thinc', 'spacy')])",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"import campy.brain_daemon failed:\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert result.stdout.strip() == "[]", (
        f"expected no torch/thinc/spacy modules loaded, got: {result.stdout!r}\n"
        f"stderr: {result.stderr}"
    )


def test_torch_thinc_spacy_not_importable_at_all():
    """B387 removed torch/torchvision/thinc/spacy from the dependency set
    entirely (pyproject.toml + requirements.txt) — not just "not imported
    eagerly". A clean install should not even have them on disk."""
    for pkg in ("torch", "torchvision", "thinc", "spacy"):
        result = subprocess.run(
            [sys.executable, "-c", f"import {pkg}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0, (
            f"{pkg} imported successfully — expected it to be absent from "
            f"the environment after B387 removed it from pyproject.toml/"
            f"requirements.txt"
        )
