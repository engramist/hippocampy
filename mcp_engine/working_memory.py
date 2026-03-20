"""
mcp_engine/working_memory.py — Context Window Awareness ("Working Memory")

Tracks what graph nodes are loaded in each LLM session's context window.
Enables smart deduplication, bloat detection, and session handoff.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOAT_WARNING_THRESHOLD = 0.75    # 75% of context window used
DEDUP_DEMOTION_FACTOR = 0.3      # Already-loaded nodes scored at 30%
DEFAULT_TOKEN_LIMIT = 128000     # Conservative default (Claude/GPT-4 class)
CHARS_PER_TOKEN = 3              # ~3 chars per token (conservative for English)

# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text. Simple heuristic — no tokenizer dependency.
    ~3 chars per token for English (conservative to avoid undercount).
    Returns int.
    """
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN


async def track_loaded(
    db: KuzuClient,
    session_id: str,
    results: list[dict],
    source: str = "current_truth",
) -> int:
    """
    Record which nodes were injected into the context window.
    Creates LOADED edges from Session to each returned node.
    Updates Session.loaded_node_count and Session.last_injection_at.

    Parameters:
        db: KuzuClient
        session_id: str
        results: list of dicts with "node_id", "node_type", "text_raw" keys
        source: "current_truth" | "system_prompt" | "onboarding" | "handoff"

    Returns:
        int — number of LOADED edges created/updated
    """
    now = datetime.now(timezone.utc).isoformat()
    count = 0

    # Map node_type to PK column name
    pk_map = {
        "Concept":          "concept_id",
        "Decision":         "decision_id",
        "Constraint":       "constraint_id",
        "Requirement":      "requirement_id",
        "ActionItem":       "action_item_id",
        "GlobalConstraint": "global_constraint_id",
        "GlobalPreference": "global_preference_id",
    }

    for r in results:
        node_id = r.get("node_id", "")
        node_type = r.get("node_type", "")
        text_raw = r.get("text_raw", "")

        if not node_id or node_type not in pk_map:
            continue

        pk_col = pk_map[node_type]
        tokens = estimate_tokens(text_raw)

        try:
            # Check if LOADED edge already exists
            check = db.execute(
                f"MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type} {{{pk_col}: $nid}}) "
                f"RETURN l.injected_at",
                {"sid": session_id, "nid": node_id}
            )
            if check.has_next():
                # Update existing edge timestamp
                await db.execute_write(
                    f"MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type} {{{pk_col}: $nid}}) "
                    f"SET l.injected_at = timestamp($now)",
                    {"sid": session_id, "nid": node_id, "now": now}
                )
            else:
                # Create new edge
                await db.execute_write(
                    f"MATCH (s:Session {{session_id: $sid}}), (n:{node_type} {{{pk_col}: $nid}}) "
                    f"CREATE (s)-[:LOADED {{injected_at: timestamp($now), "
                    f"token_estimate: $tokens, source: $source}}]->(n)",
                    {"sid": session_id, "nid": node_id, "now": now,
                     "tokens": tokens, "source": source}
                )
            count += 1
        except Exception:
            _logger.debug("track_loaded: failed for %s -> %s:%s", session_id, node_type, node_id)

    # Update session metadata
    if count > 0:
        try:
            loaded_count = _count_loaded(db, session_id)
            await db.execute_write(
                "MATCH (s:Session {session_id: $sid}) "
                "SET s.loaded_node_count = $count, "
                "    s.last_injection_at = timestamp($now)",
                {"sid": session_id, "count": loaded_count, "now": now}
            )
        except Exception:
            pass

    return count


def get_loaded_node_ids(db: KuzuClient, session_id: str) -> set[str]:
    """
    Return set of node_ids currently loaded in this session's context.
    Queries all LOADED edges from this Session.
    """
    loaded = set()
    pk_map = {
        "Concept":          "concept_id",
        "Decision":         "decision_id",
        "Constraint":       "constraint_id",
        "Requirement":      "requirement_id",
        "ActionItem":       "action_item_id",
        "GlobalConstraint": "global_constraint_id",
        "GlobalPreference": "global_preference_id",
    }

    for node_type, pk_col in pk_map.items():
        try:
            r = db.execute(
                f"MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type}) "
                f"RETURN n.{pk_col}",
                {"sid": session_id}
            )
            while r.has_next():
                row = r.get_next()
                if row[0]:
                    loaded.add(row[0])
        except Exception:
            pass

    return loaded


def deduplicate_results(
    results: list[dict],
    loaded_ids: set[str],
) -> list[dict]:
    """
    Demote (not exclude) already-loaded nodes in retrieval results.
    Adds "already_in_context" flag and reduces relevance_score.
    """
    for r in results:
        if r.get("node_id") in loaded_ids:
            r["already_in_context"] = True
            # Demote the ranking score
            if "_rank" in r:
                r["_rank"] *= DEDUP_DEMOTION_FACTOR
        else:
            r["already_in_context"] = False

    results.sort(key=lambda r: r.get("_rank", 0), reverse=True)
    return results


