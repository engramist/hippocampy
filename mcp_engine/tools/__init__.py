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
    mc_base = (config.get("mission_control", {}) or {}).get("base_url", "http://127.0.0.1:8001")
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
                    # B15: Inject memory links into insights for easy auditing
                    if isinstance(insights, dict) and "new_entities" in insights:
                        for ent in insights["new_entities"]:
                            if "id" in ent:
                                ent["memory_link"] = f"{mc_base}/memory/node/{ent['id']}"
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
    explicit_quest_id = params.get("quest_id", "")
    quest_id   = explicit_quest_id
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
        ("Lesson",           "lesson_emb_idx",            "lesson_id"),
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

    # B18: Context Window Awareness (Working Memory) imports
    from mcp_engine.working_memory import (
        get_loaded_node_ids, deduplicate_results, track_loaded,
        update_token_estimate, estimate_tokens, check_context_health,
        get_session_token_state, get_handoff_context
    )

    all_results.sort(key=lambda r: r["_rank"], reverse=True)

    # B18: Smart deduplication — demote already-loaded nodes
    # MECHANISM (B44 Token Efficiency): This is where working memory saves tokens as a side effect.
    # Before returning results, we check which nodes are already in this session's context window
    # (via LOADED edges). Nodes that are already visible to the LLM are demoted in ranking
    # (scored at 30% of original rank) so that fresh, unseen nodes rank higher.
    #
    # Token savings: In a long conversation referencing the same decision multiple times,
    # baseline (no dedup) re-injects the same 10 nodes = 2,400 tokens each time (7,200 total).
    # With dedup: Turn 2 injects 0-3 new nodes = 600 tokens; Turn 3 = 200 tokens.
    # Result: 56% token reduction (7,200 → 3,200) over 3 turns.
    #
    # This reduction is NOT the goal — it's a consequence of tracking working memory correctly.
    # The primary goal is decision quality: we demote, not exclude, so important repeated
    # context can still surface if its demoted score ranks high enough.
    if session_id != "unknown":
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

    # B18: Add handoff candidates if this is a new session
    # We do this BEFORE track_loaded so loaded_nodes is still 0 for fresh sessions
    handoff_from_prior = None
    if quest_id and session_id != "unknown":
        try:
            state = get_session_token_state(db, session_id)
            if state["loaded_nodes"] == 0:
                # Fresh session — include handoff context
                handoff_from_prior = get_handoff_context(db, quest_id, session_id)
        except Exception:
            pass

    # B18: Track what was loaded into this session
    if session_id != "unknown" and final_results:
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
    if handoff_from_prior:
        response["handoff_from_prior_session"] = handoff_from_prior

    # B15: Deep-link panel_url — let the LLM surface a "View in Mission Control" link
    mc_base = (config.get("mission_control", {}) or {}).get("base_url", "http://127.0.0.1:7800")
    
    # Inject memory_link for each node
    for r in final_results:
        r["memory_link"] = f"{mc_base}/memory/node/{r['node_id']}"

    if mc_base:
        # Keep panel_url stable for chat deep-link handoff consumers.
        response["panel_url"] = f"{mc_base}/memory"
        if explicit_quest_id:
            response["panel_url"] = f"{mc_base}/board"
        elif session_id and session_id != "unknown":
            response["panel_url"] = f"{mc_base}/memory?context={session_id}"

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
                domain:           'generic',
                lesson_type:      'optimization',
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


