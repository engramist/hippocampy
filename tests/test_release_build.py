"""Test the release build script exists and is well-formed."""
from pathlib import Path
import subprocess


def test_release_build_script_exists():
    """Release build script should exist."""
    script = Path("scripts/release_build.sh")
    assert script.exists()


def test_release_build_script_syntax():
    """Script should pass bash -n syntax check."""
    result = subprocess.run(
        ["bash", "-n", "scripts/release_build.sh"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"


def test_release_build_script_has_strict_mode():
    """Script should use set -euo pipefail."""
    content = Path("scripts/release_build.sh").read_text()
    assert "set -euo pipefail" in content


def test_release_build_script_runs_audit():
    """Script should call audit_public_release.sh before building."""
    content = Path("scripts/release_build.sh").read_text()
    assert "audit_public_release" in content


def test_release_build_script_runs_twine_check():
    """Script should run twine check on built artifacts."""
    content = Path("scripts/release_build.sh").read_text()
    assert "twine check" in content


def test_release_build_script_requires_publish_flag():
    """Script should never upload to PyPI without explicit --publish flag."""
    content = Path("scripts/release_build.sh").read_text()
    assert "--publish" in content
    # Check that twine upload to real PyPI is inside a conditional check
    lines = content.split("\n")
    in_publish_block = False
    for i, line in enumerate(lines):
        if "elif [ " in line and "--publish" in line:
            in_publish_block = True
        elif line.strip().startswith("elif ") or line.strip().startswith("else"):
            in_publish_block = False
        
        if "twine upload dist/*" in line and "testpypi" not in line.lower():
            # Must be inside a --publish conditional
            assert in_publish_block, f"Unconditional twine upload found at line {i}: {line}"
