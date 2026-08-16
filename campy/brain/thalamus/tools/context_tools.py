"""Context assembly and ingestion routing handlers."""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from ._shared import get_loop_queue
from .capture import notify_turn

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)



async def ingest_document(params: dict, db, config: dict) -> dict:
    """
    Ingest a local file into the graph as Document + DocumentExtract nodes.
    Runs chunking, embedding, and DERIVED_FROM wiring.
    Queues each extract for the Gated Consolidation Loop.

    params: {file_path, quest_id?}
    """
    file_path = params.get("file_path", "").strip()
    quest_id  = params.get("quest_id", "")

    if not file_path:
        return {"error": "file_path is required"}

    from campy.brain.sensory_cortex.ingest import ingest_document as _ingest
    return await _ingest(
        db=db,
        file_path=file_path,
        config=config,
        loop_queue=get_loop_queue(),
        quest_id=quest_id,
    )


async def ingest_data(params: dict, db, config: dict) -> dict:
    """
    Unified ingestion entry point. Classifies file/content input and routes it
    to the graph/document/tabular ingestion path without creating a shadow store.

    params: {file_path?, content?, mime_type?, session_id, quest_id?}
    """
    from campy.brain.temporal_lobe.memory_router import classify_input

    file_path = (params.get("file_path") or "").strip()
    content = params.get("content")
    mime_type = params.get("mime_type")
    session_id = (params.get("session_id") or "unknown").strip() or "unknown"
    quest_id = (params.get("quest_id") or "").strip()

    if not file_path and not content:
        return {"error": "file_path or content is required"}

    route = classify_input(content=content, file_path=file_path, mime_type=mime_type)
    _logger.info(
        "ingest_data classified input as storage_type=%s confidence=%.2f suggested_tool=%s (%s)",
        route.storage_type, route.confidence, route.suggested_tool, route.reason,
    )

    async def _record_turn() -> dict:
        return await notify_turn(
            {
                "role": params.get("role", "user"),
                "content": content or "",
                "session_id": session_id,
            },
            db,
            config,
        )

    if file_path:
        result = await ingest_document({"file_path": file_path, "quest_id": quest_id}, db, config)
    elif route.storage_type in ("tabular", "graph+tabular"):
        # B251: classify_input() can recommend the tabular path for pasted
        # content (no file_path) - route it there instead of silently
        # falling through to notify_turn regardless of the classification.
        # "graph+tabular" is a dual-write: the conversational turn is
        # still recorded alongside the tabular data.
        from campy.brain.sensory_cortex.tabular_ingest import ingest_tabular_from_content

        tabular_result = await ingest_tabular_from_content(
            db, content or "", config, get_loop_queue(), quest_id
        )
        if route.storage_type == "graph+tabular":
            result = {"tabular": tabular_result, "graph": await _record_turn()}
        else:
            result = {"tabular": tabular_result}
    else:
        result = await _record_turn()

    return {
        "route": {
            "storage_type": route.storage_type,
            "reason": route.reason,
            "confidence": route.confidence,
            "suggested_tool": route.suggested_tool,
        },
        "result": result,
    }


async def compile_context(params: dict, db, config: dict) -> dict:
    """
    Compile a bounded ContextBundle for multi-entity or broad memory queries.

    params: {query, token_budget?, agent_type?, output_format?, session_id?, quest_id?,
             include_tabular?, include_summaries?}
    """
    from campy.brain.thalamus.bundle_compiler import compile_bundle
    from campy.brain.thalamus.formatters import format_bundle

    query = (params.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}

    token_budget = int(params.get("token_budget") or 32000)
    agent_type = params.get("output_format") or params.get("agent_type") or "generic"

    bundle = await compile_bundle(
        query=query,
        db=db,
        config=config,
        token_budget=token_budget,
        agent_type=agent_type,
        quest_id=params.get("quest_id"),
        session_id=params.get("session_id"),
        include_tabular=params.get("include_tabular", True),
        include_summaries=params.get("include_summaries", True),
    )

    return {
        "bundle": bundle.to_dict(),
        "formatted": format_bundle(bundle, agent_type),
        "agent_type": agent_type,
    }


