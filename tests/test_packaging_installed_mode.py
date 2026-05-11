"""Tests for packaging in installed (wheel/sdist) mode.

This module verifies that SideQuests works correctly when installed via:
- pip install dist/sidequests_brain-*.whl
- pip install dist/sidequests_brain-*.tar.gz

Tests verify:
- CLI commands work from installed package
- Path resolution works without repo-root assumptions
- Package data is available
- Runtime state goes to ~/.sidequests

Related card: B230 - Packaging Hardening for Installed Mode
"""

import subprocess
import tempfile
import venv
from pathlib import Path

import pytest


@pytest.fixture
def temp_venv():
    """Create a temporary virtual environment for testing.

    Yields:
        Path to the temporary venv directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_path = Path(tmpdir) / "venv"
        venv.create(venv_path, with_pip=True)
        yield venv_path


@pytest.fixture
def wheel_path():
    """Get path to the built wheel artifact.

    Skips test if wheel not found.
    """
    dist_dir = Path(__file__).parent.parent / "dist"
    wheels = list(dist_dir.glob("sidequests_brain-*.whl"))

    if not wheels:
        pytest.skip(
            "No wheel found in dist/. Run: python -m build --wheel --sdist"
        )

    return wheels[0]


class TestInstalledModeBasics:
    """Test basic functionality in a clean installed environment."""

    def test_wheel_installs_in_clean_venv(self, temp_venv, wheel_path):
        """Verify wheel installs successfully in clean venv."""
        python_exe = temp_venv / "bin" / "python"
        pip_exe = temp_venv / "bin" / "pip"

        # Install wheel
        result = subprocess.run(
            [str(pip_exe), "install", str(wheel_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"pip install failed: {result.stderr}"

    def test_sidequests_help_works(self, temp_venv, wheel_path):
        """Verify 'sidequests --help' works from installed wheel."""
        python_exe = temp_venv / "bin" / "python"
        pip_exe = temp_venv / "bin" / "pip"

        # Install wheel
        subprocess.run([str(pip_exe), "install", str(wheel_path)], check=True)

        # Run sidequests --help
        result = subprocess.run(
            [str(python_exe), "-m", "sidequests.cli.main", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"sidequests --help failed: {result.stderr}"
        assert "sidequests" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_cli_subcommands_available(self, temp_venv, wheel_path):
        """Verify key CLI subcommands are available."""
        python_exe = temp_venv / "bin" / "python"
        pip_exe = temp_venv / "bin" / "pip"

        # Install wheel
        subprocess.run([str(pip_exe), "install", str(wheel_path)], check=True)

        # Check install command
        result = subprocess.run(
            [str(python_exe), "-m", "sidequests.cli.main", "install", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"install subcommand not found: {result.stderr}"

        # Check status command
        result = subprocess.run(
            [str(python_exe), "-m", "sidequests.cli.main", "status", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"status subcommand not found: {result.stderr}"

        # Check activity command
        result = subprocess.run(
            [str(python_exe), "-m", "sidequests.cli.main", "activity", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"activity subcommand not found: {result.stderr}"


class TestInstalledModePathResolution:
    """Test that paths work correctly in installed mode."""

    def test_import_paths_module(self, temp_venv, wheel_path):
        """Verify sidequests.paths module imports successfully."""
        python_exe = temp_venv / "bin" / "python"
        pip_exe = temp_venv / "bin" / "pip"

        # Install wheel
        subprocess.run([str(pip_exe), "install", str(wheel_path)], check=True)

        # Try importing paths module
        result = subprocess.run(
            [
                str(python_exe),
                "-c",
                "from sidequests.paths import runtime_dir; print(runtime_dir())",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"Failed to import paths: {result.stderr}"
        assert ".sidequests" in result.stdout

    def test_runtime_dir_uses_home(self, temp_venv, wheel_path):
        """Verify runtime_dir() returns ~/.sidequests path."""
        python_exe = temp_venv / "bin" / "python"
        pip_exe = temp_venv / "bin" / "pip"

        # Install wheel
        subprocess.run([str(pip_exe), "install", str(wheel_path)], check=True)

        # Check runtime_dir
        result = subprocess.run(
            [
                str(python_exe),
                "-c",
                "from sidequests.paths import runtime_dir; import os; rd = runtime_dir(); print(str(rd)); assert str(os.path.expanduser('~/.sidequests')) in str(rd)",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"runtime_dir check failed: {result.stderr}"


class TestInstalledModePackageData:
    """Test that package data is included and accessible."""

    def test_wheel_contains_package_modules(self, wheel_path):
        """Verify wheel contains required package modules."""
        import zipfile

        with zipfile.ZipFile(wheel_path) as z:
            names = z.namelist()

            # Check for required modules
            assert any(
                "sidequests/__init__.py" in n for n in names
            ), "sidequests/__init__.py not in wheel"
            assert any(
                "mcp_engine" in n for n in names
            ), "mcp_engine not in wheel"
            assert any(
                "adapters" in n for n in names
            ), "adapters not in wheel"

    def test_wheel_excludes_runtime_state(self, wheel_path):
        """Verify wheel does NOT contain runtime state."""
        import zipfile

        with zipfile.ZipFile(wheel_path) as z:
            names = z.namelist()
            names_str = "\n".join(names)

            # Should not contain runtime artifacts
            assert ".sidequests" not in names_str
            assert "brain.db" not in names_str
            assert "brain.sock" not in names_str


class TestInstalledModeImports:
    """Test that imports work correctly from installed package."""

    def test_core_imports_available(self, temp_venv, wheel_path):
        """Verify core modules can be imported from installed wheel."""
        python_exe = temp_venv / "bin" / "python"
        pip_exe = temp_venv / "bin" / "pip"

        # Install wheel
        subprocess.run([str(pip_exe), "install", str(wheel_path)], check=True)

        # Test core imports
        imports_to_test = [
            "sidequests",
            "sidequests.paths",
            "sidequests.cli.main",
            "mcp_engine",
        ]

        for module in imports_to_test:
            result = subprocess.run(
                [str(python_exe), "-c", f"import {module}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert (
                result.returncode == 0
            ), f"Failed to import {module}: {result.stderr}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
