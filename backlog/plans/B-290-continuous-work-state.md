# B290 — Continuous Work State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maintain a live WorkSummary per session so any agent (Claude Code, Codex, Gemini CLI, VS Code Copilot) can pick up where the previous agent left off with zero user action.

**Architecture:** Every `notify_turn` call fires a non-blocking background coroutine that upserts a `WorkSummary` node and rewrites the `## Current Work` section of `CONTEXT.md`. The session_start hook reads that section and injects the resume line before the first agent message. A post-commit git hook forces a checkpoint on every commit.

**Tech Stack:** Python 3.14, KuzuDB (Cypher), bash, asyncio, subprocess for git reads.

**Spec:** `docs/superpowers/specs/2026-06-26-continuous-work-state-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `campy/brain/hippocampus/schema.py` | Modify | Add WorkSummary + WorkArtifact node DDLs + rel tables |
| `campy/brain/thalamus/tools/work_summary.py` | Create | Core CWS module: git read, resume line, snapshot, CONTEXT.md write |
| `campy/brain/thalamus/tools/__init__.py` | Modify | Fire `update_work_summary` task at end of `notify_turn`; add `register_artifact` tool |
| `adapters/claude_code/hook_user_turn.py` | Modify | Pass `agent_source`, `repo_root`, `git_branch` in notify_turn params |
| `campy/brain/thalamus/file_bridge.py` | Modify | Preserve `## Current Work` section during `generate_context_md` |
| `adapters/claude_code/hooks/session_start.sh` | Modify | Inject resume line from CONTEXT.md at session start |
| `campy/cli/notify_turn_cmd.py` | Create | `campy notify-turn` CLI wrapper for the post-commit hook |
| `campy/cli/main.py` | Modify | Register `notify-turn` CLI subcommand |
| `.githooks/post-commit` | Create | Force WorkSummary checkpoint on every commit |
| `adapters/claude_code/setup.py` | Modify | Run `git config core.hooksPath .githooks` during setup |
| `adapters/claude_code/hooks/post_tool_use.sh` | Modify | Detect `*.md` Write/Edit and call `register_artifact` |
| `tests/test_cws.py` | Create | Tests for work_summary.py, schema nodes, CONTEXT.md writer |
| `tests/test_register_artifact.py` | Create | Tests for register_artifact MCP tool |

---

## Task 1: Schema — WorkSummary and WorkArtifact nodes

**Files:**
- Modify: `campy/brain/hippocampus/schema.py`
- Test: `tests/test_cws.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/test_cws.py`:

```python
# tests/test_cws.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_work_summary_node_exists_in_schema():
    """WorkSummary must be a registered node table."""
    from campy.brain.hippocampus.schema import _NODE_TABLES
    assert "WorkSummary" in _NODE_TABLES
    ddl = _NODE_TABLES["WorkSummary"]
    assert "summary_id" in ddl
    assert "resume_line" in ddl
    assert "snapshot_text" in ddl
    assert "git_branch" in ddl
    assert "turn_count" in ddl


def test_work_artifact_node_exists_in_schema():
    """WorkArtifact must be a registered node table."""
    from campy.brain.hippocampus.schema import _NODE_TABLES
    assert "WorkArtifact" in _NODE_TABLES
    ddl = _NODE_TABLES["WorkArtifact"]
    assert "artifact_id" in ddl
    assert "file_path" in ddl
    assert "document_type" in ddl
    assert "title" in ddl
    assert "summary" in ddl
    assert "linked_card" in ddl
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
pytest tests/test_cws.py::test_work_summary_node_exists_in_schema tests/test_cws.py::test_work_artifact_node_exists_in_schema -v
```

Expected: `FAILED` — `WorkSummary` not in `_NODE_TABLES`.

- [ ] **Step 1.3: Add WorkSummary DDL to schema.py**

In `campy/brain/hippocampus/schema.py`, find `_NODE_TABLES = {` and add these two entries alongside the other node definitions (after the `Session` entry is a good location):

```python
    "WorkSummary": """
        summary_id      STRING,
        session_id      STRING,
        agent_source    STRING,
        git_branch      STRING,
        git_commit      STRING,
        active_card     STRING,
        resume_line     STRING,
        snapshot_text   STRING,
        turn_count      INT32,
        last_updated_at TIMESTAMP,
        PRIMARY KEY (summary_id)
    """,

    "WorkArtifact": """
        artifact_id      STRING,
        file_path        STRING,
        document_type    STRING,
        title            STRING,
        summary          STRING,
        linked_card      STRING,
        session_id       STRING,
        agent_source     STRING,
        created_at       TIMESTAMP,
        last_modified_at TIMESTAMP,
        PRIMARY KEY (artifact_id)
    """,
```

- [ ] **Step 1.4: Add relationship table DDLs**

In the same file, find the block of `CREATE REL TABLE` strings (around line 839 near `PLANNED_IN`) and add:

```python
    "CREATE REL TABLE IF NOT EXISTS CREATED_IN (FROM WorkArtifact TO Session)",
    "CREATE REL TABLE IF NOT EXISTS DOCUMENTS (FROM WorkArtifact TO Plan)",
```

- [ ] **Step 1.5: Run tests to verify they pass**

```bash
pytest tests/test_cws.py::test_work_summary_node_exists_in_schema tests/test_cws.py::test_work_artifact_node_exists_in_schema -v
```

Expected: both `PASSED`.

- [ ] **Step 1.6: Commit**

```bash
git add campy/brain/hippocampus/schema.py tests/test_cws.py
git commit -m "feat(cws): add WorkSummary and WorkArtifact node tables to schema (B290)"
```

---

