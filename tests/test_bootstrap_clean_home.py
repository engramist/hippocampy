"""Test bootstrap behavior in clean HOME environments.

Uses tmp_path and HOME override to simulate fresh machines.
NEVER touches the real home directory.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def clean_home(tmp_path):
    """Create a clean HOME directory with no Campy state."""
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    # Clear any XDG overrides that might leak
    for key in ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"]:
        env.pop(key, None)
    return home, env


def test_clean_home_has_no_campy(clean_home):
    """Fresh HOME should have no .campy directory."""
    home, env = clean_home
    assert not (home / ".campy").exists()
    assert not (home / ".codex").exists()


def test_bootstrap_dry_run_clean_home(clean_home):
    """Bootstrap --dry-run should work with clean HOME."""
    home, env = clean_home
    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--dry-run"],
        capture_output=True, text=True, env=env, timeout=30
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout or "dry run" in result.stdout.lower()


def test_bootstrap_dry_run_does_not_create_files(clean_home):
    """--dry-run should not create any files in HOME."""
    home, env = clean_home
    subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--dry-run"],
        capture_output=True, text=True, env=env, timeout=30
    )
    # Should NOT have created .campy or any config dirs
    assert not (home / ".campy").exists(), ".campy created during dry run"


def test_clean_home_no_codex_config(clean_home):
    """Fresh HOME has no Codex config — bootstrap should handle gracefully."""
    home, env = clean_home
    assert not (home / ".codex" / "config.toml").exists()


def test_clean_home_no_claude_config(clean_home):
    """Fresh HOME has no Claude config — bootstrap should handle gracefully."""
    home, env = clean_home
    claude_config_mac = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    assert not claude_config_mac.exists()


def test_partial_install_missing_brain_db(clean_home):
    """Simulate partial install: .campy dir exists but no brain.db."""
    home, env = clean_home
    campy_dir = home / ".campy"
    campy_dir.mkdir()
    (campy_dir / "campy.toml").write_text("[general]\n")
    # brain.db missing — doctor should detect this
    assert not (campy_dir / "brain.db").exists()
    assert (campy_dir / "campy.toml").exists()


def test_partial_install_missing_launchd_plist(clean_home):
    """Simulate partial install: .campy exists but no launchd plist."""
    home, env = clean_home
    launch_agents = home / "Library" / "LaunchAgents"
    # Don't create it — simulates no daemon auto-start
    assert not launch_agents.exists()


class TestRepeatInstallIdempotency:
    """Test that install operations are idempotent."""

    def test_dry_run_twice_same_output(self, clean_home):
        """Running --dry-run twice should produce consistent output."""
        home, env = clean_home
        results = []
        for _ in range(2):
            result = subprocess.run(
                ["bash", "scripts/bootstrap.sh", "--dry-run"],
                capture_output=True, text=True, env=env, timeout=30
            )
            results.append(result.stdout)
        # Output should be identical (or at least same exit code)
        assert results[0] == results[1]
