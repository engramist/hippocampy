# B-17: Semantic Quest Routing ("The Hippocampus")

## Overview

Replace git-only MainQuest identification with a semantic routing mechanism. Currently `compute_quest_id(repo_root)` produces a deterministic hash — works for CLI-in-a-repo but breaks for desktop apps (Claude Desktop, ChatGPT) and non-dev users without git. The fix: `mcp_engine/hippocampus.py` — a two-phase (System 1 / System 2) router that determines which MainQuest a session belongs to based on **semantic content**, where git context is just one high-confidence signal.

Architecture doc: `B17-B18-architecture.md`

---

## Implementation Order

```
Phase 1: Schema migration (new properties + REROUTED_FROM relationship)
Phase 2: hippocampus.py — core routing module
Phase 3: quest.py refactor — legacy compat + UUID path + active quest queries
Phase 4: tools.py — wire notify_turn + current_truth through hippocampus
Phase 5: tools.py — add set_quest tool
Phase 6: All 4 adapters — _inject_git_context → _inject_context + set_quest tool
Phase 7: Tests — tests/test_hippocampus.py + update tests/test_quest.py
```

---

## Phase 1: Schema Migration

### File: `mcp_engine/schema.py`

**1.1 Add new columns to MainQuest DDL** (in `NODE_TABLES["MainQuest"]`, after `last_active_at TIMESTAMP`):

```python
    "MainQuest": """
        quest_id        STRING,
        name            STRING,
        status          STRING,
        completed_at    TIMESTAMP,
        purpose         STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        created_at      TIMESTAMP,
        last_active_at  TIMESTAMP,
        git_repo_root       STRING,
        purpose_embedding   FLOAT[384],
        routing_method      STRING,
        PRIMARY KEY (quest_id)
    """,
```

New columns:
- `git_repo_root STRING` — nullable, populated for git-anchored quests. Allows reverse lookup "which quest is this repo?"
- `purpose_embedding FLOAT[384]` — dedicated routing vector. Updated as quest purpose evolves. **NOT HNSW-indexed** (Python-side search, <50 active quests)
- `routing_method STRING` — "git" | "semantic_s1" | "semantic_s2" | "explicit"

**1.2 Add new columns to Session DDL** (in `NODE_TABLES["Session"]`, after `purpose STRING`):

```python
    "Session": """
        session_id     STRING,
        started_at     TIMESTAMP,
        last_active_at TIMESTAMP,
        onboarded      BOOLEAN,
        purpose        STRING,
        routing_state       STRING,
        routing_confidence  DOUBLE,
        routing_method      STRING,
        content_embedding   FLOAT[384],
        PRIMARY KEY (session_id)
    """,
```

New columns:
- `routing_state STRING` — "tentative" | "consolidated" | "locked"
- `routing_confidence DOUBLE` — 0.0–1.0, strength of quest binding
- `routing_method STRING` — how this session was routed ("git" | "semantic_s1" | "semantic_s2" | "explicit")
- `content_embedding FLOAT[384]` — running mean of message embeddings (for re-routing)

**1.3 Add REROUTED_FROM relationship** (append to `REL_TABLES` list):

```python
    "CREATE REL TABLE IF NOT EXISTS REROUTED_FROM (FROM Session TO MainQuest, rerouted_at TIMESTAMP, reason STRING)",
```

**1.4 Do NOT create HNSW index on purpose_embedding.** Active MainQuests will typically number <50. Python-side cosine similarity is faster and avoids the Kùzu 0.11.3 limitation where HNSW-indexed columns cannot be updated in-place.

---

## Phase 2: Core Routing Module

### File: `mcp_engine/hippocampus.py` (CREATE NEW)

```python
"""
mcp_engine/hippocampus.py — Semantic Quest Routing ("The Hippocampus")

Two-phase routing: System 1 (fast, no LLM) and System 2 (LLM disambiguation).
Git context is one high-confidence signal, not a separate code path.

Progressive consolidation: tentative → consolidated → locked.
Prediction error triggers reconsolidation (re-routing with audit trail).
"""

from __future__ import annotations
import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from mcp_engine.graph import embeddings as emb

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing thresholds (match CLAUDE.md architecture)
# ---------------------------------------------------------------------------

S1_AUTO_BIND_THRESHOLD = 0.85     # System 1 accepts immediately
S1_ESCALATION_THRESHOLD = 0.60    # Below this = new quest; between = escalate to S2
S2_CONFIDENCE_LOW_THRESHOLD = 0.85  # S2 below this → routing_confidence_low = true
CONSOLIDATION_THRESHOLD = 0.85    # Promote tentative → consolidated
DISCONFIRMATION_THRESHOLD = 0.30  # Prediction error trigger
DISCONFIRMATION_COUNT = 3         # Consecutive low-similarity messages before reroute
PURPOSE_DRIFT_THRESHOLD = 0.40    # Re-embed purpose when divergence exceeds this

GIT_WEIGHT = 0.95
WORKSPACE_WEIGHT = 0.70
ENTITY_OVERLAP_BOOST = 0.15
MESSAGE_CONFIRM_BOOST = 0.10      # Per confirming message (up to 5)
ARTIFACT_CONFIRM_BOOST = 0.15
ENTITY_CONFIRM_BOOST = 0.20
GIT_CONFIRM_BOOST = 0.30


@dataclass
class RoutingResult:
    quest_id: str
    confidence: float
    method: str          # "git" | "semantic_s1" | "semantic_s2" | "explicit"
    is_new_quest: bool
    routing_state: str   # "tentative" | "consolidated" | "locked"
```

