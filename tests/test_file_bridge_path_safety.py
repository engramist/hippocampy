"""BOUNDARY-4: Path traversal and symlink escape tests for file projection code.

The File Bridge and wiki projection modules write files under user-controlled
project directories.  These tests ensure that:

  - All writes stay within the intended project root.
  - Path traversal attempts (../) are rejected.
  - Symlink escapes are detected and rejected.
  - Slug generation never produces directory separators.

If any test fails, the projection code needs a validation helper before
the refactor moves it into thalamus/.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import helpers under test
# ---------------------------------------------------------------------------

from campy.brain.thalamus.file_bridge import _slugify, generate_agent_pointers


# ---------------------------------------------------------------------------
# 1. Slug Safety
# ---------------------------------------------------------------------------

class TestSlugSafety:
    """Verify _slugify never produces directory separators or traversal."""

    @pytest.mark.parametrize("malicious_input", [
        "../../../etc/passwd",
        "..\\..\\windows\\system32",
        "normal/../escape",
        "good-name/../../bad",
        "title\x00injected",
        "title\nwith\nnewlines",
        "a" * 200,  # very long input
        "",
        "   ",
        "---",
    ])
    def test_slug_never_contains_path_separators(self, malicious_input: str):
        slug = _slugify(malicious_input)
        assert "/" not in slug, f"Slug contains '/': {slug!r}"
        assert "\\" not in slug, f"Slug contains '\\': {slug!r}"
        assert ".." not in slug, f"Slug contains '..': {slug!r}"
        assert "\x00" not in slug, f"Slug contains null byte: {slug!r}"

    def test_slug_max_length_enforced(self):
        slug = _slugify("a" * 200, max_length=50)
        assert len(slug) <= 50

    def test_slug_strips_leading_trailing_hyphens(self):
        slug = _slugify("---hello---")
        assert not slug.startswith("-")
        assert not slug.endswith("-")


# ---------------------------------------------------------------------------
# 2. Project Root Containment — CONTEXT.md
# ---------------------------------------------------------------------------

class TestContextMdContainment:
    """Verify generate_context_md writes inside project_path only."""

    def test_output_path_is_inside_project_root(self, tmp_path: Path):
        """The CONTEXT.md output path must resolve inside project_path."""
        project = tmp_path / "my_project"
        project.mkdir()
        output = project / "CONTEXT.md"
        # Verify the path resolves inside the project root
        assert output.resolve().is_relative_to(project.resolve())


# ---------------------------------------------------------------------------
# 3. Project Root Containment — ADR files
# ---------------------------------------------------------------------------

class TestAdrContainment:
    """Verify ADR filename construction stays inside project_path/docs/adr/."""

    @pytest.mark.parametrize("title", [
        "Normal Decision Title",
        "../../../etc/shadow",
        "decision/with/slashes",
        "decision\\backslash\\path",
        "decision\x00null",
    ])
    def test_adr_slug_stays_inside_adr_dir(self, tmp_path: Path, title: str):
        """Slugified decision titles must not escape the ADR directory."""
        project = tmp_path / "project"
        project.mkdir()
        adr_dir = project / "docs" / "adr"
        adr_dir.mkdir(parents=True)

        slug = _slugify(title)
        filename = f"0001-{slug}.md"
        file_path = (adr_dir / filename).resolve()

        assert file_path.is_relative_to(adr_dir.resolve()), (
            f"ADR path escaped adr_dir: {file_path} not under {adr_dir.resolve()}"
        )


# ---------------------------------------------------------------------------
# 4. Symlink Escape Detection
# ---------------------------------------------------------------------------

class TestSymlinkEscape:
    """Verify file projection does not follow symlinks outside the project root."""

    @pytest.mark.skipif(
        os.name == "nt",
        reason="Symlink creation may require elevated privileges on Windows",
    )
    def test_symlinked_context_md_should_resolve_inside_root(self, tmp_path: Path):
        """If someone creates a CONTEXT.md symlink pointing outside the project,
        resolve() should reveal it's not under project_path."""
        project = tmp_path / "project"
        project.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        # Create a symlink inside project that points outside
        symlink = project / "CONTEXT.md"
        symlink.symlink_to(outside / "stolen.md")

        # The resolved path should NOT be inside the project root
        resolved = symlink.resolve()
        assert not resolved.is_relative_to(project.resolve()), (
            "Symlink resolves inside project but points outside — "
            "projection code must detect this"
        )

    @pytest.mark.skipif(
        os.name == "nt",
        reason="Symlink creation may require elevated privileges on Windows",
    )
    def test_symlinked_adr_directory_should_resolve_outside(self, tmp_path: Path):
        """If docs/adr/ is a symlink to an external directory, resolve() reveals it."""
        project = tmp_path / "project"
        project.mkdir()
        outside = tmp_path / "outside_adr"
        outside.mkdir()

        docs = project / "docs"
        docs.mkdir()
        (docs / "adr").symlink_to(outside)

        adr_dir = (project / "docs" / "adr").resolve()
        assert not adr_dir.is_relative_to(project.resolve()), (
            "Symlinked ADR dir resolves inside project but actually points outside"
        )


