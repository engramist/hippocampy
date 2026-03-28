# B-18: Context Window Awareness ("Working Memory")

## Overview

Model each LLM session as a tracked working memory buffer. The Brain currently has no visibility into what's loaded in each LLM's context window — `current_truth` can re-inject the same facts repeatedly, session handoffs lose track of what the LLM already knows, and there's no bloat detection. B18 adds LOADED edge tracking, smart deduplication, token estimation, and session handoff intelligence.

Architecture doc: `B17-B18-architecture.md`

**Dependency:** B17 (Hippocampus) must be implemented first. B18 layers on top of the Session schema changes and `notify_turn` rewire from B17.

---

## Implementation Order

```
Phase 1: Schema additions (Session properties + LOADED relationship)
Phase 2: working_memory.py — core module (load tracking, dedup, token estimation)
Phase 3: Wire into current_truth response + query paths
Phase 4: Wire into notify_turn (token tracking per message)
Phase 5: context_status tool + bloat detection
Phase 6: Session handoff logic
Phase 7: Adapter updates (context_status tool + token_limit from LLMProvider)
Phase 8: Tests — tests/test_working_memory.py
```

---

## Phase 1: Schema Additions

### File: `mcp_engine/schema.py`

**1.1 Add new columns to Session DDL** (additive to B17 changes — after B17's `content_embedding FLOAT[384]`):

```python
    "Session": """
        session_id          STRING,
        started_at          TIMESTAMP,
        last_active_at      TIMESTAMP,
        onboarded           BOOLEAN,
        purpose             STRING,
        routing_state       STRING,
        routing_confidence  DOUBLE,
        routing_method      STRING,
        content_embedding   FLOAT[384],
        token_estimate      INT64,
        token_limit         INT64,
        loaded_node_count   INT32,
        last_injection_at   TIMESTAMP,
        PRIMARY KEY (session_id)
    """,
```

New columns (B18-specific):
- `token_estimate INT64` — estimated total tokens in context window (cumulative)
- `token_limit INT64` — model's context window size (from LLMProvider node or adapter param)
- `loaded_node_count INT32` — number of graph nodes currently in working memory
- `last_injection_at TIMESTAMP` — when current_truth last returned results for this session

**1.2 Add LOADED relationship** (append to `REL_TABLES` list):

```python
    "CREATE REL TABLE IF NOT EXISTS LOADED (FROM Session TO Concept, FROM Session TO Decision, FROM Session TO Constraint, FROM Session TO Requirement, FROM Session TO ActionItem, FROM Session TO GlobalConstraint, FROM Session TO GlobalPreference, injected_at TIMESTAMP, token_estimate INT32, source STRING)",
```

Properties:
- `injected_at TIMESTAMP` — when this node was injected into the session's context
- `token_estimate INT32` — estimated tokens this node consumed in context
- `source STRING` — "current_truth" | "system_prompt" | "onboarding" | "handoff"

---

## Phase 2: Core Module

### File: `mcp_engine/working_memory.py` (CREATE NEW)

```python
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
```

#### 2.1 Function: `estimate_tokens()`

```python
def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text. Simple heuristic — no tokenizer dependency.
    ~3 chars per token for English (conservative to avoid undercount).
    Returns int.
    """
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN
```

#### 2.2 Function: `track_loaded()`

```python
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

    Logic:
    1. For each result, determine the node table + PK column from node_type
    2. MERGE a LOADED edge from Session to the node
       ON CREATE: set injected_at, token_estimate, source
       ON MATCH: update injected_at only (re-injection refreshes timestamp)
    3. Update Session.loaded_node_count = count of LOADED edges
    4. Update Session.last_injection_at = now
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
```

#### 2.3 Function: `get_loaded_node_ids()`

```python
def get_loaded_node_ids(db: KuzuClient, session_id: str) -> set[str]:
    """
    Return set of node_ids currently loaded in this session's context.
    Queries all LOADED edges from this Session.

    Uses per-table queries since LOADED is multi-FROM/TO.
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
```

#### 2.4 Function: `deduplicate_results()`

```python
def deduplicate_results(
    results: list[dict],
    loaded_ids: set[str],
) -> list[dict]:
    """
    Demote (not exclude) already-loaded nodes in retrieval results.
    Adds "already_in_context" flag and reduces relevance_score.

    Why demote not exclude: LLM might need a refresher on a loaded fact
    if the conversation has moved on. But fresh information should rank higher.

    Logic:
    1. For each result: if node_id in loaded_ids → multiply _rank by DEDUP_DEMOTION_FACTOR
    2. Add "already_in_context": True/False flag
    3. Re-sort by adjusted _rank
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
```

#### 2.5 Function: `update_token_estimate()`

```python
async def update_token_estimate(
    db: KuzuClient,
    session_id: str,
    new_tokens: int,
) -> None:
    """
    Increment the session's cumulative token estimate.
    Called after each notify_turn (message tokens) and current_truth (injection tokens).

    Logic:
    1. Read current token_estimate from Session
    2. Add new_tokens
    3. Write back
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
```

#### 2.6 Function: `get_session_token_state()`

```python
def get_session_token_state(db: KuzuClient, session_id: str) -> dict:
    """
    Returns current token usage vs. limit for a session.

    Returns:
        {
            "estimated_tokens": int,
            "token_limit": int,
            "utilization": float (0.0-1.0),
            "loaded_nodes": int,
        }
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
```

#### 2.7 Function: `check_context_health()`

```python
def check_context_health(db: KuzuClient, session_id: str) -> Optional[str]:
    """
    Returns warning message if context is getting bloated.
    Returns None if context is healthy.
    """
    state = get_session_token_state(db, session_id)
    if state["utilization"] > BLOAT_WARNING_THRESHOLD:
        return (
            f"Context window is {state['utilization']:.0%} full "
            f"({state['estimated_tokens']}/{state['token_limit']} tokens). "
            f"Consider starting a fresh conversation."
        )
    return None
```

#### 2.8 Function: `get_handoff_context()`

```python
def get_handoff_context(
    db: KuzuClient,
    quest_id: str,
    new_session_id: str,
    limit: int = 5,
) -> list[dict]:
    """
    When a new session starts for the same quest, return the most important
    nodes from the prior session's working memory.

    Steps:
    1. Find most recent prior session on this quest (not the new session)
    2. Get what was loaded in that session, ranked by pathway_strength
    3. Return top N as handoff candidates

    Returns list of {node_id, node_type, text_raw, pathway_strength}
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
```

#### 2.9 Helper: `_count_loaded()`

```python
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
```

---

## Phase 3: Wire Into current_truth

### File: `mcp_engine/tools.py`

**3.1 Update `current_truth()` — add deduplication before returning results.**

After the existing ranking block (after `all_results.sort(...)` at ~line 217), insert:

```python
    # B18: Smart deduplication — demote already-loaded nodes
    if session_id != "unknown":
        from mcp_engine.working_memory import get_loaded_node_ids, deduplicate_results
        try:
            loaded_ids = get_loaded_node_ids(db, session_id)
            if loaded_ids:
                all_results = deduplicate_results(all_results, loaded_ids)
        except Exception:
            _logger.debug("current_truth dedup failed for session %s", session_id)
```

**3.2 After building the final response (after `return {"results": ...}`), add load tracking.**

Replace the return statement at ~line 226:

```python
    final_results = all_results[:limit]

    # B18: Track what was loaded into this session
    if session_id != "unknown" and final_results:
        from mcp_engine.working_memory import track_loaded, update_token_estimate, estimate_tokens, check_context_health
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
```

---

## Phase 4: Wire Into notify_turn

### File: `mcp_engine/tools.py`

**4.1 After the Message creation block (~line 116), add token tracking:**

```python
    # B18: Update token estimate for this message
    if session_id != "unknown":
        from mcp_engine.working_memory import update_token_estimate, estimate_tokens
        try:
            msg_tokens = estimate_tokens(content)
            await update_token_estimate(db, session_id, msg_tokens)
        except Exception:
            pass
```

**4.2 Accept `token_limit` from adapter and store on Session.**

After the session creation/binding (after `get_or_create_session` or hippocampus routing), add:

```python
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
```

---

## Phase 5: context_status Tool

### File: `mcp_engine/tools.py`

**5.1 Add `context_status` handler** (before TOOL_HANDLERS dict):

```python
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
```

**5.2 Add to TOOL_HANDLERS:**

```python
TOOL_HANDLERS = {
    ...
    "context_status":   context_status,
}
```

---

## Phase 6: Adapter Updates

### All 4 adapters: `adapters/{claude_code,claude_desktop,codex,gemini_cli}/adapter.py`

**6.1 Add `context_status` to TOOLS list:**

```python
    {
        "name": "context_status",
        "description": (
            "Check the health of the current context window — token usage, "
            "loaded knowledge, and handoff suggestions. Use when context feels "
            "bloated or when starting a new session on an existing project."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    },
```

**6.2 Add `context_status` to tool dispatch** (in the catch-all block):

```python
        if tool_name in ("ingest_document", "explore_graph", "complete_quest", "set_quest", "context_status"):
```

**6.3 Add `token_limit` to `_inject_context()` (from B17):**

Update the `_inject_context()` function added in B17 to also send token_limit:

```python
def _inject_context(params: dict) -> dict:
    """Add available context signals to any tool params dict."""
    ctx = {**params}
    if _REPO_ROOT:
        ctx["repo_root"] = _REPO_ROOT
    if _GIT_BRANCH:
        ctx["git_branch"] = _GIT_BRANCH
    import os
    ctx.setdefault("workspace_path", os.getcwd())
    # B18: Send token_limit so Brain can track context window size
    ctx.setdefault("token_limit", _TOKEN_LIMIT)
    return ctx
```

Add a module-level constant after `_REPO_ROOT, _GIT_BRANCH = detect_git_context()`:

```python
# Token limits per known model family (conservative estimates)
# Adapters can override via LLMProvider node in the graph
_TOKEN_LIMIT = 128000  # default (Claude Code / GPT-4 class)
```

---

## Phase 7: Tests

### File: `tests/test_working_memory.py` (CREATE NEW)

```python
"""
Tests for B18 Context Window Awareness (Working Memory).

Run with: python3 -m pytest tests/test_working_memory.py -v
"""

import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
```

**7.1 Token estimation tests:**

```python
class TestTokenEstimation:

    def test_estimate_tokens_basic(self):
        from mcp_engine.working_memory import estimate_tokens
        assert estimate_tokens("hello world") > 0

    def test_estimate_tokens_empty(self):
        from mcp_engine.working_memory import estimate_tokens
        assert estimate_tokens("") == 0

    def test_estimate_tokens_scales_with_length(self):
        from mcp_engine.working_memory import estimate_tokens
        short = estimate_tokens("hello")
        long = estimate_tokens("hello " * 100)
        assert long > short * 10
```

**7.2 Load tracking tests:**

```python
class TestLoadTracking:

    @pytest.mark.asyncio
    async def test_track_loaded_creates_edges(self):
        """track_loaded creates LOADED edges for each result."""
        from mcp_engine.working_memory import track_loaded

        writes = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        results = [
            {"node_id": "d1", "node_type": "Decision", "text_raw": "Use PostgreSQL"},
            {"node_id": "c1", "node_type": "Constraint", "text_raw": "No external APIs"},
        ]

        count = await track_loaded(MockDB(), "sess-1", results)

        assert count == 2
        combined = " ".join(w["query"] for w in writes)
        assert "LOADED" in combined
        assert "loaded_node_count" in combined

    @pytest.mark.asyncio
    async def test_track_loaded_skips_unknown_types(self):
        """Skips nodes with unrecognized node_type."""
        from mcp_engine.working_memory import track_loaded

        writes = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append(query)

        results = [
            {"node_id": "x1", "node_type": "UnknownType", "text_raw": "data"},
        ]

        count = await track_loaded(MockDB(), "sess-1", results)
        assert count == 0
```

**7.3 Deduplication tests:**

```python
class TestDeduplication:

    def test_demotes_loaded_nodes(self):
        """Already-loaded nodes get demoted in ranking."""
        from mcp_engine.working_memory import deduplicate_results

        results = [
            {"node_id": "d1", "_rank": 1.0, "text_raw": "old"},
            {"node_id": "d2", "_rank": 0.8, "text_raw": "new"},
        ]
        loaded_ids = {"d1"}

        deduped = deduplicate_results(results, loaded_ids)

        assert deduped[0]["node_id"] == "d2"  # new node now ranks first
        assert deduped[1]["already_in_context"] is True
        assert deduped[0]["already_in_context"] is False

    def test_empty_loaded_no_change(self):
        """No loaded nodes → no demotion."""
        from mcp_engine.working_memory import deduplicate_results

        results = [
            {"node_id": "d1", "_rank": 1.0},
            {"node_id": "d2", "_rank": 0.8},
        ]

        deduped = deduplicate_results(results, set())

        assert deduped[0]["node_id"] == "d1"
        assert all(not r["already_in_context"] for r in deduped)

    def test_same_query_twice_demotes_second_time(self):
        """Second call with same results ranks fresh content higher."""
        from mcp_engine.working_memory import deduplicate_results

        results = [
            {"node_id": "d1", "_rank": 1.0, "text_raw": "fact A"},
            {"node_id": "d2", "_rank": 0.9, "text_raw": "fact B"},
            {"node_id": "d3", "_rank": 0.5, "text_raw": "fact C"},
        ]

        # First call: nothing loaded
        deduped1 = deduplicate_results(results, set())
        assert deduped1[0]["node_id"] == "d1"

        # Second call: d1 and d2 are now loaded
        for r in results:
            r["_rank"] = {"d1": 1.0, "d2": 0.9, "d3": 0.5}[r["node_id"]]
        deduped2 = deduplicate_results(results, {"d1", "d2"})
        assert deduped2[0]["node_id"] == "d3"  # fresh content ranks first
```

**7.4 Context health tests:**

```python
class TestContextHealth:

    def test_bloat_warning_above_threshold(self):
        """Returns warning when utilization exceeds threshold."""
        from mcp_engine.working_memory import check_context_health

        class MockResult:
            def has_next(self): return True
            def get_next(self): return [100000, 128000, 12]  # ~78% utilization

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        warning = check_context_health(MockDB(), "sess-1")
        assert warning is not None
        assert "78%" in warning or "full" in warning

    def test_no_warning_below_threshold(self):
        """Returns None when utilization is healthy."""
        from mcp_engine.working_memory import check_context_health

        class MockResult:
            def has_next(self): return True
            def get_next(self): return [30000, 128000, 5]  # ~23% utilization

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        warning = check_context_health(MockDB(), "sess-1")
        assert warning is None
```

**7.5 Session handoff tests:**

```python
class TestSessionHandoff:

    def test_handoff_returns_prior_session_nodes(self):
        """Returns loaded nodes from most recent prior session on same quest."""
        from mcp_engine.working_memory import get_handoff_context

        query_count = [0]

        class MockResult:
            def __init__(self, rows=None):
                self._rows = rows or []; self._idx = 0
            def has_next(self): return self._idx < len(self._rows)
            def get_next(self):
                row = self._rows[self._idx]; self._idx += 1; return row

        class MockDB:
            def execute(self, query, params=None):
                query_count[0] += 1
                if "WORKING_ON" in query and "session_id" in query:
                    # Prior session found
                    return MockResult([["prev-sess"]])
                if "LOADED" in query and "Decision" in query:
                    return MockResult([["d1", "Use PostgreSQL", 0.95]])
                return MockResult()

        handoff = get_handoff_context(MockDB(), "quest-1", "new-sess")
        assert len(handoff) >= 1
        assert handoff[0]["node_id"] == "d1"
        assert handoff[0]["pathway_strength"] == 0.95

    def test_handoff_returns_empty_for_first_session(self):
        """Returns empty list when no prior session exists."""
        from mcp_engine.working_memory import get_handoff_context

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        handoff = get_handoff_context(MockDB(), "quest-1", "first-sess")
        assert handoff == []
```

**7.6 Token state test:**

```python
class TestTokenState:

    def test_get_session_token_state_returns_defaults(self):
        """Returns sensible defaults when session has no token data."""
        from mcp_engine.working_memory import get_session_token_state

        class MockResult:
            def has_next(self): return True
            def get_next(self): return [None, None, None]

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        state = get_session_token_state(MockDB(), "sess-1")
        assert state["estimated_tokens"] == 0
        assert state["token_limit"] == 128000
        assert state["utilization"] == 0.0
        assert state["loaded_nodes"] == 0
```

**7.7 context_status tool test:**

```python
class TestContextStatusTool:

    @pytest.mark.asyncio
    async def test_context_status_returns_structure(self):
        from mcp_engine.tools import context_status

        class MockResult:
            def __init__(self, rows=None):
                self._rows = rows or []; self._idx = 0
            def has_next(self): return self._idx < len(self._rows)
            def get_next(self):
                row = self._rows[self._idx]; self._idx += 1; return row

        class MockDB:
            def execute(self, query, params=None):
                if "token_estimate" in query:
                    return MockResult([[45000, 128000, 12]])
                return MockResult()

        result = await context_status(
            {"session_id": "sess-1"}, MockDB(), {}
        )

        assert "token_estimate" in result
        assert "token_limit" in result
        assert "utilization" in result
        assert "loaded_nodes" in result
        assert "bloat_warning" in result
        assert "handoff_available" in result

    @pytest.mark.asyncio
    async def test_context_status_requires_session_id(self):
        from mcp_engine.tools import context_status

        result = await context_status({}, None, {})
        assert "error" in result
```

---

## Summary of All File Changes

| File | Action | Description |
|------|--------|-------------|
| `mcp_engine/schema.py` | **MODIFY** | Add 4 columns to Session (additive to B17), add LOADED rel table |
| `mcp_engine/working_memory.py` | **CREATE** | New module: ~300 lines, 9 functions |
| `mcp_engine/tools.py` | **MODIFY** | Wire dedup into current_truth, token tracking into notify_turn, add context_status |
| `adapters/claude_code/adapter.py` | **MODIFY** | Add context_status tool, token_limit to _inject_context |
| `adapters/claude_desktop/adapter.py` | **MODIFY** | Same changes as claude_code |
| `adapters/codex/adapter.py` | **MODIFY** | Same changes as claude_code |
| `adapters/gemini_cli/adapter.py` | **MODIFY** | Same changes as claude_code |
| `tests/test_working_memory.py` | **CREATE** | New test file: ~250 lines, 7 test classes |

---

## Critical Files to Read Before Implementing

- `mcp_engine/tools.py` — current current_truth + notify_turn (B17 changes applied first)
- `mcp_engine/schema.py` — Session DDL (B17 changes applied first)
- `mcp_engine/graph/kuzu_client.py` — execute, execute_write interface
- `adapters/claude_code/adapter.py` — TOOLS list, _inject_context (B17 changes applied first)
- `tests/test_quest.py` — MockDB patterns for test consistency
- `mcp_engine/hippocampus.py` — B17 module (created in B17, needed for integration)