#### 2.1 Function: `route_session()`

```python
async def route_session(
    db: KuzuClient,
    session_id: str,
    content: str,
    embedding_model: str,
    git_repo_root: str = "",
    workspace_path: str = "",
    llm_client=None,
    config: dict = {},
) -> RoutingResult:
    """
    Main entry point. Called on first notify_turn for a new session.
    Returns RoutingResult with quest_id, confidence, method, is_new_quest.

    Logic:
    1. Check if session already has a WORKING_ON edge → return existing binding
    2. Try System 1 git match → if hit, bind with confidence 0.95, state "locked"
    3. Embed content → System 1 semantic match against active quest purpose_embeddings
    4. If workspace_path matches existing Workspace node → boost matching quest +0.15
    5. Threshold check:
       - Best > S1_AUTO_BIND_THRESHOLD → auto-bind, state "tentative" (or "locked" if git)
       - S1_ESCALATION_THRESHOLD–S1_AUTO_BIND_THRESHOLD → escalate to System 2
       - < S1_ESCALATION_THRESHOLD → create new quest
    6. System 2 (if needed): LLM disambiguates top 3 candidates
    7. Create WORKING_ON edge + set Session routing fields
    8. Return result
    """
    # Step 1: check existing binding
    existing = _check_existing_binding(db, session_id)
    if existing:
        return existing

    # Step 2: System 1 git match
    if git_repo_root:
        git_result = _system1_git_match(db, git_repo_root)
        if git_result:
            await _bind_session(db, session_id, git_result, 0.95, "git", "locked")
            # Populate git_repo_root on the quest if not already set
            await _ensure_git_repo_root(db, git_result, git_repo_root)
            return RoutingResult(git_result, 0.95, "git", False, "locked")

    # Step 3: Embed content + semantic search
    content_embedding = emb.embed(content, model_name=embedding_model)
    active_quests = get_active_quests_with_embeddings(db)

    if not active_quests:
        # Cold start — no quests exist, create new one
        quest_id = await create_new_quest(db, content, content_embedding,
                                           embedding_model, git_repo_root)
        await _bind_session(db, session_id, quest_id, 0.95, "semantic_s1", "tentative",
                            content_embedding=content_embedding)
        return RoutingResult(quest_id, 0.95, "semantic_s1", True, "tentative")

    # Step 3b: Compute similarities
    candidates = _system1_semantic_match(content_embedding, active_quests)

    # Step 4: Workspace boost
    if workspace_path:
        candidates = _apply_workspace_boost(db, candidates, workspace_path)

    if not candidates:
        quest_id = await create_new_quest(db, content, content_embedding,
                                           embedding_model, git_repo_root)
        await _bind_session(db, session_id, quest_id, 0.95, "semantic_s1", "tentative",
                            content_embedding=content_embedding)
        return RoutingResult(quest_id, 0.95, "semantic_s1", True, "tentative")

    best_id, best_score = candidates[0]

    # Step 5: Threshold check
    if best_score >= S1_AUTO_BIND_THRESHOLD:
        await _bind_session(db, session_id, best_id, best_score, "semantic_s1",
                            "tentative", content_embedding=content_embedding)
        return RoutingResult(best_id, best_score, "semantic_s1", False, "tentative")

    if best_score >= S1_ESCALATION_THRESHOLD:
        # Step 6: System 2 disambiguation
        if llm_client:
            s2_id, s2_conf = await _system2_disambiguate(
                llm_client, candidates[:3], content, db
            )
            if s2_id:
                state = "tentative" if s2_conf < S2_CONFIDENCE_LOW_THRESHOLD else "tentative"
                await _bind_session(db, session_id, s2_id, s2_conf, "semantic_s2",
                                    state, content_embedding=content_embedding)
                return RoutingResult(s2_id, s2_conf, "semantic_s2", False, state)
            # LLM said "new quest"
            quest_id = await create_new_quest(db, content, content_embedding,
                                               embedding_model, git_repo_root)
            await _bind_session(db, session_id, quest_id, 0.90, "semantic_s2", "tentative",
                                content_embedding=content_embedding)
            return RoutingResult(quest_id, 0.90, "semantic_s2", True, "tentative")
        else:
            # No LLM available — bind tentatively to best match
            await _bind_session(db, session_id, best_id, best_score, "semantic_s1",
                                "tentative", content_embedding=content_embedding)
            return RoutingResult(best_id, best_score, "semantic_s1", False, "tentative")

    # Below escalation threshold — create new quest
    quest_id = await create_new_quest(db, content, content_embedding,
                                       embedding_model, git_repo_root)
    await _bind_session(db, session_id, quest_id, 0.95, "semantic_s1", "tentative",
                        content_embedding=content_embedding)
    return RoutingResult(quest_id, 0.95, "semantic_s1", True, "tentative")
```

#### 2.2 Function: `_check_existing_binding()`

