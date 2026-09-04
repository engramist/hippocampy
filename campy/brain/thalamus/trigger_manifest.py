from __future__ import annotations
from campy.brain.hippocampus.graph.gateway import get_gateway
"""
mcp_engine/trigger_manifest.py — Trigger Manifest Compiler (Phase 2)

Queries Procedure and Lesson nodes with trigger metadata from KuzuDB
and compiles a JSON manifest file. Claude Code hook scripts grep this
manifest on every tool call — zero daemon round-trip on the hot path.

Generated artefact:
  ~/.campy/triggers/manifest.json
"""


import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)


def get_manifest_path() -> Path:
    """Return the trigger manifest path, creating the directory if needed."""
    from campy.paths import runtime_dir
    d = runtime_dir() / "triggers"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d / "manifest.json"


def _build_snippet(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, breaking at sentence boundary if possible."""
    if not text or len(text) <= max_chars:
        return text or ""
    # Try to break at a sentence boundary
    truncated = text[:max_chars]
    last_period = truncated.rfind(".")
    if last_period > max_chars // 2:
        return truncated[:last_period + 1]
    return truncated.rstrip() + "..."


def _procedure_snippet(name: str, description: str, steps_json: str, max_chars: int) -> str:
    """Build a context snippet from a Procedure node's fields."""
    parts = []
    if name:
        parts.append(name)
    if description:
        parts.append(description)
    if steps_json:
        try:
            steps = json.loads(steps_json)
            if isinstance(steps, list):
                for i, step in enumerate(steps[:3], 1):
                    step_text = step if isinstance(step, str) else str(step)
                    parts.append(f"{i}. {step_text}")
        except (json.JSONDecodeError, TypeError):
            pass
    full_text = "\n".join(parts)
    return _build_snippet(full_text, max_chars)


async def compile_manifest(db: "KuzuClient", config: dict) -> dict:
    """Compile trigger manifest from graph state.

    Queries Procedure and Lesson nodes with non-empty trigger_pattern,
    writes a JSON manifest to ~/.campy/triggers/manifest.json.

    Returns: summary dict with counts.
    """
    max_snippet_chars = config.get("hooks", {}).get("max_snippet_chars", 2000)
    triggers = []
    procedure_count = 0
    lesson_count = 0

    # --- Procedures with triggers ---
    try:
        gw = get_gateway(db)
        proc_rows = await gw.run("thalamus.trigger_manifest_procedures")
    except Exception as e:
        _logger.warning("Failed to query Procedure triggers: %s", e)
        proc_rows = []

    for row in proc_rows:
        snippet = _procedure_snippet(
            row.get("name", ""),
            row.get("description", ""),
            row.get("steps_json", ""),
            max_snippet_chars,
        )
        triggers.append({
            "id": row.get("id", ""),
            "source_type": "procedure",
            "name": row.get("name", ""),
            "pattern": row.get("pattern", ""),
            "hook_type": row.get("hook_type", "PreToolUse"),
            "tool": row.get("tool", ""),
            "project_scope": row.get("project_scope", ""),
            "strength": row.get("strength", 1.0),
            "domain": row.get("domain", ""),
            "context_snippet": snippet,
        })
        procedure_count += 1

    # --- Lessons with triggers ---
    try:
        gw = get_gateway(db)
        lesson_rows = await gw.run("thalamus.trigger_manifest_lessons")
    except Exception as e:
        _logger.warning("Failed to query Lesson triggers: %s", e)
        lesson_rows = []

    for row in lesson_rows:
        text = row.get("text", "") or ""
        lesson_type = row.get("lesson_type", "")
        name = f"Lesson ({lesson_type})" if lesson_type else "Lesson"
        triggers.append({
            "id": row.get("id", ""),
            "source_type": "lesson",
            "name": name,
            "pattern": row.get("pattern", ""),
            "hook_type": row.get("hook_type", "PostToolUse"),
            "tool": row.get("tool", ""),
            "project_scope": row.get("project_scope", ""),
            "strength": row.get("strength", 1.0),
            "domain": row.get("domain", ""),
            "context_snippet": _build_snippet(text, max_snippet_chars),
        })
        lesson_count += 1

    # --- Write manifest atomically ---
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": 1,
        "triggers": triggers,
    }

    manifest_path = get_manifest_path()
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(manifest_path.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp_path, str(manifest_path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    _logger.info(
        "Compiled trigger manifest: %d triggers (%d procedures, %d lessons) -> %s",
        len(triggers), procedure_count, lesson_count, manifest_path,
    )

    return {
        "triggers_compiled": len(triggers),
        "procedures": procedure_count,
        "lessons": lesson_count,
        "manifest_path": str(manifest_path),
    }