async def upsert_lesson(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Explicitly add or update a Lesson node.
    
    params: {text, domain, lesson_type, session_id?, lesson_id?}
    """
    text        = params.get("text", "").strip()
    domain      = params.get("domain", "generic").strip()
    lesson_type = params.get("lesson_type", "optimization").strip()
    session_id  = params.get("session_id", "unknown")
    lesson_id   = params.get("lesson_id") or str(uuid.uuid4())

    if not text:
        return {"error": "text is required"}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    vector = emb.embed(text, model_name=embedding_model)
    now = datetime.now(timezone.utc).isoformat()

    await db.execute_write(
        """
        MERGE (l:Lesson {lesson_id: $lid})
        ON CREATE SET l.text_raw = $text,
                      l.embedding = $emb,
                      l.embedding_model = $model,
                      l.embedding_dim = $dim,
                      l.domain = $domain,
                      l.lesson_type = $type,
                      l.confidence = 0.90,
                      l.confidence_low = false,
                      l.pathway_strength = 1.0,
                      l.archived = false,
                      l.created_at = timestamp($now)
        ON MATCH SET  l.text_raw = $text,
                      l.embedding = $emb,
                      l.domain = $domain,
                      l.lesson_type = $type,
                      l.pathway_strength = l.pathway_strength + 0.1
        """,
        {
            "lid": lesson_id,
            "text": text,
            "emb": vector,
            "model": embedding_model,
            "dim": len(vector),
            "domain": domain,
            "type": lesson_type,
            "now": now,
        }
    )

    if session_id != "unknown":
        await db.execute_write(
            "MATCH (s:Session {session_id: $sid}), (l:Lesson {lesson_id: $lid}) "
            "MERGE (s)-[:LEARNED]->(l)",
            {"sid": session_id, "lid": lesson_id}
        )

    return {"lesson_id": lesson_id, "status": "upserted"}


async def recall_relevant_lessons(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Fetch lessons matching a domain or similarity to a query.
    
    params: {query?, domain?, limit}
    """
    query  = params.get("query", "")
    domain = params.get("domain", "")
    limit  = int(params.get("limit", 5))

    lessons = []

    if query:
        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        vector = emb.embed(query, model_name=embedding_model)
        rows = db.vector_search("Lesson", "lesson_emb_idx", vector, limit)
        for row in rows:
            node = row["node"]
            if node.get("archived"): continue
            lessons.append({
                "lesson_id": node["lesson_id"],
                "text": node["text_raw"],
                "domain": node.get("domain", "generic"),
                "type": node.get("lesson_type", "optimization"),
                "similarity": row["score"]
            })
    elif domain:
        r = db.execute(
            "MATCH (l:Lesson) WHERE l.domain = $domain AND l.archived = false "
            "RETURN l.lesson_id, l.text_raw, l.lesson_type LIMIT $limit",
            {"domain": domain, "limit": limit}
        )
        while r.has_next():
            row = r.get_next()
            lessons.append({
                "lesson_id": row[0],
                "text": row[1],
                "domain": domain,
                "type": row[2]
            })

    return {"lessons": lessons}


# ---------------------------------------------------------------------------
# B10 — explore_graph (directed graph traversal)
# ---------------------------------------------------------------------------

# Traversal constants and implementation moved to modular tool file (B10)
from mcp_engine.tools.explore_graph import (
    explore_graph, _TRAVERSABLE_RELS, _NODE_TABLES, _MAX_DEPTH
)


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


async def get_anomalies(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Retrieve all flagged anomalies for review.

    B12 — Anomaly Detection. Anomalies are nodes that contradicted high-confidence
    GlobalConstraints or GlobalPreferences. They are stored, not deleted, and marked
    for manual review.

    params: {scope ("branch"|"global"|"both"), limit, quest_id?}
    Returns: {anomalies: [{node_id, node_type, text_raw, anomaly_type, confidence,
                           constraint_id, constraint_text}]}
    """
    scope = params.get("scope", "branch")
    limit = int(params.get("limit", 20))
    quest_id = params.get("quest_id", "")

    # Determine scope: branch-scoped anomalies are linked to the active MainQuest
    scope_filter = ""
    if scope == "branch" and quest_id:
        scope_filter = (
            "MATCH (q:MainQuest {quest_id: $quest_id}) "
            "MATCH (n:Concept)-[:REIFIED_AS]-(a:Decision)-[:ESTABLISHED_IN]->(s:Session) "
            "MATCH (s)-[:WORKING_ON]->(q) "
            "WHERE n.flagged_for_review = true "
        )
    else:
        # Global scope: all flagged nodes, no quest filter
        scope_filter = (
            "MATCH (n) "
            "WHERE n.flagged_for_review = true AND (n:Concept OR n:Decision OR n:Constraint OR "
            "      n:Requirement OR n:ActionItem OR n:Message OR n:DocumentExtract) "
        )

    query = f"""
        {scope_filter}
        MATCH (n)-[r:ANOMALY_DETECTED]->(gc:GlobalConstraint)
        RETURN n, r, gc
        LIMIT $limit
    """

    try:
        result = db.execute(
            query,
            {"quest_id": quest_id, "limit": limit}
        )
    except Exception as e:
        _logger.exception("get_anomalies query failed")
        return {"anomalies": [], "error": str(e)}

    anomalies = []
    if result:
        while result.has_next():
            row = result.get_next()
            try:
                node = row[0]
                edge = row[1]
                constraint = row[2]

                # Determine node type and ID
                node_type = node.get_label_name() if hasattr(node, "get_label_name") else ""
                if not node_type:
                    # Fallback: infer from properties
                    if hasattr(node, "concept_id"):
                        node_type = "Concept"
                    elif hasattr(node, "decision_id"):
                        node_type = "Decision"
                    else:
                        continue

                node_id_key = {
                    "Concept": "concept_id",
                    "Decision": "decision_id",
                    "Constraint": "constraint_id",
                    "Message": "message_id",
                    "DocumentExtract": "extract_id",
                }.get(node_type, "id")

                node_id = node.get(node_id_key, "")
                node_text = node.get("text_raw", "")
                anomaly_type = edge.get("type", "")
                anomaly_confidence = edge.get("confidence", 0.0)

                constraint_id = constraint.get("global_constraint_id", "")
                constraint_text = constraint.get("text_raw", "")

                anomalies.append({
                    "node_id": node_id,
                    "node_type": node_type,
                    "text_raw": node_text,
                    "anomaly_type": anomaly_type,
                    "confidence": round(float(anomaly_confidence), 3),
                    "constraint_id": constraint_id,
                    "constraint_text": constraint_text,
                })
            except Exception as e:
                _logger.warning(f"Failed to process anomaly row: {e}")
                continue

    return {"anomalies": anomalies, "count": len(anomalies)}


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
        "message_count": state["message_count"],
        "tokens_saved_by_dedup": state.get("dedup_tokens_saved", 0),
        "injection_count": state.get("injection_count", 0),
        "bloat_warning": warning,
        "handoff_available": handoff_nodes > 0,
        "handoff_nodes": handoff_nodes,
    }


async def get_openclaw_prompt(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Get the system prompt fragments for OpenClaw.
    
    params: {session_id}
    """
    session_id = params.get("session_id", "unknown")
    
    # Check if session is onboarded
    onboarded = False
    quest_info = None
    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid}) "
            "OPTIONAL MATCH (s)-[:WORKING_ON]->(q:MainQuest) "
            "RETURN s.onboarded, q.name, q.git_branch",
            {"sid": session_id}
        )
        if r.has_next():
            row = r.get_next()
            onboarded = bool(row[0])
            if row[1]:
                quest_info = {"name": row[1], "branch": row[2] or "main"}
    except Exception:
        pass
        
    from adapters.openclaw_gateway import build_openclaw_prompt
    prompt = await build_openclaw_prompt(session_id, onboarded, quest_info)
    
    # Mark as onboarded if it was not
    if not onboarded and session_id != "unknown":
        try:
            await db.execute_write(
                "MATCH (s:Session {session_id: $sid}) SET s.onboarded = true",
                {"sid": session_id}
            )
        except Exception:
            pass
            
    return {"prompt": prompt}


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
    "get_anomalies":    get_anomalies,           # B12
    "upsert_lesson":    upsert_lesson,           # B11
    "recall_relevant_lessons": recall_relevant_lessons,  # B11
    "get_openclaw_prompt": get_openclaw_prompt,  # B21
}