```python
def _check_existing_binding(db: KuzuClient, session_id: str) -> Optional[RoutingResult]:
    """
    Check if session already has a WORKING_ON edge.
    Returns RoutingResult if bound, None otherwise.

    Query:
        MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest)
        RETURN q.quest_id, s.routing_confidence, s.routing_method, s.routing_state
    """
    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest) "
            "RETURN q.quest_id, s.routing_confidence, s.routing_method, s.routing_state",
            {"sid": session_id}
        )
        if r.has_next():
            row = r.get_next()
            return RoutingResult(
                quest_id=row[0] or "",
                confidence=float(row[1] or 0.0),
                method=row[2] or "unknown",
                is_new_quest=False,
                routing_state=row[3] or "tentative",
            )
    except Exception:
        _logger.exception("_check_existing_binding failed for %s", session_id)
    return None
```

#### 2.3 Function: `_system1_git_match()`

```python
def _system1_git_match(db: KuzuClient, git_repo_root: str) -> Optional[str]:
    """
    Check if a MainQuest exists with matching git_repo_root.
    Also checks legacy hash match for backward compatibility.
    Returns quest_id or None.

    Two checks:
    1. Direct git_repo_root property match:
       MATCH (q:MainQuest {git_repo_root: $root}) WHERE q.status = 'active'
       RETURN q.quest_id
    2. Legacy hash match (compute_quest_id from repo_root):
       MATCH (q:MainQuest {quest_id: $hash_id}) WHERE q.status = 'active'
       RETURN q.quest_id
    """
    # Check 1: git_repo_root property
    try:
        r = db.execute(
            "MATCH (q:MainQuest) "
            "WHERE q.git_repo_root = $root AND q.status = 'active' "
            "RETURN q.quest_id LIMIT 1",
            {"root": git_repo_root}
        )
        if r.has_next():
            return r.get_next()[0]
    except Exception:
        pass

    # Check 2: legacy hash
    from mcp_engine.quest import compute_quest_id
    legacy_id = compute_quest_id(git_repo_root, "")
    try:
        r = db.execute(
            "MATCH (q:MainQuest {quest_id: $qid}) "
            "WHERE q.status = 'active' "
            "RETURN q.quest_id LIMIT 1",
            {"qid": legacy_id}
        )
        if r.has_next():
            return r.get_next()[0]
    except Exception:
        pass

    return None
```

#### 2.4 Function: `get_active_quests_with_embeddings()`

```python
def get_active_quests_with_embeddings(db: KuzuClient) -> list[dict]:
    """
    Return all active MainQuests with their purpose_embedding.
    Returns list of {"quest_id": str, "purpose_embedding": list[float], "name": str, "purpose": str}

    Query:
        MATCH (q:MainQuest)
        WHERE q.status = 'active' AND q.archived = false
        RETURN q.quest_id, q.purpose_embedding, q.name, q.purpose, q.embedding
        LIMIT 100

    Note: falls back to q.embedding if purpose_embedding is null (pre-migration quests).
    """
    quests = []
    try:
        r = db.execute(
            "MATCH (q:MainQuest) "
            "WHERE q.status = 'active' AND q.archived = false "
            "RETURN q.quest_id, q.purpose_embedding, q.name, q.purpose, q.embedding "
            "LIMIT 100"
        )
        while r.has_next():
            row = r.get_next()
            purpose_emb = row[1] or row[4]  # fallback to embedding if purpose_embedding null
            if purpose_emb:
                quests.append({
                    "quest_id": row[0],
                    "purpose_embedding": list(purpose_emb),
                    "name": row[2] or "",
                    "purpose": row[3] or "",
                })
    except Exception:
        _logger.exception("get_active_quests_with_embeddings failed")
    return quests
```

#### 2.5 Function: `_system1_semantic_match()`

```python
def _system1_semantic_match(
    content_embedding: list[float],
    active_quests: list[dict],
) -> list[tuple[str, float]]:
    """
    Cosine similarity between content_embedding and each quest's purpose_embedding.
    Returns sorted list of (quest_id, similarity) descending.

    Uses Python-side dot product (vectors are L2-normalized by embeddings.py).
    No HNSW index needed — small cardinality.
    """
    results = []
    for q in active_quests:
        pe = q["purpose_embedding"]
        if not pe or len(pe) != len(content_embedding):
            continue
        sim = sum(a * b for a, b in zip(content_embedding, pe))
        results.append((q["quest_id"], sim))
    results.sort(key=lambda x: x[1], reverse=True)
    return results
```

#### 2.6 Function: `_apply_workspace_boost()`

```python
def _apply_workspace_boost(
    db: KuzuClient,
    candidates: list[tuple[str, float]],
    workspace_path: str,
) -> list[tuple[str, float]]:
    """
    If workspace_path matches an existing Workspace node linked to a quest,
    boost that quest's score by ENTITY_OVERLAP_BOOST (0.15).

    Query:
        MATCH (q:MainQuest)-[:ANCHORED_TO]->(w:Workspace {path: $path})
        WHERE q.status = 'active'
        RETURN q.quest_id
    """
    boosted_ids = set()
    try:
        r = db.execute(
            "MATCH (q:MainQuest)-[:ANCHORED_TO]->(w:Workspace {path: $path}) "
            "WHERE q.status = 'active' "
            "RETURN q.quest_id",
            {"path": workspace_path}
        )
        while r.has_next():
            boosted_ids.add(r.get_next()[0])
    except Exception:
        pass

    if not boosted_ids:
        return candidates

    return sorted(
        [(qid, score + ENTITY_OVERLAP_BOOST if qid in boosted_ids else score)
         for qid, score in candidates],
        key=lambda x: x[1], reverse=True,
    )
```

