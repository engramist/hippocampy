"""
mcp_engine/tools.py — MCP Tool Implementations (Brain Daemon side)

The IPC server in brain_daemon.py dispatches JSON-RPC calls here.
All writes go through db.execute_write() to respect the asyncio write lock.
"""

from __future__ import annotations
import asyncio
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

_logger = logging.getLogger(__name__)

# B160 dictionary helpers
from mcp_engine.dictionary import find_dictionary, load_dictionary, ingest_dictionary, DICTIONARY_PATHS
# KuzuClient imported only for type checking — kuzu is a C extension not needed
# during unit tests (db is always a mock or real object passed in at runtime).
if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

from mcp_engine.graph import embeddings as emb
from mcp_engine.quest import (
    get_or_create_main_quest, get_or_create_session,
    create_side_quest, get_quest_context,
)
try:
    from mcp_engine.loop.step4_pattern import (
        detect_ordered_plan_steps,
        has_plan_signal,
        infer_outcome_valence,
    )
except ModuleNotFoundError as exc:
    if exc.name != "mcp_engine.loop.step4_pattern":
        raise
    # Some benchmark consumers provide a minimal mcp_engine.loop shim while
    # importing this module from campy-brain. Keep the tool surface
    # importable with local equivalents of the passive plan/outcome helpers.
    _PLAN_SIGNALS = [
        r"(?:^|\n)\s*(?:step\s+)?\d+[\.\):]",
        r"\bmy (?:approach|plan|strategy)\b",
        r"\bhere(?:'s| is) (?:the|my) plan\b",
        r"\bi(?:'ll| will) (?:start by|begin with|first)\b",
        r"\bthe steps (?:are|would be)\b",
    ]
    _SUCCESS_SIGNALS = [
        r"\bperfect\b", r"\bgreat job\b", r"\bexactly (?:right|what)\b",
        r"\bship it\b", r"\bapproved\b", r"\blooks good\b", r"\bwell done\b",
        r"\bnailed it\b", r"\ball tests pass\b", r"\bmerged?\b",
    ]
    _FAILURE_SIGNALS = [
        r"\bthat(?:'s| is) wrong\b", r"\brevert\b", r"\bundo\b",
        r"\bthat broke\b", r"\bfailed\b", r"\brollback\b",
        r"\bnot what i (?:asked|wanted|meant)\b", r"\bstart over\b",
        r"\btry again\b", r"\bwrong approach\b",
    ]

    def detect_ordered_plan_steps(text: str) -> list[str]:
        if not text:
            return []
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        steps: list[str] = []
        numbered = re.compile(r"^(?:step\s+)?\d+[\.\):]\s+(.+)$", re.IGNORECASE)
        bullet = re.compile(r"^[-]\s+(.+)$")
        ordered_words = re.compile(r"^(?:first|then|next|finally)\b[:\-]?\s*(.+)$", re.IGNORECASE)
        for line in lines:
            m_num = numbered.match(line)
            if m_num:
                steps.append(m_num.group(1).strip())
                continue
            m_ord = ordered_words.match(line)
            if m_ord:
                steps.append(m_ord.group(1).strip())
                continue
            m_bul = bullet.match(line)
            if m_bul and ordered_words.match(m_bul.group(1).strip()):
                steps.append(m_bul.group(1).strip())
        seen = set()
        clean: list[str] = []
        for step in steps:
            key = step.lower()
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            clean.append(step)
        return clean

    def has_plan_signal(text: str) -> bool:
        lower = (text or "").lower()
        return any(re.search(p, lower) for p in _PLAN_SIGNALS)

    def infer_outcome_valence(text: str) -> float | None:
        lower = (text or "").lower()
        success_hits = sum(1 for p in _SUCCESS_SIGNALS if re.search(p, lower))
        failure_hits = sum(1 for p in _FAILURE_SIGNALS if re.search(p, lower))
        if success_hits == 0 and failure_hits == 0:
            return None
        if success_hits > failure_hits:
            return 0.8
        if failure_hits > success_hits:
            return -0.8
        return None
# ARC artifact ingestion tool
from mcp_engine.tools.arc_artifacts import ingest_arc_artifacts
from mcp_engine.tools.arc_mechanics import publish_mechanic_summary, recall_mechanic_priors

# ---------------------------------------------------------------------------
# M3 runtime state — initialized by brain_daemon.py at startup
# ---------------------------------------------------------------------------

_loop_queue: Optional[asyncio.Queue] = None


def init_loop_queue(queue: asyncio.Queue) -> None:
    """Called once by BrainDaemon.start() after the event loop is running."""
    global _loop_queue
    _loop_queue = queue


