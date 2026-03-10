"""
mcp_engine/tools.py — MCP Tool Implementations (Brain Daemon side)

The IPC server in brain_daemon.py dispatches JSON-RPC calls here.
All writes go through db.execute_write() to respect the asyncio write lock.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.graph import embeddings as emb

# ---------------------------------------------------------------------------
# M3 runtime state — initialized by brain_daemon.py at startup
# ---------------------------------------------------------------------------

# Queue of (message_id, text) tuples for the Gated Consolidation Loop worker
_loop_queue: asyncio.Queue | None = None


def init_loop_queue(queue: asyncio.Queue) -> None:
    """Called once by BrainDaemon.start() after the event loop is running."""
    global _loop_queue
    _loop_queue = queue

# ---------------------------------------------------------------------------
# M2 Tools
# ---------------------------------------------------------------------------

async def notify_turn(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Receive a conversation turn from the adapter and store it as a Message node.
    Called by the LLM (assistant turns) and by the UserPromptSubmit hook (user turns).
    Returns immediately — Loop processing is queued for background (M3+).

    params: {role, content, session_id}
    """
    role       = params.get("role", "user")
    content    = params.get("content", "")
    session_id = params.get("session_id", "unknown")

    # Truncate at max_ingest_chars (sentence boundary preferred — simple truncation for now)
    max_chars = config.get("ingestion", {}).get("max_ingest_chars", 4000)
    if len(content) > max_chars:
        content = content[:max_chars].rsplit(".", 1)[0] + "."

    if not content.strip():
        return {"status": "skipped", "reason": "empty content"}

    # Embed the message content
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    vector = emb.embed(content, model_name=embedding_model)

    message_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

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

    # Link to Session if it exists
    await db.execute_write(
        """
        MATCH (s:Session {session_id: $session_id}), (m:Message {message_id: $message_id})
        MERGE (m)-[:SENT_IN]->(s)
        """,
        {"session_id": session_id, "message_id": message_id}
    )

    # Enqueue for Gated Consolidation Loop processing (M3+)
    if _loop_queue is not None:
        await _loop_queue.put((message_id, content))

    return {"status": "queued", "message_id": message_id}


async def current_truth(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Retrieve relevant memory for a query.
    Embeds query, runs vector search across all artifact tables, returns ranked results.

    params: {query, session_id, scope ("branch"|"global"|"both"), limit}
    """
    query      = params.get("query", "")
    session_id = params.get("session_id", "unknown")
    scope      = params.get("scope", "branch")
    limit      = int(params.get("limit", 10))

    if not query.strip():
        return {"results": []}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    query_vector = emb.embed(query, model_name=embedding_model)

    # Search across all artifact node tables (UNION ALL via Python at M2)
    # M3+: use projected graphs for active-only prefiltering
    artifact_tables = [
        ("Decision",          "decision_emb_idx",           "decision_id"),
        ("Constraint",        "constraint_emb_idx",         "constraint_id"),
        ("Requirement",       "requirement_emb_idx",        "requirement_id"),
        ("ActionItem",        "action_item_emb_idx",        "action_item_id"),
        ("GlobalConstraint",  "globalconstraint_emb_idx",   "global_constraint_id"),
        ("GlobalPreference",  "globalpreference_emb_idx",   "global_preference_id"),
    ]

    all_results = []
    per_table_limit = max(limit, 5)  # fetch enough per table before merging

    for table_name, index_name, _pk in artifact_tables:
        try:
            rows = db.vector_search(index_name, query_vector, per_table_limit)
            for row in rows:
                node = row["node"]
                all_results.append({
                    "node_id":         node.get("decision_id") or node.get("constraint_id")
                                       or node.get("requirement_id") or node.get("action_item_id")
                                       or node.get("global_constraint_id")
                                       or node.get("global_preference_id", "unknown"),
                    "node_type":       table_name,
                    "text_raw":        node.get("text_raw", ""),
                    "confidence":      node.get("confidence", 0.0),
                    "confidence_low":  node.get("confidence_low", True),
                    "pathway_strength": node.get("pathway_strength", 0.0),
                    "similarity":      row["score"],
                    # Compound rank score: pathway_strength × confidence (strength is 0 at M2,
                    # so we fall back to similarity until M4 pathway updates are implemented)
                    "_rank": (node.get("pathway_strength", 0.0) * node.get("confidence", 0.0))
                              or row["score"],
                })
        except Exception:
            # Index may not exist yet if no nodes of this type have been created
            pass

    # Sort by rank score, return top N
    all_results.sort(key=lambda r: r["_rank"], reverse=True)
    for r in all_results:
        del r["_rank"]

    return {"results": all_results[:limit]}


# ---------------------------------------------------------------------------
# Dispatch table (used by brain_daemon.py)
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "notify_turn":   notify_turn,
    "current_truth": current_truth,
    # M5 tools registered here when implemented:
    # "branch_quest":   branch_quest,
    # "complete_quest": complete_quest,
    # "diff_since":     diff_since,
    # "get_open_loops": get_open_loops,
}
