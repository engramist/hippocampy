"""Test the validation script exists and is well-formed."""
from pathlib import Path
import subprocess


def test_validation_script_exists():
    """Validation script should exist."""
    assert Path("scripts/validate_one_click_install.sh").exists()


def test_validation_script_syntax():
    """Script should pass bash -n check."""
    result = subprocess.run(
        ["bash", "-n", "scripts/validate_one_click_install.sh"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"


def test_validation_script_has_strict_mode():
    """Script should use set -euo pipefail."""
    content = Path("scripts/validate_one_click_install.sh").read_text()
    assert "set -euo pipefail" in content


def test_validation_script_supports_dry_run():
    """Script should support --dry-run."""
    content = Path("scripts/validate_one_click_install.sh").read_text()
    assert "--dry-run" in content


def test_validation_script_supports_temp_home():
    """Script should support --use-temp-home."""
    content = Path("scripts/validate_one_click_install.sh").read_text()
    assert "--use-temp-home" in content


def test_validation_dry_run():
    """Validation --dry-run should succeed."""
    result = subprocess.run(
        ["bash", "scripts/validate_one_click_install.sh", "--dry-run"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0
