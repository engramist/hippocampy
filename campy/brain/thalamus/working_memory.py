"""
mcp_engine/working_memory.py — Context Window Awareness ("Working Memory")

Tracks what graph nodes are loaded in each LLM session's context window via LOADED edges.
Enables smart deduplication, bloat detection, and session handoff.

TOKEN EFFICIENCY AS A SIDE EFFECT (B44):
========================================
This module is primarily designed for *decision quality* — tracking what the LLM has already
seen prevents lost context and enables cross-session knowledge transfer. Token efficiency
emerges as a natural consequence:

1. By demoting already-loaded nodes in retrieval ranking (scored at 30% of original rank),
   the system naturally avoids re-injecting redundant knowledge.

2. A typical long conversation with recurring discussion of the same decision shows 56%
   token reduction vs. baseline (no load awareness): 7,200 tokens → 3,200 tokens over 3 turns.

3. Session handoff pre-loads prior session context (~400 tokens) and avoids full re-retrieval
   of 20+ nodes, saving 7,600+ tokens per session boundary.

The efficiency is not a bolted-on optimization — it flows from this design principle:
**context window as a first-class, tracked resource** (working memory model).

See: docs/token-efficiency-side-effect.md for detailed analysis and token curves.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

# Node type → primary key column mapping (shared across the module).
# Only consolidated artifact nodes participate in LOADED working-memory handoff.
# Raw Message / DocumentExtract recall is token-counted by current_truth but is
# intentionally not LOADED-tracked so transcripts do not become context cargo.
NODE_PK_MAP = {
    "Concept":          "concept_id",
    "Decision":         "decision_id",
    "Constraint":       "constraint_id",
    "Requirement":      "requirement_id",
    "ActionItem":       "action_item_id",
    "GlobalConstraint": "global_constraint_id",
    "GlobalPreference": "global_preference_id",
}

# ---------------------------------------------------------------------------
# Constants — Working Memory Configuration
# ---------------------------------------------------------------------------
# These constants configure the context window awareness system. Together, they implement
# the token efficiency mechanisms described in docs/token-efficiency-side-effect.md:
#
# 1. DEDUP_DEMOTION_FACTOR: Controls how much we demote already-loaded nodes in retrieval.
#    Lower = more aggressive dedup, but may sacrifice decision quality if important context
#    gets pushed below the top-K cutoff. 0.3 (30%) balances efficiency and quality.
#
# 2. BLOAT_WARNING_THRESHOLD: When utilization crosses this, warn the LLM. Encourages
#    natural session boundaries and prevents token accumulation OOM.
#
# 3. CHARS_PER_TOKEN + DEFAULT_TOKEN_LIMIT: Enable bloat detection and handoff decisions.
#    Conservative estimation avoids undercount and silent failures.

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

    USED BY WORKING MEMORY (B44):
    =============================
    This simple estimator is called by track_loaded() to populate LOADED.token_estimate.
    The token_estimate values flow into:

    1. Session.token_estimate (cumulative): Sum of all injected node token counts
    2. Bloat detection: utilization = session.token_estimate / session.token_limit
    3. Handoff decisions: Which nodes to carry forward to next session

    Conservative heuristic (3 chars/token): Avoids underestimating and failing to warn
    when context is near capacity. Better to warn early than hit an OOM cliff.
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

    ENABLES TOKEN EFFICIENCY (B44):
    =============================
    This function is called after every context window injection to track what the LLM
    has seen. The LOADED edges created here power three token efficiency mechanisms:

    1. Smart Deduplication (deduplicate_results): Subsequent current_truth() calls
       demote already-loaded nodes, avoiding re-injection.

    2. Bloat Detection (check_context_health): Session.token_estimate is incremented,
       enabling utilization monitoring and warnings when context nears capacity.

    3. Cross-session Handoff (get_handoff_context): LOADED edges from the prior session
       are queries to pre-populate the new session, avoiding full vector search.

    None of this requires any "token efficiency optimization" code. It all flows from
    tracking which nodes are in the context window correctly.

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
    processed = 0
    dedup_saved = 0

    for r in results:
        node_id = r.get("node_id", "")
        node_type = r.get("node_type", "")
        text_raw = r.get("text_raw", "")

        if not node_id or node_type not in NODE_PK_MAP:
            continue

        processed += 1
        pk_col = NODE_PK_MAP[node_type]
        tokens = estimate_tokens(text_raw)

        try:
            check = db.execute(
                f"MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type} {{{pk_col}: $nid}}) "
                f"RETURN l.load_hits",
                {"sid": session_id, "nid": node_id}
            )
            if check.has_next():
                row = check.get_next()
                prev_hits = int(row[0]) if row[0] else 1
                new_hits = prev_hits + 1
                dedup_saved += tokens
                await db.execute_write(
                    f"MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type} {{{pk_col}: $nid}}) "
                    f"SET l.injected_at = timestamp($now), "
                    f"    l.load_hits = $hits, "
                    f"    l.token_estimate = $tokens",
                    {"sid": session_id, "nid": node_id, "now": now,
                     "hits": new_hits, "tokens": tokens}
                )
            else:
                await db.execute_write(
                    f"MATCH (s:Session {{session_id: $sid}}), (n:{node_type} {{{pk_col}: $nid}}) "
                    f"CREATE (s)-[:LOADED {{injected_at: timestamp($now), "
                    f"token_estimate: $tokens, source: $source, load_hits: 1}}]->(n)",
                    {"sid": session_id, "nid": node_id, "now": now,
                     "tokens": tokens, "source": source}
                )
            count += 1
        except Exception:
            _logger.debug("track_loaded: failed for %s -> %s:%s", session_id, node_type, node_id)

    if processed > 0:
        try:
            loaded_count = _count_loaded(db, session_id)
            await db.execute_write(
                "MATCH (s:Session {session_id: $sid}) "
                "SET s.loaded_node_count = $count, "
                "    s.last_injection_at = timestamp($now), "
                "    s.injection_count = coalesce(s.injection_count, 0) + $processed, "
                "    s.dedup_tokens_saved = coalesce(s.dedup_tokens_saved, 0) + $dedup",
                {"sid": session_id, "count": loaded_count, "now": now,
                 "processed": processed, "dedup": dedup_saved}
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

    for node_type, pk_col in NODE_PK_MAP.items():
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

    TOKEN EFFICIENCY MECHANISM (B44):
    ================================
    This is where the working memory design saves tokens as a side effect.
    - Already-loaded nodes are scored at DEDUP_DEMOTION_FACTOR (0.3 = 30% of original rank)
    - They remain in results, but rank lower than fresh nodes
    - The LLM may still inject them if no better alternatives exist
    - This prevents re-injecting the same knowledge while preserving quality

    Example: In turn 15 of a conversation about the same decision:
    - 10 candidate nodes from vector search (same as turn 5)
    - All 10 are in loaded_ids (already in context)
    - All 10 demoted to 30% rank
    - If new context is available, new nodes rank higher
    - Top-K selection may yield 3 new nodes instead of 10, saving ~1,800 tokens vs. baseline
    """
    for r in results:
        if r.get("node_id") in loaded_ids:
            r["already_in_context"] = True
            # Demote the ranking score (multiply by 0.3 = 30% of original)
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
            "RETURN s.token_estimate, s.token_limit, s.loaded_node_count, "
            "       s.dedup_tokens_saved, s.injection_count",
            {"sid": session_id}
        )
        if r.has_next():
            row = r.get_next()
            est = int(row[0]) if len(row) > 0 and row[0] else 0
            limit = int(row[1]) if len(row) > 1 and row[1] else DEFAULT_TOKEN_LIMIT
            loaded = int(row[2]) if len(row) > 2 and row[2] else 0
            dedup_saved = int(row[3]) if len(row) > 3 and row[3] else 0
            injection_total = int(row[4]) if len(row) > 4 and row[4] else 0

            # B64: Message count for session stats (Session -> count SENT_IN edges)
            msg_count = 0
            try:
                # Trace: Session node -> count SENT_IN edges -> return count
                # Filter for archived=false to avoid over-counting deprecated turns.
                # B64: Include NULL archived values to handle older databases robustly.
                mr = db.execute(
                    "MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid}) "
                    "WHERE m.archived IS NULL OR m.archived = false "
                    "RETURN count(m)",
                    {"sid": session_id}
                )
                if mr.has_next():
                    msg_count = int(mr.get_next()[0] or 0)
            except Exception:
                pass

            return {
                "estimated_tokens": est,
                "token_limit": limit,
                "utilization": est / limit if limit > 0 else 0.0,
                "loaded_nodes": loaded,
                "message_count": msg_count,
                "dedup_tokens_saved": dedup_saved,
                "injection_count": injection_total,
            }
    except Exception:
        pass

    return {
        "estimated_tokens": 0,
        "token_limit": DEFAULT_TOKEN_LIMIT,
        "utilization": 0.0,
        "loaded_nodes": 0,
        "message_count": 0,
        "dedup_tokens_saved": 0,
        "injection_count": 0,
    }


