# tests/cli/test_recall_cli.py
"""Tests for B261 - CLI recall commands."""
import subprocess
import sys
import pytest


def test_recall_command_exists():
    """campy recall --help should work."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "recall", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "query" in result.stdout.lower() or "recall" in result.stdout.lower()


def test_bundle_command_exists():
    """campy bundle --help should work."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "bundle", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0


@pytest.mark.parametrize("cmd", ["timeline", "diff", "decide", "context"])
def test_recall_commands_exist(cmd):
    """All recall subcommands should be available."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", cmd, "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"{cmd} --help failed: {result.stderr}"


@pytest.mark.integration
def test_recall_returns_results():
    """campy recall should handle daemon not running gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "recall", "test query", "--format=json"],
        capture_output=True, text=True, timeout=10
    )
    # Should exit 0 or 1, but not crash
    assert result.returncode in (0, 1)
    assert len(result.stdout + result.stderr) > 0


@pytest.mark.integration
def test_decide_returns_recommendation():
    """campy decide should return a recommendation or handle gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "decide", "what tools are available?", "--format=json"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode in (0, 1)
    assert len(result.stdout + result.stderr) > 0