## Task 2: work_summary.py — git read, resume line, CONTEXT.md writer

**Files:**
- Create: `campy/brain/thalamus/tools/work_summary.py`
- Test: `tests/test_cws.py`

- [ ] **Step 2.1: Write failing tests for resume line and CONTEXT.md writing**

Add to `tests/test_cws.py`:

```python
def test_read_git_state_returns_unknown_for_empty_root():
    from campy.brain.thalamus.tools.work_summary import _read_git_state
    branch, commit = _read_git_state("")
    assert branch == "unknown"
    assert commit == "unknown"


def test_write_context_md_section_creates_file(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="Working on B290 (branch: main · abc1234). Last active: 2026-06-26 via claude_code.",
        snapshot_text="",
        turn_count=1,
        agent_source="claude_code",
        branch="main",
        commit="abc1234",
        ts="2026-06-26 20:53",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "## Current Work" in content
    assert "Working on B290" in content
    assert "abc1234" in content


def test_write_context_md_section_preserves_existing_content(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section
    # Pre-existing CONTEXT.md with other sections
    (tmp_path / "CONTEXT.md").write_text(
        "# My Project\n\nSome description.\n\n## Language\n\n**foo**: bar\n"
    )
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="Working on B290.",
        snapshot_text="",
        turn_count=1,
        agent_source="claude_code",
        branch="main",
        commit="abc1234",
        ts="2026-06-26 20:53",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "## Current Work" in content
    assert "## Language" in content
    assert "**foo**" in content


def test_write_context_md_section_replaces_existing_current_work(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section
    (tmp_path / "CONTEXT.md").write_text(
        "## Current Work\n_Last active: old_\n\n**Resume:** Old resume line.\n\n## Language\n\n**foo**: bar\n"
    )
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="New resume line.",
        snapshot_text="",
        turn_count=1,
        agent_source="codex",
        branch="feat/x",
        commit="def5678",
        ts="2026-06-26 21:00",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "New resume line." in content
    assert "Old resume line." not in content
    assert "## Language" in content


def test_snapshot_written_at_interval(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section, _SNAPSHOT_INTERVAL
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="Resume.",
        snapshot_text="**Active card:** B290",
        turn_count=_SNAPSHOT_INTERVAL,
        agent_source="claude_code",
        branch="main",
        commit="abc",
        ts="2026-06-26 20:53",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "<details>" in content
    assert "**Active card:** B290" in content


def test_snapshot_not_written_between_intervals(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section, _SNAPSHOT_INTERVAL
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="Resume.",
        snapshot_text="should not appear",
        turn_count=_SNAPSHOT_INTERVAL - 1,
        agent_source="claude_code",
        branch="main",
        commit="abc",
        ts="2026-06-26 20:53",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "<details>" not in content
    assert "should not appear" not in content
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
pytest tests/test_cws.py -k "git_state or context_md" -v
```

Expected: `ModuleNotFoundError` — `work_summary` not yet created.

- [ ] **Step 2.3: Create work_summary.py**

Create `campy/brain/thalamus/tools/work_summary.py`:

