"""Test the bootstrap installer script."""
from pathlib import Path
import subprocess


def test_bootstrap_script_exists():
    """Bootstrap script should exist."""
    assert Path("scripts/bootstrap.sh").exists()


def test_bootstrap_script_syntax():
    """Script should pass bash -n syntax check."""
    result = subprocess.run(
        ["bash", "-n", "scripts/bootstrap.sh"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"


def test_bootstrap_script_has_strict_mode():
    """Script should use set -euo pipefail."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "set -euo pipefail" in content


def test_bootstrap_script_supports_dry_run():
    """Script should support --dry-run flag."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "--dry-run" in content
    assert "DRY_RUN" in content or "dry_run" in content


def test_bootstrap_script_supports_help():
    """Script should support --help flag."""
    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Usage" in result.stdout or "usage" in result.stdout


def test_bootstrap_script_checks_python():
    """Script should check for Python version."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "python" in content.lower()
    assert "3.12" in content or "python3" in content


def test_bootstrap_script_prefers_pipx():
    """Script should check for pipx before falling back."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "pipx" in content


def test_bootstrap_script_never_deletes_brain_db():
    """Script must NEVER delete brain.db."""
    content = Path("scripts/bootstrap.sh").read_text()
    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "rm -rf" in stripped and ".campy" in stripped:
            assert False, f"Dangerous delete found: {stripped}"


def test_bootstrap_script_calls_campy_install():
    """Script should call campy install after package install."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "campy install" in content or "campy setup" in content


def test_bootstrap_script_calls_doctor():
    """Script should call campy doctor for diagnostics."""
    content = Path("scripts/bootstrap.sh").read_text()
    assert "campy doctor" in content


def test_readme_documents_the_one_line_bootstrap_command():
    """B237: docs/homebrew-install.md already links to 'the main README
    Quickstart and scripts/bootstrap.sh' for the one-liner, but the README
    never actually got it - that cross-reference was silently broken."""
    content = Path("README.md").read_text()
    assert "curl -fsSL" in content
    assert "scripts/bootstrap.sh" in content
    assert "--dry-run" in content  # safer inspect-first variant


def test_bootstrap_dry_run_does_not_install():
    """--dry-run should not actually install anything."""
    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--dry-run"],
        capture_output=True, text=True,
        timeout=30
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout or "dry run" in result.stdout.lower()
