"""
campy/brain/thalamus/handoff.py — B383 Automated Model Handoff Generator.

Generates a markdown "Handoff Artifact" a developer can paste into a
different model's chat when switching mid-task, so the new model
doesn't start cold or reverse prior work. Builds on top of existing
infrastructure rather than duplicating it:

- Session -> quest resolution: same retrieval.get_main_quest_for_session
  pattern as model_router.py (B382).
- Active Plan(s): reuses model_router.get_active_plans_for_quest
  directly (Plan.status='active' via the real TARGETS edge to
  MainQuest).
- Execution DAG: reuses model_router.get_active_task_graph_for_session +
  task_graph.get_graph_tasks (TaskGraph/TaskNode.status) -- not
  ActionItem, which (like B382's card) B383's card also assumed has a
  status field it doesn't have.
- Decisions/Constraints/WorkArtifacts: new quest-scoped queries
  (queries/handoff.py) broadening B290's WorkSummary's session-only
  scope to the whole quest's history across sessions.
- Deprecated-fact exclusion: reuses the same
  thalamus.context_deprecated_by_out_{table} queries
  compile_card_context already proves out (B323).
- "[LOADED]" dedup: reuses working_memory.track_loaded/
  get_loaded_node_ids (B44) so a second handoff call for the same
  session doesn't repeat identical content.

Not built in v1 (see backlog/B383.md's completion notes for why):
"negative controls" are heuristically extracted from Constraint text,
not a first-class tracked entity (nothing in the schema tracks them);
"definition of done" is out of scope entirely (no signal anywhere to
build it from); SessionEnd-hook/Unix-socket automation is a v2 item.
"""

from __future__ import annotations

import re
import time

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus.model_router import (
    get_active_plans,
    get_active_task_graph_status,
    resolve_quest_id,
    row_get,
)
from campy.brain.thalamus.working_memory import get_loaded_node_ids, track_loaded

# Total entity boundary across all sections, matching the card's stated
# bound (verified by counting in generate_handoff, not just trusting the
# per-query LIMITs to compose correctly).
MAX_HANDOFF_NODES = 40

_NEGATIVE_CONTROL_PATTERN = re.compile(
    r"\b(do\s+not|don'?t|never|must\s+not|avoid|shall\s+not)\b",
    re.IGNORECASE,
)


def _gateway(db) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)


async def _get_quest_decisions(gw, quest_id: str) -> list[dict]:
    if not quest_id:
        return []
    try:
        rows = await gw.run("handoff.get_quest_decisions", qid=quest_id)
    except Exception:
        return []
    decisions = []
    for r in (rows or []):
        did = row_get(r, "decision_id", 0)
        if not did:
            continue
        decisions.append({
            "id": did,
            "text": row_get(r, "text_raw", 1),
            "confidence": row_get(r, "confidence", 2),
        })
    return decisions


async def _get_quest_constraints(gw, quest_id: str) -> list[dict]:
    if not quest_id:
        return []
    try:
        rows = await gw.run("handoff.get_quest_constraints", qid=quest_id)
    except Exception:
        return []
    constraints = []
    for r in (rows or []):
        cid = row_get(r, "constraint_id", 0)
        if not cid:
            continue
        constraints.append({
            "id": cid,
            "text": row_get(r, "text_raw", 1),
            "confidence": row_get(r, "confidence", 2),
        })
    return constraints


async def _get_quest_work_artifacts(gw, quest_id: str) -> list[dict]:
    if not quest_id:
        return []
    try:
        rows = await gw.run("handoff.get_quest_work_artifacts", qid=quest_id)
    except Exception:
        return []
    files = []
    for r in (rows or []):
        fp = row_get(r, "file_path", 0)
        if not fp:
            continue
        files.append({
            "file_path": fp,
            "title": row_get(r, "title", 1),
            "document_type": row_get(r, "document_type", 2),
        })
    return files


async def _exclude_deprecated(gw, table: str, items: list[dict]) -> list[dict]:
    """Drop items with an outgoing DEPRECATED_BY edge -- same per-node
    check compile_card_context._card_context_deprecated_by already
    proves out, reused directly against the same NamedQueries rather
    than importing that private helper across modules."""
    qname = f"thalamus.context_deprecated_by_out_{table.lower()}"
    kept = []
    for item in items:
        try:
            rows = await gw.run(qname, id=item["id"])
            if rows:
                continue  # has a newer replacement -- exclude
        except Exception:
            pass  # fail open: keep the item if the check itself fails
        kept.append(item)
    return kept


def _extract_negative_controls(constraints: list[dict]) -> list[str]:
    """Heuristic extraction only -- nothing in the schema tracks
    "do not do X" rules as a first-class entity (verified by direct
    grep before writing this; see backlog/B383.md). Flags constraint
    text containing negative-framed language, clearly labeled as
    heuristic in the rendered markdown, not asserted as authoritative."""
    negatives = []
    for c in constraints:
        text = c.get("text") or ""
        if _NEGATIVE_CONTROL_PATTERN.search(text):
            negatives.append(text)
    return negatives


def _cap_total_nodes(sections: dict, max_total: int) -> dict:
    """Enforce the ≤N total-node boundary across all sections combined,
    trimming the least-recent items first (each list is already ordered
    most-recent-first by its NamedQuery)."""
    order = ["decisions", "constraints", "task_nodes", "files"]
    counts = {k: len(sections.get(k) or []) for k in order}
    total = sum(counts.values())
    if total <= max_total:
        return sections
    over = total - max_total
    # Trim from the end of each list, round-robin, least-important
    # section last (files first, since they're supplementary context).
    trim_order = ["files", "task_nodes", "constraints", "decisions"]
    for key in trim_order:
        if over <= 0:
            break
        items = sections.get(key) or []
        trim_n = min(over, len(items))
        if trim_n > 0:
            sections[key] = items[: len(items) - trim_n]
            over -= trim_n
    return sections