```python
"""
campy/brain/thalamus/tools/work_summary.py

Continuous Work State (CWS) — B290.

Maintains a live WorkSummary node per session, updated on every turn
via a non-blocking background task fired from notify_turn. Also writes
the ## Current Work section of CONTEXT.md so any agent reading the
project directory gets the resume line without querying the daemon.
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = 10  # turns between full snapshot updates
# Export as _SNAPSHOT_INTERVAL for tests
_SNAPSHOT_INTERVAL = SNAPSHOT_INTERVAL


def _read_git_state(repo_root: str) -> tuple[str, str]:
    """Return (branch, short_commit). Falls back to ('unknown', 'unknown')."""
    if not repo_root:
        return "unknown", "unknown"
    try:
        branch = subprocess.check_output(
            ["git", "-C", repo_root, "branch", "--show-current"],
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode().strip() or "unknown"
        commit = subprocess.check_output(
            ["git", "-C", repo_root, "log", "-1", "--format=%h"],
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode().strip() or "unknown"
        return branch, commit
    except Exception:
        return "unknown", "unknown"


async def _get_active_plan_info(session_id: str, db: "KuzuClient") -> tuple[str, str]:
    """Return (active_card, plan_goal) for the session's most recent plan."""
    try:
        rows = await db.execute_read(
            "MATCH (p:Plan)-[:PLANNED_IN]->(s:Session {session_id: $sid}) "
            "WHERE p.archived = false "
            "RETURN p.plan_id, p.goal "
            "ORDER BY p.created_at DESC LIMIT 1",
            {"sid": session_id},
        )
        if rows:
            row = rows[0]
            goal = row.get("p.goal") or row.get("goal") or ""
            # Extract card ID e.g. "B290" from goal text
            m = re.search(r'\bB\d+\b', goal)
            card = m.group(0) if m else (goal[:30] if goal else "No active card")
            return card, goal
    except Exception:
        _logger.debug("_get_active_plan_info failed for session %s", session_id, exc_info=True)
    return "No active card", ""


def _build_resume_line(
    card: str,
    goal: str,
    branch: str,
    commit: str,
    agent_source: str,
    ts: str,
) -> str:
    """Build a ~50-token resume line."""
    parts = []
    if card and card != "No active card":
        parts.append(f"Working on {card}")
    else:
        parts.append("No active card")
    parts.append(f"(branch: {branch} · {commit}).")
    if goal and card != "No active card":
        # Truncate long goals
        short_goal = goal[:80] + "…" if len(goal) > 80 else goal
        parts.append(f"Goal: {short_goal}.")
    parts.append(f"Last active: {ts} via {agent_source}.")
    return " ".join(parts)


async def _build_snapshot(session_id: str, db: "KuzuClient", turn_count: int) -> str:
    """Build the full ~800-token snapshot markdown string."""
    lines: list[str] = []

    # Active card
    card, goal = await _get_active_plan_info(session_id, db)
    lines.append(f"**Active card:** {card}")
    if goal and card != "No active card":
        lines.append(f"**Goal:** {goal[:120]}")

    # Recent decisions
    try:
        dec_rows = await db.execute_read(
            "MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid}) "
            "WHERE d.archived = false "
            "RETURN d.text_raw "
            "ORDER BY d.created_at DESC LIMIT 5",
            {"sid": session_id},
        )
        if dec_rows:
            lines.append("**Recent decisions:**")
            for r in dec_rows:
                text = r.get("d.text_raw") or r.get("text_raw") or ""
                if text:
                    lines.append(f"- {text[:120]}")
    except Exception:
        _logger.debug("snapshot: decision query failed", exc_info=True)

    # Files in flight via WorkArtifact
    try:
        art_rows = await db.execute_read(
            "MATCH (wa:WorkArtifact)-[:CREATED_IN]->(s:Session {session_id: $sid}) "
            "RETURN wa.file_path, wa.title "
            "ORDER BY wa.last_modified_at DESC LIMIT 10",
            {"sid": session_id},
        )
        if art_rows:
            lines.append("**Files in flight:**")
            for r in art_rows:
                fp = r.get("wa.file_path") or r.get("file_path") or ""
                title = r.get("wa.title") or r.get("title") or ""
                if fp:
                    suffix = f" — {title}" if title else ""
                    lines.append(f"- {fp}{suffix}")
    except Exception:
        _logger.debug("snapshot: artifact query failed", exc_info=True)

    return "\n".join(lines)


def _write_context_md_section(
    project_root: str,
    resume_line: str,
    snapshot_text: str,
    turn_count: int,
    agent_source: str,
    branch: str,
    commit: str,
    ts: str,
) -> None:
    """Write/replace the '## Current Work' section in CONTEXT.md."""
    if not project_root:
        return
    context_path = Path(project_root) / "CONTEXT.md"

    header = (
        f"## Current Work\n"
        f"_Last active: {ts} via {agent_source} — branch: {branch} ({commit})_\n"
    )
    resume_block = f"\n**Resume:** {resume_line}\n"

    should_show_snapshot = (
        snapshot_text
        and turn_count > 0
        and (turn_count % _SNAPSHOT_INTERVAL == 0)
    )
    if should_show_snapshot:
        details_block = (
            f"\n<details>\n"
            f"<summary>Session snapshot (turn {turn_count})</summary>\n\n"
            f"{snapshot_text}\n\n"
            f"</details>\n"
        )
    else:
        details_block = ""

    new_section = header + resume_block + details_block

    if context_path.exists():
        original = context_path.read_text(encoding="utf-8")
        if "## Current Work" in original:
            start = original.index("## Current Work")
            # Find next ## heading after this section
            next_h = original.find("\n## ", start + 4)
            if next_h == -1:
                updated = original[:start] + new_section
            else:
                updated = original[:start] + new_section + "\n" + original[next_h + 1:]
        else:
            # Prepend before existing content
            updated = new_section + "\n---\n\n" + original
        context_path.write_text(updated, encoding="utf-8")
    else:
        context_path.write_text(new_section, encoding="utf-8")


async def update_work_summary(
    session_id: str,
    db: "KuzuClient",
    config: dict,
    agent_source: str = "mcp",
    repo_root: str = "",
) -> None:
    """
    Main entry point — called from notify_turn as asyncio.create_task.

    Always updates resume_line. Updates snapshot every SNAPSHOT_INTERVAL turns.
    Never raises — all errors are logged at DEBUG and swallowed so the caller
    (notify_turn) is never affected.
    """
    if session_id == "unknown":
        return
    try:
        branch, commit = _read_git_state(repo_root)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        summary_id = f"ws-{session_id}"
        now_iso = datetime.now(timezone.utc).isoformat()

        # Get current turn_count from existing node
        existing = await db.execute_read(
            "MATCH (ws:WorkSummary {summary_id: $sid}) RETURN ws.turn_count",
            {"sid": summary_id},
        )
        if existing:
            tc = existing[0].get("ws.turn_count") or existing[0].get("turn_count")
            turn_count = int(tc or 0) + 1
        else:
            turn_count = 1

        card, goal = await _get_active_plan_info(session_id, db)
        resume_line = _build_resume_line(card, goal, branch, commit, agent_source, ts)

        should_snapshot = (turn_count % _SNAPSHOT_INTERVAL == 0)
        snapshot_text = ""
        if should_snapshot:
            snapshot_text = await _build_snapshot(session_id, db, turn_count)

        # Upsert WorkSummary node
        if existing:
            set_clause = (
                "ws.resume_line = $rl, ws.turn_count = $tc, "
                "ws.last_updated_at = timestamp($ts), ws.git_branch = $br, "
                "ws.git_commit = $co, ws.agent_source = $as, ws.active_card = $card"
            )
            params: dict = {
                "sid": summary_id, "rl": resume_line, "tc": turn_count,
                "ts": now_iso, "br": branch, "co": commit,
                "as": agent_source, "card": card,
            }
            if should_snapshot:
                set_clause += ", ws.snapshot_text = $snap"
                params["snap"] = snapshot_text
            await db.execute_write(
                f"MATCH (ws:WorkSummary {{summary_id: $sid}}) SET {set_clause}",
                params,
            )
        else:
            await db.execute_write(
                "CREATE (ws:WorkSummary {"
                "  summary_id: $sid, session_id: $sess, agent_source: $as, "
                "  git_branch: $br, git_commit: $co, active_card: $card, "
                "  resume_line: $rl, snapshot_text: $snap, turn_count: $tc, "
                "  last_updated_at: timestamp($ts)"
                "})",
                {
                    "sid": summary_id, "sess": session_id, "as": agent_source,
                    "br": branch, "co": commit, "card": card,
                    "rl": resume_line, "snap": snapshot_text,
                    "tc": turn_count, "ts": now_iso,
                },
            )

        _write_context_md_section(
            repo_root, resume_line, snapshot_text,
            turn_count, agent_source, branch, commit, ts,
        )

    except Exception:
        _logger.debug(
            "update_work_summary failed for session %s", session_id, exc_info=True
        )
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
pytest tests/test_cws.py -k "git_state or context_md or snapshot" -v
```