async def ask(params: dict, db: "KuzuClient", config: dict) -> dict:
    """MCP tool handler for `ask`. Thin wrapper over run_ask()."""
    from campy.brain.thalamus.ask import run_ask
    query = params.get("query", "")
    session_id = params.get("session_id", "")
    token_budget = params.get("token_budget", 32000)
    capture = params.get("capture", True)
    if not query:
        return {"error": "query is required"}
    answer = await run_ask(
        query=query,
        session_id=session_id,
        db=db,
        config=config,
        token_budget=token_budget,
        capture=capture,
    )
    return {"answer": answer}


async def memory_decision(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Recommend whether and how to recall SideQuests memory.

    Uses transparent lexical/phase-based routing to recommend the appropriate
    recall tool or suggest no recall for the current user prompt.

    params: {
        user_prompt (required): str,
        task_phase (optional): str (e.g., 'planning', 'debugging'),
        available_context_summary (optional): str,
        session_id (optional): str,
        client_name (optional): str (e.g., 'codex', 'claude-desktop')
    }

    Returns:
    {
        should_recall: bool,
        recommended_tool: str,
        query: str,
        reason: str,
        confidence: float (0.0-1.0),
        context_budget: str ("compact", "moderate", "exhaustive"),
        anti_bloat_guidance: str,
    }
    """
    from campy.brain.thalamus.memory_decision import decide_memory_action

    user_prompt = params.get("user_prompt", "").strip()
    if not user_prompt:
        return {
            "should_recall": False,
            "recommended_tool": "none",
            "query": "",
            "reason": "Empty user prompt; no recall needed.",
            "confidence": 1.0,
            "context_budget": "compact",
            "anti_bloat_guidance": "No action needed.",
        }

    task_phase = params.get("task_phase", "unknown")
    available_context_summary = params.get("available_context_summary")
    session_id = params.get("session_id")
    client_name = params.get("client_name")

    recommendation = decide_memory_action(
        user_prompt=user_prompt,
        task_phase=task_phase,
        available_context_summary=available_context_summary,
        session_id=session_id,
        client_name=client_name,
    )

    return recommendation


# ---------------------------------------------------------------------------
# B323 — compile_card_context: a context bundle keyed on a card id or branch
# name, rather than a free-text query. Reuses bundle_compiler.py's
# BundleSection/ContextBundle shapes (imported lazily below, matching this
# module's existing lazy-import convention for compile_context) rather than
# inventing a second bundle representation.
# ---------------------------------------------------------------------------

_CARD_NODE_TABLES: dict[str, str] = {
    "MainQuest": "quest_id",
    "SideQuest": "quest_id",
    "ActionItem": "action_item_id",
}
# Text column each card table is matched against when resolving target_id.
_CARD_TEXT_COLUMNS: dict[str, str] = {
    "MainQuest": "name",
    "SideQuest": "name",
    "ActionItem": "text_raw",
}
_DEP_NODE_PK: dict[str, str] = {**_CARD_NODE_TABLES, "Workspace": "workspace_id"}
_DEP_REL_TYPES = ("TASK_BLOCKS", "TASK_ENABLES", "ANCHORED_TO")
_DEP_REL_PROPS: dict[str, tuple[str, ...]] = {
    "TASK_BLOCKS": ("declared_by", "confidence", "observed_at", "source", "source_version", "authority"),
    "TASK_ENABLES": ("declared_by", "confidence", "observed_at", "source", "source_version", "authority"),
    "ANCHORED_TO": (),
}
_DEPRECATED_BY_TABLES = ("Concept", "Decision", "Constraint", "Lesson")
_CARD_CONTEXT_DEFAULT_HOPS = 3
_CARD_CONTEXT_MAX_HOPS = 5
_CARD_CONTEXT_HOP_LIMIT = 25  # per (node, rel, direction) — bounds fan-out, not depth


def _resolve_card_context_target(db, target_id: str) -> Optional[dict]:
    """Resolve target_id against a card (MainQuest/SideQuest/ActionItem) or
    a Workspace.branch_name. Cards take priority on ambiguity, and exact
    text matches take priority over a lexical CONTAINS match (mirrors the
    B303 card-identifier convention in quests.py)."""
    for table, pk in _CARD_NODE_TABLES.items():
        col = _CARD_TEXT_COLUMNS[table]
        try:
            r = db.execute(
                f"MATCH (n:{table}) WHERE n.{col} = $tid RETURN n.{pk} LIMIT 1",
                {"tid": target_id},
            )
            if r.has_next():
                node_id = r.get_next()[0]
                if node_id:
                    return {
                        "table": table, "pk": pk, "node_id": node_id,
                        "interpreted_as": f"{table} (exact match)",
                    }
        except Exception:
            continue

    for table, pk in _CARD_NODE_TABLES.items():
        col = _CARD_TEXT_COLUMNS[table]
        try:
            r = db.execute(
                f"MATCH (n:{table}) WHERE n.{col} CONTAINS $tid RETURN n.{pk} LIMIT 1",
                {"tid": target_id},
            )
            if r.has_next():
                node_id = r.get_next()[0]
                if node_id:
                    return {
                        "table": table, "pk": pk, "node_id": node_id,
                        "interpreted_as": f"{table} (lexical match)",
                    }
        except Exception:
            continue

    try:
        r = db.execute(
            "MATCH (w:Workspace) WHERE w.branch_name = $tid RETURN w.workspace_id LIMIT 1",
            {"tid": target_id},
        )
        if r.has_next():
            node_id = r.get_next()[0]
            if node_id:
                return {
                    "table": "Workspace", "pk": "workspace_id", "node_id": node_id,
                    "interpreted_as": "Workspace.branch_name",
                }
    except Exception:
        pass

    return None


def _card_context_dependency_hop(db, frontier: list[tuple[str, str]]) -> list[dict]:
    """One hop of TASK_BLOCKS/TASK_ENABLES/ANCHORED_TO, both directions,
    from every (table, node_id) pair in `frontier`.

    Bounded by construction: this function only ever expands the given
    frontier by exactly one hop — there is no Cypher `*` anywhere in these
    queries. compile_card_context drives how many times this is called
    (clamped to _CARD_CONTEXT_MAX_HOPS), and stops early once the frontier
    is empty. A MATCH against a (table, rel) pair the schema doesn't define
    (e.g. SideQuest against ANCHORED_TO) returns zero rows rather than
    raising — confirmed against Kùzu 0.11.3 — so no per-pair type guard is
    needed here. Left un-guarded against real query errors so a genuine
    failure propagates to compile_card_context's fail-open handling.
    """
    edges: list[dict] = []
    for table, node_id in frontier:
        pk = _DEP_NODE_PK.get(table)
        if not pk:
            continue
        for rel in _DEP_REL_TYPES:
            props = _DEP_REL_PROPS.get(rel, ())
            prop_select = "".join(f", r.{p} AS {p}" for p in props)
            for direction, pattern in (
                ("out", f"(a:{table} {{{pk}: $id}})-[r:{rel}]->(b)"),
                ("in", f"(a:{table} {{{pk}: $id}})<-[r:{rel}]-(b)"),
            ):
                query = f"MATCH {pattern} RETURN label(b) AS b_label, b{prop_select} LIMIT {_CARD_CONTEXT_HOP_LIMIT}"
                res = db.execute(query, {"id": node_id})
                while res.has_next():
                    row = res.get_next()
                    b_label = row[0]
                    b_node = row[1] or {}
                    b_pk = _DEP_NODE_PK.get(b_label)
                    if not b_pk:
                        continue
                    b_dict = b_node if isinstance(b_node, dict) else dict(b_node)
                    b_id = b_dict.get(b_pk)
                    if not b_id:
                        continue
                    edge = {
                        "rel_type": rel,
                        "direction": direction,
                        "from_table": table,
                        "from_id": node_id,
                        "to_table": b_label,
                        "to_id": b_id,
                    }
                    for i, prop in enumerate(props, start=2):
                        edge[prop] = row[i]
                    edges.append(edge)
    return edges


def _card_context_edge_identity(edge: dict) -> tuple:
    """Canonical identity for a dependency edge, normalized to the true DB
    direction (a)-[:REL]->(b) regardless of which endpoint's frontier
    expansion discovered it. Both endpoints of a bidirectional BFS will
    otherwise rediscover the same underlying edge from opposite ends —
    this collapses those duplicates in compile_card_context's dependency
    section."""
    if edge["direction"] == "out":
        return (edge["rel_type"], edge["from_table"], edge["from_id"], edge["to_table"], edge["to_id"])
    return (edge["rel_type"], edge["to_table"], edge["to_id"], edge["from_table"], edge["from_id"])


def _card_context_lessons_for_quest(db, quest_id: str) -> list[dict]:
    """PRODUCED_LESSON only exists FROM MainQuest TO Lesson."""
    try:
        r = db.execute(
            "MATCH (q:MainQuest {quest_id: $qid})-[:PRODUCED_LESSON]->(l:Lesson) "
            "RETURN l.lesson_id, l.text_raw, l.confidence, l.archived LIMIT 20",
            {"qid": quest_id},
        )
    except Exception:
        _logger.exception("compile_card_context: PRODUCED_LESSON lookup failed for %s", quest_id)
        return []
    out = []
    while r.has_next():
        row = r.get_next()
        out.append({
            "lesson_id": row[0], "text": row[1], "confidence": row[2], "archived": row[3],
        })
    return out


def _card_context_deprecated_by(db, table: str, node_id: str, pk: str) -> list[dict]:
    """DEPRECATED_BY only covers Concept/Decision/Constraint/Lesson
    self-pairs (direction: (older)-[:DEPRECATED_BY]->(newer)). Checked in
    both directions so callers see both "this is stale, replaced by X" and
    "this replaced Y"."""
    if table not in _DEPRECATED_BY_TABLES:
        return []
    out: list[dict] = []
    try:
        r = db.execute(
            f"MATCH (a:{table} {{{pk}: $id}})-[:DEPRECATED_BY]->(b:{table}) "
            f"RETURN b.{pk} LIMIT 10",
            {"id": node_id},
        )
        while r.has_next():
            out.append({"related_node_id": r.get_next()[0], "relation": "deprecated_by"})
    except Exception:
        _logger.exception("compile_card_context: DEPRECATED_BY (outgoing) lookup failed for %s:%s", table, node_id)
    try:
        r = db.execute(
            f"MATCH (a:{table})-[:DEPRECATED_BY]->(b:{table} {{{pk}: $id}}) "
            f"RETURN a.{pk} LIMIT 10",
            {"id": node_id},
        )
        while r.has_next():
            out.append({"related_node_id": r.get_next()[0], "relation": "deprecates"})
    except Exception:
        _logger.exception("compile_card_context: DEPRECATED_BY (incoming) lookup failed for %s:%s", table, node_id)
    return out


def _card_context_solved_by(db, table: str, node_id: str, pk: str) -> list[dict]:
    """SOLVED_BY attribution — only defined FROM Decision/ActionItem/Lesson
    TO AgentWorker (schema.SOLVED_BY_TABLES)."""
    from campy.brain.hippocampus.schema import SOLVED_BY_TABLES

    if table not in SOLVED_BY_TABLES:
        return []
    out: list[dict] = []
    try:
        r = db.execute(
            f"MATCH (n:{table} {{{pk}: $id}})-[r:SOLVED_BY]->(w:AgentWorker) "
            f"RETURN w.worker_id, r.confidence, r.observed_at LIMIT 10",
            {"id": node_id},
        )
        while r.has_next():
            row = r.get_next()
            out.append({
                "worker_id": row[0],
                "confidence": row[1],
                "observed_at": str(row[2]) if row[2] is not None else None,
            })
    except Exception:
        _logger.exception("compile_card_context: SOLVED_BY lookup failed for %s:%s", table, node_id)
    return out


_CARD_CONTEXT_SECTION_HEADERS = {
    "target": "## Target",
    "dependencies": "## Dependencies (blockers / enablers / anchors)",
    "lessons": "## Prior Lessons",
    "superseded": "## Superseded / Deprecated",
    "attribution": "## Agent Attribution",
}


def _card_context_item_line(section_type: str, item: dict) -> str:
    if section_type == "target":
        return f"{item.get('table')} `{item.get('node_id')}` (resolved as: {item.get('interpreted_as')})"
    if section_type == "dependencies":
        arrow = "->" if item.get("direction") == "out" else "<-"
        return (
            f"[{item.get('rel_type')}] {item.get('from_table')}:{item.get('from_id')} "
            f"{arrow} {item.get('to_table')}:{item.get('to_id')} (hop {item.get('hop')})"
        )
    if section_type == "lessons":
        return (
            f"{item.get('quest_table')}:{item.get('quest_id')} produced Lesson "
            f"`{item.get('lesson_id')}`: {item.get('text')}"
        )
    if section_type == "superseded":
        return f"{item.get('table')}:{item.get('node_id')} {item.get('relation')} `{item.get('related_node_id')}`"
    if section_type == "attribution":
        return f"{item.get('table')}:{item.get('node_id')} solved by {item.get('worker_id')}"
    return str(item)


def _render_card_context_markdown(bundle, target_id: str, interpreted_as: str,
                                   max_hops: int, dependency_failed: bool) -> str:
    """Render a ContextBundle produced by compile_card_context as Markdown.
    A dedicated renderer (not the formatters/ package) because this bundle's
    section vocabulary (target/dependencies/lessons/superseded/attribution)
    is specific to card context, not the query-driven bundle_compiler
    sections (exact_fact/semantic/graph/tabular/summary) those formatters
    render — see ClaudeCodeFormatter._format_section for the sibling
    convention this mirrors (BundleSection in, per-section-type Markdown
    out)."""
    lines = [f"# Card Context: {target_id}", "", f"_Resolved as: {interpreted_as} | max_hops={max_hops}_", ""]
    for section in bundle.sections:
        lines.append(_CARD_CONTEXT_SECTION_HEADERS.get(section.section_type, f"## {section.section_type.title()}"))
        lines.append("")
        if not section.content:
            lines.append("_None_")
        else:
            for item in section.content:
                lines.append(f"- {_card_context_item_line(section.section_type, item)}")
        lines.append("")
    if dependency_failed:
        lines.append("_Dependency traversal failed — showing target context only (fail-open, per B318)._")
        lines.append("")
    lines.append("---")
    return "\n".join(lines)


async def compile_card_context(params: dict, db, config: dict) -> dict:
    """
    B323 — Compile a bounded context bundle keyed on a card id
    (MainQuest/SideQuest/ActionItem) or a Workspace.branch_name, rather
    than a free-text query.

    params: {target_id: str, max_hops?: int}

    - Resolves target_id against a card first, a branch name second;
      `interpreted_as` in the response says which.
    - Traverses ANCHORED_TO / TASK_BLOCKS / TASK_ENABLES outward from the
      resolved node, bounded to `max_hops` (default 3, hard-clamped to a
      maximum of 5 — no unbounded Cypher `*` is ever issued).
    - Pulls PRODUCED_LESSON and DEPRECATED_BY content reachable from
      dependencies, plus SOLVED_BY agent attribution on each item.
    - Returns structured data (`bundle`, a bundle_compiler.ContextBundle
      dict) *and* a rendered `markdown` string built from that structure.

    Fail-open (B318): if the dependency traversal itself raises, the
    returned bundle keeps its "target" section and simply omits the
    dependency/lesson/superseded/attribution sections — this function
    never raises for a traversal failure. Only a missing/unresolvable
    target_id returns an `{"error": ...}` dict.
    """
    from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle
    import time

    target_id = (params.get("target_id") or "").strip()
    if not target_id:
        return {"error": "target_id is required"}

    try:
        max_hops = int(params.get("max_hops") or _CARD_CONTEXT_DEFAULT_HOPS)
    except (TypeError, ValueError):
        max_hops = _CARD_CONTEXT_DEFAULT_HOPS
    max_hops = max(1, min(max_hops, _CARD_CONTEXT_MAX_HOPS))

    start_time = time.time()

    resolution = _resolve_card_context_target(db, target_id)
    if resolution is None:
        return {
            "error": (
                f"target_id {target_id!r} did not resolve to a card "
                f"(MainQuest/SideQuest/ActionItem) or a Workspace.branch_name"
            )
        }

    table = resolution["table"]
    pk = resolution["pk"]
    node_id = resolution["node_id"]
    interpreted_as = resolution["interpreted_as"]

    sections: list[BundleSection] = [
        BundleSection(
            section_type="target",
            content=[{
                "table": table, "node_id": node_id,
                "interpreted_as": interpreted_as, "target_id": target_id,
            }],
            token_estimate=20,
            source_node_ids=[node_id],
        )
    ]
    sources: list[str] = [node_id]

    dependency_failed = False
    reached: dict[tuple[str, str], int] = {(table, node_id): 0}
    dep_edges: list[dict] = []
    seen_edge_ids: set[tuple] = set()
    try:
        frontier = [(table, node_id)]
        for hop in range(1, max_hops + 1):
            if not frontier:
                break
            hop_edges = _card_context_dependency_hop(db, frontier)
            next_frontier: list[tuple[str, str]] = []
            for edge in hop_edges:
                eid = _card_context_edge_identity(edge)
                if eid in seen_edge_ids:
                    continue
                seen_edge_ids.add(eid)
                dep_edges.append({**edge, "hop": hop})
                key = (edge["to_table"], edge["to_id"])
                if key not in reached:
                    reached[key] = hop
                    next_frontier.append(key)
            frontier = next_frontier
    except Exception:
        _logger.exception("compile_card_context: dependency traversal failed for target_id=%s", target_id)
        dependency_failed = True

    if not dependency_failed:
        if dep_edges:
            sections.append(BundleSection(
                section_type="dependencies",
                content=dep_edges,
                token_estimate=len(dep_edges) * 40,
                source_node_ids=[eid for e in dep_edges for eid in (e["from_id"], e["to_id"])],
            ))

        lesson_content: list[dict] = []
        superseded_content: list[dict] = []
        attribution_content: list[dict] = []
        for (r_table, r_id), _hop in reached.items():
            if r_table == "MainQuest":
                for lesson in _card_context_lessons_for_quest(db, r_id):
                    lesson_content.append({**lesson, "quest_table": r_table, "quest_id": r_id})
                    lesson_id = lesson.get("lesson_id")
                    if lesson_id:
                        for dep in _card_context_deprecated_by(db, "Lesson", lesson_id, "lesson_id"):
                            superseded_content.append({"table": "Lesson", "node_id": lesson_id, **dep})
                        for sb in _card_context_solved_by(db, "Lesson", lesson_id, "lesson_id"):
                            attribution_content.append({"table": "Lesson", "node_id": lesson_id, **sb})

            r_pk = _DEP_NODE_PK.get(r_table)
            if r_pk:
                for sb in _card_context_solved_by(db, r_table, r_id, r_pk):
                    attribution_content.append({"table": r_table, "node_id": r_id, **sb})

        if lesson_content:
            sections.append(BundleSection(
                section_type="lessons",
                content=lesson_content,
                token_estimate=len(lesson_content) * 60,
                source_node_ids=[l["lesson_id"] for l in lesson_content if l.get("lesson_id")],
            ))
        if superseded_content:
            sections.append(BundleSection(
                section_type="superseded",
                content=superseded_content,
                token_estimate=len(superseded_content) * 30,
                source_node_ids=[s["node_id"] for s in superseded_content if s.get("node_id")],
            ))
        if attribution_content:
            sections.append(BundleSection(
                section_type="attribution",
                content=attribution_content,
                token_estimate=len(attribution_content) * 20,
                source_node_ids=[a["worker_id"] for a in attribution_content if a.get("worker_id")],
            ))

    bundle = ContextBundle(
        query=target_id,
        sections=sections,
        total_token_estimate=sum(s.token_estimate for s in sections),
        token_budget=0,
        truncated=dependency_failed,
        sources=sources,
        compilation_ms=(time.time() - start_time) * 1000,
    )

    return {
        "bundle": bundle.to_dict(),
        "markdown": _render_card_context_markdown(bundle, target_id, interpreted_as, max_hops, dependency_failed),
        "target_id": target_id,
        "interpreted_as": interpreted_as,
        "max_hops": max_hops,
        "dependency_traversal_failed": dependency_failed,
    }
