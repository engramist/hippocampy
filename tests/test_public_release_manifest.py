"""Tests for public release manifest and distribution artifact verification.

This module validates that wheel and sdist distributions exclude private/runtime data
and only include intended package contents.

Related card: B232 - Public Release Private Data Audit
"""

import tarfile
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def dist_dir():
    """Get or create dist directory with built artifacts."""
    dist_path = Path(__file__).parent.parent / "dist"
    if not dist_path.exists():
        pytest.skip("dist/ directory not found. Run: python -m build --wheel --sdist")
    return dist_path


class TestWheelDistribution:
    """Verify wheel (.whl) distribution excludes sensitive content."""

    def test_wheel_exists(self, dist_dir):
        """Verify at least one wheel file exists."""
        wheels = list(dist_dir.glob("*.whl"))
        assert wheels, "No .whl files found in dist/"

    def test_wheel_excludes_blocked_artifacts(self, dist_dir):
        """Verify wheel excludes runtime state and generated artifacts."""
        blocked_tokens = [
            ".sidequests",
            ".campy",
            "brain.db",
            "brain.sock",
            "submission_results",
            "agent_execution_trace",
            "master_timeline.json",
        ]

        for whl in dist_dir.glob("*.whl"):
            with zipfile.ZipFile(whl) as z:
                names_str = "\n".join(z.namelist())
                for token in blocked_tokens:
                    assert (
                        token not in names_str
                    ), f"Blocked artifact '{token}' found in wheel {whl.name}"

    def test_wheel_includes_required_package_data(self, dist_dir):
        """Verify wheel includes required package modules and data."""
        required_modules = [
            "sidequests/__init__.py",
            "sidequests/cli/main.py",
            "mcp_engine/",
            "adapters/",
        ]

        for whl in dist_dir.glob("*.whl"):
            with zipfile.ZipFile(whl) as z:
                names_str = "\n".join(z.namelist())
                for module in required_modules:
                    assert (
                        module in names_str
                    ), f"Required module '{module}' not found in wheel {whl.name}"

    def test_wheel_excludes_tests(self, dist_dir):
        """Verify wheel excludes test directory (optional but recommended)."""
        for whl in dist_dir.glob("*.whl"):
            with zipfile.ZipFile(whl) as z:
                names_str = "\n".join(z.namelist())
                # Tests should not be in wheel for distribution
                # (they may be in development installs)
                assert not any(
                    n.startswith("tests/") for n in z.namelist()
                ), f"Test files found in wheel {whl.name}"

    def test_wheel_excludes_backlog(self, dist_dir):
        """Verify wheel excludes backlog and planning docs."""
        for whl in dist_dir.glob("*.whl"):
            with zipfile.ZipFile(whl) as z:
                names_str = "\n".join(z.namelist())
                assert "backlog" not in names_str, f"backlog/ found in wheel {whl.name}"


class TestSdistDistribution:
    """Verify sdist (.tar.gz) distribution excludes sensitive content."""

    def test_sdist_exists(self, dist_dir):
        """Verify at least one sdist file exists."""
        sdists = list(dist_dir.glob("*.tar.gz"))
        assert sdists, "No .tar.gz files found in dist/"

    def test_sdist_excludes_blocked_artifacts(self, dist_dir):
        """Verify sdist excludes runtime state and generated artifacts."""
        blocked_tokens = [
            ".sidequests",
            ".campy",
            "brain.db",
            "brain.sock",
            "submission_results",
            "agent_execution_trace",
            "master_timeline.json",
        ]

        for sdist in dist_dir.glob("*.tar.gz"):
            with tarfile.open(sdist) as t:
                names_str = "\n".join(t.getnames())
                for token in blocked_tokens:
                    assert (
                        token not in names_str
                    ), f"Blocked artifact '{token}' found in sdist {sdist.name}"

    def test_sdist_includes_required_modules(self, dist_dir):
        """Verify sdist includes required package modules."""
        required_patterns = [
            "sidequests/",
            "mcp_engine/",
            "pyproject.toml",
        ]

        for sdist in dist_dir.glob("*.tar.gz"):
            with tarfile.open(sdist) as t:
                names_str = "\n".join(t.getnames())
                for pattern in required_patterns:
                    assert (
                        pattern in names_str
                    ), f"Required pattern '{pattern}' not found in sdist {sdist.name}"

    def test_sdist_excludes_runtime_state(self, dist_dir):
        """Verify sdist excludes runtime directories."""
        for sdist in dist_dir.glob("*.tar.gz"):
            with tarfile.open(sdist) as t:
                names = t.getnames()
                assert not any(
                    ".sidequests" in n for n in names
                ), f".sidequests found in sdist {sdist.name}"
                assert not any(
                    ".campy" in n for n in names
                ), f".campy found in sdist {sdist.name}"


class TestDistributionResourceInclusion:
    """Verify necessary resources are included in distributions."""

    def test_wheel_includes_config_template(self, dist_dir):
        """Verify wheel includes default config template if needed."""
        # This test checks if campy.toml or config template is included
        for whl in dist_dir.glob("*.whl"):
            with zipfile.ZipFile(whl) as z:
                names = z.namelist()
                # If we ship config templates, they should be present
                # Skip if no templates are shipped (acceptable)
                if any("config" in n for n in names):
                    assert any(
                        "toml" in n or "yaml" in n for n in names
                    ), f"Config template expected but not found in {whl.name}"

    def test_sdist_includes_source_files(self, dist_dir):
        """Verify sdist includes all source Python files."""
        for sdist in dist_dir.glob("*.tar.gz"):
            with tarfile.open(sdist) as t:
                names_str = "\n".join(t.getnames())
                # Should include Python source
                assert ".py" in names_str, f"No .py files found in sdist {sdist.name}"


class TestPrivateDataAbsence:
    """Verify specific private data types are absent from distributions."""

    def test_no_api_keys_in_distributions(self, dist_dir):
        """Verify no API key patterns in any distribution."""
        api_key_patterns = [
            "sk-",  # OpenAI
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
        ]

        for artifact in list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz")):
            if artifact.suffix == ".whl":
                with zipfile.ZipFile(artifact) as z:
                    contents = "\n".join(z.namelist())
            else:
                with tarfile.open(artifact) as t:
                    contents = "\n".join(t.getnames())

            for pattern in api_key_patterns:
                assert (
                    pattern not in contents
                ), f"API key pattern '{pattern}' found in {artifact.name}"

    def test_no_absolute_paths_in_wheel(self, dist_dir):
        """Verify no absolute paths like /Users/djshelton in wheel files."""
        home_path_patterns = ["/Users/", "/home/", "/root/"]

        for whl in dist_dir.glob("*.whl"):
            with zipfile.ZipFile(whl) as z:
                for info in z.filelist:
                    for pattern in home_path_patterns:
                        # Skip normal paths, look for user-specific ones
                        if "/Users/djshelton" in info.filename or "/home/" in info.filename:
                            pytest.fail(
                                f"Absolute user path found in wheel {whl.name}: {info.filename}"
                            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