Expected: all 6 tests `PASSED`.

- [ ] **Step 2.5: Commit**

```bash
git add campy/brain/thalamus/tools/work_summary.py tests/test_cws.py
git commit -m "feat(cws): add work_summary module — git read, resume line, CONTEXT.md writer (B290)"
```

---

## Task 3: Wire update_work_summary into notify_turn

**Files:**
- Modify: `campy/brain/thalamus/tools/__init__.py`
- Modify: `adapters/claude_code/hook_user_turn.py`
- Test: `tests/test_cws.py`

- [ ] **Step 3.1: Write failing test**

Add to `tests/test_cws.py`:

```python
@pytest.mark.asyncio
async def test_notify_turn_fires_update_work_summary():
    """notify_turn must fire update_work_summary as a background task."""
    from campy.brain.thalamus.tools import notify_turn

    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[])
    mock_db.execute_write = AsyncMock(return_value=None)
    mock_db.execute = MagicMock()
    mock_db.execute.return_value.has_next.return_value = False

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}

    fired = []

    async def fake_update(session_id, db, config, agent_source="mcp", repo_root=""):
        fired.append(session_id)

    with patch("campy.brain.thalamus.tools.work_summary.update_work_summary", side_effect=fake_update), \
         patch("campy.brain.hippocampus.graph.embeddings.embed", return_value=[0.1] * 384), \
         patch("campy.brain.thalamus.tools.get_or_create_main_quest", new_callable=AsyncMock, return_value="q1"), \
         patch("campy.brain.thalamus.tools.get_or_create_session", new_callable=AsyncMock):
        await notify_turn(
            {"role": "user", "content": "hello", "session_id": "sess-cws-1",
             "repo_root": "/tmp/repo", "agent_source": "claude_code"},
            mock_db, config,
        )
        # Allow background task to run
        await asyncio.sleep(0)

    assert "sess-cws-1" in fired
```

- [ ] **Step 3.2: Run test to verify it fails**

```bash
pytest tests/test_cws.py::test_notify_turn_fires_update_work_summary -v
```

Expected: `FAILED` — `fired` is empty (task not yet fired).

- [ ] **Step 3.3: Add asyncio.create_task call to notify_turn**

In `campy/brain/thalamus/tools/__init__.py`, find the `return response` at the end of `notify_turn` (around line 1060) and add the background task immediately before it:

```python
    # B290: Continuous Work State — fire non-blocking WorkSummary update.
    # Use module-level attribute access (_cws.update_work_summary) so that
    # tests can patch the function via patch("...work_summary.update_work_summary")
    # without the `from ... import` reference-copy defeating the mock.
    if session_id != "unknown":
        try:
            from campy.brain.thalamus.tools import work_summary as _cws
            _agent_source = params.get("agent_source", "mcp")
            asyncio.create_task(
                _cws.update_work_summary(session_id, db, config, _agent_source, repo_root)
            )
        except Exception:
            pass  # Never block the response path

    return response
```

- [ ] **Step 3.4: Update hook_user_turn.py to pass agent_source, repo_root, git_branch**

In `adapters/claude_code/hook_user_turn.py`, replace the `params` construction:

```python
    import os
    import subprocess

    repo_root = ""
    git_branch = "main"
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
        git_branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
    except Exception:
        pass

    params = {
        "role": "user",
        "content": content,
        "session_id": session_id,
        "agent_source": "claude_code",
        "repo_root": repo_root,
        "git_branch": git_branch,
    }
```

Replace the existing `params = {"role": "user", "content": content, "session_id": session_id}` line.

- [ ] **Step 3.5: Run test to verify it passes**

```bash
pytest tests/test_cws.py::test_notify_turn_fires_update_work_summary -v
```

Expected: `PASSED`.

- [ ] **Step 3.6: Run existing notify_turn tests to confirm no regression**

```bash
pytest tests/test_ask_orchestrator.py -v
```

Expected: all `PASSED`.

- [ ] **Step 3.7: Commit**

```bash
git add campy/brain/thalamus/tools/__init__.py adapters/claude_code/hook_user_turn.py tests/test_cws.py
git commit -m "feat(cws): wire update_work_summary into notify_turn; pass agent_source from hook (B290)"
```

---

## Task 4: Guard generate_context_md against overwriting ## Current Work

**Files:**
- Modify: `campy/brain/thalamus/file_bridge.py`
- Test: `tests/test_cws.py`

- [ ] **Step 4.1: Write failing test**

Add to `tests/test_cws.py`:

