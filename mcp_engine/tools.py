"""
mcp_engine/tools.py — MCP Tool Implementations (Brain Daemon side)

The IPC server in brain_daemon.py dispatches JSON-RPC calls here.
All writes go through db.execute_write() to respect the asyncio write lock.
"""

from __future__ import annotations
import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

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
        content = content[:max_chars].rsplit(".", 1)[0] + "."

    if not content.strip():
        return {"status": "skipped", "reason": "empty content"}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    vector     = emb.embed(content, model_name=embedding_model)
    message_id = str(uuid.uuid4())
    now        = datetime.now(timezone.utc).isoformat()

    # M5: resolve MainQuest + upsert Session before writing message
    quest_id = ""
    if repo_root:
        quest_id = await get_or_create_main_quest(
            db, repo_root, git_branch, embedding_model, now
        )
        await get_or_create_session(db, session_id, quest_id, now)

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
            created_at:      $created_at
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

    # Enqueue for Gated Consolidation Loop (M3+)
    if _loop_queue is not None:
        await _loop_queue.put((message_id, content))

    return {"status": "queued", "message_id": message_id, "quest_id": quest_id}


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

    # Resolve quest_id if not provided but git context is
    if not quest_id and repo_root:
        from mcp_engine.quest import compute_quest_id
        quest_id = compute_quest_id(repo_root, git_branch)

    query_vector = emb.embed(query, model_name=embedding_model)

    # Vector search across artifact tables
    artifact_tables = [
        ("Decision",         "decision_emb_idx",         "decision_id"),
        ("Constraint",       "constraint_emb_idx",        "constraint_id"),
        ("Requirement",      "requirement_emb_idx",       "requirement_id"),
        ("ActionItem",       "action_item_emb_idx",       "action_item_id"),
        ("GlobalConstraint", "globalconstraint_emb_idx",  "global_constraint_id"),
        ("GlobalPreference", "globalpreference_emb_idx",  "global_preference_id"),
    ]

    all_results = []
    per_table_limit = max(limit, 5)

    for table_name, index_name, pk in artifact_tables:
        try:
            rows = db.vector_search(index_name, query_vector, per_table_limit)
            for row in rows:
                node = row["node"]
                if node.get("archived", False):
                    continue
                node_id = (node.get("decision_id") or node.get("constraint_id")
                           or node.get("requirement_id") or node.get("action_item_id")
                           or node.get("global_constraint_id")
                           or node.get("global_preference_id", "unknown"))
                all_results.append({
                    "node_id":          node_id,
                    "node_type":        table_name,
                    "text_raw":         node.get("text_raw", ""),
                    "confidence":       node.get("confidence", 0.0),
                    "confidence_low":   node.get("confidence_low", True),
                    "pathway_strength": node.get("pathway_strength", 0.0),
                    "similarity":       row["score"],
                    "_rank": (node.get("pathway_strength", 0.0) * node.get("confidence", 0.0))
                              or row["score"],
                })
        except Exception:
            pass

    all_results.sort(key=lambda r: r["_rank"], reverse=True)
    for r in all_results:
        del r["_rank"]

    # M5: include quest context for branch scope
    quest_ctx = {}
    if quest_id and scope in ("branch", "both"):
        quest_ctx = get_quest_context(db, quest_id, limit=5)

    return {"results": all_results[:limit], "quest_context": quest_ctx}


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
# Dispatch table
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "notify_turn":   notify_turn,
    "current_truth": current_truth,
    "branch_quest":  branch_quest,
    "diff_since":    diff_since,
    "get_open_loops": get_open_loops,
}