#### 2.7 Function: `_system2_disambiguate()`

```python
async def _system2_disambiguate(
    llm_client,
    candidates: list[tuple[str, float]],
    content: str,
    db: KuzuClient,
) -> tuple[Optional[str], float]:
    """
    LLM picks the right quest or says "new".
    Returns (quest_id, confidence) or (None, 0.0) for "new quest".

    Prompt includes:
    - Message content (first 500 chars)
    - Each candidate's name, purpose, and top 3 recent artifact text_raw values

    Forced output: {"quest_id": "..." | "new", "confidence": 0.0-1.0}

    Uses achat() if available, else chat().
    """
    # Build candidate context
    candidate_descs = []
    for i, (qid, score) in enumerate(candidates):
        desc = f"Candidate {i+1} (score={score:.2f}): "
        try:
            r = db.execute(
                "MATCH (q:MainQuest {quest_id: $qid}) RETURN q.name, q.purpose",
                {"qid": qid}
            )
            if r.has_next():
                row = r.get_next()
                desc += f"Name: {row[0]}, Purpose: {row[1]}"
        except Exception:
            desc += f"quest_id={qid}"
        candidate_descs.append(desc)

    prompt = (
        "You are routing a new conversation to the correct project context.\n\n"
        f"New message: {content[:500]}\n\n"
        "Active projects:\n" + "\n".join(candidate_descs) + "\n\n"
        'Which project does this message belong to? '
        'Return JSON only: {"quest_id": "<id>" or "new", "confidence": 0.0-1.0}\n'
        'If none match, return {"quest_id": "new", "confidence": 0.95}'
    )

    try:
        import json
        if hasattr(llm_client, 'achat'):
            response = await llm_client.achat([{"role": "user", "content": prompt}])
        else:
            import asyncio
            response = await asyncio.to_thread(llm_client.chat, prompt)

        data = json.loads(response.strip())
        qid = data.get("quest_id", "new")
        conf = float(data.get("confidence", 0.0))

        if qid == "new":
            return (None, 0.0)

        # Validate returned quest_id is in candidates
        valid_ids = {c[0] for c in candidates}
        if qid in valid_ids:
            return (qid, conf)
        return (None, 0.0)  # LLM returned invalid ID → treat as "new"

    except Exception:
        _logger.exception("_system2_disambiguate failed")
        return (None, 0.0)
```

#### 2.8 Function: `create_new_quest()`

```python
async def create_new_quest(
    db: KuzuClient,
    content: str,
    content_embedding: list[float],
    embedding_model: str,
    git_repo_root: str = "",
) -> str:
    """
    Create a new MainQuest with UUID.
    Sets purpose from first message content (first 200 chars).
    Sets purpose_embedding from content_embedding.
    Returns quest_id.
    """
    from datetime import datetime, timezone

    quest_id = str(uuid.uuid4()).replace("-", "")[:32]
    name = content[:80].strip() or "New Quest"
    purpose = content[:200].strip()
    now = datetime.now(timezone.utc).isoformat()
    routing_method = "git" if git_repo_root else "semantic_s1"

    await db.execute_write(
        """
        CREATE (q:MainQuest {
            quest_id:           $quest_id,
            name:               $name,
            status:             'active',
            completed_at:       null,
            purpose:            $purpose,
            text_raw:           $name,
            embedding:          $embedding,
            embedding_model:    $embedding_model,
            embedding_dim:      $embedding_dim,
            confidence:         1.0,
            confidence_low:     false,
            pathway_strength:   1.0,
            archived:           false,
            created_at:         timestamp($now),
            last_active_at:     timestamp($now),
            git_repo_root:      $git_repo_root,
            purpose_embedding:  $purpose_embedding,
            routing_method:     $routing_method
        })
        """,
        {
            "quest_id":          quest_id,
            "name":              name,
            "purpose":           purpose,
            "embedding":         content_embedding,
            "embedding_model":   embedding_model,
            "embedding_dim":     len(content_embedding),
            "now":               now,
            "git_repo_root":     git_repo_root or "",
            "purpose_embedding": content_embedding,
            "routing_method":    routing_method,
        }
    )
    return quest_id
```

#### 2.9 Function: `_bind_session()`

```python
async def _bind_session(
    db: KuzuClient,
    session_id: str,
    quest_id: str,
    confidence: float,
    method: str,
    state: str,
    content_embedding: list[float] = None,
) -> None:
    """
    Create WORKING_ON edge + set Session routing fields.
    MERGE session first (may not exist yet on first notify_turn).
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    params = {
        "sid": session_id,
        "now": now,
        "routing_state": state,
        "routing_confidence": confidence,
        "routing_method": method,
    }

    set_clause = (
        "s.routing_state = $routing_state, "
        "s.routing_confidence = $routing_confidence, "
        "s.routing_method = $routing_method"
    )

    if content_embedding:
        params["content_embedding"] = content_embedding
        set_clause += ", s.content_embedding = $content_embedding"

    await db.execute_write(
        f"""
        MERGE (s:Session {{session_id: $sid}})
        ON CREATE SET s.started_at     = timestamp($now),
                      s.last_active_at = timestamp($now),
                      s.onboarded      = false,
                      s.purpose        = '',
                      {set_clause}
        ON MATCH SET  s.last_active_at = timestamp($now),
                      {set_clause}
        """,
        params,
    )

    await db.execute_write(
        "MATCH (s:Session {session_id: $sid}), (q:MainQuest {quest_id: $qid}) "
        "MERGE (s)-[:WORKING_ON]->(q)",
        {"sid": session_id, "qid": quest_id},
    )
```

