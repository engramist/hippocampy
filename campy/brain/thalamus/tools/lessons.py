"""Planning primitives and lesson/procedure memory handlers."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.provenance import provenance_fields
from campy.brain.hippocampus.schema import upsert_agent_worker_and_link

from ._shared import (
    _CONCEPT_INDEX,
    _LESSON_INDEX,
    _PLAN_INDEX,
    _logger,
    _safe_result_dict,
)

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient



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
    capture_source: str | None = None,
    evidence_ref: str | None = None,
) -> tuple[str, list[str], str]:
    """Create Plan + PlanStep chain and basic relationships.

    B312: `capture_source`/`evidence_ref` are the primary-capture-path
    provenance identifiers (e.g. "agent:claude-code" / a message_id). When
    omitted (the default — every caller other than capture.py's
    notify_turn), all four provenance columns stay NULL, matching prior
    behavior. Note `source` here is Plan's pre-existing "plan origin"
    field ("active"/"passive") — a different, narrower concept than the
    B312 provenance `source` column, which PlanStep gets but Plan does not
    (Plan already had a `source` column before this card; see schema.py).
    """
    plan_id = str(uuid.uuid4())
    step_ids = [str(uuid.uuid4()) for _ in steps]
    goal_vec = emb.embed(goal, model_name=embedding_model)

    prov = (
        provenance_fields(source=capture_source, evidence_ref=evidence_ref)
        if capture_source
        else {"source": None, "source_version": None, "observed_at": None, "evidence_ref": None}
    )

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
            rows = db.vector_search("Concept", _CONCEPT_INDEX, step_vec, 5)
            for row in rows:
                # B279: ACTS_ON links require true cosine similarity >= 0.75.
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
                completed_at: NULL,
                source_version: $prov_source_version,
                observed_at: timestamp($prov_observed_at),
                evidence_ref: $prov_evidence_ref
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
                "prov_source_version": prov["source_version"],
                "prov_observed_at": prov["observed_at"],
                "prov_evidence_ref": prov["evidence_ref"],
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
                    completed_at: NULL,
                    source: $prov_source,
                    source_version: $prov_source_version,
                    observed_at: timestamp($prov_observed_at),
                    evidence_ref: $prov_evidence_ref
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
                    "prov_source": prov["source"],
                    "prov_source_version": prov["source_version"],
                    "prov_observed_at": prov["observed_at"],
                    "prov_evidence_ref": prov["evidence_ref"],
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
        candidates = db.vector_search("Plan", _PLAN_INDEX, goal_vec, 12)
    except Exception:
        return warnings, suggestions

    for item in candidates:
        node = _safe_result_dict(item.get("node", {}))
        pid = node.get("plan_id", "")
        if not pid or pid == exclude_plan_id:
            continue

        similarity = float(item.get("score", 0.0) or 0.0)
        # B279: warnings/suggestions only consider true cosine similarity > 0.75.
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
                                     embedding_model: str, now_iso: str,
                                     trigger_signals: list[str] | None = None,
                                     capture_source: str | None = None,
                                     evidence_ref: str | None = None) -> str | None:
    """Create a Lesson and connect it to the Plan when |valence| is strong.

    B312: `capture_source`/`evidence_ref` populate provenance when this is
    called from the primary capture path (capture.py's notify_turn). Other
    callers (e.g. quests.py's report_outcome) omit them and the Lesson's
    provenance columns stay NULL, matching prior behavior.
    """
    if abs(valence) <= 0.7:
        return None

    lesson_text = f"Plan outcome ({'success' if valence > 0 else 'failure'}): {outcome.strip()}"
    # B301: record which signal(s) drove the polarity so a system-labeled
    # outcome is auditable from the Lesson node itself.
    if trigger_signals:
        lesson_text += f"\n[valence_trigger: {', '.join(trigger_signals)}]"
    lesson_id = str(uuid.uuid4())
    vec = emb.embed(lesson_text, model_name=embedding_model)

    prov = (
        provenance_fields(source=capture_source, evidence_ref=evidence_ref)
        if capture_source
        else {"source": None, "source_version": None, "observed_at": None, "evidence_ref": None}
    )

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
            created_at: timestamp($created_at),
            source: $prov_source,
            source_version: $prov_source_version,
            observed_at: timestamp($prov_observed_at),
            evidence_ref: $prov_evidence_ref
        })
        """,
        {
            "lesson_id": lesson_id,
            "text_raw": lesson_text,
            "embedding": vec,
            "embedding_model": embedding_model,
            "embedding_dim": len(vec),
            "created_at": now_iso,
            "prov_source": prov["source"],
            "prov_source_version": prov["source_version"],
            "prov_observed_at": prov["observed_at"],
            "prov_evidence_ref": prov["evidence_ref"],
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

    # B323: derive AgentWorker + SOLVED_BY in the same write that set this
    # Lesson's B312 provenance (prov["source"]) — never as a separate pass.
    # No-ops when capture_source is None/"user:direct" (see
    # upsert_agent_worker_and_link's docstring).
    try:
        await upsert_agent_worker_and_link(
            db,
            worker_id=prov["source"],
            node_table="Lesson",
            node_id=lesson_id,
            observed_at=prov["observed_at"],
        )
    except Exception:
        _logger.exception("B323: SOLVED_BY link failed for lesson %s", lesson_id)

    return lesson_id


async def _synthesize_lesson(quest_id: str, db, config: dict) -> None:
    """
    Background coroutine: synthesize a Lesson node from quest artifacts.

    1. Query the top confirmed artifacts linked to this quest
    2. Ask LLM to synthesize the hardest obstacle and key lesson
    3. Store as Lesson node (confidence_low=true) + PRODUCED_LESSON edge
    """
    try:
        from campy.brain.llm.provider import create_llm_client
        from campy.brain.hippocampus.graph import embeddings as emb

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
    
    params: {text, domain, lesson_type, session_id?, lesson_id?, scene_wl_hash?, scene_graph_vector?, archetype?, progress_score?, valence?, trigger?}
    trigger is an optional dict: {pattern, hook_type, tool, project_scope}
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

    # Phase 2: Associative Hooks — trigger metadata
    trigger_meta = params.get("trigger") or {}
    trigger_pattern = (trigger_meta.get("pattern") or "").strip() or None
    trigger_hook_type = (trigger_meta.get("hook_type") or "").strip() or None
    trigger_tool = (trigger_meta.get("tool") or "").strip() or None
    trigger_project_scope = (trigger_meta.get("project_scope") or "").strip() or None
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

    # B312: upsert_lesson is one of the two named primary-capture-path
    # write sites (the other is capture.py's notify_turn). `source`
    # defaults from the caller's agent_source using the same "agent:<id>"
    # convention already used elsewhere (see capture.py / work_summary.py);
    # `evidence_ref` defaults to the session_id being processed. Explicit
    # params always win.
    agent_source = (params.get("agent_source") or "mcp").strip()
    prov_source = (params.get("source") or f"agent:{agent_source}").strip()
    prov_source_version = params.get("source_version")
    prov_evidence_ref = params.get("evidence_ref") or (
        session_id if session_id != "unknown" else None
    )
    prov = provenance_fields(
        source=prov_source,
        source_version=prov_source_version,
        evidence_ref=prov_evidence_ref,
    )

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
                created_at:       timestamp($now),
                trigger_pattern:       $trig_pattern,
                trigger_hook_type:     $trig_hook_type,
                trigger_tool:          $trig_tool,
                trigger_project_scope: $trig_scope,
                source:                $prov_source,
                source_version:        $prov_source_version,
                observed_at:           timestamp($prov_observed_at),
                evidence_ref:          $prov_evidence_ref
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
                "trig_pattern": trigger_pattern,
                "trig_hook_type": trigger_hook_type,
                "trig_tool": trigger_tool,
                "trig_scope": trigger_project_scope,
                "prov_source": prov["source"],
                "prov_source_version": prov["source_version"],
                "prov_observed_at": prov["observed_at"],
                "prov_evidence_ref": prov["evidence_ref"],
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
                l.pathway_strength = l.pathway_strength + 0.1,
                l.trigger_pattern       = $trig_pattern,
                l.trigger_hook_type     = $trig_hook_type,
                l.trigger_tool          = $trig_tool,
                l.trigger_project_scope = $trig_scope,
                l.source                = $prov_source,
                l.source_version        = $prov_source_version,
                l.observed_at           = timestamp($prov_observed_at),
                l.evidence_ref          = $prov_evidence_ref
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
                "trig_pattern": trigger_pattern,
                "trig_hook_type": trigger_hook_type,
                "trig_tool": trigger_tool,
                "trig_scope": trigger_project_scope,
                "prov_source": prov["source"],
                "prov_source_version": prov["source_version"],
                "prov_observed_at": prov["observed_at"],
                "prov_evidence_ref": prov["evidence_ref"],
            }
        )

    if session_id != "unknown":
        await db.execute_write(
            "MATCH (s:Session {session_id: $sid}), (l:Lesson {lesson_id: $lid}) "
            "MERGE (s)-[:LEARNED]->(l)",
            {"sid": session_id, "lid": lesson_id}
        )

    # B323: derive AgentWorker + SOLVED_BY in the same write that set this
    # Lesson's B312 provenance (prov_source, which defaults to
    # "agent:<agent_source>" above) — never as a separate capture pass.
    try:
        await upsert_agent_worker_and_link(
            db,
            worker_id=prov["source"],
            node_table="Lesson",
            node_id=lesson_id,
            observed_at=prov["observed_at"],
        )
    except Exception:
        _logger.exception("B323: SOLVED_BY link failed for lesson %s", lesson_id)

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
        rows = db.vector_search("Lesson", _LESSON_INDEX, vector, limit)
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
