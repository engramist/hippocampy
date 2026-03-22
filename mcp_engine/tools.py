"""
mcp_engine/tools.py — MCP Tool Implementations (Brain Daemon side)

The IPC server in brain_daemon.py dispatches JSON-RPC calls here.
All writes go through db.execute_write() to respect the asyncio write lock.
"""

from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

_logger = logging.getLogger(__name__)

# KuzuClient imported only for type checking — kuzu is a C extension not needed
# during unit tests (db is always a mock or real object passed in at runtime).
if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

from mcp_engine.graph import embeddings as emb
from mcp_engine.quest import (
    get_or_create_main_quest, get_or_create_session,
    create_side_quest, get_quest_context,
)

# ---------------------------------------------------------------------------
# M3 runtime state — initialized by brain_daemon.py at startup
# ---------------------------------------------------------------------------

_loop_queue: Optional[asyncio.Queue] = None


def init_loop_queue(queue: asyncio.Queue) -> None:
    """Called once by BrainDaemon.start() after the event loop is running."""
    global _loop_queue
    _loop_queue = queue


# ---------------------------------------------------------------------------
# M2/M5 — notify_turn
# ---------------------------------------------------------------------------

async def notify_turn(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Receive a conversation turn from the adapter and store it as a Message node.
    M5: also resolves/creates the MainQuest from git context, upserts Session.

    params: {role, content, session_id, repo_root?, git_branch?}
    """
    role       = params.get("role", "user")
    content    = params.get("content", "")
    session_id = params.get("session_id", "unknown")
    repo_root  = params.get("repo_root", "")
    git_branch = params.get("git_branch", "main")

    max_chars = config.get("ingestion", {}).get("max_ingest_chars", 4000)
    if len(content) > max_chars:
        # D5 fix: fall back to word boundary if no sentence period found.
        truncated = content[:max_chars]
        idx = truncated.rfind(".")
        if idx > 0:
            content = truncated[:idx + 1]
        else:
            idx = truncated.rfind(" ")
            content = (truncated[:idx] if idx > 0 else truncated) + "…"

    if not content.strip():
        return {"status": "skipped", "reason": "empty content"}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    vector     = emb.embed(content, model_name=embedding_model)
    message_id = str(uuid.uuid4())
    now        = datetime.now(timezone.utc).isoformat()

    # Route session via Hippocampus (all sessions, not just git)
    quest_id = ""
    if repo_root:
        # Legacy git path — fast and deterministic
        quest_id = await get_or_create_main_quest(
            db, repo_root, git_branch, embedding_model, now
        )
        await get_or_create_session(db, session_id, quest_id, now)
    else:
        # Semantic routing — no git context available
        from mcp_engine.hippocampus import route_session
        try:
            result = await route_session(
                db, session_id, content, embedding_model,
                workspace_path=params.get("workspace_path", ""),
                config=config,
            )
            quest_id = result.quest_id
        except Exception:
            _logger.exception("hippocampus.route_session failed")

    # B18: Set token_limit from adapter if provided
    token_limit = params.get("token_limit", 0)
    if token_limit and session_id != "unknown":
        try:
            await db.execute_write(
                "MATCH (s:Session {session_id: $sid}) "
                "WHERE s.token_limit IS NULL OR s.token_limit = 0 "
                "SET s.token_limit = $limit",
                {"sid": session_id, "limit": int(token_limit)}
            )
        except Exception:
            pass

    # Write Message node
    await db.execute_write(
        """
        CREATE (m:Message {
            message_id:      $message_id,
            text_raw:        $text_raw,
            embedding:       $embedding,
            embedding_model: $embedding_model,
            embedding_dim:   $embedding_dim,
            role:            $role,
            byte_start:      0,
            byte_end:        $byte_end,
            confidence:      0.0,
            confidence_low:  true,
            pathway_strength: 0.0,
            archived:        false,
            created_at:      timestamp($created_at)
        })
        """,
        {
            "message_id":      message_id,
            "text_raw":        content,
            "embedding":       vector,
            "embedding_model": embedding_model,
            "embedding_dim":   len(vector),
            "role":            role,
            "byte_end":        len(content.encode()),
            "created_at":      now,
        }
    )

    # B18: Update token estimate for this message
    if session_id != "unknown":
        from mcp_engine.working_memory import update_token_estimate, estimate_tokens
        try:
            msg_tokens = estimate_tokens(content)
            await update_token_estimate(db, session_id, msg_tokens)
        except Exception:
            pass

    # Link Message → Session
    if session_id != "unknown":
        await db.execute_write(
            """
            MATCH (s:Session {session_id: $session_id}),
                  (m:Message {message_id: $message_id})
            MERGE (m)-[:SENT_IN]->(s)
            """,
            {"session_id": session_id, "message_id": message_id}
        )

    # Update routing strength for subsequent messages (not the first)
    if quest_id and not repo_root:
        from mcp_engine.hippocampus import update_routing_strength, get_active_quests_with_embeddings
        try:
            quests = get_active_quests_with_embeddings(db)
            quest_emb = next((q["purpose_embedding"] for q in quests
                              if q["quest_id"] == quest_id), None)
            if quest_emb:
                await update_routing_strength(db, session_id, vector, quest_emb)
        except Exception:
            pass

    # Enqueue for Gated Consolidation Loop (M3+)
    if _loop_queue is not None:
        await _loop_queue.put((message_id, content, role, session_id))

    # B14: Read previous loop summary (completed by the time this fires)
    insights = None
    if session_id != "unknown":
        import json as _json
        try:
            r = db.execute(
                "MATCH (s:Session {session_id: $sid}) "
                "RETURN s.last_loop_summary",
                {"sid": session_id}
            )
            if r.has_next():
                raw = r.get_next()[0]
                if raw:
                    insights = _json.loads(raw)
        except Exception:
            pass  # Non-critical

    response = {
        "status": "queued",
        "message_id": message_id,
        "quest_id": quest_id,
    }
    if insights:
        response["insights"] = insights

    return response


# ---------------------------------------------------------------------------
# M2/M5 — current_truth
# ---------------------------------------------------------------------------

async def current_truth(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Retrieve relevant memory for a query.
    M5: branch scope adds quest-linked artifacts to the result set.

    params: {query, session_id, scope ("branch"|"global"|"both"), limit,
             quest_id?, repo_root?, git_branch?}
    """
    query      = params.get("query", "")
    session_id = params.get("session_id", "unknown")
    scope      = params.get("scope", "branch")
    limit      = int(params.get("limit", 10))
    quest_id   = params.get("quest_id", "")
    repo_root  = params.get("repo_root", "")
    git_branch = params.get("git_branch", "main")

    if not query.strip():
        return {"results": [], "quest_context": {}}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # Resolve quest_id: prefer explicit, then git hash, then session binding
    if not quest_id and repo_root:
        from mcp_engine.quest import compute_quest_id
        quest_id = compute_quest_id(repo_root, git_branch)
    if not quest_id and session_id != "unknown":
        # Resolve via Session → WORKING_ON → MainQuest
        try:
            r = db.execute(
                "MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest) "
                "RETURN q.quest_id",
                {"sid": session_id}
            )
            if r.has_next():
                quest_id = r.get_next()[0] or ""
        except Exception:
            pass

    query_vector = emb.embed(query, model_name=embedding_model)

    # Vector search across artifact tables
    # D6 fix: include Concept nodes — they are the majority of extracted entities
    # and most have not been reified to specific artifact types. Without this,
    # most of the graph is invisible to current_truth.
    artifact_tables = [
        ("Concept",          "concept_emb_idx",           "concept_id"),
        ("Decision",         "decision_emb_idx",         "decision_id"),
        ("Constraint",       "constraint_emb_idx",        "constraint_id"),
        ("Requirement",      "requirement_emb_idx",       "requirement_id"),
        ("ActionItem",       "actionitem_emb_idx",        "action_item_id"),
        ("GlobalConstraint", "globalconstraint_emb_idx",  "global_constraint_id"),
        ("GlobalPreference", "globalpreference_emb_idx",  "global_preference_id"),
    ]

    all_results = []
    per_table_limit = max(limit, 5)

    for table_name, index_name, pk in artifact_tables:
        try:
            rows = db.vector_search(table_name, index_name, query_vector, per_table_limit)
            for row in rows:
                node = row["node"]
                if node.get("archived", False):
                    continue
                node_id = (node.get("concept_id")
                           or node.get("decision_id") or node.get("constraint_id")
                           or node.get("requirement_id") or node.get("action_item_id")
                           or node.get("global_constraint_id")
                           or node.get("global_preference_id", "unknown"))
                ps = node.get("pathway_strength", 0.0) or 0.0
                conf = node.get("confidence", 0.0) or 0.0
                similarity = row["score"]

                # B31 fix: balanced ranking that weights similarity heavily.
                # Old formula (ps * conf) caused stale high-strength nodes to
                # dominate over semantically relevant new ones. New formula:
                #   50% similarity (semantic match to query)
                #   30% strength signal (pathway_strength * confidence)
                #   20% recency (decays over days)
                created_at = node.get("created_at")
                recency = 1.0
                if created_at:
                    try:
                        from datetime import datetime, timezone
                        if hasattr(created_at, 'timestamp'):
                            created_ts = created_at.timestamp()
                        else:
                            created_ts = datetime.fromisoformat(str(created_at).replace('Z', '+00:00')).timestamp()
                        days_old = (datetime.now(timezone.utc).timestamp() - created_ts) / 86400
                        recency = 1.0 / (1.0 + days_old)
                    except Exception:
                        recency = 0.5

                strength = (ps * conf) if (ps > 0.0 and conf > 0.0) else 0.0
                # Normalize strength to ~0-1 range (cap at 3.0 which is high)
                strength_norm = min(strength / 3.0, 1.0)
                rank = (similarity * 0.5) + (strength_norm * 0.3) + (recency * 0.2)

                all_results.append({
                    "node_id":          node_id,
                    "node_type":        table_name,
                    "text_raw":         node.get("text_raw", ""),
                    "confidence":       conf,
                    "confidence_low":   node.get("confidence_low", True),
                    "pathway_strength": ps,
                    "similarity":       similarity,
                    "_rank":            rank,
                })
        except Exception:
            _logger.exception("current_truth vector search failed for table %s", table_name)

    all_results.sort(key=lambda r: r["_rank"], reverse=True)

    # B18: Smart deduplication — demote already-loaded nodes
    if session_id != "unknown":
        from mcp_engine.working_memory import get_loaded_node_ids, deduplicate_results
        try:
            loaded_ids = get_loaded_node_ids(db, session_id)
            if loaded_ids:
                all_results = deduplicate_results(all_results, loaded_ids)
        except Exception:
            _logger.debug("current_truth dedup failed for session %s", session_id)

    for r in all_results:
        if "_rank" in r:
            del r["_rank"]

    # M5: include quest context for branch scope
    quest_ctx = {}
    if quest_id and scope in ("branch", "both"):
        quest_ctx = get_quest_context(db, quest_id, limit=5)

    final_results = all_results[:limit]

    # B18: Track what was loaded into this session
    if session_id != "unknown" and final_results:
        from mcp_engine.working_memory import (
            track_loaded, update_token_estimate, estimate_tokens,
            check_context_health, get_session_token_state
        )
        try:
            await track_loaded(db, session_id, final_results, source="current_truth")
            # Update token estimate for injected content
            injected_tokens = sum(estimate_tokens(r.get("text_raw", "")) for r in final_results)
            await update_token_estimate(db, session_id, injected_tokens)
        except Exception:
            _logger.debug("current_truth load tracking failed for session %s", session_id)

    # B18: Add bloat warning if applicable
    bloat_warning = None
    if session_id != "unknown":
        try:
            bloat_warning = check_context_health(db, session_id)
        except Exception:
            pass

    response = {"results": final_results, "quest_context": quest_ctx}
    if bloat_warning:
        response["bloat_warning"] = bloat_warning

    # B18: Add handoff candidates if this is a new session
    if quest_id and session_id != "unknown":
        from mcp_engine.working_memory import get_handoff_context
        try:
            state = get_session_token_state(db, session_id)
            if state["loaded_nodes"] == 0:
                # Fresh session — include handoff context
                handoff = get_handoff_context(db, quest_id, session_id)
                if handoff:
                    response["handoff_from_prior_session"] = handoff
        except Exception:
            pass

    return response


# ---------------------------------------------------------------------------
# M5 — branch_quest
# ---------------------------------------------------------------------------

async def branch_quest(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Manually declare a SideQuest branching from the current MainQuest.

    params: {name, purpose, parent_quest_id, repo_root?, git_branch?}
    Returns {side_quest_id, name, parent_quest_id}.
    """
    name             = params.get("name", "").strip()
    purpose          = params.get("purpose", "").strip()
    parent_quest_id  = params.get("parent_quest_id", "")
    repo_root        = params.get("repo_root", "")
    git_branch       = params.get("git_branch", "main")

    if not name:
        return {"error": "name is required"}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    now = datetime.now(timezone.utc).isoformat()

    # Resolve parent quest if not supplied
    if not parent_quest_id and repo_root:
        from mcp_engine.quest import compute_quest_id
        parent_quest_id = compute_quest_id(repo_root, git_branch)

    if not parent_quest_id:
        return {"error": "parent_quest_id required (or provide repo_root + git_branch)"}

    side_quest_id = await create_side_quest(
        db, name, purpose, parent_quest_id, embedding_model, now
    )

    return {
        "side_quest_id":  side_quest_id,
        "name":           name,
        "parent_quest_id": parent_quest_id,
    }


# ---------------------------------------------------------------------------
# M5 — diff_since
# ---------------------------------------------------------------------------

async def diff_since(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Return nodes created or modified since a given ISO timestamp.
    Useful for synchronizing adapters after a gap.

    params: {since_iso, quest_id?, limit}
    Returns {decisions, constraints, requirements, action_items, since_iso}.
    """
    since_iso = params.get("since_iso", "")
    quest_id  = params.get("quest_id", "")
    limit     = int(params.get("limit", 20))

    if not since_iso:
        return {"error": "since_iso is required"}

    result = {"since_iso": since_iso, "decisions": [], "constraints": [],
              "requirements": [], "action_items": []}

    table_map = [
        ("Decision",     "decision_id",     "decisions"),
        ("Constraint",   "constraint_id",   "constraints"),
        ("Requirement",  "requirement_id",  "requirements"),
        ("ActionItem",   "action_item_id",  "action_items"),
    ]

    for label, pk, key in table_map:
        try:
            r = db.execute(
                f"""
                MATCH (a:{label})
                WHERE a.archived = false AND a.created_at > $since
                RETURN a.{pk}, a.text_raw, a.confidence, a.confidence_low,
                       a.pathway_strength, a.created_at
                ORDER BY a.created_at DESC
                LIMIT $limit
                """,
                {"since": since_iso, "limit": limit}
            )
            while r.has_next():
                row = r.get_next()
                result[key].append({
                    "node_id":          row[0],
                    "text_raw":         row[1],
                    "confidence":       row[2],
                    "confidence_low":   row[3],
                    "pathway_strength": row[4],
                    "created_at":       str(row[5]),
                })
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# M5 — get_open_loops
# ---------------------------------------------------------------------------

async def get_open_loops(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Return soft-lock Concept nodes (confidence_low=true, not archived).
    These are candidates awaiting UI confirmation or additional context.

    params: {quest_id?, limit}
    Returns {open_loops: [{concept_id, text_raw, gist_class, confidence}]}
    """
    limit    = int(params.get("limit", 20))
    loops    = []

    try:
        r = db.execute(
            """
            MATCH (c:Concept {confidence_low: true, archived: false})
            RETURN c.concept_id, c.text_raw, c.gist_class, c.schema_org_type,
                   c.confidence, c.pathway_strength, c.created_at
            ORDER BY c.created_at DESC
            LIMIT $limit
            """,
            {"limit": limit}
        )
        while r.has_next():
            row = r.get_next()
            loops.append({
                "concept_id":       row[0],
                "text_raw":         row[1],
                "gist_class":       row[2],
                "schema_org_type":  row[3],
                "confidence":       row[4],
                "pathway_strength": row[5],
                "created_at":       str(row[6]),
            })
    except Exception:
        pass

    return {"open_loops": loops}


# ---------------------------------------------------------------------------
# M8 — analogical_search
# ---------------------------------------------------------------------------

async def analogical_search(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Cross-quest semantic search (M8).
    Finds similar decisions, constraints, and requirements from ANY historical
    MainQuest — not just the current branch.

    params: {query, current_quest_id?, limit, min_similarity?}
    Returns {results, query, cross_quest, searched_tables}.
    """
    from mcp_engine.analogical import analogical_search as _search
    return await _search(params, db, config)


# ---------------------------------------------------------------------------
# M6 — ingest_document
# ---------------------------------------------------------------------------

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

    from mcp_engine.ingest import ingest_document as _ingest
    return await _ingest(
        db=db,
        file_path=file_path,
        config=config,
        loop_queue=_loop_queue,
        quest_id=quest_id,
    )


# ---------------------------------------------------------------------------
# B11 — complete_quest + Lesson synthesis
# ---------------------------------------------------------------------------

async def complete_quest(params: dict, db, config: dict) -> dict:
    """
    Mark a quest as completed and trigger background Lesson synthesis.

    params: {quest_id}
    Returns: {status, quest_id}
    """
    quest_id = params.get("quest_id", "").strip()
    if not quest_id:
        return {"error": "quest_id is required"}

    now = datetime.now(timezone.utc).isoformat()

    # Mark MainQuest as completed
    try:
        await db.execute_write(
            "MATCH (q:MainQuest {quest_id: $qid}) "
            "SET q.status = 'completed', q.completed_at = timestamp($now)",
            {"qid": quest_id, "now": now}
        )
    except Exception:
        # Try SideQuest
        try:
            await db.execute_write(
                "MATCH (q:SideQuest {quest_id: $qid}) "
                "SET q.status = 'completed', q.completed_at = timestamp($now)",
                {"qid": quest_id, "now": now}
            )
        except Exception as e:
            _logger.error("complete_quest: could not mark %s completed: %s", quest_id, e)
            return {"error": str(e)}

    # B11: synthesize lesson in background (fire-and-forget)
    asyncio.create_task(_synthesize_lesson(quest_id, db, config))

    return {"status": "completed", "quest_id": quest_id}


async def _synthesize_lesson(quest_id: str, db, config: dict) -> None:
    """
    Background coroutine: synthesize a Lesson node from quest artifacts.

    1. Query the top confirmed artifacts linked to this quest
    2. Ask LLM to synthesize the hardest obstacle and key lesson
    3. Store as Lesson node (confidence_low=true) + PRODUCED_LESSON edge
    """
    try:
        from mcp_engine.llm.provider import create_llm_client
        from mcp_engine.graph import embeddings as emb

        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )

        # Gather up to 10 confirmed artifacts from this quest
        artifact_rows = []
        for table, pk in [("Decision", "decision_id"), ("Constraint", "constraint_id"),
                           ("Requirement", "requirement_id")]:
            try:
                r = db.execute(
                    f"MATCH (a:{table}) WHERE a.archived = false "
                    f"AND a.confidence_low = false "
                    f"RETURN a.text_raw, a.confidence "
                    f"ORDER BY a.pathway_strength DESC LIMIT 5"
                )
                while r.has_next():
                    row = r.get_next()
                    artifact_rows.append(f"[{table}] {row[0]}")
            except Exception:
                pass

        if not artifact_rows:
            _logger.info("_synthesize_lesson: no confirmed artifacts for quest %s", quest_id)
            return

        artifacts_text = "\n".join(artifact_rows[:10])

        # Create LLM client — skip if unavailable
        llm = create_llm_client(config)
        if llm is None:
            _logger.warning("_synthesize_lesson: LLM unavailable for quest %s", quest_id)
            return

        prompt = (
            "Given these artifacts from a completed project quest:\n\n"
            f"{artifacts_text}\n\n"
            "Synthesize in 1-2 sentences:\n"
            "1. The hardest obstacle overcome\n"
            "2. The key lesson learned that would help someone doing similar work\n\n"
            'Return JSON only: {"lesson": "...", "obstacle": "..."}'
        )

        import json as _json
        response_text = await asyncio.to_thread(llm.chat, prompt)

        try:
            data = _json.loads(response_text)
            lesson_text    = data.get("lesson", "").strip()
            obstacle_text  = data.get("obstacle", "").strip()
        except Exception:
            lesson_text   = response_text.strip()[:500]
            obstacle_text = ""

        if not lesson_text:
            return

        # Embed, store Lesson node, link PRODUCED_LESSON
        vector    = await asyncio.to_thread(emb.embed, lesson_text, embedding_model)
        lesson_id = str(uuid.uuid4())
        now       = datetime.now(timezone.utc).isoformat()

        await db.execute_write(
            """
            CREATE (l:Lesson {
                lesson_id:        $lesson_id,
                text_raw:         $text_raw,
                embedding:        $embedding,
                embedding_model:  $embedding_model,
                embedding_dim:    $embedding_dim,
                obstacle_summary: $obstacle_summary,
                source_quest_id:  $source_quest_id,
                confidence:       0.70,
                confidence_low:   true,
                pathway_strength: 0.70,
                archived:         false,
                created_at:       timestamp($created_at)
            })
            """,
            {
                "lesson_id":       lesson_id,
                "text_raw":        lesson_text,
                "embedding":       vector,
                "embedding_model": embedding_model,
                "embedding_dim":   len(vector),
                "obstacle_summary": obstacle_text,
                "source_quest_id": quest_id,
                "created_at":      now,
            }
        )

        # Link MainQuest → Lesson
        try:
            await db.execute_write(
                "MATCH (q:MainQuest {quest_id: $qid}), (l:Lesson {lesson_id: $lid}) "
                "CREATE (q)-[:PRODUCED_LESSON]->(l)",
                {"qid": quest_id, "lid": lesson_id}
            )
        except Exception:
            pass  # Quest may be a SideQuest — no PRODUCED_LESSON for SideQuest yet

        _logger.info("_synthesize_lesson: stored lesson %s for quest %s", lesson_id, quest_id)

    except Exception as e:
        _logger.exception("_synthesize_lesson error for quest %s: %s", quest_id, e)


# ---------------------------------------------------------------------------
# B10 — explore_graph (directed graph traversal)
# ---------------------------------------------------------------------------

# Traversal is constrained to allowlisted relationship types.
# No arbitrary Cypher — prevents unbounded queries.
_TRAVERSABLE_RELS = frozenset({
    "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
    "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
    "CO_OCCURS_WITH", "REIFIED_AS", "DEPRECATED_BY",
    "BELONGS_TO", "DERIVED_FROM", "ESTABLISHED",
    "HAS_PREF_LABEL", "HAS_ALT_LABEL",
    "PRODUCED_LESSON",
})

# Node tables to search when resolving start_node_id
_NODE_TABLES: list[tuple[str, str]] = [
    ("Concept",          "concept_id"),
    ("Decision",         "decision_id"),
    ("Constraint",       "constraint_id"),
    ("Requirement",      "requirement_id"),
    ("ActionItem",       "action_item_id"),
    ("GlobalConstraint", "global_constraint_id"),
    ("GlobalPreference", "global_preference_id"),
    ("MainQuest",        "quest_id"),
    ("SideQuest",        "quest_id"),
    ("Message",          "message_id"),
    ("Document",         "document_id"),
    ("Lesson",           "lesson_id"),   # B11
]

_MAX_DEPTH = 3


async def explore_graph(params: dict, db, config: dict) -> dict:
    """
    Directed graph traversal from a known node.

    params:
      start_node_id:    str (required) — any node's primary key
      relationship_type: str (optional) — filter to one rel type
      direction:        str — "outgoing" | "incoming" | "both" (default)
      depth:            int — 1–3 (default 1; capped at _MAX_DEPTH)

    Returns:
      {start_node_id, start_node_type, nodes, edges}
      nodes: [{node_id, node_type, text_raw, confidence, pathway_strength}]
      edges: [{source, target, type}]

    Security:
      - Only allowlisted relationship types
      - Depth capped at 3
      - Read-only (uses db.execute, never execute_write)
      - No arbitrary Cypher input
    """
    start_id  = params.get("start_node_id", "").strip()
    rel_type  = params.get("relationship_type", "").strip().upper()
    direction = params.get("direction", "both")
    depth     = min(int(params.get("depth", 1)), _MAX_DEPTH)

    if not start_id:
        return {"error": "start_node_id is required"}

    if rel_type and rel_type not in _TRAVERSABLE_RELS:
        return {
            "error": f"Unknown relationship type: {rel_type}",
            "allowed": sorted(_TRAVERSABLE_RELS),
        }

    if direction not in ("outgoing", "incoming", "both"):
        direction = "both"

    # ── Find start node ────────────────────────────────────────────────────
    start_table = None
    for table, pk in _NODE_TABLES:
        try:
            r = db.execute(
                f"MATCH (n:{table}) WHERE n.{pk} = $id RETURN n LIMIT 1",
                {"id": start_id}
            )
            if r.has_next():
                start_table = table
                break
        except Exception:
            continue

    if start_table is None:
        return {
            "start_node_id":   start_id,
            "start_node_type": None,
            "nodes":           [],
            "edges":           [],
            "error":           "start_node_id not found in any node table",
        }

    # ── Build traversal query ──────────────────────────────────────────────
    # Kuzu variable-length path syntax: (a)-[r*1..N]-(b)
    # Direction determines edge pattern.
    depth_range = f"1..{depth}"

    if rel_type:
        rel_pattern = f"[r:{rel_type}*{depth_range}]"
    else:
        rel_pattern = f"[r*{depth_range}]"

    if direction == "outgoing":
        edge_pattern = f"-{rel_pattern}->"
    elif direction == "incoming":
        edge_pattern = f"<-{rel_pattern}-"
    else:
        edge_pattern = f"-{rel_pattern}-"

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()

    # Iterative single-hop traversal (more compatible with Kuzu 0.11.3)
    # than variable-length path queries, which may have limitations.
    _traverse_iterative(
        db=db,
        start_id=start_id,
        start_table=start_table,
        rel_type=rel_type,
        direction=direction,
        depth=depth,
        nodes=nodes,
        edges=edges,
        seen_ids=seen_ids,
    )

    return {
        "start_node_id":   start_id,
        "start_node_type": start_table,
        "nodes":           nodes,
        "edges":           edges,
    }


def _traverse_iterative(
    db,
    start_id: str,
    start_table: str,
    rel_type: str,
    direction: str,
    depth: int,
    nodes: list,
    edges: list,
    seen_ids: set,
    _current_depth: int = 0,
    _seen_edges: set | None = None,
) -> None:
    """
    Iterative BFS traversal. Kuzu 0.11.3 variable-length paths have
    syntax edge cases, so we do hop-by-hop instead.
    """
    if _current_depth >= depth:
        return

    # seen_edges prevents duplicate entries in the edges list.
    # Each edge is a (source_id, target_id, rel_type) tuple.
    # Without this, multi-hop BFS can re-discover the same edge from the
    # reverse direction in a later hop (e.g. A→B found on hop 0 as outgoing,
    # then found again on hop 1 from B as incoming with source=A, target=B).
    if _seen_edges is None:
        _seen_edges = set()

    frontier = [(start_id, start_table)]
    for hop in range(depth):
        next_frontier = []
        for node_id, node_table in frontier:
            pk = _pk_for_table(node_table)
            if pk is None:
                continue

            # Build per-table queries for each known node type
            for target_table, target_pk in _NODE_TABLES:
                try:
                    if rel_type:
                        rel_clause_out = f"[r:{rel_type}]"
                        rel_clause_in  = f"[r:{rel_type}]"
                    else:
                        rel_clause_out = "[r]"
                        rel_clause_in  = "[r]"

                    queries = []
                    # B32 fix: Kuzu 0.11.3 doesn't have type() for relationship labels.
                    # Use label(r) if available, or iterate over specific rel types.
                    # Workaround: when rel_type is specified, use it directly.
                    # When wildcard, we run a query per known rel type.
                    iter_rels = [rel_type] if rel_type else sorted(_TRAVERSABLE_RELS)
                    for iter_rel in iter_rels:
                        rc_out = f"[r:{iter_rel}]"
                        rc_in  = f"[r:{iter_rel}]"
                        if direction in ("outgoing", "both"):
                            queries.append((
                                f"MATCH (a:{node_table})-{rc_out}->(b:{target_table}) "
                                f"WHERE a.{pk} = $id "
                                f"RETURN b.{target_pk}, b.text_raw, b.confidence, b.pathway_strength",
                                node_id, "out", iter_rel,
                            ))
                        if direction in ("incoming", "both"):
                            queries.append((
                                f"MATCH (a:{node_table})<-{rc_in}-(b:{target_table}) "
                                f"WHERE a.{pk} = $id "
                                f"RETURN b.{target_pk}, b.text_raw, b.confidence, b.pathway_strength",
                                node_id, "in", iter_rel,
                            ))

                    for query, qid, qdir, qrel in queries:
                        try:
                            r = db.execute(query, {"id": qid})
                            while r.has_next():
                                row = r.get_next()
                                neighbor_id  = str(row[0]) if row[0] is not None else None
                                text_raw     = str(row[1]) if row[1] is not None else ""
                                confidence   = float(row[2]) if row[2] is not None else 0.0
                                pathway_str  = float(row[3]) if row[3] is not None else 0.0
                                edge_rel     = qrel  # use the known rel type from the query

                                if neighbor_id and neighbor_id not in seen_ids:
                                    seen_ids.add(neighbor_id)
                                    nodes.append({
                                        "node_id":          neighbor_id,
                                        "node_type":        target_table,
                                        "text_raw":         text_raw[:200],
                                        "confidence":       confidence,
                                        "pathway_strength": pathway_str,
                                    })
                                    next_frontier.append((neighbor_id, target_table))

                                if neighbor_id:
                                    if qdir == "out":
                                        edge_key = (node_id, neighbor_id, edge_rel)
                                        if edge_key not in _seen_edges:
                                            _seen_edges.add(edge_key)
                                            edges.append({
                                                "source": node_id,
                                                "target": neighbor_id,
                                                "type":   edge_rel,
                                            })
                                    else:
                                        edge_key = (neighbor_id, node_id, edge_rel)
                                        if edge_key not in _seen_edges:
                                            _seen_edges.add(edge_key)
                                            edges.append({
                                                "source": neighbor_id,
                                                "target": node_id,
                                                "type":   edge_rel,
                                            })
                        except Exception:
                            pass  # table+rel combo may not exist — normal for sparse schemas
                except Exception:
                    continue

        frontier = next_frontier
        if not frontier:
            break


def _pk_for_table(table: str) -> str | None:
    """Return the primary key column name for a node table."""
    for t, pk in _NODE_TABLES:
        if t == table:
            return pk
    return None


async def set_quest(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Explicit user override: bind session to a named quest.
    Creates new quest if name doesn't match existing.
    Sets routing_state = "locked", routing_confidence = 1.0.

    params: {session_id, quest_name, quest_id?}
    """
    session_id = params.get("session_id", "").strip()
    quest_name = params.get("quest_name", "").strip()
    quest_id   = params.get("quest_id", "").strip()

    if not session_id:
        return {"error": "session_id is required"}
    if not quest_name and not quest_id:
        return {"error": "quest_name or quest_id is required"}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # Find existing quest by name or ID
    found_id = ""
    if quest_id:
        try:
            r = db.execute(
                "MATCH (q:MainQuest {quest_id: $qid}) RETURN q.quest_id",
                {"qid": quest_id}
            )
            if r.has_next():
                found_id = r.get_next()[0]
        except Exception:
            pass
    elif quest_name:
        try:
            r = db.execute(
                "MATCH (q:MainQuest) WHERE q.name = $name AND q.status = 'active' "
                "RETURN q.quest_id LIMIT 1",
                {"name": quest_name}
            )
            if r.has_next():
                found_id = r.get_next()[0]
        except Exception:
            pass

    if not found_id:
        # Create new quest
        from mcp_engine.hippocampus import create_new_quest
        content_embedding = emb.embed(quest_name, model_name=embedding_model)
        found_id = await create_new_quest(
            db, quest_name, content_embedding, embedding_model
        )

    # Bind session with locked state
    from mcp_engine.hippocampus import _bind_session
    await _bind_session(db, session_id, found_id, 1.0, "explicit", "locked")

    return {"quest_id": found_id, "quest_name": quest_name, "routing_state": "locked"}


async def context_status(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Check the health of the current context window.

    params: {session_id}
    Returns: {token_estimate, token_limit, utilization, loaded_nodes,
              bloat_warning, handoff_available, handoff_nodes}
    """
    session_id = params.get("session_id", "").strip()
    if not session_id:
        return {"error": "session_id is required"}

    from mcp_engine.working_memory import (
        get_session_token_state, check_context_health, get_handoff_context
    )

    state = get_session_token_state(db, session_id)
    warning = check_context_health(db, session_id)

    # Check for handoff availability
    quest_id = ""
    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest) "
            "RETURN q.quest_id",
            {"sid": session_id}
        )
        if r.has_next():
            quest_id = r.get_next()[0] or ""
    except Exception:
        pass

    handoff_nodes = 0
    if quest_id:
        handoff = get_handoff_context(db, quest_id, session_id)
        handoff_nodes = len(handoff)

    return {
        "token_estimate": state["estimated_tokens"],
        "token_limit": state["token_limit"],
        "utilization": round(state["utilization"], 3),
        "loaded_nodes": state["loaded_nodes"],
        "bloat_warning": warning,
        "handoff_available": handoff_nodes > 0,
        "handoff_nodes": handoff_nodes,
    }


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "notify_turn":      notify_turn,
    "current_truth":    current_truth,
    "branch_quest":     branch_quest,
    "complete_quest":   complete_quest,
    "diff_since":       diff_since,
    "get_open_loops":   get_open_loops,
    "ingest_document":  ingest_document,
    "analogical_search": analogical_search,
    "explore_graph":    explore_graph,
    "set_quest":        set_quest,
    "context_status":   context_status,
}