```python
@pytest.mark.asyncio
async def test_generate_context_md_preserves_current_work_section(tmp_path):
    """campy context regen must not overwrite the ## Current Work section."""
    from campy.brain.thalamus.file_bridge import generate_context_md

    # Pre-write a CONTEXT.md with a Current Work section
    context_file = tmp_path / "CONTEXT.md"
    context_file.write_text(
        "## Current Work\n_Last active: now_\n\n**Resume:** Working on B290.\n\n"
        "## Language\n\n**foo**: bar\n"
    )

    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[])

    await generate_context_md(tmp_path, mock_db)

    content = context_file.read_text()
    assert "## Current Work" in content
    assert "Working on B290" in content
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
pytest tests/test_cws.py::test_generate_context_md_preserves_current_work_section -v
```

Expected: `FAILED` — "Working on B290" not found (generate_context_md overwrites the file).

- [ ] **Step 4.3: Add Current Work preservation to generate_context_md**

In `campy/brain/thalamus/file_bridge.py`, find `generate_context_md`. Before the final `output_path.write_text(...)` line (around line 165), add:

```python
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
```

Also remove (or change) the existing `output_path.write_text("\n".join(lines), encoding="utf-8")` line that comes just after — replace it with the block above so there's only one write.

- [ ] **Step 4.4: Run test to verify it passes**

```bash
pytest tests/test_cws.py::test_generate_context_md_preserves_current_work_section -v
```

Expected: `PASSED`.

- [ ] **Step 4.5: Commit**

```bash
git add campy/brain/thalamus/file_bridge.py tests/test_cws.py
git commit -m "feat(cws): preserve ## Current Work section in generate_context_md (B290)"
```

---

## Task 5: session_start.sh — inject resume line

**Files:**
- Modify: `adapters/claude_code/hooks/session_start.sh`

- [ ] **Step 5.1: Update session_start.sh**

In `adapters/claude_code/hooks/session_start.sh`, add a new block at the top, immediately after the `set -euo pipefail` line and before the `command -v campy` check:

```bash
# B290: Inject resume line from CONTEXT.md ## Current Work section.
# Fast path — no daemon required, reads a plain file.
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
CONTEXT_FILE="$REPO_ROOT/CONTEXT.md"
if [ -f "$CONTEXT_FILE" ]; then
    RESUME=$(grep -A 3 "^## Current Work" "$CONTEXT_FILE" 2>/dev/null \
      | grep "^\*\*Resume:\*\*" | sed 's/\*\*Resume:\*\* //')
    if [ -n "$RESUME" ]; then
        # Validate branch still exists (BSD-compatible — no grep -P)
        BRANCH=$(echo "$RESUME" | sed -n 's/.*branch: \([^ ·)]*\).*/\1/p')
        if [ -n "$BRANCH" ] && ! git branch --list "$BRANCH" 2>/dev/null | grep -q "$BRANCH"; then
            RESUME="$RESUME (note: branch $BRANCH no longer exists — may have been merged)"
        fi
        echo "[Campy] $RESUME"
    fi
fi
```

- [ ] **Step 5.2: Verify the script is valid bash**

```bash
bash -n adapters/claude_code/hooks/session_start.sh
```

Expected: no output (syntax valid).

- [ ] **Step 5.3: Smoke test the hook manually**

Create a temp CONTEXT.md and run the relevant lines:

```bash
TMPDIR=$(mktemp -d)
cat > "$TMPDIR/CONTEXT.md" <<'EOF'
## Current Work
_Last active: 2026-06-26 20:53 via claude_code — branch: main (abc1234)_

**Resume:** Working on B290 (branch: main · abc1234). Last active: 2026-06-26 via claude_code.

## Language

**foo**: bar
EOF

grep -A 3 "^## Current Work" "$TMPDIR/CONTEXT.md" | grep "^\*\*Resume:\*\*" | sed 's/\*\*Resume:\*\* //'
```

Expected output:
```
Working on B290 (branch: main · abc1234). Last active: 2026-06-26 via claude_code.
```

Clean up: `rm -rf "$TMPDIR"`

- [ ] **Step 5.4: Also copy the updated hook to .claude/hooks/ (project-level)**

```bash
cp adapters/claude_code/hooks/session_start.sh .claude/hooks/session_start.sh
```

- [ ] **Step 5.5: Commit**

```bash
git add adapters/claude_code/hooks/session_start.sh .claude/hooks/session_start.sh
git commit -m "feat(cws): inject resume line from CONTEXT.md in session_start hook (B290)"
```

---

## Task 6: campy notify-turn CLI + post-commit git hook + setup wiring

**Files:**
- Create: `campy/cli/notify_turn_cmd.py`
- Modify: `campy/cli/main.py`
- Create: `.githooks/post-commit`
- Modify: `adapters/claude_code/setup.py`

- [ ] **Step 6.1: Create notify_turn_cmd.py**

Create `campy/cli/notify_turn_cmd.py`:

```python
"""
campy/cli/notify_turn_cmd.py — `campy notify-turn` CLI subcommand.

Thin wrapper over call_brain("notify_turn", ...) used by the
.githooks/post-commit hook to force a WorkSummary checkpoint on commit.

Usage:
    campy notify-turn --role system --content "committed: abc1234 fix auth bug"
"""
import asyncio
import typer
from typing import Optional

app = typer.Typer(help="Send a turn to the Campy brain daemon.", hidden=True)


@app.callback(invoke_without_command=True)
def notify_turn_cmd(
    role: str = typer.Option("system", "--role", "-r", help="Role: user | assistant | system"),
    content: str = typer.Option(..., "--content", "-c", help="Turn content to capture"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s"),
):
    """Send a single turn to the daemon (used by git hooks and scripts)."""
    import os
    import subprocess

    repo_root = ""
    git_branch = "main"
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
        git_branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
    except Exception:
        pass

    sid = session_id or f"git-hook-{os.getpid()}"
    params = {
        "role": role,
        "content": content,
        "session_id": sid,
        "agent_source": "git_hook",
        "repo_root": repo_root,
        "git_branch": git_branch,
    }

    try:
        from campy.brain_transport import call_brain
        asyncio.run(call_brain("notify_turn", params, timeout=5.0))
    except Exception:
        pass  # Never block a commit
```

