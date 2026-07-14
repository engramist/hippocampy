"""Quest, planning lifecycle, and review/ops handlers."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.thalamus.tools.task_graph import (
    advance_task,
    fail_task,
    get_ready_tasks,
    get_task_graph,
    register_task_graph,
)

from ._shared import (
    _PLAN_INDEX,
    _PROCEDURE_INDEX,
    _clamp,
    _logger,
    _normalize_steps,
    _safe_result_dict,
    create_side_quest,
)
from .lessons import (
    _create_plan_graph,
    _plan_feedback_from_similarity,
    _store_plan_outcome_lesson,
    _synthesize_lesson,
)

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient



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
        from campy.brain.hippocampus.quest import compute_quest_id
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
        from campy.brain.hippocampus.hippocampus import create_new_quest
        content_embedding = emb.embed(quest_name, model_name=embedding_model)
        found_id = await create_new_quest(
            db, quest_name, content_embedding, embedding_model
        )

    # Bind session with locked state
    from campy.brain.hippocampus.hippocampus import _bind_session
    await _bind_session(db, session_id, found_id, 1.0, "explicit", "locked")

    return {"quest_id": found_id, "quest_name": quest_name, "routing_state": "locked"}


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
        trigger_signals=params.get("trigger_signals"),
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
        rows = db.vector_search("Plan", _PLAN_INDEX, query_vec, max(limit * 4, 12))
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
            neighbors = db.vector_search("Procedure", _PROCEDURE_INDEX, qvec, limit)
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