#### 2.10 Function: `_ensure_git_repo_root()`

```python
async def _ensure_git_repo_root(db: KuzuClient, quest_id: str, git_repo_root: str) -> None:
    """
    Populate git_repo_root on existing quest if not already set.
    Migration step: first post-upgrade CLI connection populates this.
    """
    try:
        await db.execute_write(
            "MATCH (q:MainQuest {quest_id: $qid}) "
            "WHERE q.git_repo_root IS NULL OR q.git_repo_root = '' "
            "SET q.git_repo_root = $root",
            {"qid": quest_id, "root": git_repo_root},
        )
    except Exception:
        pass
```

#### 2.11 Function: `update_routing_strength()`

```python
async def update_routing_strength(
    db: KuzuClient,
    session_id: str,
    message_embedding: list[float],
    quest_purpose_embedding: list[float],
) -> float:
    """
    Called per message after the first. Updates routing_confidence on Session.
    Promotes tentative → consolidated when threshold reached.
    Returns new routing_confidence.

    Logic:
    1. Compute similarity = dot(message_embedding, quest_purpose_embedding)
    2. If similarity > 0.70: boost routing_confidence by MESSAGE_CONFIRM_BOOST (capped at 1.0)
    3. If routing_confidence >= CONSOLIDATION_THRESHOLD and routing_state == "tentative":
       promote to "consolidated"
    4. Track consecutive low-similarity messages for prediction error detection
    """
    sim = sum(a * b for a, b in zip(message_embedding, quest_purpose_embedding))

    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid}) "
            "RETURN s.routing_confidence, s.routing_state",
            {"sid": session_id},
        )
        if not r.has_next():
            return 0.0
        row = r.get_next()
        current_conf = float(row[0] or 0.0)
        current_state = row[1] or "tentative"
    except Exception:
        return 0.0

    # Boost or maintain
    new_conf = current_conf
    if sim > 0.70:
        new_conf = min(1.0, current_conf + MESSAGE_CONFIRM_BOOST)

    # Promote tentative → consolidated
    new_state = current_state
    if new_conf >= CONSOLIDATION_THRESHOLD and current_state == "tentative":
        new_state = "consolidated"

    try:
        await db.execute_write(
            "MATCH (s:Session {session_id: $sid}) "
            "SET s.routing_confidence = $conf, s.routing_state = $state",
            {"sid": session_id, "conf": new_conf, "state": new_state},
        )
    except Exception:
        pass

    return new_conf
```

#### 2.12 Function: `reconsolidate()`

```python
async def reconsolidate(
    db: KuzuClient,
    session_id: str,
    new_content: str,
    embedding_model: str,
    llm_client=None,
    config: dict = {},
) -> RoutingResult:
    """
    Re-route after prediction error.
    Called when user explicitly says "this is about X" or "new project",
    or when disconfirming signal threshold reached.

    Steps:
    1. Get current quest binding
    2. Delete WORKING_ON edge
    3. Create REROUTED_FROM edge (audit trail)
    4. Re-run route_session with full accumulated context
    5. Return new RoutingResult
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # Get current binding
    old_quest_id = ""
    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest) "
            "RETURN q.quest_id",
            {"sid": session_id},
        )
        if r.has_next():
            old_quest_id = r.get_next()[0]
    except Exception:
        pass

    if old_quest_id:
        # Remove WORKING_ON edge
        try:
            await db.execute_write(
                "MATCH (s:Session {session_id: $sid})-[w:WORKING_ON]->(q:MainQuest {quest_id: $qid}) "
                "DELETE w",
                {"sid": session_id, "qid": old_quest_id},
            )
        except Exception:
            pass

        # Create REROUTED_FROM audit edge
        try:
            await db.execute_write(
                "MATCH (s:Session {session_id: $sid}), (q:MainQuest {quest_id: $qid}) "
                "CREATE (s)-[:REROUTED_FROM {rerouted_at: timestamp($now), reason: $reason}]->(q)",
                {"sid": session_id, "qid": old_quest_id, "now": now,
                 "reason": "prediction_error"},
            )
        except Exception:
            pass

    # Re-run routing
    return await route_session(
        db, session_id, new_content, embedding_model,
        llm_client=llm_client, config=config,
    )
```

---

## Phase 3: Quest Module Refactor

### File: `mcp_engine/quest.py`

**3.1 Mark `compute_quest_id()` as legacy:**

Add this docstring update (do not delete the function — backward compat):

