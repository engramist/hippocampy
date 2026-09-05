from __future__ import annotations
from campy.brain.hippocampus.graph.gateway import get_gateway
"""
mcp_engine/file_bridge.py — File Bridge: graph-to-file projection

Generates files from KuzuDB graph state so that external skills
(Claude Code, Gemini, Codex) can read structured project context
without direct graph access.

Generated artefacts:
  - CONTEXT.md          domain glossary from Concept nodes
  - docs/adr/NNNN-*.md  architecture decision records from Decision nodes
  - Agent config file pointers (CLAUDE.md, AGENTS.md, GEMINI.md)
"""


import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

CAMPY_POINTER = (
    "\n\n## Memory\n"
    "This project uses Campy for persistent memory. "
    "Call `memory_decision` before architectural decisions.\n"
)


def _resolve_project_child(project_path: Path, *parts: str) -> Path:
    """Resolve a child path and verify it stays inside the project root.

    Canonicalises both the project root and the target path with
    ``Path.resolve()`` (which follows symlinks) and checks that the
    target is still a descendant of the project root.

    Raises ``ValueError`` if the resolved target falls outside the
    project root — e.g. via ``../`` traversal or a symlink escape.
    """
    root = project_path.resolve()
    target = (project_path / Path(*parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError(
            f"Path escapes outside project root: "
            f"{target} is not under {root}"
        )
    return target


def _slugify(text: str, max_length: int = 50) -> str:
    """Lowercase, replace non-alphanumeric chars with hyphens, strip edges."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    slug = slug.strip("-")
    return slug[:max_length].rstrip("-")


def _truncate_to_sentences(text: str, max_sentences: int = 2) -> str:
    """Return the first *max_sentences* sentences of *text*."""
    if not text:
        return ""
    # Split on sentence-ending punctuation followed by whitespace
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    truncated = " ".join(parts[:max_sentences])
    # Ensure it ends with punctuation
    if truncated and truncated[-1] not in ".!?":
        truncated += "."
    return truncated


# ---------------------------------------------------------------------------
# Function 1 — CONTEXT.md
# ---------------------------------------------------------------------------

async def generate_context_md(project_path: Path, db: "KuzuClient") -> Path:
    """Query Concept nodes and render a CONTEXT.md glossary file."""

    # --- fetch concepts ---
    gw = get_gateway(db)
    rows = await gw.run("thalamus.file_bridge_concepts")

    # --- fetch relationships ---
    rel_rows = await gw.run("thalamus.file_bridge_concept_relationships")

    # --- fetch project description ---
    desc_rows = await gw.run("thalamus.file_bridge_global_constraints")

    project_name = project_path.name

    # Build description from GlobalConstraint nodes
    if desc_rows:
        desc_parts = [
            _truncate_to_sentences(r["text"], 1)
            for r in desc_rows
            if r.get("text")
        ]
        description = " ".join(desc_parts).strip() or "Project domain terminology."
    else:
        description = "Project domain terminology."

    # --- render ---
    lines: list[str] = [
        f"# {project_name}",
        "",
        description,
        "",
        "## Language",
        "",
    ]

    for row in rows:
        name = row.get("name") or ""
        definition = row.get("definition") or ""
        alt_labels = row.get("alt_labels") or ""

        # Skip concepts missing required fields
        if not name.strip() or not definition.strip():
            continue

        truncated_def = _truncate_to_sentences(definition, 2)

        lines.append(f"**{name}**:")
        lines.append(f"{truncated_def}")

        if alt_labels and alt_labels.strip():
            lines.append(f"_Avoid_: {alt_labels}")

        lines.append("")

    # --- relationships section (only if we have data) ---
    if rel_rows:
        lines.append("## Relationships")
        lines.append("")
        for rel in rel_rows:
            from_name = rel.get("from_name", "")
            rel_type = rel.get("rel_type", "")
            to_name = rel.get("to_name", "")
            if from_name and rel_type and to_name:
                lines.append(f"- {from_name} --[{rel_type}]--> {to_name}")
        lines.append("")

    output_path = _resolve_project_child(project_path, "CONTEXT.md")

    # B290: Preserve the ## Current Work section if it already exists.
    # CWS owns that section exclusively; regen must not overwrite it.
    current_work_block = ""
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        if "## Current Work" in existing:
            start = existing.index("## Current Work")
            next_h = existing.find("\n## ", start + 4)
            if next_h == -1:
                current_work_block = existing[start:]
            else:
                current_work_block = existing[start:next_h + 1]

    body = "\n".join(lines)
    if current_work_block:
        body = current_work_block.rstrip("\n") + "\n\n---\n\n" + body

    output_path.write_text(body, encoding="utf-8")
    _logger.info("Generated %s (%d concepts)", output_path, len(rows))
    return output_path


# ---------------------------------------------------------------------------
# Function 2 — ADR files
# ---------------------------------------------------------------------------

async def generate_adrs(project_path: Path, db: "KuzuClient") -> list[Path]:
    """Query Decision nodes and render Architecture Decision Record files."""

    gw = get_gateway(db)
    rows = await gw.run("thalamus.file_bridge_decisions")

    adr_dir = _resolve_project_child(project_path, "docs", "adr")
    adr_dir.mkdir(parents=True, exist_ok=True)

    # Load existing manifest
    manifest_path = adr_dir / ".campy-manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _logger.warning("Corrupt ADR manifest, starting fresh")
            manifest = {}
    else:
        manifest = {}

    generated = manifest.get("generated", {})
    written_paths: list[Path] = []

    for idx, row in enumerate(rows, start=1):
        decision_id = str(row.get("id", ""))
        title = row.get("title") or ""
        context = row.get("context") or ""

        if not title.strip():
            continue

        slug = _slugify(title)
        filename = f"{idx:04d}-{slug}.md"

        content = f"# {title}\n\n{_truncate_to_sentences(context, 3)}\n"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Skip if already in manifest with same hash
        if decision_id in generated:
            existing = generated[decision_id]
            if existing.get("hash") == content_hash:
                _logger.debug("ADR %s unchanged, skipping", decision_id)
                continue

        file_path = adr_dir / filename
        file_path.write_text(content, encoding="utf-8")
        written_paths.append(file_path)

        generated[decision_id] = {"file": filename, "hash": content_hash}
        _logger.info("Generated ADR %s -> %s", decision_id, filename)

    # Persist manifest
    manifest["generated"] = generated
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    return written_paths


# ---------------------------------------------------------------------------
# Function 3 — Agent config pointers
# ---------------------------------------------------------------------------

def generate_agent_pointers(project_path: Path) -> list[str]:
    """Append memory pointer to agent config files that lack one.

    Only appends, never overwrites, never creates files that don't exist.
    """
    modified: list[str] = []
    for filename in ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]:
        filepath = _resolve_project_child(project_path, filename)
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            if "memory_decision" not in content:
                filepath.write_text(content + CAMPY_POINTER, encoding="utf-8")
                modified.append(filename)
    return modified


# ---------------------------------------------------------------------------
# Function 4 — Orchestrator
# ---------------------------------------------------------------------------

async def regen_all(project_path: Path, db: "KuzuClient") -> dict:
    """Regenerate all file-bridge artefacts and return a summary."""
    context_path = await generate_context_md(project_path, db)
    adr_paths = await generate_adrs(project_path, db)
    pointer_files = generate_agent_pointers(project_path)

    return {
        "context_md": str(context_path),
        "adrs_generated": len(adr_paths),
        "adr_paths": [str(p) for p in adr_paths],
        "pointers_modified": pointer_files,
    }


# ---------------------------------------------------------------------------
# Function 5 — Bidirectional sync check
# ---------------------------------------------------------------------------

async def check_file_changes(
    project_path: Path,
    db: "KuzuClient",
    last_mtimes: dict,
) -> dict:
    """Check if CONTEXT.md or ADR files were manually edited.

    Returns updated mtimes dict for the caller to persist across calls.
    """
    files_to_check: list[Path] = []

    context_path = _resolve_project_child(project_path, "CONTEXT.md")
    if context_path.exists():
        files_to_check.append(context_path)

    adr_dir = _resolve_project_child(project_path, "docs", "adr")
    if adr_dir.exists():
        files_to_check.extend(
            p for p in adr_dir.glob("*.md")
            if p.name != ".campy-manifest.json"
        )

    for filepath in files_to_check:
        current_mtime = filepath.stat().st_mtime
        last_mtime = last_mtimes.get(str(filepath), 0)
        if current_mtime > last_mtime + 5:  # 5s debounce for our own writes
            _logger.info(
                "Detected manual edit to %s, queuing for ingestion", filepath
            )
            # Queue the file content for GCL ingestion via the ingest_document
            # pattern.  For now, log it — full ingestion wiring comes in daemon
            # integration.
        last_mtimes[str(filepath)] = current_mtime

    return last_mtimes
