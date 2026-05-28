"""Tests for Phase 2 trigger manifest compiler and hook scripts."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Manifest compiler unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compile_manifest_empty_graph(tmp_path):
    """Manifest compiles to 0 triggers when graph has no trigger-bearing nodes."""
    from campy.brain.thalamus.trigger_manifest import compile_manifest

    db = AsyncMock()
    db.execute_read = AsyncMock(return_value=[])

    with patch("campy.brain.thalamus.trigger_manifest.get_manifest_path",
               return_value=tmp_path / "manifest.json"):
        result = await compile_manifest(db, {})

    assert result["triggers_compiled"] == 0
    assert result["procedures"] == 0
    assert result["lessons"] == 0

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["version"] == 1
    assert manifest["triggers"] == []
    assert "generated_at" in manifest


@pytest.mark.asyncio
async def test_compile_manifest_with_procedure_trigger(tmp_path):
    """Procedures with trigger_pattern appear in the compiled manifest."""
    from campy.brain.thalamus.trigger_manifest import compile_manifest

    proc_row = {
        "id": "proc-001",
        "name": "OD Container Setup",
        "description": "Run docker with OD env vars",
        "steps_json": '["export OAUTH_TOKEN", "docker run myimage"]',
        "pattern": "docker run|docker build",
        "hook_type": "PreToolUse",
        "tool": "Bash",
        "project_scope": "",
        "strength": 1.0,
        "domain": "ops",
    }

    db = AsyncMock()
    # First call returns procedures, second returns lessons
    db.execute_read = AsyncMock(side_effect=[[proc_row], []])

    with patch("campy.brain.thalamus.trigger_manifest.get_manifest_path",
               return_value=tmp_path / "manifest.json"):
        result = await compile_manifest(db, {})

    assert result["triggers_compiled"] == 1
    assert result["procedures"] == 1
    assert result["lessons"] == 0

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    trigger = manifest["triggers"][0]
    assert trigger["id"] == "proc-001"
    assert trigger["source_type"] == "procedure"
    assert trigger["pattern"] == "docker run|docker build"
    assert trigger["hook_type"] == "PreToolUse"
    assert trigger["tool"] == "Bash"
    assert "OD Container Setup" in trigger["context_snippet"]


@pytest.mark.asyncio
async def test_compile_manifest_with_lesson_trigger(tmp_path):
    """Lessons with trigger_pattern appear in the compiled manifest."""
    from campy.brain.thalamus.trigger_manifest import compile_manifest

    lesson_row = {
        "id": "lesson-001",
        "text": "SSO tokens expire after 8 hours. Run `aws sso login` to refresh.",
        "lesson_type": "edge-case",
        "pattern": "no AWS credentials|expired token|InvalidIdentityToken",
        "hook_type": "PostToolUse",
        "tool": "Bash",
        "project_scope": "",
        "strength": 0.9,
        "domain": "aws",
    }

    db = AsyncMock()
    db.execute_read = AsyncMock(side_effect=[[], [lesson_row]])

    with patch("campy.brain.thalamus.trigger_manifest.get_manifest_path",
               return_value=tmp_path / "manifest.json"):
        result = await compile_manifest(db, {})

    assert result["triggers_compiled"] == 1
    assert result["procedures"] == 0
    assert result["lessons"] == 1

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    trigger = manifest["triggers"][0]
    assert trigger["source_type"] == "lesson"
    assert trigger["hook_type"] == "PostToolUse"
    assert "SSO tokens" in trigger["context_snippet"]


@pytest.mark.asyncio
async def test_compile_manifest_snippet_truncation(tmp_path):
    """Context snippets are capped at max_snippet_chars."""
    from campy.brain.thalamus.trigger_manifest import compile_manifest

    long_text = "A" * 5000
    lesson_row = {
        "id": "lesson-long",
        "text": long_text,
        "lesson_type": "optimization",
        "pattern": "test",
        "hook_type": "PostToolUse",
        "tool": "",
        "project_scope": "",
        "strength": 1.0,
        "domain": "",
    }

    db = AsyncMock()
    db.execute_read = AsyncMock(side_effect=[[], [lesson_row]])

    config = {"hooks": {"max_snippet_chars": 200}}
    with patch("campy.brain.thalamus.trigger_manifest.get_manifest_path",
               return_value=tmp_path / "manifest.json"):
        result = await compile_manifest(db, config)

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    snippet = manifest["triggers"][0]["context_snippet"]
    assert len(snippet) <= 203  # 200 + "..."


# ---------------------------------------------------------------------------
# Hook script integration tests
# ---------------------------------------------------------------------------

HOOKS_DIR = Path("adapters/claude_code/hooks")


def test_pre_tool_use_no_manifest():
    """PreToolUse hook exits cleanly when no manifest exists."""
    result = subprocess.run(
        ["bash", str(HOOKS_DIR / "pre_tool_use.sh")],
        capture_output=True, text=True, timeout=10,
        env={
            **os.environ,
            "CLAUDE_TOOL_NAME": "Bash",
            "CLAUDE_TOOL_INPUT": '{"command":"echo hello"}',
            "CAMPY_TRIGGER_MANIFEST": "/tmp/campy_nonexistent_manifest.json",
        },
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_matches_pattern():
    """PreToolUse hook outputs context when pattern matches tool input."""
    manifest = {
        "version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "triggers": [
            {
                "id": "test-proc-1",
                "source_type": "procedure",
                "name": "Docker Setup",
                "pattern": "docker run|docker build",
                "hook_type": "PreToolUse",
                "tool": "Bash",
                "project_scope": "",
                "strength": 1.0,
                "context_snippet": "Always set OAUTH_TOKEN before running docker.",
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(manifest, f)
        manifest_path = f.name

    try:
        result = subprocess.run(
            ["bash", str(HOOKS_DIR / "pre_tool_use.sh")],
            capture_output=True, text=True, timeout=10,
            env={
                **os.environ,
                "CLAUDE_TOOL_NAME": "Bash",
                "CLAUDE_TOOL_INPUT": '{"command":"docker run myimage"}',
                "CAMPY_TRIGGER_MANIFEST": manifest_path,
            },
        )
        assert result.returncode == 0
        assert "Docker Setup" in result.stdout
        assert "OAUTH_TOKEN" in result.stdout
    finally:
        os.unlink(manifest_path)


def test_pre_tool_use_skips_wrong_tool():
    """PreToolUse hook produces no output when tool filter doesn't match."""
    manifest = {
        "version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "triggers": [
            {
                "id": "test-proc-1",
                "source_type": "procedure",
                "name": "Docker Setup",
                "pattern": "docker",
                "hook_type": "PreToolUse",
                "tool": "Bash",
                "project_scope": "",
                "strength": 1.0,
                "context_snippet": "Should not appear.",
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(manifest, f)
        manifest_path = f.name

    try:
        result = subprocess.run(
            ["bash", str(HOOKS_DIR / "pre_tool_use.sh")],
            capture_output=True, text=True, timeout=10,
            env={
                **os.environ,
                "CLAUDE_TOOL_NAME": "Edit",
                "CLAUDE_TOOL_INPUT": '{"file_path":"docker/Dockerfile"}',
                "CAMPY_TRIGGER_MANIFEST": manifest_path,
            },
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""
    finally:
        os.unlink(manifest_path)


def test_pre_tool_use_skips_post_tool_triggers():
    """PreToolUse hook ignores triggers with hook_type=PostToolUse."""
    manifest = {
        "version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "triggers": [
            {
                "id": "test-lesson-1",
                "source_type": "lesson",
                "name": "SSO Lesson",
                "pattern": "docker",
                "hook_type": "PostToolUse",
                "tool": "Bash",
                "project_scope": "",
                "strength": 1.0,
                "context_snippet": "Should not appear in PreToolUse.",
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(manifest, f)
        manifest_path = f.name

    try:
        result = subprocess.run(
            ["bash", str(HOOKS_DIR / "pre_tool_use.sh")],
            capture_output=True, text=True, timeout=10,
            env={
                **os.environ,
                "CLAUDE_TOOL_NAME": "Bash",
                "CLAUDE_TOOL_INPUT": '{"command":"docker run test"}',
                "CAMPY_TRIGGER_MANIFEST": manifest_path,
            },
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""
    finally:
        os.unlink(manifest_path)


def test_post_tool_use_hook_exists():
    """PostToolUse hook script exists and is executable."""
    hook = HOOKS_DIR / "post_tool_use.sh"
    assert hook.exists(), f"PostToolUse hook not found at {hook}"
    assert os.access(hook, os.X_OK), "PostToolUse hook is not executable"
    content = hook.read_text()
    assert "PostToolUse" in content
    assert "manifest" in content.lower()


def test_post_tool_use_no_manifest():
    """PostToolUse hook exits cleanly when no manifest exists."""
    result = subprocess.run(
        ["bash", str(HOOKS_DIR / "post_tool_use.sh")],
        capture_output=True, text=True, timeout=10,
        input="some error output",
        env={
            **os.environ,
            "CLAUDE_TOOL_NAME": "Bash",
            "CAMPY_TRIGGER_MANIFEST": "/tmp/campy_nonexistent_manifest.json",
        },
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------

def test_build_snippet_truncation():
    """_build_snippet respects max_chars and tries sentence boundaries."""
    from campy.brain.thalamus.trigger_manifest import _build_snippet

    # Short text — no truncation
    assert _build_snippet("Hello world.", 100) == "Hello world."

    # Long text with sentence boundary
    text = "First sentence. Second sentence. Third sentence is very long."
    result = _build_snippet(text, 35)
    assert result.endswith(".")
    assert len(result) <= 38  # some tolerance for boundary

    # Empty text
    assert _build_snippet("", 100) == ""
    assert _build_snippet(None, 100) == ""


def test_procedure_snippet_with_steps():
    """_procedure_snippet includes name and parsed steps."""
    from campy.brain.thalamus.trigger_manifest import _procedure_snippet

    steps_json = '["Step one", "Step two", "Step three"]'
    snippet = _procedure_snippet("My Proc", "A description.", steps_json, 2000)
    assert "My Proc" in snippet
    assert "Step one" in snippet
    assert "Step two" in snippet