```python
def compute_quest_id(repo_root: str, git_branch: str) -> str:
    """
    LEGACY: Deterministic quest_id from repo root path only.
    Kept for backward compatibility with existing git-anchored quests.
    New quests use UUID via hippocampus.create_new_quest().
    """
    raw = repo_root.strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

**3.2 Update `get_or_create_main_quest()` to set new fields:**

After the existing `CREATE` Cypher (line 66), add the new columns to the CREATE statement:

Replace the CREATE block (lines 65–94) with:

```python
        vector = emb.embed(name, model_name=embedding_model)
        await db.execute_write(
            """
            CREATE (q:MainQuest {
                quest_id:           $quest_id,
                name:               $name,
                status:             'active',
                completed_at:       null,
                purpose:            $purpose,
                text_raw:           $name,
                embedding:          $embedding,
                embedding_model:    $embedding_model,
                embedding_dim:      $embedding_dim,
                confidence:         1.0,
                confidence_low:     false,
                pathway_strength:   1.0,
                archived:           false,
                created_at:         timestamp($now),
                last_active_at:     timestamp($now),
                git_repo_root:      $git_repo_root,
                purpose_embedding:  $purpose_embedding,
                routing_method:     'git'
            })
            """,
            {
                "quest_id":          quest_id,
                "name":              name,
                "purpose":           f"Project work on {name}",
                "embedding":         vector,
                "embedding_model":   embedding_model,
                "embedding_dim":     len(vector),
                "now":               now,
                "git_repo_root":     repo_root,
                "purpose_embedding": vector,
            }
        )
```

**3.3 Update `get_or_create_session()` to set routing fields:**

Replace lines 105–116 (the MERGE Session block):

```python
        await db.execute_write(
            """
            MERGE (s:Session {session_id: $sid})
            ON CREATE SET s.started_at          = timestamp($now),
                          s.last_active_at      = timestamp($now),
                          s.onboarded           = false,
                          s.purpose             = '',
                          s.routing_state       = 'locked',
                          s.routing_confidence  = 0.95,
                          s.routing_method      = 'git'
            ON MATCH SET  s.last_active_at = timestamp($now)
            """,
            {"sid": session_id, "now": now}
        )
```

Note: `get_or_create_session()` is only called from the legacy `notify_turn` git path now, so routing_state defaults to "locked" with "git" method.

---

## Phase 4: Wire Tools Through Hippocampus

### File: `mcp_engine/tools.py`

**4.1 Update `notify_turn()`** — Replace lines 79–86 (the `if repo_root:` block):

```python
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
```

**Important:** The git path is kept as the fast lane — it calls existing `get_or_create_main_quest()` which now sets the new fields. The hippocampus path handles non-git sessions.

**4.2 After the Message creation block (line 116), add routing strength update:**

```python
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
```

**4.3 Update `current_truth()`** — Replace lines 163–166 (the `if not quest_id and repo_root:` block):

```python
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
```

**4.4 Add `set_quest` tool handler** (before the TOOL_HANDLERS dict):

```python
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
```

**4.5 Update TOOL_HANDLERS dict** (add set_quest):

```python
TOOL_HANDLERS = {
    "notify_turn":       notify_turn,
    "current_truth":     current_truth,
    "branch_quest":      branch_quest,
    "complete_quest":    complete_quest,
    "diff_since":        diff_since,
    "get_open_loops":    get_open_loops,
    "ingest_document":   ingest_document,
    "analogical_search": analogical_search,
    "explore_graph":     explore_graph,
    "set_quest":         set_quest,
}
```

---

## Phase 5: Adapter Updates

### All 4 adapters: `adapters/{claude_code,claude_desktop,codex,gemini_cli}/adapter.py`

**5.1 Add `set_quest` to TOOLS list** (append after `complete_quest` entry):

```python
    {
        "name": "set_quest",
        "description": (
            "Explicitly bind this session to a named project/quest. "
            "Use when the user says 'this is about X' or starts a new project. "
            "Creates a new quest if the name doesn't match an existing one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id":  {"type": "string"},
                "quest_name":  {"type": "string",
                                "description": "Name of the quest to bind to."},
                "quest_id":    {"type": "string",
                                "description": "Optional: bind to a specific quest_id."},
            },
            "required": ["session_id", "quest_name"],
        },
    },
```

**5.2 Rename `_inject_git_context` → `_inject_context`:**

In all 4 adapters, replace:

```python
def _inject_git_context(params: dict) -> dict:
    """Add repo_root + git_branch to any tool params dict."""
    return {**params, "repo_root": _REPO_ROOT, "git_branch": _GIT_BRANCH}
```

With:

```python
def _inject_context(params: dict) -> dict:
    """Add available context signals to any tool params dict."""
    ctx = {**params}
    if _REPO_ROOT:
        ctx["repo_root"] = _REPO_ROOT
    if _GIT_BRANCH:
        ctx["git_branch"] = _GIT_BRANCH
    # workspace_path = CWD even without git (for hippocampus routing)
    import os
    ctx.setdefault("workspace_path", os.getcwd())
    return ctx
```

**5.3 Update all references from `_inject_git_context` to `_inject_context`:**

In `handle_mcp_request()`, replace:

```python
        tool_input = _inject_git_context(params.get("arguments", {}))
```

With:

```python
        tool_input = _inject_context(params.get("arguments", {}))
```

**5.4 Add `set_quest` to tool dispatch** (in the catch-all block):

In the `if tool_name in ("ingest_document", "explore_graph", "complete_quest"):` block, add `"set_quest"`:

```python
        if tool_name in ("ingest_document", "explore_graph", "complete_quest", "set_quest"):
```

---

## Phase 7: Tests

### File: `tests/test_hippocampus.py` (CREATE NEW)

```python
"""
Tests for B17 Semantic Quest Routing (Hippocampus).

Run with: python3 -m pytest tests/test_hippocampus.py -v
"""

