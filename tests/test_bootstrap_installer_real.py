"""
tests/test_bootstrap_installer_real.py — Real end-to-end tests for B237.

tests/test_bootstrap_script.py only ever runs scripts/bootstrap.sh in
--dry-run or --help mode, or greps its source text. None of that exercises
a real, non-dry-run install - which is exactly the gap that let Step 4's
PATH-resolution bug ship: on a genuinely fresh machine (no campy ever on
PATH before), the script's own preferred pipx install path would install
correctly and then immediately fail its own verification step, because
Step 4 only ever checked the managed-venv fallback path
($HOME/.campy/venv/bin), never the pipx bin directory the pipx branch
actually installs into.

These tests run the real script against a real pipx, in a real isolated
temp $HOME with a minimal $PATH (no pre-existing campy, matching a fresh
machine), installing a tiny zero-dependency fixture package
(tests/fixtures/fake_campy_pkg) instead of the real hippocampy package so
the test doesn't need to install sentence-transformers/spacy/etc.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PKG = REPO_ROOT / "tests" / "fixtures" / "fake_campy_pkg"
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.sh"

pytestmark = pytest.mark.skipif(shutil.which("pipx") is None, reason="pipx not installed")


def _minimal_path() -> str:
    """A PATH with just enough for bash, pipx, and a real python3.12+ to
    work - explicitly excluding any pre-existing ~/.local/bin (or any other
    dir a stale campy install might live on) so it can't leak in and mask
    the bug this test exists to catch."""
    dirs: list[str] = []
    for tool in ("bash", "pipx", "python3.13", "python3.12", "python3", "uname", "env"):
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
def isolated_home():
    tmp = tempfile.mkdtemp(prefix="bootstrap_e2e_home_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def _run_bootstrap(isolated_home: Path, *extra_args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(isolated_home)
    env["PATH"] = _minimal_path()
    for var in ("PIPX_HOME", "PIPX_BIN_DIR", "PIPX_DEFAULT_PYTHON", "VIRTUAL_ENV"):
        env.pop(var, None)

    return subprocess.run(
        ["bash", str(BOOTSTRAP), "--dev-source", str(FIXTURE_PKG),
         "--no-start", "--no-register", *extra_args],
        capture_output=True, text=True, env=env, timeout=180,
    )


def test_bootstrap_pipx_install_verifies_on_a_fresh_machine(isolated_home):
    """The exact scenario the B237 audit reproduced: a fresh machine with
    no campy ever on PATH, using bootstrap.sh's own preferred (pipx) path.
    Step 4 must succeed, not exit 1 right after a successful install."""
    result = _run_bootstrap(isolated_home)

    assert result.returncode == 0, (
        f"bootstrap.sh exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "campy CLI not found in PATH after install" not in result.stdout
    assert "Step 4: Verifying campy CLI" in result.stdout


def test_bootstrap_finds_the_freshly_installed_binary_not_a_stale_one(isolated_home):
    """Regression guard for the audit's second finding: Step 4 must resolve
    the binary it JUST installed (under the isolated pipx bin dir inside
    our temp $HOME), not silently succeed via some unrelated PATH entry."""
    result = _run_bootstrap(isolated_home)

    assert result.returncode == 0
    assert str(isolated_home) in result.stdout, (
        "expected Step 4 to report a campy path inside the isolated temp "
        f"HOME ({isolated_home}); stdout:\n{result.stdout}"
    )


def test_bootstrap_pipx_path_runs_full_pipeline_cleanly(isolated_home):
    """With --no-start/--no-register only skipping steps 5 and 7, Step 6
    (doctor) still runs against the freshly-verified binary - the whole
    pipeline should complete without hitting the Step 4 failure branch."""
    result = _run_bootstrap(isolated_home)

    assert result.returncode == 0
    assert "Installation Complete" in result.stdout
