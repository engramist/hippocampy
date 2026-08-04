"""
tests/test_validation_harness_real.py — Real end-to-end tests for B238.

tests/test_validation_script.py only ever runs scripts/validate_one_click_
install.sh in --dry-run mode or greps its source text - it never actually
runs a --use-temp-home validation pass. That's exactly the gap that let a
real, confirmed bug ship: the harness isolates $HOME for --use-temp-home
but never isolates $PATH, so a pre-existing campy anywhere on the invoking
shell's PATH silently shadows whatever the fresh temp-home install just
did. The 2026-08-03 audit's own manual run hit exactly this - it "passed"
by verifying a stale, wrong-Python-version campy instead of the one it
had just installed into the isolated temp HOME.

These tests run the real harness against a real pipx, planting a fake
"stale" campy on PATH first (simulating a real prior install) and
confirming the harness's temp-home run resolves the freshly-installed
binary instead of the stale one.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PKG = REPO_ROOT / "tests" / "fixtures" / "fake_campy_pkg"
HARNESS = REPO_ROOT / "scripts" / "validate_one_click_install.sh"

pytestmark = pytest.mark.skipif(shutil.which("pipx") is None, reason="pipx not installed")

_STALE_MARKER = "STALE-CAMPY-MARKER"


def _minimal_real_path() -> str:
    dirs: list[str] = []
    for tool in ("bash", "pipx", "python3.13", "python3.12", "python3", "uname", "env", "mktemp"):
        found = shutil.which(tool)
        if found:
            d = str(Path(found).parent)
            if d not in dirs:
                dirs.append(d)
    for base in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
        if base not in dirs:
            dirs.append(base)
    return ":".join(dirs)


@pytest.fixture()
def stale_campy_dir():
    """A directory containing a fake 'campy' that prints a marker so tests
    can prove it was (or wasn't) the binary that actually ran."""
    tmp = tempfile.mkdtemp(prefix="stale_campy_bin_")
    script = Path(tmp) / "campy"
    script.write_text(f'#!/usr/bin/env bash\necho "{_STALE_MARKER} $*"\nexit 0\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def _run_harness(stale_campy_dir: Path, *extra_args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Stale dir FIRST, matching how a real prior install would naturally
    # already be on the user's PATH before this harness run.
    env["PATH"] = f"{stale_campy_dir}:{_minimal_real_path()}"
    for var in ("HOME", "PIPX_HOME", "PIPX_BIN_DIR", "PIPX_DEFAULT_PYTHON"):
        env.pop(var, None)
    # HOME must still resolve somewhere for pipx/bash/etc before the
    # harness creates its own temp HOME internally.
    env["HOME"] = str(Path(tempfile.gettempdir()))

    return subprocess.run(
        ["bash", str(HARNESS), "--use-temp-home", "--skip-daemon",
         "--package", str(FIXTURE_PKG), *extra_args],
        capture_output=True, text=True, env=env, timeout=180,
    )


def test_harness_does_not_report_stale_campy_from_ambient_path(stale_campy_dir):
    result = _run_harness(stale_campy_dir)

    assert _STALE_MARKER not in result.stdout, (
        f"harness resolved the stale campy on the ambient PATH instead of "
        f"the freshly-installed one:\n{result.stdout}"
    )


def test_harness_runs_the_freshly_installed_binary(stale_campy_dir):
    """Positive check to accompany the negative one above: the harness's
    own `campy doctor` step should show RUNTIME output from the real
    fixture binary it just installed (its main() print), not just pipx's
    install-log line mentioning the package name, and not the stale one."""
    result = _run_harness(stale_campy_dir)

    assert "fakecampy 0.1.0 called with args" in result.stdout, (
        f"expected the fixture binary's own runtime output (not just "
        f"pipx's install-log mention of the package name); stdout:\n{result.stdout}"
    )


def test_harness_campy_cli_check_passes_on_a_fresh_install(stale_campy_dir):
    result = _run_harness(stale_campy_dir)

    assert "campy CLI available" in result.stdout
    assert "✗ campy CLI available" not in result.stdout