import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
```

**7.1 System 1 git match tests:**

```python
class TestSystem1GitMatch:

    def test_git_match_finds_by_git_repo_root(self):
        """Finds quest by git_repo_root property."""
        from mcp_engine.hippocampus import _system1_git_match

        class MockResult:
            def __init__(self, rows):
                self._rows = rows
                self._idx = 0
            def has_next(self): return self._idx < len(self._rows)
            def get_next(self):
                row = self._rows[self._idx]; self._idx += 1; return row

        class MockDB:
            def execute(self, query, params=None):
                if "git_repo_root" in query:
                    return MockResult([["quest-abc"]])
                return MockResult([])

        assert _system1_git_match(MockDB(), "/repo/myapp") == "quest-abc"

    def test_git_match_falls_back_to_legacy_hash(self):
        """Falls back to compute_quest_id hash when git_repo_root not populated."""
        from mcp_engine.hippocampus import _system1_git_match
        from mcp_engine.quest import compute_quest_id

        legacy_id = compute_quest_id("/repo/myapp", "")

        class MockResult:
            def __init__(self, rows):
                self._rows = rows; self._idx = 0
            def has_next(self): return self._idx < len(self._rows)
            def get_next(self):
                row = self._rows[self._idx]; self._idx += 1; return row

        class MockDB:
            def execute(self, query, params=None):
                if "git_repo_root" in query:
                    return MockResult([])  # no match on property
                if legacy_id in str(params):
                    return MockResult([[legacy_id]])
                return MockResult([])

        assert _system1_git_match(MockDB(), "/repo/myapp") == legacy_id

    def test_git_match_returns_none_when_no_match(self):
        """Returns None when neither git_repo_root nor legacy hash matches."""
        from mcp_engine.hippocampus import _system1_git_match

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()

        assert _system1_git_match(MockDB(), "/nonexistent") is None
```

**7.2 System 1 semantic match tests:**

```python
class TestSystem1SemanticMatch:

    def test_returns_sorted_by_similarity(self):
        """Returns candidates sorted by descending similarity."""
        from mcp_engine.hippocampus import _system1_semantic_match

        quests = [
            {"quest_id": "q1", "purpose_embedding": [1.0, 0.0, 0.0]},
            {"quest_id": "q2", "purpose_embedding": [0.0, 1.0, 0.0]},
        ]
        content_emb = [0.9, 0.1, 0.0]  # closer to q1
        results = _system1_semantic_match(content_emb, quests)

        assert results[0][0] == "q1"
        assert results[0][1] > results[1][1]

    def test_empty_quests_returns_empty(self):
        from mcp_engine.hippocampus import _system1_semantic_match
        assert _system1_semantic_match([1.0, 0.0], []) == []