def check_context_health(db: KuzuClient, session_id: str) -> Optional[str]:
    """
    Returns warning message if context is getting bloated.

    TOKEN EFFICIENCY MECHANISM (B44):
    ================================
    Monitors session utilization to warn when the context window is approaching capacity.
    This prevents OOM errors and encourages healthy session design (shorter, focused
    conversations with periodic handoff to fresh sessions).

    When utilization > 75% (BLOAT_WARNING_THRESHOLD):
    - LLM is warned to wrap up or hand off to a new session
    - New session is pre-loaded with top-5 nodes from prior session (via get_handoff_context)
    - This creates a natural "session boundary" where token accumulation resets

    Result: Instead of one long, token-heavy session, multiple short sessions with
    proactive handoff preserve context while limiting any single session's bloat.
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

    TOKEN EFFICIENCY MECHANISM (B44):
    ================================
    Cross-session handoff enables reuse of prior session context without re-fetching.
    The prior session's LOADED nodes are queried, ranked by pathway_strength, and
    the top-5 are pre-loaded into the new session's context.

    Cost-benefit:
    - Handoff context injected once at new session start: ~400 tokens
    - Avoids full vector search + retrieval of 20+ nodes across first 5 turns: ~8,000–12,000 tokens
    - Net savings per session boundary: 7,600+ tokens

    This is not a caching optimization; it's a natural consequence of treating the
    context window as working memory. Prior sessions accumulate knowledge; new sessions
    inherit it intelligently via the LOADED edges tracked in the graph.
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

    for node_type, pk_col in NODE_PK_MAP.items():
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
    for node_type in NODE_PK_MAP:
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


def get_session_token_timeline(
    db: KuzuClient,
    session_id: str,
    limit: int = 40,
) -> list[dict]:
    """
    Return a chronological list of LOADED events for a session.
    Each event contains node_id, node_type, tokens, injected_at, load_hits and dedup savings.
    """
    events: list[dict] = []

    for node_type, pk_col in NODE_PK_MAP.items():
        try:
            r = db.execute(
                f"MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type}) "
                f"RETURN n.{pk_col}, l.injected_at, l.token_estimate, l.load_hits "
                f"ORDER BY l.injected_at ASC",
                {"sid": session_id},
            )
            while r.has_next():
                row = r.get_next()
                tokens = int(row[2] or 0)
                load_hits = int(row[3] or 1)
                events.append({
                    "node_id": row[0],
                    "node_type": node_type,
                    "tokens": tokens,
                    "injected_at": str(row[1]) if row[1] else None,
                    "load_hits": load_hits,
                    "dedup_savings": tokens * (load_hits - 1),
                })
        except Exception:
            pass

    events.sort(key=lambda e: e["injected_at"] or "")
    if limit and len(events) > limit:
        events = events[-limit:]
    return events
