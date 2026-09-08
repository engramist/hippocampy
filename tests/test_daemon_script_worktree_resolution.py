"""Regression test for the ai.hippocampy.brain launchd-from-worktree incident.

Incident (2026-08-04): some agent session ran the daemon-start CLI from
inside an isolated git worktree under .claude/worktrees/. campy.cli.launchd's
_daemon_script()/resolve_system_python() resolved paths via
Path(__file__).parent.parent.parent, which pointed at the worktree instead of
the canonical repo. The shared, machine-wide launchd job got repointed at
that worktree, which (being an ephemeral checkout) lacked the untracked
InvertorsDocs/GistSeedExamples.md the daemon needs at startup — launchd's
keep-alive supervision then crash-looped the daemon indefinitely, burning CPU
and leaving every concurrent session's MCP calls degraded ("Brain: OFFLINE").

This test creates a real throwaway git worktree (matching the actual failure
mode exactly, not a mock) and asserts path resolution still lands on the main
checkout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

def _get_canonical_repo_root() -> Path:
    fallback = Path(__file__).resolve().parent.parent
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(fallback),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            common_dir = Path(res.stdout.strip())
            root = common_dir.parent if common_dir.name == ".git" else common_dir
            if (root / "brain_daemon.py").is_file():
                return root
    except Exception:
        pass
    return fallback


REPO_ROOT = _get_canonical_repo_root()


@pytest.fixture
def throwaway_worktree(tmp_path):
    """A real git worktree of the current HEAD, cleaned up after the test."""
    worktree_path = tmp_path / "throwaway-worktree"
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "HEAD", "--detach"],
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
    )
    try:
        yield worktree_path
    finally:
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path), "--force"],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )


def _resolve_from(worktree_path: Path) -> dict[str, str]:
    """Run campy.cli.launchd's resolvers with the module loaded from worktree_path."""
    script = (
        "import sys; sys.path.insert(0, %r); "
        "import campy.cli.launchd as m; "
        "print(m.__file__); "
        "print(m._canonical_repo_root()); "
        "print(m._daemon_script())"
    ) % str(worktree_path)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"resolver subprocess failed: {result.stderr}"
    lines = result.stdout.strip().splitlines()
    return {"module_file": lines[0], "repo_root": lines[1], "daemon_script": lines[2]}


def test_daemon_script_resolves_to_main_checkout_when_run_from_worktree(throwaway_worktree):
    resolved = _resolve_from(throwaway_worktree)

    # Sanity: the module really was loaded from the throwaway worktree, not
    # some cached/installed copy — otherwise this test would prove nothing.
    assert str(throwaway_worktree) in resolved["module_file"]

    # The actual regression guard: despite running from the worktree, both
    # the resolved repo root and the daemon script path must land on the
    # main checkout, never the worktree.
    assert resolved["repo_root"] == str(REPO_ROOT)
    assert resolved["daemon_script"] == str(REPO_ROOT / "brain_daemon.py")
    assert str(throwaway_worktree) not in resolved["daemon_script"]


def test_canonical_repo_root_resolves_to_main_checkout():
    """Verify _canonical_repo_root() resolves to main checkout whether run from main or worktree."""
    import campy.cli.launchd as launchd

    assert launchd._canonical_repo_root() == REPO_ROOT