async def update_token_estimate(
    db: KuzuClient,
    session_id: str,
    new_tokens: int,
) -> None:
    """
    Increment the session's cumulative token estimate.
    """
    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid}) "
            "RETURN s.token_estimate",
            {"sid": session_id}
        )
        current = 0
        if r.has_next():
            val = r.get_next()[0]
            current = int(val) if val else 0

        await db.execute_write(
            "MATCH (s:Session {session_id: $sid}) "
            "SET s.token_estimate = $est",
            {"sid": session_id, "est": current + new_tokens}
        )
    except Exception:
        pass


def get_session_token_state(db: KuzuClient, session_id: str) -> dict:
    """
    Returns current token usage vs. limit for a session.
    """
    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid}) "
            "RETURN s.token_estimate, s.token_limit, s.loaded_node_count",
            {"sid": session_id}
        )
        if r.has_next():
            row = r.get_next()
            est = int(row[0]) if row[0] else 0
            limit = int(row[1]) if row[1] else DEFAULT_TOKEN_LIMIT
            loaded = int(row[2]) if row[2] else 0
            return {
                "estimated_tokens": est,
                "token_limit": limit,
                "utilization": est / limit if limit > 0 else 0.0,
                "loaded_nodes": loaded,
            }
    except Exception:
        pass

    return {
        "estimated_tokens": 0,
        "token_limit": DEFAULT_TOKEN_LIMIT,
        "utilization": 0.0,
        "loaded_nodes": 0,
    }


def check_context_health(db: KuzuClient, session_id: str) -> Optional[str]:
    """
    Returns warning message if context is getting bloated.
    """
    state = get_session_token_state(db, session_id)
    if state["utilization"] > BLOAT_WARNING_THRESHOLD:
        return (
            f"Context window is {state['utilization']:.0%} full "
            f"({state['estimated_tokens']}/{state['token_limit']} tokens). "
            f"Consider starting a fresh conversation."
        )
    return None


def get_handoff_context(
    db: KuzuClient,
    quest_id: str,
    new_session_id: str,
    limit: int = 5,
) -> list[dict]:
    """
    When a new session starts for the same quest, return the most important
    nodes from the prior session's working memory.
    """
    # Find prior session
    prev_session_id = ""
    try:
        r = db.execute(
            "MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid}) "
            "WHERE s.session_id <> $new_sid "
            "RETURN s.session_id "
            "ORDER BY s.last_active_at DESC "
            "LIMIT 1",
            {"qid": quest_id, "new_sid": new_session_id}
        )
        if r.has_next():
            prev_session_id = r.get_next()[0] or ""
    except Exception:
        pass

    if not prev_session_id:
        return []

    # Get loaded nodes from prior session
    handoff = []
    pk_map = {
        "Concept":          "concept_id",
        "Decision":         "decision_id",
        "Constraint":       "constraint_id",
        "Requirement":      "requirement_id",
        "ActionItem":       "action_item_id",
        "GlobalConstraint": "global_constraint_id",
        "GlobalPreference": "global_preference_id",
    }

    for node_type, pk_col in pk_map.items():
        try:
            r = db.execute(
                f"MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type}) "
                f"WHERE n.archived = false "
                f"RETURN n.{pk_col}, n.text_raw, n.pathway_strength "
                f"ORDER BY n.pathway_strength DESC "
                f"LIMIT $limit",
                {"sid": prev_session_id, "limit": limit}
            )
            while r.has_next():
                row = r.get_next()
                handoff.append({
                    "node_id": row[0],
                    "node_type": node_type,
                    "text_raw": row[1] or "",
                    "pathway_strength": float(row[2]) if row[2] else 0.0,
                })
        except Exception:
            pass

    # Sort by pathway_strength and return top N
    handoff.sort(key=lambda x: x["pathway_strength"], reverse=True)
    return handoff[:limit]


def _count_loaded(db: KuzuClient, session_id: str) -> int:
    """Count total LOADED edges from this session."""
    total = 0
    pk_map = {
        "Concept":          "concept_id",
        "Decision":         "decision_id",
        "Constraint":       "constraint_id",
        "Requirement":      "requirement_id",
        "ActionItem":       "action_item_id",
        "GlobalConstraint": "global_constraint_id",
        "GlobalPreference": "global_preference_id",
    }
    for node_type in pk_map:
        try:
            r = db.execute(
                f"MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type}) "
                f"RETURN count(*)",
                {"sid": session_id}
            )
            if r.has_next():
                total += int(r.get_next()[0] or 0)
        except Exception:
            pass
    return total