- [ ] **Step 6.2: Register notify-turn in main.py**

In `campy/cli/main.py`, find the other `app.add_typer` calls and add:

```python
from campy.cli.notify_turn_cmd import app as notify_turn_app
app.add_typer(notify_turn_app, name="notify-turn")
```

- [ ] **Step 6.3: Verify CLI is importable**

```bash
python3 -c "from campy.cli.notify_turn_cmd import app; print('ok')"
```

Expected: `ok`

- [ ] **Step 6.4: Create .githooks/post-commit**

```bash
mkdir -p .githooks
```

Create `.githooks/post-commit`:

```bash
#!/usr/bin/env bash
# B290: Force a WorkSummary checkpoint on every commit.
# Installed by: campy setup (git config core.hooksPath .githooks)
# The || true ensures a missing daemon never blocks a commit.
COMMIT=$(git log -1 --oneline 2>/dev/null || echo "unknown commit")
campy notify-turn --role system --content "committed: $COMMIT" 2>/dev/null || true
```

Make it executable:

```bash
chmod +x .githooks/post-commit
```

- [ ] **Step 6.5: Test post-commit hook dry run**

```bash
bash .githooks/post-commit
```

Expected: no error (may silently fail if daemon is down — that's correct behaviour).

- [ ] **Step 6.6: Add git config wiring to campy setup**

In `adapters/claude_code/setup.py`, find the `register()` function and add after the existing `install_hooks()` call:

```python
    # B290: Install .githooks directory as the project git hooks path
    _configure_git_hooks(project_root)
```

Add the new function:

```python
def _configure_git_hooks(project_root: Path) -> None:
    """Set core.hooksPath to .githooks so post-commit fires on every commit."""
    import subprocess
    githooks_dir = project_root / ".githooks"
    githooks_dir.mkdir(exist_ok=True)
    post_commit = githooks_dir / "post-commit"
    if not post_commit.exists():
        # Copy from repo if running from development checkout
        src = REPO_ROOT / ".githooks" / "post-commit"
        if src.exists():
            import shutil
            shutil.copy2(src, post_commit)
            post_commit.chmod(0o755)
    try:
        subprocess.run(
            ["git", "-C", str(project_root), "config", "core.hooksPath", ".githooks"],
            check=True, capture_output=True, timeout=5,
        )
    except Exception as e:
        print(f"  Warning: could not set core.hooksPath: {e}")
```

- [ ] **Step 6.7: Verify setup.py imports cleanly**

```bash
python3 -c "from adapters.claude_code.setup import register; print('ok')"
```

Expected: `ok`

- [ ] **Step 6.8: Commit**

```bash
git add campy/cli/notify_turn_cmd.py campy/cli/main.py .githooks/post-commit adapters/claude_code/setup.py
git commit -m "feat(cws): add campy notify-turn CLI, post-commit hook, setup wiring (B290)"
```

---

## Task 7: register_artifact MCP tool

**Files:**
- Modify: `campy/brain/thalamus/tools/__init__.py`
- Test: `tests/test_register_artifact.py`

- [ ] **Step 7.1: Write failing tests**

Create `tests/test_register_artifact.py`:

```python
# tests/test_register_artifact.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_register_artifact_upserts_new_node():
    from campy.brain.thalamus.tools import register_artifact

    written = []
    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[])  # no existing node
    async def capture_write(q, p=None):
        written.append((q, p))
    mock_db.execute_write = capture_write

    await register_artifact(
        {
            "file_path": "backlog/B290.md",
            "document_type": "backlog_card",
            "title": "B290 — Continuous Work State",
            "summary": "Cross-agent handoff via hot WorkSummary writes.",
            "linked_card": "B290",
            "session_id": "sess-1",
            "agent_source": "claude_code",
        },
        mock_db,
        {},
    )

    assert any("WorkArtifact" in q for q, _ in written)


@pytest.mark.asyncio
async def test_register_artifact_updates_existing_node():
    from campy.brain.thalamus.tools import register_artifact

    written = []
    # Simulate existing node
    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[{"wa.artifact_id": "art-1"}])
    async def capture_write(q, p=None):
        written.append((q, p))
    mock_db.execute_write = capture_write

    await register_artifact(
        {
            "file_path": "backlog/B290.md",
            "title": "Updated title",
            "session_id": "sess-1",
        },
        mock_db,
        {},
    )

    assert any("SET" in q for q, _ in written)


@pytest.mark.asyncio
async def test_register_artifact_infers_document_type_from_path():
    from campy.brain.thalamus.tools import register_artifact

    written_params = []
    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[])
    async def capture_write(q, p=None):
        written_params.append(p or {})
    mock_db.execute_write = capture_write

    await register_artifact(
        {"file_path": "docs/superpowers/specs/2026-06-26-cws.md", "session_id": "s1"},
        mock_db,
        {},
    )

    doc_types = [p.get("dt") for p in written_params if "dt" in p]
    assert any(dt == "spec" for dt in doc_types)


def test_register_artifact_in_tool_handlers():
    from campy.brain.thalamus.tools import TOOL_HANDLERS
    assert "register_artifact" in TOOL_HANDLERS
```

- [ ] **Step 7.2: Run tests to verify they fail**

```bash
pytest tests/test_register_artifact.py -v
```

Expected: `ImportError` or `KeyError` — `register_artifact` not yet defined.

- [ ] **Step 7.3: Implement register_artifact**

In `campy/brain/thalamus/tools/__init__.py`, add the function before the `TOOL_HANDLERS` dict:

```python
# ---------------------------------------------------------------------------
# B290: register_artifact — document provenance tracking
# ---------------------------------------------------------------------------

_ARTIFACT_TYPE_MAP = {
    "backlog/plans": "plan",
    "docs/superpowers/specs": "spec",
    "docs/superpowers": "spec",
    "backlog": "backlog_card",
    "docs": "spec",
}

def _infer_document_type(file_path: str) -> str:
    """Infer document_type from repo-relative file path."""
    for prefix, doc_type in _ARTIFACT_TYPE_MAP.items():
        if file_path.startswith(prefix):
            return doc_type
    name = file_path.lower()
    if "readme" in name:
        return "readme"
    if "adr" in name or "architecture" in name:
        return "adr"
    return "other"


async def register_artifact(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Upsert a WorkArtifact node for a structured document.

    params: {
        file_path     STRING  required — repo-relative path
        document_type STRING  optional — inferred from path if absent
        title         STRING  optional
        summary       STRING  optional
        linked_card   STRING  optional — e.g. "B290"
        session_id    STRING  optional
        agent_source  STRING  optional
    }
    """
    import uuid as _uuid

    file_path = (params.get("file_path") or "").strip()
    if not file_path:
        return {"status": "skipped", "reason": "file_path required"}

    session_id = params.get("session_id", "unknown")
    agent_source = params.get("agent_source", "mcp")
    document_type = params.get("document_type") or _infer_document_type(file_path)
    title = params.get("title", "")
    summary = params.get("summary", "")
    linked_card = params.get("linked_card", "")

    # Infer linked_card from filename if not provided
    if not linked_card:
        import re as _re
        m = _re.search(r'\bB\d+\b', file_path)
        if m:
            linked_card = m.group(0)

    now_iso = datetime.now(timezone.utc).isoformat()

    # Check for existing node by file_path
    existing = await db.execute_read(
        "MATCH (wa:WorkArtifact {file_path: $fp}) RETURN wa.artifact_id",
        {"fp": file_path},
    )

    if existing:
        artifact_id = existing[0].get("wa.artifact_id") or existing[0].get("artifact_id")
        set_parts = ["wa.last_modified_at = timestamp($ts)"]
        up: dict = {"fp": file_path, "ts": now_iso}
        if title:
            set_parts.append("wa.title = $ti"); up["ti"] = title
        if summary:
            set_parts.append("wa.summary = $su"); up["su"] = summary
        if linked_card:
            set_parts.append("wa.linked_card = $lc"); up["lc"] = linked_card
        if document_type:
            set_parts.append("wa.document_type = $dt"); up["dt"] = document_type
        await db.execute_write(
            f"MATCH (wa:WorkArtifact {{file_path: $fp}}) SET {', '.join(set_parts)}",
            up,
        )
    else:
        artifact_id = str(_uuid.uuid4())
        await db.execute_write(
            "CREATE (wa:WorkArtifact {"
            "  artifact_id: $aid, file_path: $fp, document_type: $dt, "
            "  title: $ti, summary: $su, linked_card: $lc, "
            "  session_id: $sess, agent_source: $as, "
            "  created_at: timestamp($ts), last_modified_at: timestamp($ts)"
            "})",
            {
                "aid": artifact_id, "fp": file_path, "dt": document_type,
                "ti": title, "su": summary, "lc": linked_card,
                "sess": session_id, "as": agent_source, "ts": now_iso,
            },
        )
        # Link to Session if known
        if session_id and session_id != "unknown":
            try:
                await db.execute_write(
                    "MATCH (wa:WorkArtifact {artifact_id: $aid}), "
                    "      (s:Session {session_id: $sid}) "
                    "MERGE (wa)-[:CREATED_IN]->(s)",
                    {"aid": artifact_id, "sid": session_id},
                )
            except Exception:
                pass

    return {"status": "ok", "artifact_id": artifact_id, "file_path": file_path}
```

- [ ] **Step 7.4: Register in TOOL_HANDLERS**

In `campy/brain/thalamus/tools/__init__.py`, find the `TOOL_HANDLERS` dict and add:

```python
    "register_artifact": _with_phase("encoding", register_artifact),
```

Add it after `"upsert_lesson"` in the encoding phase section.

- [ ] **Step 7.5: Run tests to verify they pass**

```bash
pytest tests/test_register_artifact.py -v
```

Expected: all 4 tests `PASSED`.

- [ ] **Step 7.6: Commit**

```bash
git add campy/brain/thalamus/tools/__init__.py tests/test_register_artifact.py
git commit -m "feat(cws): add register_artifact MCP tool for document provenance (B290)"
```

---

## Task 8: PostToolUse hook — auto-capture *.md file writes

**Files:**
- Modify: `adapters/claude_code/hooks/post_tool_use.sh`

- [ ] **Step 8.1: Add *.md detection block to post_tool_use.sh**

In `adapters/claude_code/hooks/post_tool_use.sh`, after the existing manifest-matching `PYEOF` block (after line 73), add:

```bash

# B290: WorkArtifact — auto-capture when agent writes/edits a *.md file.
# CLAUDE_TOOL_NAME is set by Claude Code for every PostToolUse call.
if [ "${CLAUDE_TOOL_NAME:-}" = "Write" ] || [ "${CLAUDE_TOOL_NAME:-}" = "Edit" ]; then
    # Extract file path from tool output (last line often contains the path)
    FILE_PATH=$(echo "$TOOL_OUTPUT" | grep -o '[^ ]*\.md' | head -1)
    if [ -n "$FILE_PATH" ] && [ -f "$FILE_PATH" ]; then
        # Extract title (first # heading) and summary (first non-heading line > 20 chars)
        TITLE=$(grep -m1 "^# " "$FILE_PATH" 2>/dev/null | sed 's/^# //')
        SUMMARY=$(grep -v "^#" "$FILE_PATH" 2>/dev/null | grep -v "^$" | awk 'length > 20 {print; exit}' | cut -c1-120)
        # Infer session from env (Claude Code sets CLAUDE_SESSION_ID)
        SESSION="${CLAUDE_SESSION_ID:-unknown}"

        python3 - "$FILE_PATH" "$TITLE" "$SUMMARY" "$SESSION" <<'ARTIFACT_EOF'
import sys, json, os
try:
    from campy.brain_transport import call_brain
    import asyncio
    file_path, title, summary, session_id = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    # Make path repo-relative
    try:
        import subprocess
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        if file_path.startswith("/"):
            rel = os.path.relpath(file_path, repo_root)
        else:
            rel = file_path
    except Exception:
        rel = file_path
    params = {
        "file_path": rel,
        "title": title,
        "summary": summary,
        "session_id": session_id,
        "agent_source": "claude_code",
    }
    asyncio.run(call_brain("register_artifact", params, timeout=3.0))
except Exception:
    pass  # Never block the agent
ARTIFACT_EOF
    fi
fi
```

- [ ] **Step 8.2: Verify the script is valid bash**

```bash
bash -n adapters/claude_code/hooks/post_tool_use.sh
```

Expected: no output.

- [ ] **Step 8.3: Copy updated hook to project .claude/hooks/**

```bash
cp adapters/claude_code/hooks/post_tool_use.sh .claude/hooks/post_tool_use.sh
```

- [ ] **Step 8.4: Commit**

```bash
git add adapters/claude_code/hooks/post_tool_use.sh .claude/hooks/post_tool_use.sh
git commit -m "feat(cws): auto-capture *.md file writes as WorkArtifact in PostToolUse hook (B290)"
```

---

## Task 9: Full integration verification

- [ ] **Step 9.1: Run the full test suite**

```bash
pytest tests/test_cws.py tests/test_register_artifact.py tests/test_ask_orchestrator.py tests/test_compression_graph.py -v
```

Expected: all tests `PASSED`.

- [ ] **Step 9.2: Verify WorkSummary schema creates cleanly**

```bash
python3 -c "
from campy.brain.hippocampus.schema import _NODE_TABLES
print('WorkSummary fields:', [f.strip().split()[0] for f in _NODE_TABLES['WorkSummary'].strip().split(',') if f.strip()])
print('WorkArtifact fields:', [f.strip().split()[0] for f in _NODE_TABLES['WorkArtifact'].strip().split(',') if f.strip()])
"
```

Expected: both lists contain the expected field names.

- [ ] **Step 9.3: Verify register_artifact is in TOOL_HANDLERS**

```bash
python3 -c "
from campy.brain.thalamus.tools import TOOL_HANDLERS
assert 'register_artifact' in TOOL_HANDLERS, 'MISSING'
print(f'register_artifact registered. Total tools: {len(TOOL_HANDLERS)}')
"
```

Expected: prints tool count (>= 52).

- [ ] **Step 9.4: Verify CONTEXT.md preservation end-to-end**

```bash
python3 -c "
import asyncio, tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from campy.brain.thalamus.file_bridge import generate_context_md
from campy.brain.thalamus.tools.work_summary import _write_context_md_section

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        # Simulate CWS writing first
        _write_context_md_section(tmp, 'Working on B290.', '', 1, 'claude_code', 'main', 'abc', '2026-06-26 20:53')
        assert 'Working on B290' in (p / 'CONTEXT.md').read_text()
        # Simulate campy context regen
        db = MagicMock(); db.execute_read = AsyncMock(return_value=[])
        await generate_context_md(p, db)
        content = (p / 'CONTEXT.md').read_text()
        assert 'Working on B290' in content, 'CWS section was overwritten!'
        print('PASS — Current Work preserved after regen')

asyncio.run(run())
"
```

Expected: `PASS — Current Work preserved after regen`

- [ ] **Step 9.5: Final commit**

```bash
git add -A
git status  # confirm nothing unexpected staged
git commit -m "feat(cws): B290 Continuous Work State — complete implementation

- WorkSummary + WorkArtifact nodes in schema
- Hot write in notify_turn via asyncio.create_task
- Resume line + 10-turn snapshot in CONTEXT.md
- session_start.sh injects resume line at session start
- post-commit git hook forces WorkSummary checkpoint
- register_artifact MCP tool for document provenance
- PostToolUse hook auto-captures *.md file writes
- generate_context_md preserves ## Current Work section

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Acceptance Criteria Checklist

- [ ] After 1 turn, `CONTEXT.md` has `## Current Work` with a populated resume line
- [ ] After 10 turns, `<details>` snapshot block is populated
- [ ] New Claude Code session injects resume line before first message
- [ ] `git commit` triggers a WorkSummary update via post-commit hook
- [ ] `campy context regen` does not overwrite `## Current Work`
- [ ] `register_artifact` upserts WorkArtifact and links to Session
- [ ] Writing a `.md` file creates a WorkArtifact node within one turn
- [ ] All existing tests pass — notify_turn is backward-compatible
- [ ] `MATCH (ws:WorkSummary) ORDER BY ws.last_updated_at DESC LIMIT 1` returns the latest state
