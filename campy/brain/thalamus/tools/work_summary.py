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
        # Plan.archived (BOOLEAN) and PLANNED_IN edge both confirmed in schema.py
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
