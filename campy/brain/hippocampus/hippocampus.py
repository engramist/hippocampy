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

from campy.brain.hippocampus.graph import embeddings as emb

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

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
        await _bind_session(db, session_id, quest_id, 0.95, "semantic_s1", "tentative")
        return RoutingResult(quest_id, 0.95, "semantic_s1", True, "tentative")

    # Step 3b: Compute similarities
    candidates = _system1_semantic_match(content_embedding, active_quests)

    # Step 4: Workspace boost
    if workspace_path:
        candidates = _apply_workspace_boost(db, candidates, workspace_path)

    if not candidates:
        quest_id = await create_new_quest(db, content, content_embedding,
                                           embedding_model, git_repo_root)
        await _bind_session(db, session_id, quest_id, 0.95, "semantic_s1", "tentative")
        return RoutingResult(quest_id, 0.95, "semantic_s1", True, "tentative")

    best_id, best_score = candidates[0]

    # Step 5: Threshold check
    if best_score >= S1_AUTO_BIND_THRESHOLD:
        await _bind_session(db, session_id, best_id, best_score, "semantic_s1", "tentative")
        return RoutingResult(best_id, best_score, "semantic_s1", False, "tentative")

    if best_score >= S1_ESCALATION_THRESHOLD:
        # Step 6: System 2 disambiguation
        if llm_client:
            s2_id, s2_conf = await _system2_disambiguate(
                llm_client, candidates[:3], content, db
            )
            if s2_id:
                state = "tentative"
                await _bind_session(db, session_id, s2_id, s2_conf, "semantic_s2", state)
                return RoutingResult(s2_id, s2_conf, "semantic_s2", False, state)
            # LLM said "new quest"
            quest_id = await create_new_quest(db, content, content_embedding,
                                               embedding_model, git_repo_root)
            await _bind_session(db, session_id, quest_id, 0.90, "semantic_s2", "tentative")
            return RoutingResult(quest_id, 0.90, "semantic_s2", True, "tentative")
        else:
            # No LLM available — bind tentatively to best match
            await _bind_session(db, session_id, best_id, best_score, "semantic_s1", "tentative")
            return RoutingResult(best_id, best_score, "semantic_s1", False, "tentative")

    # Below escalation threshold — create new quest
    quest_id = await create_new_quest(db, content, content_embedding,
                                       embedding_model, git_repo_root)
    await _bind_session(db, session_id, quest_id, 0.95, "semantic_s1", "tentative")
    return RoutingResult(quest_id, 0.95, "semantic_s1", True, "tentative")


def _check_existing_binding(db: KuzuClient, session_id: str) -> Optional[RoutingResult]:
    """
    Check if session already has a WORKING_ON edge.
    Returns RoutingResult if bound, None otherwise.
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


def _system1_git_match(db: KuzuClient, git_repo_root: str) -> Optional[str]:
    """
    Check if a MainQuest exists with matching git_repo_root.
    Also checks legacy hash match for backward compatibility.
    Returns quest_id or None.
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
    from campy.brain.hippocampus.quest import compute_quest_id
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


def get_active_quests_with_embeddings(db: KuzuClient) -> list[dict]:
    """
    Return all active MainQuests with their purpose_embedding.
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


def _system1_semantic_match(
    content_embedding: list[float],
    active_quests: list[dict],
) -> list[tuple[str, float]]:
    """
    Cosine similarity between content_embedding and each quest's purpose_embedding.
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


def _apply_workspace_boost(
    db: KuzuClient,
    candidates: list[tuple[str, float]],
    workspace_path: str,
) -> list[tuple[str, float]]:
    """
    If workspace_path matches an existing Workspace node linked to a quest,
    boost that quest's score by ENTITY_OVERLAP_BOOST (0.15).
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


async def _system2_disambiguate(
    llm_client,
    candidates: list[tuple[str, float]],
    content: str,
    db: KuzuClient,
) -> tuple[Optional[str], float]:
    """
    LLM picks the right quest or says "new".
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

        # Handle string response or structured response from some SDKs
        if hasattr(response, 'content'):
            response_text = response.content
        else:
            response_text = str(response)

        # Extract JSON if wrapped in code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        data = json.loads(response_text.strip())
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


async def create_new_quest(
    db: KuzuClient,
    content: str,
    content_embedding: list[float],
    embedding_model: str,
    git_repo_root: str = "",
) -> str:
    """
    Create a new MainQuest with UUID.
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


async def _bind_session(
    db: KuzuClient,
    session_id: str,
    quest_id: str,
    confidence: float,
    method: str,
    state: str,
) -> None:
    """
    Create WORKING_ON edge + set Session routing fields.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    session_params = {
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
        session_params,
    )

    # B35 fix: separate params dict — Kuzu 0.11.3 rejects unused parameters
    await db.execute_write(
        "MATCH (s:Session {session_id: $sid}), (q:MainQuest {quest_id: $qid}) "
        "MERGE (s)-[:WORKING_ON]->(q)",
        {"sid": session_id, "qid": quest_id},
    )


async def _ensure_git_repo_root(db: KuzuClient, quest_id: str, git_repo_root: str) -> None:
    """
    Populate git_repo_root on existing quest if not already set.
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


async def update_routing_strength(
    db: KuzuClient,
    session_id: str,
    message_embedding: list[float],
    quest_purpose_embedding: list[float],
) -> float:
    """
    Called per message after the first. Updates routing_confidence on Session.
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