# ---------------------------------------------------------------------------
# B66/B67/B68/B69 — Planning + Outcome helpers
# ---------------------------------------------------------------------------

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _normalize_steps(raw_steps: list[str]) -> list[str]:
    steps: list[str] = []
    seen = set()
    for step in raw_steps:
        text = (step or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        steps.append(text)
    return steps


def _safe_result_dict(node) -> dict:
    """Defensive cast for Kuzu node records that behave like dicts."""
    try:
        return dict(node)
    except Exception:
        return node if isinstance(node, dict) else {}


def _session_active_plan_id(db, session_id: str) -> str:
    try:
        r = db.execute(
            "MATCH (p:Plan)-[:PLANNED_IN]->(s:Session {session_id: $sid}) "
            "WHERE p.status = 'active' "
            "RETURN p.plan_id "
            "ORDER BY p.created_at DESC LIMIT 1",
            {"sid": session_id},
        )
        if r.has_next():
            return r.get_next()[0] or ""
    except Exception:
        pass
    return ""


async def _create_plan_graph(
    *,
    db,
    goal: str,
    steps: list[str],
    session_id: str,
    embedding_model: str,
    now_iso: str,
    strategy: str = "",
    source: str = "active",
    confidence: float = 0.90,
    confidence_low: bool = False,
) -> tuple[str, list[str], str]:
    """Create Plan + PlanStep chain and basic relationships."""
    plan_id = str(uuid.uuid4())
    step_ids = [str(uuid.uuid4()) for _ in steps]
    goal_vec = emb.embed(goal, model_name=embedding_model)

    # Resolve quest_id from session if not provided
    quest_id = ""
    if session_id and session_id != "unknown":
        try:
            rq = db.execute(
                "MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q) "
                "RETURN q.quest_id LIMIT 1",
                {"sid": session_id},
            )
            if rq.has_next():
                quest_id = rq.get_next()[0] or ""
        except Exception:
            pass

    # Pre-calculate step data and ACTS_ON links
    step_params = []
    for idx, (step_id, step_text) in enumerate(zip(step_ids, steps), start=1):
        step_vec = emb.embed(step_text, model_name=embedding_model)
        acts_on = []
        try:
            # B75: pre-calculate ACTS_ON via vector search
            rows = db.vector_search("Concept", "concept_emb_idx", step_vec, 5)
            for row in rows:
                if row["score"] >= 0.75:
                    node = _safe_result_dict(row.get("node", {}))
                    cid = node.get("concept_id")
                    if cid and not node.get("archived", False):
                        acts_on.append(cid)
        except Exception:
            pass

        step_params.append({
            "step_id": step_id,
            "step_number": idx,
            "description": step_text,
            "embedding": step_vec,
            "acts_on": acts_on
        })

    try:
        # B75: Create Plan node first
        await db.execute_write(
            """
            CREATE (p:Plan {
                plan_id: $plan_id,
                goal: $goal,
                strategy: $strategy,
                source: $source,
                embedding: $embedding,
                embedding_model: $embedding_model,
                embedding_dim: $embedding_dim,
                step_count: $step_count,
                valence: NULL,
                valence_source: NULL,
                status: 'active',
                confidence: $confidence,
                confidence_low: $confidence_low,
                pathway_strength: $pathway_strength,
                archived: false,
                created_at: timestamp($created_at),
                completed_at: NULL
            })
            """,
            {
                "plan_id": plan_id,
                "goal": goal,
                "strategy": strategy,
                "source": source,
                "embedding": goal_vec,
                "embedding_model": embedding_model,
                "embedding_dim": len(goal_vec),
                "step_count": len(steps),
                "confidence": confidence,
                "confidence_low": confidence_low,
                "pathway_strength": max(confidence, 0.5),
                "created_at": now_iso,
            }
        )

        # B68: Create each PlanStep individually (separate CREATE for each step)
        # This allows passive plan detection to work with test assertions
        for s in step_params:
            await db.execute_write(
                """
                CREATE (ps:PlanStep {
                    step_id: $step_id,
                    step_number: $step_number,
                    description: $description,
                    embedding: $embedding,
                    embedding_model: $embedding_model,
                    embedding_dim: $embedding_dim,
                    expected_outcome: NULL,
                    actual_outcome: NULL,
                    valence: NULL,
                    status: 'pending',
                    created_at: timestamp($created_at),
                    completed_at: NULL
                })
                """,
                {
                    "step_id": s["step_id"],
                    "step_number": s["step_number"],
                    "description": s["description"],
                    "embedding": s["embedding"],
                    "embedding_model": embedding_model,
                    "embedding_dim": len(s["embedding"]),
                    "created_at": now_iso,
                }
            )
            # Link to Plan
            await db.execute_write(
                """
                MATCH (p:Plan {plan_id: $plan_id})
                MATCH (ps:PlanStep {step_id: $step_id})
                MERGE (ps)-[:STEP_OF]->(p)
                """,
                {"plan_id": plan_id, "step_id": s["step_id"]}
            )
            # Link ACTS_ON relationships
            if s["acts_on"]:
                await db.execute_write(
                    """
                    UNWIND $cids AS cid
                    MATCH (ps:PlanStep {step_id: $sid})
                    MATCH (c:Concept {concept_id: cid})
                    MERGE (ps)-[:ACTS_ON]->(c)
                    """,
                    {"sid": s["step_id"], "cids": s["acts_on"]}
                )

        # Kuzu parser compatibility: perform optional relationships as
        # separate conditional writes instead of Cypher FOREACH blocks.
        if session_id and session_id != "unknown":
            await db.execute_write(
                """
                MATCH (p:Plan {plan_id: $plan_id})
                MATCH (s:Session {session_id: $session_id})
                MERGE (p)-[:PLANNED_IN]->(s)
                """,
                {"plan_id": plan_id, "session_id": session_id},
            )

        if quest_id:
            # Try to link to either MainQuest or SideQuest
            try:
                await db.execute_write(
                    """
                    MATCH (p:Plan {plan_id: $plan_id})
                    MATCH (q:MainQuest {quest_id: $quest_id})
                    MERGE (p)-[:TARGETS]->(q)
                    """,
                    {"plan_id": plan_id, "quest_id": quest_id},
                )
            except Exception:
                # Quest might be a SideQuest, try that
                try:
                    await db.execute_write(
                        """
                        MATCH (p:Plan {plan_id: $plan_id})
                        MATCH (q:SideQuest {quest_id: $quest_id})
                        MERGE (p)-[:TARGETS]->(q)
                        """,
                        {"plan_id": plan_id, "quest_id": quest_id},
                    )
                except Exception:
                    # Neither quest type found, skip the relationship
                    pass

        # B75 Call 2: chain steps with NEXT_STEP
        if len(step_ids) > 1:
            next_pairs = [{"a": a, "b": b} for a, b in zip(step_ids, step_ids[1:])]
            await db.execute_write(
                """
                UNWIND $pairs AS pair
                MATCH (x:PlanStep {step_id: pair.a}), (y:PlanStep {step_id: pair.b})
                MERGE (x)-[:NEXT_STEP]->(y)
                """,
                {"pairs": next_pairs}
            )

    except Exception as e:
        _logger.exception("B75: Transactional plan write failed, cleaning up %s", plan_id)
        # Compensating delete to ensure atomicity.
        # Delete steps by known ids first, then delete plan node.
        try:
            if step_ids:
                await db.execute_write(
                    "UNWIND $ids AS sid MATCH (ps:PlanStep {step_id: sid}) DETACH DELETE ps",
                    {"ids": step_ids},
                )
            await db.execute_write(
                "MATCH (p:Plan {plan_id: $pid}) DETACH DELETE p",
                {"pid": plan_id},
            )
        except Exception:
            pass
        raise e

    return plan_id, step_ids, quest_id



def _plan_feedback_from_similarity(db, goal_vec: list[float], exclude_plan_id: str) -> tuple[list[dict], list[dict]]:
    """Amygdala reflex: similar historical plans -> warnings/suggestions."""
    warnings: list[dict] = []
    suggestions: list[dict] = []

    try:
        candidates = db.vector_search("Plan", "plan_emb_idx", goal_vec, 12)
    except Exception:
        return warnings, suggestions

    for item in candidates:
        node = _safe_result_dict(item.get("node", {}))
        pid = node.get("plan_id", "")
        if not pid or pid == exclude_plan_id:
            continue

        similarity = float(item.get("score", 0.0) or 0.0)
        if similarity <= 0.75:
            continue

        valence = node.get("valence")
        if valence is None:
            continue
        valence = float(valence)

        step_rows: list[dict] = []
        try:
            rs = db.execute(
                "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid}) "
                "RETURN ps.step_number, ps.description, ps.valence, ps.status "
                "ORDER BY ps.step_number ASC",
                {"pid": pid},
            )
            while rs.has_next():
                row = rs.get_next()
                step_rows.append(
                    {
                        "step_number": int(row[0]),
                        "description": row[1] or "",
                        "valence": row[2],
                        "status": row[3] or "",
                    }
                )
        except Exception:
            pass

        payload = {
            "plan_id": pid,
            "goal": node.get("goal", ""),
            "valence": valence,
            "similarity": round(similarity, 4),
            "steps": step_rows,
            "score": abs(valence * similarity),
        }
        if valence < -0.5:
            warnings.append(payload)
        elif valence > 0.5:
            suggestions.append(payload)

    warnings.sort(key=lambda x: x["score"], reverse=True)
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    for row in warnings:
        row.pop("score", None)
    for row in suggestions:
        row.pop("score", None)
    return warnings[:5], suggestions[:5]


async def _store_plan_outcome_lesson(db, *, plan_id: str, outcome: str, valence: float, session_id: str,
                                     embedding_model: str, now_iso: str) -> str | None:
    """Create a Lesson and connect it to the Plan when |valence| is strong."""
    if abs(valence) <= 0.7:
        return None

    lesson_text = f"Plan outcome ({'success' if valence > 0 else 'failure'}): {outcome.strip()}"
    lesson_id = str(uuid.uuid4())
    vec = emb.embed(lesson_text, model_name=embedding_model)

    await db.execute_write(
        """
        CREATE (l:Lesson {
            lesson_id: $lesson_id,
            text_raw: $text_raw,
            embedding: $embedding,
            embedding_model: $embedding_model,
            embedding_dim: $embedding_dim,
            domain: 'planning',
            lesson_type: 'optimization',
            confidence: 0.85,
            confidence_low: false,
            pathway_strength: 0.85,
            archived: false,
            created_at: timestamp($created_at)
        })
        """,
        {
            "lesson_id": lesson_id,
            "text_raw": lesson_text,
            "embedding": vec,
            "embedding_model": embedding_model,
            "embedding_dim": len(vec),
            "created_at": now_iso,
        },
    )

    await db.execute_write(
        "MATCH (p:Plan {plan_id: $pid}), (l:Lesson {lesson_id: $lid}) "
        "MERGE (p)-[:PRODUCED_PLAN_LESSON]->(l)",
        {"pid": plan_id, "lid": lesson_id},
    )

    if session_id and session_id != "unknown":
        await db.execute_write(
            "MATCH (s:Session {session_id: $sid}), (l:Lesson {lesson_id: $lid}) "
            "MERGE (s)-[:LEARNED]->(l)",
            {"sid": session_id, "lid": lesson_id},
        )

    return lesson_id


async def _maybe_create_passive_plan_from_turn(
    *,
    db,
    content: str,
    session_id: str,
    embedding_model: str,
    now_iso: str,
) -> dict | None:
    """B68 Layer B fallback: infer plan from structured text if not actively declared."""
    if not has_plan_signal(content):
        return None

    steps = detect_ordered_plan_steps(content)
    if len(steps) < 3:
        return None

    goal = content.split("\n", 1)[0].strip()[:240] or "Passively detected plan"
    goal_vec = emb.embed(goal, model_name=embedding_model)

    # Dedup against existing plans by similarity > 0.90
    try:
        existing = db.vector_search("Plan", "plan_emb_idx", goal_vec, 6)
        for row in existing:
            if float(row.get("score", 0.0) or 0.0) > 0.90:
                return None
    except Exception:
        pass

    plan_id, step_ids, quest_id = await _create_plan_graph(
        db=db,
        goal=goal,
        steps=steps,
        session_id=session_id,
        embedding_model=embedding_model,
        now_iso=now_iso,
        source="passive",
        confidence=0.70,
        confidence_low=True,
    )
    return {"plan_id": plan_id, "step_ids": step_ids, "quest_id": quest_id}


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

    # B91: Passive Graph Pre-Activation (Warm Frontier)
    if session_id != "unknown":
        from mcp_engine.warm_frontier import compute_warm_frontier
        try:
            await compute_warm_frontier(db, session_id, vector, config)
        except Exception:
            _logger.debug("compute_warm_frontier failed for session %s", session_id)

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

    # B192: Create FOLLOWED_BY edge from the previous message in the same session
    if session_id != "unknown":
        try:
            prev_r = db.execute(
                "MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid}) "
                "WHERE m.message_id <> $mid "
                "RETURN m.message_id, m.created_at "
                "ORDER BY m.created_at DESC LIMIT 1",
                {"sid": session_id, "mid": message_id},
            )
            if prev_r.has_next():
                prow = prev_r.get_next()
                prev_id = prow[0]
                prev_created = prow[1]
                gap_seconds = 0.0
                try:
                    prev_dt = datetime.fromisoformat(str(prev_created))
                    now_dt = datetime.fromisoformat(now)
                    gap_seconds = (now_dt - prev_dt).total_seconds()
                except Exception:
                    gap_seconds = 0.0

                await db.execute_write(
                    "MATCH (p:Message {message_id: $prev}), (c:Message {message_id: $curr}) "
                    "MERGE (p)-[r:FOLLOWED_BY]->(c) "
                    "ON CREATE SET r.gap_seconds = $gap "
                    "ON MATCH SET r.gap_seconds = $gap",
                    {"prev": prev_id, "curr": message_id, "gap": gap_seconds},
                )
        except Exception:
            _logger.exception("Failed to write FOLLOWED_BY for message %s", message_id)

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
        precomputed = params.get("precomputed")
        await _loop_queue.put((message_id, content, role, session_id, precomputed))

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

    passive_plan = None
    # B68: passive structural plan detection from natural-language ordered steps.
    try:
        if session_id != "unknown":
            passive_plan = await _maybe_create_passive_plan_from_turn(
                db=db,
                content=content,
                session_id=session_id,
                embedding_model=embedding_model,
                now_iso=now,
            )
    except Exception:
        _logger.exception("passive plan detection failed")

    # B69: outcome sense (success/failure language) can auto-report outcome.
    try:
        inferred_valence = infer_outcome_valence(content)
        if inferred_valence is not None and session_id != "unknown":
            active_plan_id = _session_active_plan_id(db, session_id)
            if active_plan_id:
                await report_outcome(
                    {
                        "plan_id": active_plan_id,
                        "outcome": content,
                        "valence": inferred_valence,
                        "session_id": session_id,
                        "valence_source": "system",
                    },
                    db,
                    config,
                )
            elif abs(inferred_valence) > 0.7:
                await _store_plan_outcome_lesson(
                    db,
                    plan_id="",
                    outcome=content,
                    valence=inferred_valence,
                    session_id=session_id,
                    embedding_model=embedding_model,
                    now_iso=now,
                )
    except Exception:
        _logger.exception("outcome sense auto-report failed")

    # -----------------------------------------------------------------------
    # B195: Active Context Push (proactive_context)
    # - Match high-confidence negative Lessons, Procedures, and KnowledgeGaps
    # - Rate-limit pushes to one per `min_turns_between_pushes` (default 5)
    # - Record pushed nodes with LOADED edges source="proactive_push"
    proactive_context = None
    try:
        if session_id != "unknown":
            from mcp_engine.working_memory import get_session_token_state, track_loaded

            state = get_session_token_state(db, session_id) or {}
            current_msg_count = int(state.get("message_count", 0) or 0)

            # Read last push count from Session node
            last_push_count = None
            try:
                lr = db.execute(
                    "MATCH (s:Session {session_id: $sid}) RETURN s.last_proactive_push_msg_count",
                    {"sid": session_id},
                )
                if lr.has_next():
                    val = lr.get_next()[0]
                    if val is not None:
                        try:
                            last_push_count = int(val)
                        except Exception:
                            last_push_count = None
            except Exception:
                last_push_count = None

            window = int((config.get("proactive_push", {}) or {}).get("min_turns_between_pushes", 5))
            allowed = False
            if last_push_count is None:
                allowed = True
            else:
                allowed = (current_msg_count - last_push_count) >= window

            if allowed:
                embedding_model = config.get("embeddings", {}).get(
                    "model", "sentence-transformers/all-MiniLM-L6-v2"
                )
                try:
                    qvec = emb.embed(content, model_name=embedding_model)
                except Exception:
                    qvec = None

                candidates: list[dict] = []

                # 1) High-confidence negative Lessons by semantic similarity
                try:
                    if qvec is not None:
                        lessons = db.vector_search("Lesson", "lesson_emb_idx", qvec, 5)
                        for it in lessons:
                            node = _safe_result_dict(it.get("node", {}))
                            conf = float(node.get("confidence") or 0.0)
                            text = (node.get("text_raw") or "")
                            if conf >= 0.8 and "failure" in text.lower():
                                candidates.append({
                                    "node_id": node.get("lesson_id"),
                                    "node_type": "Lesson",
                                    "text_raw": text,
                                    "lesson_id": node.get("lesson_id"),
                                    "text": text,
                                    "type": node.get("lesson_type") or "lesson",
                                    "domain": node.get("domain") or "generic",
                                })
                except Exception:
                    _logger.debug("proactive: lesson search failed")

                # 2) Relevant Procedures via semantic search
                try:
                    if qvec is not None:
                        procs = db.vector_search("Procedure", "procedure_emb_idx", qvec, 3)
                        for it in procs:
                            node = _safe_result_dict(it.get("node", {}))
                            text = node.get("description", "") or ""
                            candidates.append({
                                "node_id": node.get("procedure_id"),
                                "node_type": "Procedure",
                                "text_raw": text,
                                "procedure_id": node.get("procedure_id"),
                                "text": text,
                                "type": "procedure",
                                "domain": node.get("archetype") or node.get("domain") or "generic",
                            })
                except Exception:
                    _logger.debug("proactive: procedure search failed")

                # 3) KnowledgeGaps by simple text-match on description/domain
                try:
                    snippet = (content or "")[:120]
                    kgq = db.execute(
                        "MATCH (g:KnowledgeGap) WHERE (g.resolved IS NULL OR g.resolved = false) "
                        "AND (lower(g.description) CONTAINS lower($snippet) OR lower(g.domain) CONTAINS lower($snippet)) "
                        "RETURN g.gap_id, g.description, g.severity ORDER BY g.severity DESC LIMIT $lim",
                        {"snippet": snippet, "lim": 3},
                    )
                    while kgq.has_next():
                        row = kgq.get_next()
                        text = row[1] or ""
                        candidates.append({
                            "node_id": row[0],
                            "node_type": "KnowledgeGap",
                            "text_raw": text,
                            "gap_id": row[0],
                            "text": text,
                            "type": "knowledge_gap",
                            "domain": "generic",
                        })
                except Exception:
                    _logger.debug("proactive: knowledge gap lookup failed")

                if candidates:
                    try:
                        # Record LOADED edges so the LLM is aware these nodes were injected
                        await track_loaded(db, session_id, candidates, source="proactive_push")
                        # Persist last push marker on Session
                        try:
                            await db.execute_write(
                                "MATCH (s:Session {session_id: $sid}) SET s.last_proactive_push_msg_count = $count",
                                {"sid": session_id, "count": current_msg_count},
                            )
                        except Exception:
                            _logger.debug("proactive: failed to persist last_proactive_push_msg_count")
                        proactive_context = {"pushed": True, "items": candidates}
                    except Exception:
                        _logger.exception("proactive: track_loaded failed")
                else:
                    proactive_context = {"pushed": False, "reason": "no_matches"}
            else:
                next_allowed = window - (current_msg_count - (last_push_count or 0))
                proactive_context = {"pushed": False, "reason": "rate_limited", "next_allowed_in_turns": max(next_allowed, 0)}
    except Exception:
        _logger.exception("proactive push failed")

    response = {
        "status": "ingested",
        "message_id": message_id,
        "quest_id": quest_id,
    }
    if insights:
        response["insights"] = insights
    if passive_plan:
        response["passive_plan"] = passive_plan
    # Always include proactive_context (B195) for caller to inspect
    response["proactive_context"] = proactive_context if proactive_context is not None else {"pushed": False, "reason": "disabled"}

    return response


# ---------------------------------------------------------------------------
# B125 Helper: Map node type to primary key column
# ---------------------------------------------------------------------------

def _get_pk_for_node_type(node_type: str) -> str:
    """Map node table name to its primary key column name."""
    pk_map = {
        "Concept": "concept_id",
        "Decision": "decision_id",
        "Constraint": "constraint_id",
        "Requirement": "requirement_id",
        "ActionItem": "action_item_id",
        "GlobalConstraint": "global_constraint_id",
        "GlobalPreference": "global_preference_id",
        "Lesson": "lesson_id",
        "Message": "message_id",
        "DocumentExtract": "extract_id",
    }
    return pk_map.get(node_type, "id")


async def reconstruct_timeline(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Reconstruct the temporal sequence of Messages (and Decisions) for a given topic.

    params: {topic, session_id?, max_hops?, include_decisions?}
    Returns: {timeline: [{message: {message_id, text, created_at}, decisions: [{decision_id, text}]}], truncated: bool}
    """
    topic = (params.get("topic") or "").strip()
    if not topic:
        return {"timeline": []}

    session_id = params.get("session_id", "").strip()
    max_hops = int(params.get("max_hops", 20))
    include_decisions = bool(params.get("include_decisions", True))

    try:
        starts = []
        # 1) Messages whose text contains the topic
        if session_id:
            r = db.execute(
                "MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid}) "
                "WHERE lower(m.text_raw) CONTAINS lower($topic) "
                "RETURN m.message_id, m.text_raw, m.created_at "
                "ORDER BY m.created_at ASC",
                {"sid": session_id, "topic": topic}
            )
        else:
            r = db.execute(
                "MATCH (m:Message) WHERE lower(m.text_raw) CONTAINS lower($topic) "
                "RETURN m.message_id, m.text_raw, m.created_at "
                "ORDER BY m.created_at ASC",
                {"topic": topic}
            )
        while r.has_next():
            row = r.get_next()
            starts.append({"message_id": row[0], "text": row[1], "created_at": row[2]})

        # 2) Messages that established Decisions containing the topic
        r2 = db.execute(
            "MATCH (m:Message)-[:ESTABLISHED]->(d:Decision) "
            "WHERE lower(d.text_raw) CONTAINS lower($topic) "
            "RETURN m.message_id, m.text_raw, m.created_at "
            "ORDER BY m.created_at ASC",
            {"topic": topic}
        )
        while r2.has_next():
            row = r2.get_next()
            if not any(s["message_id"] == row[0] for s in starts):
                starts.append({"message_id": row[0], "text": row[1], "created_at": row[2]})

        if not starts:
            return {"timeline": [], "found_starts": 0}

        # Use the earliest matching start
        start = starts[0]
        timeline = []
        curr_id = start["message_id"]

        def _fetch_message(mid: str):
            try:
                rr = db.execute(
                    "MATCH (m:Message {message_id: $mid}) RETURN m.message_id, m.text_raw, m.created_at",
                    {"mid": mid}
                )
                if rr.has_next():
                    rrow = rr.get_next()
                    return {"message_id": rrow[0], "text": rrow[1], "created_at": str(rrow[2])}
            except Exception:
                pass
            return None

        def _fetch_decisions_for_message(mid: str):
            out = []
            try:
                rd = db.execute(
                    "MATCH (m:Message {message_id: $mid})-[:ESTABLISHED]->(d:Decision) "
                    "RETURN d.decision_id, d.text_raw ORDER BY d.created_at ASC",
                    {"mid": mid}
                )
                while rd.has_next():
                    rdd = rd.get_next()
                    out.append({"decision_id": rdd[0], "text": rdd[1]})
            except Exception:
                pass
            return out

        # Append start message
        msg = _fetch_message(curr_id)
        if msg:
            timeline.append({"message": msg, "decisions": _fetch_decisions_for_message(curr_id) if include_decisions else []})

        # Walk FOLLOWED_BY chain up to max_hops
        for _ in range(max_hops):
            try:
                nr = db.execute(
                    "MATCH (m:Message {message_id: $mid})-[:FOLLOWED_BY]->(n:Message) "
                    "RETURN n.message_id, n.text_raw, n.created_at LIMIT 1",
                    {"mid": curr_id}
                )
                if not nr.has_next():
                    break
                nrow = nr.get_next()
                next_id = nrow[0]
                msg = _fetch_message(next_id)
                if not msg:
                    break
                timeline.append({"message": msg, "decisions": _fetch_decisions_for_message(next_id) if include_decisions else []})
                curr_id = next_id
            except Exception:
                break

        truncated = len(timeline) >= max_hops
        return {"timeline": timeline, "truncated": truncated}

    except Exception:
        _logger.exception("reconstruct_timeline failed")
        return {"timeline": [], "error": "internal"}

# ---------------------------------------------------------------------------
# M2/M5 — current_truth
# ---------------------------------------------------------------------------

async def current_truth(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Retrieve relevant memory for a query.
    M5: branch scope adds quest-linked artifacts to the result set.
    B125: Optional include_rationale includes originating message content.

    params: {query, session_id, scope ("branch"|"global"|"both"), limit,
             quest_id?, repo_root?, git_branch?, include_rationale?}
    """
    query      = params.get("query", "")
    session_id = params.get("session_id", "unknown")
    scope      = params.get("scope", "branch")
    limit      = int(params.get("limit", 10))
    explicit_quest_id = params.get("quest_id", "")
    quest_id   = explicit_quest_id
    repo_root  = params.get("repo_root", "")
    git_branch = params.get("git_branch", "main")
    include_rationale = params.get("include_rationale", False)  # B125

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
        # Raw episodic memory must be searchable too. Consolidated artifacts
        # are ideal for "current truth", but freshly captured turns may not
        # have produced a Decision/Lesson yet.
        ("Message",          "message_emb_idx",           "message_id"),
        ("DocumentExtract",  "documentextract_emb_idx",   "extract_id"),
    ]

    all_raw_results = []
    per_table_limit = max(limit, 5)

    for table_name, index_name, pk in artifact_tables:
        try:
            rows = db.vector_search(table_name, index_name, query_vector, per_table_limit)
            for row in rows:
                all_raw_results.append((table_name, pk, row))
        except Exception:
            _logger.exception("current_truth vector search failed for table %s", table_name)

    # Episodic exact-match fallback. Vector search alone is not enough for
    # "what did we just say about X?" because raw Message nodes are deliberately
    # low-confidence/low-strength until consolidation. Exact text hits should
    # still surface as recall evidence.
    lexical_message_ids: set[str] = set()
    try:
        lexical_limit = max(limit, 5)
        rr = db.execute(
            "MATCH (m:Message) "
            "WHERE lower(m.text_raw) CONTAINS lower($query) "
            "RETURN m.message_id, m.text_raw, m.role, m.confidence, "
            "m.confidence_low, m.pathway_strength, m.created_at "
            f"ORDER BY m.created_at DESC LIMIT {lexical_limit}",
            {"query": query},
        )
        while rr.has_next():
            mid, text, role, conf, conf_low, ps, created_at = rr.get_next()
            lexical_message_ids.add(mid)
            all_raw_results.append((
                "Message",
                "message_id",
                {
                    "node": {
                        "message_id": mid,
                        "text_raw": text,
                        "role": role,
                        "confidence": conf or 0.0,
                        "confidence_low": True if conf_low is None else bool(conf_low),
                        "pathway_strength": ps or 0.0,
                        "created_at": created_at,
                        "archived": False,
                    },
                    "score": 1.0,
                    "lexical_exact": True,
                },
            ))
    except Exception:
        _logger.debug("current_truth lexical message fallback failed", exc_info=True)

    # Batch outcome signal lookup for retrieved nodes
    # We check both the node itself (if it's a Concept) and the parent Concept
    # (if it's a Reified artifact) to capture all outcome signals.
    outcome_map = {}
    node_ids = []
    for table, pk, r in all_raw_results:
        node = r["node"]
        nid = node.get(pk)
        if nid:
            node_ids.append(nid)

    if node_ids:
        try:
            # Query for signals linked directly to a Concept OR to a Concept 
            # that was REIFIED_AS the artifact.
            ro = db.execute(
                """
                UNWIND $ids AS nid
                OPTIONAL MATCH (ps:PlanStep)-[o:OUTCOME_SIGNAL]->(c:Concept {concept_id: nid})
                OPTIONAL MATCH (ps2:PlanStep)-[o2:OUTCOME_SIGNAL]->(c2:Concept)-[:REIFIED_AS]->(a) 
                WHERE (a.decision_id = nid OR a.constraint_id = nid OR a.requirement_id = nid OR a.action_item_id = nid)
                WITH nid, 
                     CASE WHEN o IS NOT NULL THEN o.valence ELSE o2.valence END AS v
                WHERE v IS NOT NULL
                RETURN nid, avg(v), count(v)
                """,
                {"ids": node_ids},
            )
            while ro.has_next():
                nid, avg_v, count = ro.get_next()
                outcome_map[nid] = (avg_v, count)
        except Exception:
            _logger.exception("current_truth batch outcome lookup failed")

    # B91: Warm Frontier (Passive Graph Pre-Activation)
    warm_nodes = {}
    if session_id != "unknown":
        from mcp_engine.warm_frontier import get_warm_nodes
        try:
            warm_nodes = get_warm_nodes(db, session_id)
        except Exception:
            pass

    all_results = []
    for table_name, pk, row in all_raw_results:
        try:
            node = row["node"]
            if node.get("archived", False):
                continue
            node_id = (node.get("concept_id")
                        or node.get("decision_id") or node.get("constraint_id")
                        or node.get("requirement_id") or node.get("action_item_id")
                        or node.get("global_constraint_id")
                        or node.get("global_preference_id")
                        or node.get("lesson_id")
                        or node.get("message_id")
                        or node.get("extract_id")
                        or "unknown")
            ps = node.get("pathway_strength", 0.0) or 0.0
            conf = node.get("confidence", 0.0) or 0.0
            similarity = row["score"]
            lexical_exact = bool(row.get("lexical_exact"))

            # B91: Warm boost
            activation_score = warm_nodes.get(node_id, 0.0)
            warm_boost = activation_score * 0.25 # Up to +0.25 boost for hot nodes

            outcome_valence = None
            outcome_warning = None
            outcome_boost = 0.0
            reifiable_types = {"Concept", "Decision", "Constraint", "Requirement", "ActionItem"}
            if table_name in reifiable_types and node_id in outcome_map:
                avg_valence, signal_count = outcome_map[node_id]
                if signal_count and avg_valence is not None:
                    outcome_valence = float(avg_valence)
                    outcome_boost = _clamp(outcome_valence * 0.3, -0.3, 0.3)
                    if outcome_valence < -0.1:
                        outcome_warning = (
                            f"This entity was involved in {int(signal_count)} failed or negative-outcome plan steps."
                        )

            # Architecture invariant: vector search finds candidate nodes, but
            # graph memory ranks them by pathway strength and confidence.
            strength = (ps * conf) if (ps > 0.0 and conf > 0.0) else 0.0
            rank = strength * (1.0 + outcome_boost)

            all_results.append({
                "node_id":          node_id,
                "node_type":        table_name,
                "text_raw":         node.get("text_raw", ""),
                "confidence":       conf,
                "confidence_low":   node.get("confidence_low", True),
                "pathway_strength": ps,
                "similarity":       similarity,
                "activation_score": activation_score, # B91: expose for debugging/tests
                "outcome_valence":  outcome_valence,
                "outcome_warning":  outcome_warning,
                "lexical_exact":     lexical_exact,
                "_rank":            rank,
            })
        except Exception:
            _logger.exception("current_truth processing failed for node %s", node_id)


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

    # B125: Add originating message rationale if requested
    if include_rationale and final_results:
        for result in final_results:
            try:
                # Try to find the originating message via ESTABLISHED_IN relationship
                node_id = result.get("node_id")
                node_type = result.get("node_type", "")
                if node_id and node_type:
                    # Simple 1-hop traversal to find originating message
                    query = f"MATCH (n:{node_type})-[r:ESTABLISHED_IN]->(m:Message) WHERE n.{_get_pk_for_node_type(node_type)} = $id RETURN m.content LIMIT 1"
                    try:
                        r = db.execute(query, {"id": node_id})
                        if r.has_next():
                            message_content = r.get_next()[0]
                            if message_content:
                                # Truncate to 200 chars as per B125 spec
                                result["originating_rationale"] = str(message_content)[:200]
                    except Exception:
                        pass
            except Exception:
                pass

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
            # Update token estimate for all returned content. track_loaded()
            # intentionally skips raw Message / DocumentExtract nodes, but if
            # they were returned, their text still consumed context window.
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


async def get_knowledge_gaps(params: dict, db: KuzuClient, config: dict) -> dict:
    """B193: Return active KnowledgeGaps for proactive metacognition."""
    limit = int(params.get("limit", 10))
    unresolved_only = bool(params.get("unresolved_only", True))
    min_severity = float(params.get("min_severity", 0.0))

    gaps: list[dict] = []
    try:
        if unresolved_only:
            r = db.execute(
                "MATCH (g:KnowledgeGap) WHERE g.resolved = false AND g.severity >= $min "
                "RETURN g.gap_id, g.domain, g.gap_type, g.description, g.severity, g.message_count, g.lesson_count, g.created_at "
                "ORDER BY g.severity DESC LIMIT $lim",
                {"min": min_severity, "lim": limit},
            )
        else:
            r = db.execute(
                "MATCH (g:KnowledgeGap) WHERE g.severity >= $min "
                "RETURN g.gap_id, g.domain, g.gap_type, g.description, g.severity, g.message_count, g.lesson_count, g.created_at "
                "ORDER BY g.severity DESC LIMIT $lim",
                {"min": min_severity, "lim": limit},
            )

        while r.has_next():
            row = r.get_next()
            gaps.append({
                "gap_id": row[0],
                "domain": row[1],
                "gap_type": row[2],
                "description": row[3],
                "severity": float(row[4] or 0.0),
                "message_count": int(row[5] or 0),
                "lesson_count": int(row[6] or 0),
                "created_at": str(row[7]) if row[7] is not None else None,
            })
    except Exception:
        _logger.exception("get_knowledge_gaps failed")

    return {"gaps": gaps}


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
# B158 — Disambiguation queue tools
# ---------------------------------------------------------------------------

async def get_disambiguation_queue(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Retrieve pending DisambiguationEvent pairs for human curation.

    params: {limit}
    Returns {pairs: [{event_id, similarity, created_at, concept_a, concept_b, shared_neighbors}], total_pending}
    """
    limit = int(params.get("limit", 10))
    pairs: list[dict] = []
    try:
        r = db.execute(
            "MATCH (e:DisambiguationEvent) "
            "WHERE e.status = 'pending' "
            "RETURN e.event_id, e.concept_id_a, e.concept_id_b, e.similarity, e.created_at "
            "ORDER BY e.created_at DESC LIMIT $lim",
            {"lim": limit}
        )
        while r.has_next():
            row = r.get_next()
            eid, a_id, b_id, sim, created_at = row[0], row[1], row[2], row[3], row[4]

            def _get_concept_with_context(cid: str):
                try:
                    rr = db.execute(
                        "MATCH (c:Concept {concept_id: $cid}) "
                        "OPTIONAL MATCH (c)-[:HAS_ALT_LABEL]->(l:Label) "
                        "RETURN c.concept_id, c.text_raw, c.gist_class, c.confidence, "
                        "       c.pathway_strength, c.confidence_low, collect(l.text) AS alt_labels",
                        {"cid": cid}
                    )
                    if rr.has_next():
                        rrow = rr.get_next()
                        return {
                            "concept_id": rrow[0],
                            "text_raw": rrow[1],
                            "gist_class": rrow[2],
                            "confidence": rrow[3],
                            "pathway_strength": rrow[4],
                            "confidence_low": rrow[5],
                            "alt_labels": rrow[6] or [],
                        }
                except Exception:
                    pass
                return None

            def _shared_neighbors(cid_a: str, cid_b: str) -> list:
                try:
                    rr = db.execute(
                        "MATCH (a:Concept {concept_id: $a})-[]->(n:Concept)<-[]-(b:Concept {concept_id: $b}) "
                        "WHERE n.archived = false "
                        "RETURN DISTINCT n.concept_id, n.text_raw LIMIT 10",
                        {"a": a_id, "b": b_id}
                    )
                    out = []
                    while rr.has_next():
                        nr = rr.get_next()
                        out.append({"concept_id": nr[0], "text_raw": nr[1]})
                    return out
                except Exception:
                    return []

            concept_a = _get_concept_with_context(a_id)
            concept_b = _get_concept_with_context(b_id)

            pairs.append({
                "event_id": eid,
                "similarity": sim,
                "created_at": str(created_at),
                "concept_a": concept_a,
                "concept_b": concept_b,
                "shared_neighbors": _shared_neighbors(a_id, b_id),
            })
    except Exception:
        _logger.exception("get_disambiguation_queue failed")

    return {"pairs": pairs, "total_pending": len(pairs)}


async def resolve_disambiguation(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Resolve a DisambiguationEvent: merge | separate | skip.

    params: {event_id, resolution}
    """
    event_id = params.get("event_id")
    resolution = params.get("resolution")
    if resolution not in ("merge", "separate", "skip"):
        return {"error": f"Invalid resolution: {resolution}. Use merge, separate, or skip."}

    try:
        r = db.execute(
            "MATCH (e:DisambiguationEvent {event_id: $eid}) "
            "RETURN e.concept_id_a, e.concept_id_b, e.status",
            {"eid": event_id}
        )
        if not r.has_next():
            return {"error": f"Event {event_id} not found"}
        ev = r.get_next()
        cid_a, cid_b, status = ev[0], ev[1], ev[2]
        if status != "pending":
            return {"error": f"Event already resolved: {status}"}

        now = datetime.now(timezone.utc).isoformat()

        if resolution == "merge":
            # Determine canonical (older) vs duplicate (newer)
            cr = db.execute(
                "MATCH (a:Concept {concept_id: $a}), (b:Concept {concept_id: $b}) "
                "RETURN a.concept_id, a.created_at, a.text_raw, b.concept_id, b.created_at, b.text_raw",
                {"a": cid_a, "b": cid_b}
            )
            if not cr.has_next():
                return {"error": "One or both concepts not found"}
            crow = cr.get_next()
            a_created, b_created = crow[1], crow[4]
            # Compare safely as strings or timestamps — fallback to cid_a
            try:
                canonical_id = cid_a if a_created <= b_created else cid_b
            except Exception:
                canonical_id = cid_a
            duplicate_id = cid_b if canonical_id == cid_a else cid_a
            duplicate_text = crow[5] if canonical_id == cid_a else crow[2]

            # Create altLabel from duplicate's text
            label_id = str(uuid.uuid4())
            await db.execute_write(
                "CREATE (l:Label {"
                "  label_id: $lid, text: $txt, label_type: 'alternative',"
                "  confidence: 0.95, source: 'user', language: 'en', created_at: timestamp($now)"
                "})",
                {"lid": label_id, "txt": duplicate_text, "now": now}
            )
            # Embed the label
            try:
                emb_vec = emb.embed(duplicate_text)
                await db.execute_write(
                    "MATCH (l:Label {label_id: $lid}) SET l.embedding = $emb",
                    {"lid": label_id, "emb": emb_vec}
                )
            except Exception:
                _logger.exception("Label embed failed")

            # Wire canonical -> altLabel
            await db.execute_write(
                "MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid}) "
                "CREATE (c)-[:HAS_ALT_LABEL {created_at: timestamp($now)}]->(l)",
                {"cid": canonical_id, "lid": label_id, "now": now}
            )

            # Redirect common edges from duplicate to canonical
            rel_types = ["REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS",
                         "PART_OF", "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS",
                         "ALTERNATIVE_TO", "CO_OCCURS_WITH"]
            for rel in rel_types:
                try:
                    await db.execute_write(
                        f"MATCH (dup:Concept {{concept_id: $dup}})-[r:{rel}]->(t:Concept) "
                        f"WHERE t.concept_id <> $can "
                        f"MATCH (can:Concept {{concept_id: $can}}) "
                        f"MERGE (can)-[:{rel}]->(t)",
                        {"dup": duplicate_id, "can": canonical_id}
                    )
                except Exception:
                    _logger.exception("Edge redirect failed for %s", rel)

            # Archive duplicate
            await db.execute_write(
                "MATCH (c:Concept {concept_id: $cid}) SET c.archived = true",
                {"cid": duplicate_id}
            )

            # Boost canonical
            await db.execute_write(
                "MATCH (c:Concept {concept_id: $cid}) "
                "SET c.pathway_strength = c.pathway_strength + 0.15, "
                "    c.confidence_low = false, "
                "    c.last_accessed_at = timestamp($now)",
                {"cid": canonical_id, "now": now}
            )

            result_msg = f"Merged: '{duplicate_text}' → altLabel of canonical concept"

        elif resolution == "separate":
            await db.execute_write(
                "MATCH (a:Concept {concept_id: $a}), (b:Concept {concept_id: $b}) "
                "SET a.confidence_low = false, b.confidence_low = false "
                "CREATE (a)-[:DISTINCT_FROM {created_at: timestamp($now), source: 'user'}]->(b)",
                {"a": cid_a, "b": cid_b, "now": now}
            )
            result_msg = "Separated: both concepts confirmed as distinct entities"

        else:  # skip
            result_msg = "Skipped: pair re-queued for later review"

        final_status = resolution if resolution != "skip" else "pending"
        await db.execute_write(
            "MATCH (e:DisambiguationEvent {event_id: $eid}) "
            "SET e.status = $status, e.resolved_at = timestamp($now), e.resolved_by = 'user'",
            {"eid": event_id, "status": final_status if final_status != "pending" else "pending", "now": now}
        )

        return {"result": result_msg, "resolution": resolution}
    except Exception:
        _logger.exception("resolve_disambiguation failed for %s", event_id)
        return {"error": "internal error"}


# ---------------------------------------------------------------------------
# B160 — Domain dictionary reload tool
# ---------------------------------------------------------------------------

async def reload_domain_dictionary(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Reload the domain dictionary from disk and ingest new entities/altLabels.

    params: {workspace_root?: string}
    """
    workspace_root = params.get("workspace_root", ".")
    try:
        dict_path = find_dictionary(workspace_root)
        if not dict_path:
            return {"error": "No domain_dictionary.yaml found", "searched": DICTIONARY_PATHS}

        entities = load_dictionary(dict_path)
        if not entities:
            return {"error": "Dictionary is empty or invalid"}

        now = datetime.now(timezone.utc).isoformat()
        result = await ingest_dictionary(entities, db, now)
        return {"status": "ok", "path": str(dict_path), **result}
    except Exception:
        _logger.exception("reload_domain_dictionary failed")
        return {"error": "internal error"}

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


async def ingest_data(params: dict, db, config: dict) -> dict:
    """
    Unified ingestion entry point. Classifies file/content input and routes it
    to the graph/document/tabular ingestion path without creating a shadow store.

    params: {file_path?, content?, mime_type?, session_id, quest_id?}
    """
    from mcp_engine.memory_router import classify_input

    file_path = (params.get("file_path") or "").strip()
    content = params.get("content")
    mime_type = params.get("mime_type")
    session_id = (params.get("session_id") or "unknown").strip() or "unknown"
    quest_id = (params.get("quest_id") or "").strip()

    if not file_path and not content:
        return {"error": "file_path or content is required"}

    route = classify_input(content=content, file_path=file_path, mime_type=mime_type)

    if file_path:
        result = await ingest_document({"file_path": file_path, "quest_id": quest_id}, db, config)
    else:
        result = await notify_turn(
            {
                "role": params.get("role", "user"),
                "content": content or "",
                "session_id": session_id,
            },
            db,
            config,
        )

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
    from mcp_engine.bundle_compiler import compile_bundle
    from mcp_engine.formatters import format_bundle

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
    
    params: {text, domain, lesson_type, session_id?, lesson_id?, scene_wl_hash?, scene_graph_vector?, archetype?, progress_score?, valence?}
    """
    text        = params.get("text", "").strip()
    domain      = params.get("domain", "generic").strip()
    lesson_type = params.get("lesson_type", "optimization").strip()
    session_id  = params.get("session_id", "unknown")
    lesson_id   = params.get("lesson_id") or str(uuid.uuid4())
    scene_wl_hash = (params.get("scene_wl_hash") or "").strip() or None
    scene_graph_vector = params.get("scene_graph_vector")
    if scene_graph_vector is not None and not isinstance(scene_graph_vector, str):
        scene_graph_vector = str(scene_graph_vector)
    archetype = (params.get("archetype") or "").strip() or None
    try:
        progress_score = None if params.get("progress_score") is None else float(params.get("progress_score"))
    except Exception:
        progress_score = None
    try:
        valence = None if params.get("valence") is None else float(params.get("valence"))
    except Exception:
        valence = None

    if not text:
        return {"error": "text is required"}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    vector = emb.embed(text, model_name=embedding_model)
    now = datetime.now(timezone.utc).isoformat()

    # KuzuDB 0.11.3: MERGE is incompatible with vector-indexed tables.
    # Use SELECT→CREATE-or-UPDATE instead.
    existing = await db.execute_read(
        "MATCH (l:Lesson {lesson_id: $lid}) RETURN l.lesson_id",
        {"lid": lesson_id},
    )
    if not existing:
        await db.execute_write(
            """
            CREATE (l:Lesson {
                lesson_id:        $lid,
                text_raw:         $text,
                embedding:        $emb,
                embedding_model:  $model,
                embedding_dim:    $dim,
                domain:           $domain,
                lesson_type:      $type,
                scene_wl_hash:    $scene_wl_hash,
                scene_graph_vector: $scene_graph_vector,
                archetype:        $archetype,
                progress_score:   $progress_score,
                valence:          $valence,
                confidence:       0.90,
                confidence_low:   false,
                pathway_strength: 1.0,
                archived:         false,
                created_at:       timestamp($now)
            })
            """,
            {
                "lid":    lesson_id,
                "text":   text,
                "emb":    vector,
                "model":  embedding_model,
                "dim":    len(vector),
                "domain": domain,
                "type":   lesson_type,
                "scene_wl_hash": scene_wl_hash,
                "scene_graph_vector": scene_graph_vector,
                "archetype": archetype,
                "progress_score": progress_score,
                "valence": valence,
                "now":    now,
            }
        )
    else:
        # Update non-embedding fields only (embedding cannot be SET on indexed property)
        await db.execute_write(
            """
            MATCH (l:Lesson {lesson_id: $lid})
            SET l.text_raw         = $text,
                l.domain           = $domain,
                l.lesson_type      = $type,
                l.scene_wl_hash    = $scene_wl_hash,
                l.scene_graph_vector = $scene_graph_vector,
                l.archetype        = $archetype,
                l.progress_score   = $progress_score,
                l.valence          = $valence,
                l.pathway_strength = l.pathway_strength + 0.1
            """,
            {
                "lid":    lesson_id,
                "text":   text,
                "domain": domain,
                "type":   lesson_type,
                "scene_wl_hash": scene_wl_hash,
                "scene_graph_vector": scene_graph_vector,
                "archetype": archetype,
                "progress_score": progress_score,
                "valence": valence,
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
                "scene_wl_hash": node.get("scene_wl_hash"),
                "progress_score": node.get("progress_score"),
                "valence": node.get("valence"),
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


async def recall_scene_graph_priors(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Return evidence-weighted priors for a scene graph signature.

    params: {wl_hash, archetype?, min_valence?, limit?}
    """
    wl_hash = (params.get("wl_hash") or "").strip()
    archetype = (params.get("archetype") or "").strip()
    if not wl_hash:
        return {"expected_progress": 0.0, "median_progress": 0.0, "evidence_count": 0, "priors": []}

    try:
        min_valence = float(params.get("min_valence", 0.0))
    except Exception:
        min_valence = 0.0
    try:
        limit = max(1, int(params.get("limit", 50)))
    except Exception:
        limit = 50

    rows: list[dict] = []
    try:
        result = db.execute(
            "MATCH (l:Lesson) "
            "WHERE l.archived = false AND l.scene_wl_hash = $wl_hash "
            "AND l.progress_score IS NOT NULL "
            "AND (l.valence IS NULL OR l.valence >= $min_valence) "
            "AND ($archetype = '' OR l.archetype = $archetype) "
            "RETURN l.lesson_id, l.progress_score, l.valence, l.archetype, l.text_raw "
            "ORDER BY l.created_at DESC LIMIT $limit",
            {
                "wl_hash": wl_hash,
                "min_valence": min_valence,
                "archetype": archetype,
                "limit": limit,
            },
        )
        while result.has_next():
            row = result.get_next()
            try:
                progress = float(row[1])
            except Exception:
                continue
            progress = max(0.0, min(1.0, progress))
            val = row[2]
            try:
                val = float(val) if val is not None else None
            except Exception:
                val = None
            rows.append(
                {
                    "lesson_id": row[0],
                    "progress_score": progress,
                    "valence": val,
                    "archetype": row[3] or "",
                    "text": row[4] or "",
                }
            )
    except Exception:
        _logger.exception("recall_scene_graph_priors failed")
        return {"expected_progress": 0.0, "median_progress": 0.0, "evidence_count": 0, "priors": []}

    if not rows:
        return {"expected_progress": 0.0, "median_progress": 0.0, "evidence_count": 0, "priors": []}

    progresses = sorted(r["progress_score"] for r in rows)
    expected = sum(progresses) / len(progresses)
    mid = len(progresses) // 2
    median = progresses[mid] if len(progresses) % 2 == 1 else (progresses[mid - 1] + progresses[mid]) / 2.0

    return {
        "expected_progress": round(expected, 4),
        "median_progress": round(median, 4),
        "evidence_count": len(rows),
        "priors": rows,
    }


# ---------------------------------------------------------------------------
# B10 — explore_graph (directed graph traversal)
# ---------------------------------------------------------------------------

# Traversal constants and implementation moved to modular tool file (B10)
from mcp_engine.tools.explore_graph import (
    explore_graph, _TRAVERSABLE_RELS, _NODE_TABLES, _MAX_DEPTH
)
from mcp_engine.tools.task_graph import (
    register_task_graph, get_ready_tasks, advance_task, fail_task, get_task_graph
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
        # Only bind quest_id if it's actually used in the query
        params = {"limit": limit}
        if scope == "branch" and quest_id:
            params["quest_id"] = quest_id
        
        result = db.execute(
            query,
            params
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


async def register_plan(params: dict, db: KuzuClient, config: dict) -> dict:
    """B67: active declaration of a multi-step strategy."""
    goal = (params.get("goal") or "").strip()
    steps = _normalize_steps(params.get("steps") or [])
    strategy = (params.get("strategy") or "").strip()
    session_id = (params.get("session_id") or "unknown").strip() or "unknown"

    if not goal:
        return {"error": "goal is required", "write_ok": False, "error_code": "missing_goal"}
    if not steps:
        return {
            "error": "steps must include at least one non-empty item",
            "write_ok": False,
            "error_code": "missing_steps",
        }

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    now = datetime.now(timezone.utc).isoformat()

    plan_id, step_ids, quest_id = await _create_plan_graph(
        db=db,
        goal=goal,
        steps=steps,
        session_id=session_id,
        embedding_model=embedding_model,
        now_iso=now,
        strategy=strategy,
        source="active",
        confidence=0.90,
        confidence_low=False,
    )

    goal_vec = emb.embed(goal, model_name=embedding_model)
    warnings, suggestions = _plan_feedback_from_similarity(db, goal_vec, plan_id)

    return {
        "status": "registered",
        "write_ok": True,
        "id": plan_id,
        "plan_id": plan_id,
        "step_ids": step_ids,
        "quest_id": quest_id,
        "result_summary": f"plan_id={plan_id} steps={len(step_ids)}",
        "warnings": warnings,
        "suggestions": suggestions,
    }


async def report_outcome(params: dict, db: KuzuClient, config: dict) -> dict:
    """B67/B69: write step-level or plan-level outcome and valence propagation."""
    plan_id = (params.get("plan_id") or "").strip()
    outcome = (params.get("outcome") or "").strip()
    session_id = (params.get("session_id") or "unknown").strip() or "unknown"
    step_number = params.get("step_number")
    valence_source = (params.get("valence_source") or "system").strip() or "system"

    if not plan_id:
        return {"error": "plan_id is required"}
    if not outcome:
        return {"error": "outcome is required"}

    try:
        valence = float(params.get("valence"))
    except Exception:
        return {"error": "valence must be a number between -1.0 and 1.0"}
    valence = _clamp(valence, -1.0, 1.0)

    now = datetime.now(timezone.utc).isoformat()
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    if step_number is not None:
        try:
            step_number = int(step_number)
        except Exception:
            return {"error": "step_number must be an integer when provided"}

        await db.execute_write(
            "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid}) "
            "WHERE ps.step_number = $step_number "
            "SET ps.actual_outcome = $outcome, "
            "    ps.valence = $valence, "
            "    ps.status = $status, "
            "    ps.completed_at = timestamp($now)",
            {
                "pid": plan_id,
                "step_number": step_number,
                "outcome": outcome,
                "valence": valence,
                "status": "succeeded" if valence >= 0 else "failed",
                "now": now,
            },
        )

        if valence < 0:
            await db.execute_write(
                "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid}) "
                "WHERE ps.step_number = $step_number "
                "MATCH (ps)-[:ACTS_ON]->(c:Concept) "
                "MERGE (ps)-[o:OUTCOME_SIGNAL]->(c) "
                "SET o.valence = $valence, o.plan_id = $pid, o.observed_at = timestamp($now)",
                {
                    "pid": plan_id,
                    "step_number": step_number,
                    "valence": valence,
                    "now": now,
                },
            )

        return {"updated": True, "plan_status": "active"}

    await db.execute_write(
        "MATCH (p:Plan {plan_id: $pid}) "
        "SET p.valence = $valence, "
        "    p.valence_source = $valence_source, "
        "    p.status = 'completed', "
        "    p.completed_at = timestamp($now)",
        {
            "pid": plan_id,
            "valence": valence,
            "valence_source": valence_source,
            "now": now,
        },
    )

    lesson_id = await _store_plan_outcome_lesson(
        db,
        plan_id=plan_id,
        outcome=outcome,
        valence=valence,
        session_id=session_id,
        embedding_model=embedding_model,
        now_iso=now,
    )

    # B197: If a procedure was applied during this plan, update its application stats
    procedure_id = (params.get("procedure_id") or None)
    if procedure_id:
        try:
            success = None
            if params.get("procedure_success") is not None:
                success = bool(params.get("procedure_success"))
            else:
                success = valence >= 0

            # Create APPLIED_PROCEDURE edge and update counters
            await db.execute_write(
                "MATCH (p:Plan {plan_id: $pid}), (pr:Procedure {procedure_id: $proc_id}) "
                "MERGE (p)-[r:APPLIED_PROCEDURE]->(pr) "
                "SET r.success = $success, r.applied_at = timestamp($now)",
                {"pid": plan_id, "proc_id": procedure_id, "success": success, "now": now},
            )

            await db.execute_write(
                "MATCH (pr:Procedure {procedure_id: $proc_id}) "
                "SET pr.application_count = coalesce(pr.application_count, 0) + 1, "
                "    pr.success_count = coalesce(pr.success_count, 0) + CASE WHEN $success THEN 1 ELSE 0 END, "
                "    pr.last_applied_at = timestamp($now)",
                {"proc_id": procedure_id, "success": success, "now": now},
            )

            await db.execute_write(
                "MATCH (pr:Procedure {procedure_id: $proc_id}) "
                "SET pr.success_rate = CASE WHEN coalesce(pr.application_count,0) > 0 "
                "THEN toFloat(coalesce(pr.success_count,0)) / toFloat(pr.application_count) ELSE 0.0 END",
                {"proc_id": procedure_id},
            )
        except Exception:
            _logger.exception("Failed to update Procedure stats for %s", procedure_id)
    return {
        "updated": True,
        "plan_status": "completed",
        "lesson_id": lesson_id,
    }


async def recall_plans(params: dict, db: KuzuClient, config: dict) -> dict:
    """B67: retrieve historical plan chains by goal similarity."""
    goal_query = (params.get("goal_query") or "").strip()
    if not goal_query:
        return {"plans": []}

    limit = int(params.get("limit", 5))
    min_valence = float(params.get("min_valence", 0.0))
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    query_vec = emb.embed(goal_query, model_name=embedding_model)

    try:
        rows = db.vector_search("Plan", "plan_emb_idx", query_vec, max(limit * 4, 12))
    except Exception:
        return {"plans": []}

    scored: list[dict] = []
    for row in rows:
        node = _safe_result_dict(row.get("node", {}))
        pid = node.get("plan_id")
        if not pid:
            continue

        valence = node.get("valence")
        if valence is None:
            continue
        valence = float(valence)
        if valence < min_valence:
            continue

        similarity = float(row.get("score", 0.0) or 0.0)
        pathway_strength = float(node.get("pathway_strength", 1.0) or 1.0)
        score = similarity * abs(valence) * max(pathway_strength, 0.1)

        steps: list[dict] = []
        try:
            rs = db.execute(
                "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid}) "
                "RETURN ps.step_number, ps.description, ps.valence, ps.status "
                "ORDER BY ps.step_number ASC",
                {"pid": pid},
            )
            while rs.has_next():
                sr = rs.get_next()
                steps.append(
                    {
                        "step_number": int(sr[0]),
                        "description": sr[1] or "",
                        "valence": sr[2],
                        "status": sr[3] or "pending",
                    }
                )
        except Exception:
            pass

        scored.append(
            {
                "plan_id": pid,
                "goal": node.get("goal", ""),
                "valence": valence,
                "similarity": round(similarity, 4),
                "pathway_strength": pathway_strength,
                "steps": steps,
                "_score": score,
            }
        )

    scored.sort(key=lambda p: p["_score"], reverse=True)
    plans = scored[:max(limit, 1)]
    for plan in plans:
        plan.pop("_score", None)
    return {"plans": plans}


async def recall_procedures(params: dict, db: KuzuClient, config: dict) -> dict:
    """B194: Retrieve applicable Procedure templates for an archetype or query."""
    archetype = (params.get("archetype") or "").strip()
    query = (params.get("query") or "").strip()
    limit = int(params.get("limit", 3))

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    results: list[dict] = []
    try:
        if archetype:
            r = db.execute(
                "MATCH (p:Procedure) WHERE p.archived = false AND p.archetype = $arch "
                "RETURN p.procedure_id, p.name, p.description, p.steps_json, p.success_count, p.success_rate "
                "ORDER BY p.success_rate DESC, p.success_count DESC LIMIT $lim",
                {"arch": archetype, "lim": limit},
            )
            while r.has_next():
                row = r.get_next()
                results.append({
                    "procedure_id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "steps_json": row[3],
                    "success_count": row[4],
                    "success_rate": row[5],
                })
            return {"procedures": results}

        if query:
            qvec = emb.embed(query, model_name=embedding_model)
            neighbors = db.vector_search("Procedure", "procedure_emb_idx", qvec, limit)
            for item in neighbors:
                node = _safe_result_dict(item.get("node", {}))
                results.append({
                    "procedure_id": node.get("procedure_id"),
                    "name": node.get("name"),
                    "description": node.get("description"),
                    "steps_json": node.get("steps_json"),
                    "similarity": float(item.get("score", 0.0) or 0.0),
                })
            return {"procedures": results}

    except Exception:
        _logger.exception("recall_procedures failed")

    return {"procedures": []}


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
# B235: Memory Decision Helper
# ---------------------------------------------------------------------------

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
    from mcp_engine.memory_decision import decide_memory_action

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
# Dispatch table
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "notify_turn":      notify_turn,
    "current_truth":    current_truth,
    "branch_quest":     branch_quest,
    "complete_quest":   complete_quest,
    "diff_since":       diff_since,
    "reconstruct_timeline": reconstruct_timeline,  # B192
    "get_open_loops":   get_open_loops,
    "ingest_document":  ingest_document,
    "ingest_data":      ingest_data,            # B251
    "compile_context":  compile_context,        # B252
    "analogical_search": analogical_search,
    "explore_graph":    explore_graph,
    "set_quest":        set_quest,
    "context_status":   context_status,
    "get_anomalies":    get_anomalies,           # B12
    "upsert_lesson":    upsert_lesson,           # B11
    "recall_relevant_lessons": recall_relevant_lessons,  # B11
    "recall_scene_graph_priors": recall_scene_graph_priors,  # A050 sibling
    "get_openclaw_prompt": get_openclaw_prompt,  # B21
    "register_plan":   register_plan,            # B67
    "report_outcome":  report_outcome,           # B67/B69
    "recall_plans":    recall_plans,             # B67
    "recall_procedures": recall_procedures,     # B194
    "get_knowledge_gaps": get_knowledge_gaps,   # B193
    "register_task_graph": register_task_graph,  # B128
    "get_ready_tasks":     get_ready_tasks,      # B128
    "advance_task":        advance_task,         # B128
    "fail_task":           fail_task,            # B128
    "get_task_graph":      get_task_graph,       # B128
    "get_disambiguation_queue": get_disambiguation_queue,  # B158
    "resolve_disambiguation": resolve_disambiguation,      # B158
    "reload_domain_dictionary": reload_domain_dictionary,  # B160
    "ingest_arc_artifacts": ingest_arc_artifacts,  # B225
    "publish_mechanic_summary": publish_mechanic_summary,  # B226
    "recall_mechanic_priors": recall_mechanic_priors,      # B227
    "memory_decision": memory_decision,          # B235
}