```

**7.3 Route session integration tests:**

```python
class TestRouteSession:

    @pytest.mark.asyncio
    async def test_cold_start_creates_new_quest(self):
        """First session with no existing quests creates a new MainQuest."""
        from mcp_engine.hippocampus import route_session

        writes = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        result = await route_session(
            MockDB(), "sess-1", "Building a web app",
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        assert result.is_new_quest is True
        assert result.quest_id != ""
        assert result.routing_state == "tentative"
        assert len(writes) > 0
        # Should create MainQuest + bind session
        combined = " ".join(w["query"] for w in writes)
        assert "MainQuest" in combined
        assert "Session" in combined

    @pytest.mark.asyncio
    async def test_git_match_binds_locked(self):
        """Git repo match binds with locked state."""
        from mcp_engine.hippocampus import route_session

        writes = []
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
                # First call: check existing binding → none
                if "WORKING_ON" in query and "routing" in query:
                    return MockResult()
                # Second call: git_repo_root match → found
                if "git_repo_root" in query:
                    return MockResult([["quest-git"]])
                # Third call: check git_repo_root set
                return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        result = await route_session(
            MockDB(), "sess-2", "some content",
            "sentence-transformers/all-MiniLM-L6-v2",
            git_repo_root="/repo/myapp"
        )

        assert result.quest_id == "quest-git"
        assert result.method == "git"
        assert result.routing_state == "locked"
        assert result.is_new_quest is False

    @pytest.mark.asyncio
    async def test_existing_binding_returns_cached(self):
        """Session already bound → returns existing binding without re-routing."""
        from mcp_engine.hippocampus import route_session

        class MockResult:
            def __init__(self, rows=None):
                self._rows = rows or []; self._idx = 0
            def has_next(self): return self._idx < len(self._rows)
            def get_next(self):
                row = self._rows[self._idx]; self._idx += 1; return row

        class MockDB:
            def execute(self, query, params=None):
                if "WORKING_ON" in query and "routing" in query:
                    return MockResult([["quest-existing", 0.92, "semantic_s1", "consolidated"]])
                return MockResult()
            async def execute_write(self, query, params=None): pass

        result = await route_session(
            MockDB(), "sess-3", "anything",
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        assert result.quest_id == "quest-existing"
        assert result.confidence == 0.92
        assert result.routing_state == "consolidated"
```

**7.4 Consolidation state transition tests:**

```python
class TestConsolidation:

    @pytest.mark.asyncio
    async def test_tentative_promotes_to_consolidated(self):
        """Routing strength above threshold promotes tentative → consolidated."""
        from mcp_engine.hippocampus import update_routing_strength

        writes = []

        class MockResult:
            def has_next(self): return True
            def get_next(self): return [0.80, "tentative"]

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append(params)

        # Use identical embeddings (similarity = 1.0) to trigger boost
        emb = [1.0] * 384
        new_conf = await update_routing_strength(MockDB(), "sess-1", emb, emb)

        assert new_conf >= 0.85  # should be boosted
        assert any(w.get("state") == "consolidated" for w in writes)

    @pytest.mark.asyncio
    async def test_locked_state_not_changed(self):
        """Locked routing state is never changed by update_routing_strength."""
        from mcp_engine.hippocampus import update_routing_strength

        writes = []

        class MockResult:
            def has_next(self): return True
            def get_next(self): return [0.95, "locked"]

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append(params)

        emb = [1.0] * 384
        await update_routing_strength(MockDB(), "sess-1", emb, emb)

        # State should remain "locked", not downgrade
        if writes:
            assert all(w.get("state", "locked") == "locked" for w in writes)
```

**7.5 Reconsolidation test:**

```python
class TestReconsolidation:

    @pytest.mark.asyncio
    async def test_reconsolidate_creates_rerouted_from_edge(self):
        """Reconsolidation creates REROUTED_FROM edge to old quest."""
        from mcp_engine.hippocampus import reconsolidate

        writes = []
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
                if "WORKING_ON" in query and "routing" not in query:
                    # First call: old binding
                    if query_count[0] <= 2:
                        return MockResult([["old-quest"]])
                return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        result = await reconsolidate(
            MockDB(), "sess-1", "New topic entirely",
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        combined = " ".join(w["query"] for w in writes)
        assert "REROUTED_FROM" in combined
        assert "DELETE" in combined  # old WORKING_ON removed
        assert result.is_new_quest is True  # should create new quest (no matches)
```

**7.6 set_quest tool test:**

```python
class TestSetQuest:

    @pytest.mark.asyncio
    async def test_set_quest_creates_new_quest_when_not_found(self):
        from mcp_engine.tools import set_quest

        writes = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append({"query": query, "params": params})

        result = await set_quest(
            {"session_id": "sess-1", "quest_name": "New Project"},
            MockDB(),
            {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
        )

        assert "quest_id" in result
        assert result["routing_state"] == "locked"

    @pytest.mark.asyncio
    async def test_set_quest_requires_session_id(self):
        from mcp_engine.tools import set_quest

        class MockDB:
            pass

        result = await set_quest({"quest_name": "x"}, MockDB(), {})
        assert "error" in result
```

**7.7 Backward compatibility test:**

```python
class TestBackwardCompat:

    @pytest.mark.asyncio
    async def test_notify_turn_with_repo_root_still_works(self):
        """Legacy git path in notify_turn still creates quest correctly."""
        from mcp_engine.tools import notify_turn, init_loop_queue
        import asyncio

        init_loop_queue(asyncio.Queue())
        writes = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, query, params=None): return MockResult()
            async def execute_write(self, query, params=None):
                writes.append(query)

        result = await notify_turn(
            {"role": "user", "content": "test message", "session_id": "s1",
             "repo_root": "/repo/myapp", "git_branch": "main"},
            MockDB(),
            {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
             "ingestion": {"max_ingest_chars": 4000}}
        )

        assert result["status"] == "queued"
        assert result["quest_id"] != ""
        combined = " ".join(writes)
        assert "MainQuest" in combined
```

---

## Summary of All File Changes

| File | Action | Description |
|------|--------|-------------|
| `mcp_engine/schema.py` | **MODIFY** | Add 3 columns to MainQuest, 4 columns to Session, 1 REL_TABLE |
| `mcp_engine/hippocampus.py` | **CREATE** | New module: ~350 lines, 12 functions |
| `mcp_engine/quest.py` | **MODIFY** | Mark compute_quest_id as legacy, add new fields to CREATE blocks |
| `mcp_engine/tools.py` | **MODIFY** | Wire hippocampus into notify_turn + current_truth, add set_quest |
| `adapters/claude_code/adapter.py` | **MODIFY** | Rename _inject_git_context → _inject_context, add set_quest tool, add to dispatch |
| `adapters/claude_desktop/adapter.py` | **MODIFY** | Same changes as claude_code |
| `adapters/codex/adapter.py` | **MODIFY** | Same changes as claude_code |
| `adapters/gemini_cli/adapter.py` | **MODIFY** | Same changes as claude_code |
| `tests/test_hippocampus.py` | **CREATE** | New test file: ~300 lines, 7 test classes |

---

## Critical Files to Read Before Implementing

- `mcp_engine/quest.py` — current quest lifecycle functions
- `mcp_engine/tools.py` — current notify_turn + current_truth implementations
- `mcp_engine/schema.py` — current DDL for MainQuest and Session
- `mcp_engine/graph/kuzu_client.py` — DB interface (execute, execute_write, vector_search)
- `mcp_engine/graph/embeddings.py` — embed(), embed_batch(), mean_pool()
- `adapters/claude_code/adapter.py` — adapter pattern (TOOLS list, _inject_git_context, handle_mcp_request)
- `tests/test_quest.py` — existing test patterns (MockDB, MockQueryResult)