async def generate_handoff(
    db,
    session_id: str = "unknown",
    quest_id: str | None = None,
    target_model_tier: str | None = None,
) -> dict:
    """
    Assemble a Handoff Artifact for `session_id`'s active quest.

    Returns:
        {
            "quest_id": str,
            "goal": str | None,
            "decisions": list[dict],
            "constraints": list[dict],
            "negative_controls": list[str],
            "task_graph_status": dict | None,
            "files": list[dict],
            "node_ids": list[str],
            "markdown": str,
            "latency_ms": float,
        }
    Never raises for a missing/cold-start quest -- always returns a
    usable (if mostly-empty) artifact.
    """
    start = time.perf_counter()
    gw = _gateway(db)

    resolved_quest_id = await resolve_quest_id(gw, session_id, quest_id)

    active_plans = await get_active_plans(gw, resolved_quest_id)
    goal = active_plans[0]["goal"] if active_plans else None

    decisions = await _get_quest_decisions(gw, resolved_quest_id)
    constraints = await _get_quest_constraints(gw, resolved_quest_id)
    decisions = await _exclude_deprecated(gw, "Decision", decisions)
    constraints = await _exclude_deprecated(gw, "Constraint", constraints)

    task_graph_status = await get_active_task_graph_status(gw, session_id)
    files = await _get_quest_work_artifacts(gw, resolved_quest_id)

    negative_controls = _extract_negative_controls(constraints)

    sections = _cap_total_nodes(
        {
            "decisions": decisions,
            "constraints": constraints,
            "task_nodes": [task_graph_status] if task_graph_status else [],
            "files": files,
        },
        MAX_HANDOFF_NODES,
    )
    decisions = sections["decisions"]
    constraints = sections["constraints"]
    files = sections["files"]

    node_ids = (
        [d["id"] for d in decisions]
        + [c["id"] for c in constraints]
        + [p["plan_id"] for p in active_plans if p.get("plan_id")]
    )

    # [LOADED] dedup (B44 working_memory.py): demote nodes already
    # surfaced to this session in a prior handoff call, then mark this
    # call's nodes as loaded.
    already_loaded: set[str] = set()
    if session_id and session_id != "unknown":
        try:
            already_loaded = get_loaded_node_ids(db, session_id)
        except Exception:
            already_loaded = set()

    markdown = _render_markdown(
        quest_id=resolved_quest_id,
        goal=goal,
        decisions=decisions,
        constraints=constraints,
        negative_controls=negative_controls,
        task_graph_status=task_graph_status,
        files=files,
        already_loaded=already_loaded,
        target_model_tier=target_model_tier,
    )

    if session_id and session_id != "unknown":
        try:
            trackable = (
                [{"node_id": d["id"], "node_type": "Decision", "text_raw": d.get("text") or ""} for d in decisions]
                + [{"node_id": c["id"], "node_type": "Constraint", "text_raw": c.get("text") or ""} for c in constraints]
            )
            if trackable:
                await track_loaded(db, session_id, trackable, source="handoff")
        except Exception:
            pass

    latency_ms = (time.perf_counter() - start) * 1000.0

    return {
        "quest_id": resolved_quest_id,
        "goal": goal,
        "decisions": decisions,
        "constraints": constraints,
        "negative_controls": negative_controls,
        "task_graph_status": task_graph_status,
        "files": files,
        "node_ids": node_ids,
        "markdown": markdown,
        "latency_ms": round(latency_ms, 3),
    }


def _render_markdown(
    *,
    quest_id: str,
    goal: str | None,
    decisions: list[dict],
    constraints: list[dict],
    negative_controls: list[str],
    task_graph_status: dict | None,
    files: list[dict],
    already_loaded: set[str],
    target_model_tier: str | None,
) -> str:
    """Clean, generic markdown -- no model-specific tags (e.g. XML) so
    it's consumable by any model (Claude, GPT, Gemini, Llama, GLM)."""
    lines = ["# Handoff"]
    if target_model_tier:
        lines.append(f"_Prepared for: {target_model_tier}_")
    lines.append("")

    lines.append("## Goal")
    lines.append(goal if goal else "No active Plan for this quest — no unfinalized goal recorded.")
    lines.append("")

    if decisions:
        lines.append("## Decisions")
        for d in decisions:
            marker = " (already seen)" if d["id"] in already_loaded else ""
            lines.append(f"- {d['text']}{marker}")
        lines.append("")

    if constraints:
        lines.append("## Constraints")
        for c in constraints:
            marker = " (already seen)" if c["id"] in already_loaded else ""
            lines.append(f"- {c['text']}{marker}")
        lines.append("")

    if negative_controls:
        lines.append("## Do Not (heuristically extracted from constraints above)")
        for nc in negative_controls:
            lines.append(f"- {nc}")
        lines.append("")

    if task_graph_status:
        lines.append("## Execution Status")
        lines.append(
            f"- TaskGraph `{task_graph_status['graph_id']}`: "
            f"{task_graph_status['pending_or_active']} pending/active, "
            f"{task_graph_status['complete']} complete "
            f"(of {task_graph_status['total']} total)"
        )
        lines.append("")

    if files:
        lines.append("## Files Touched")
        for f in files:
            suffix = f" — {f['title']}" if f.get("title") else ""
            lines.append(f"- `{f['file_path']}`{suffix}")
        lines.append("")

    if not (decisions or constraints or task_graph_status or files):
        lines.append(
            "_No recorded decisions, constraints, or execution state for this quest yet — "
            "cold start._"
        )
        lines.append("")

    return "\n".join(lines)