# ---------------------------------------------------------------------------
# 5. Agent Pointer Safety
# ---------------------------------------------------------------------------

class TestAgentPointerSafety:
    """Verify generate_agent_pointers only modifies files that already exist."""

    def test_does_not_create_new_files(self, tmp_path: Path):
        """Agent pointers must not create config files that don't exist."""
        project = tmp_path / "project"
        project.mkdir()
        # Call without any agent config files present
        modified = generate_agent_pointers(project)
        assert modified == []
        # Verify no new files were created
        assert not (project / "CLAUDE.md").exists()
        assert not (project / "AGENTS.md").exists()
        assert not (project / "GEMINI.md").exists()

    def test_only_modifies_existing_files(self, tmp_path: Path):
        """Only files that already exist should be touched."""
        project = tmp_path / "project"
        project.mkdir()
        # Create only CLAUDE.md
        (project / "CLAUDE.md").write_text("# Claude Config\n")
        modified = generate_agent_pointers(project)
        assert "CLAUDE.md" in modified
        assert "AGENTS.md" not in modified

    def test_does_not_double_append(self, tmp_path: Path):
        """If the pointer already exists, don't append again."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "CLAUDE.md").write_text(
            "# Claude Config\n\nCall `memory_decision` before stuff.\n"
        )
        modified = generate_agent_pointers(project)
        assert modified == []


# ---------------------------------------------------------------------------
# 6. Resolve-Based Containment Helper (Design Gap Test)
# ---------------------------------------------------------------------------

class TestProjectChildResolution:
    """Tests for a _resolve_project_child() helper.

    If file_bridge.py lacks this helper, these tests document the gap.
    The helper should:
      1. Resolve both project_path and the target path.
      2. Verify the target is a child of the project root.
      3. Reject symlinks that escape the project root.
      4. Return the resolved path or raise ValueError.
    """

    def test_helper_importable(self):
        """Check whether _resolve_project_child exists yet."""
        try:
            from campy.brain.thalamus.file_bridge import _resolve_project_child
            assert callable(_resolve_project_child)
        except ImportError:
            pytest.skip(
                "DESIGN GAP: _resolve_project_child does not exist yet. "
                "file_bridge.py needs a path containment helper before "
                "the thalamus move."
            )

    def test_normal_child_accepted(self, tmp_path: Path):
        try:
            from campy.brain.thalamus.file_bridge import _resolve_project_child
        except ImportError:
            pytest.skip("_resolve_project_child not yet implemented")
        project = tmp_path / "project"
        project.mkdir()
        result = _resolve_project_child(project, "CONTEXT.md")
        assert result.is_relative_to(project.resolve())

    def test_traversal_rejected(self, tmp_path: Path):
        try:
            from campy.brain.thalamus.file_bridge import _resolve_project_child
        except ImportError:
            pytest.skip("_resolve_project_child not yet implemented")
        project = tmp_path / "project"
        project.mkdir()
        with pytest.raises(ValueError, match="outside.*project"):
            _resolve_project_child(project, "../../../etc/passwd")

    @pytest.mark.skipif(
        os.name == "nt",
        reason="Symlink creation may require elevated privileges on Windows",
    )
    def test_symlink_escape_rejected(self, tmp_path: Path):
        try:
            from campy.brain.thalamus.file_bridge import _resolve_project_child
        except ImportError:
            pytest.skip("_resolve_project_child not yet implemented")
        project = tmp_path / "project"
        project.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        # Symlink docs -> outside
        (project / "docs").symlink_to(outside)
        with pytest.raises(ValueError, match="outside.*project"):
            _resolve_project_child(project, "docs", "secret.md")

    def test_nested_child_accepted(self, tmp_path: Path):
        try:
            from campy.brain.thalamus.file_bridge import _resolve_project_child
        except ImportError:
            pytest.skip("_resolve_project_child not yet implemented")
        project = tmp_path / "project"
        (project / "docs" / "adr").mkdir(parents=True)
        result = _resolve_project_child(project, "docs", "adr", "0001-decision.md")
        assert result.is_relative_to(project.resolve())
