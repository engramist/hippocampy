"""ARC-specific MCP query tools for Agent v2.

These handlers stay on the existing ARC schema surface and return compact,
predictable dictionaries for the ARC-side adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _first_row(result: Any) -> Any:
    if result is None:
        return None
    try:
        if result.has_next():
            return result.get_next()
    except Exception:
        return None
    return None


def _iter_rows(result: Any) -> Iterable[Any]:
    if result is None:
        return []
    while True:
        try:
            if not result.has_next():
                return
            yield result.get_next()
        except Exception:
            return


def _row_get(row: Any, key: str, index: int, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[index]
    except Exception:
        return default


def _error(message: str) -> dict:
    return {"ok": False, "error": message}


async def arc_perceive_state(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    step = params.get("step")
    if not task_id:
        return _error("task_id is required")
    if step is None:
        return _error("step is required")

    entities = params.get("entities") or []
    snapshot_id = f"{task_id}_step{step}"

    await db.execute_write(
        "MERGE (s:GridSnapshot {snapshot_id: $sid}) "
        "SET s.task_id = $tid, s.step = $step, s.grid_hash = $hash, "
        "    s.n_entities = $n, s.created_at = current_timestamp()",
        {
            "sid": snapshot_id,
            "tid": task_id,
            "step": step,
            "hash": params.get("grid_hash", ""),
            "n": len(entities),
        },
    )

    for ent in entities:
        entity_id = f"{task_id}_e{ent.get('color_id', 0)}_{ent.get('region_index', 0)}"
        await db.execute_write(
            "MERGE (e:GridEntity {entity_id: $eid}) "
            "SET e.task_id = $tid, e.color_id = $cid, "
            "    e.centroid_row = $cr, e.centroid_col = $cc, "
            "    e.pixel_count = $pc, e.inferred_role = $role, "
            "    e.last_updated_step = $step",
            {
                "eid": entity_id,
                "tid": task_id,
                "cid": ent.get("color_id"),
                "cr": ent.get("centroid_row"),
                "cc": ent.get("centroid_col"),
                "pc": ent.get("pixel_count"),
                "role": ent.get("role", "unknown"),
                "step": step,
            },
        )

    effect_id = None
    if params.get("action_taken"):
        effect_id = f"{task_id}_step{step}_effect"
        effect = params.get("effect") or {}
        await db.execute_write(
            "MERGE (ae:ActionEffect {effect_id: $eid}) "
            "SET ae.task_id = $tid, ae.action_id = $aid, ae.step = $step, "
            "    ae.n_cells_changed = $ncc, ae.apparent_effect = $eff",
            {
                "eid": effect_id,
                "tid": task_id,
                "aid": params["action_taken"],
                "step": step,
                "ncc": effect.get("n_cells_changed", 0),
                "eff": effect.get("apparent_effect", "unknown"),
            },
        )

    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "entity_count": len(entities),
        "delta_from_previous": None,
        "action_taken": params.get("action_taken"),
        "effect_id": effect_id,
    }


async def arc_get_game_context(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    if not task_id:
        return _error("task_id is required")

    hyp_result = db.execute(
        "MATCH (h:Hypothesis {task_id: $tid}) WHERE h.status = 'active' RETURN count(h)",
        {"tid": task_id},
    )
    hyp_row = _first_row(hyp_result)
    hyp_count = _safe_int(_row_get(hyp_row, "count(h)", 0, 0))

    step_result = db.execute(
        "MATCH (s:GridSnapshot {task_id: $tid}) RETURN max(s.step)",
        {"tid": task_id},
    )
    step_row = _first_row(step_result)
    latest_step = _safe_int(_row_get(step_row, "max(s.step)", 0, 0))

    action_result = db.execute(
        "MATCH (af:ActionFact {task_id: $tid}) RETURN af.action_id, af.value_status, af.confidence",
        {"tid": task_id},
    )
    actions: dict[str, dict] = {}
    for row in _iter_rows(action_result):
        action_id = _row_get(row, "af.action_id", 0, "") or ""
        if not action_id:
            continue
        actions[action_id] = {
            "value_status": _row_get(row, "af.value_status", 1, "unknown") or "unknown",
            "confidence": _safe_float(_row_get(row, "af.confidence", 2, 0.0)),
        }

    return {
        "hypothesis_count": hyp_count,
        "step": latest_step,
        "action_summary": actions,
        "goal": None,
        "progress_trend": "unknown",
    }


async def arc_get_action_evidence(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    action_id = params.get("action_id")
    if not task_id:
        return _error("task_id is required")
    if not action_id:
        return _error("action_id is required")

    result = db.execute(
        "MATCH (af:ActionFact {task_id: $tid, action_id: $aid}) "
        "RETURN af.fact_type, af.confidence, af.value_status, af.evidence_count, "
        "af.observation_count, COALESCE(af.falsified_count, 0)",
        {"tid": task_id, "aid": action_id},
    )

    row = _first_row(result)
    if row is None:
        return {
            "tested": False,
            "action_id": action_id,
            "fact_type": None,
            "confidence": 0.0,
            "value_status": "untested",
            "evidence_count": 0,
            "steps_used": 0,
            "falsified_count": 0,
            "causal_power": 0.0,
        }

    confidence = _safe_float(_row_get(row, "af.confidence", 1, 0.0))
    value_status = _row_get(row, "af.value_status", 2, "unknown") or "unknown"
    observation_count = _safe_int(_row_get(row, "af.observation_count", 4, 0))
    # B278: read the explicit falsification counter (not derived from status).
    falsified_count = _safe_int(_row_get(row, "falsified_count", 5, 0))
    return {
        "tested": True,
        "action_id": action_id,
        "fact_type": _row_get(row, "af.fact_type", 0, None),
        "confidence": confidence,
        "value_status": value_status,
        "evidence_count": _safe_int(_row_get(row, "af.evidence_count", 3, 0)),
        "steps_used": observation_count,
        "falsified_count": falsified_count,
        "causal_power": confidence,
    }


async def arc_get_untested_actions(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    if not task_id:
        return _error("task_id is required")

    available = params.get("available_actions") or []
    result = db.execute(
        "MATCH (af:ActionFact {task_id: $tid}) RETURN DISTINCT af.action_id",
        {"tid": task_id},
    )
    tested: list[str] = []
    tested_set: set[str] = set()
    for row in _iter_rows(result):
        action_id = _row_get(row, "af.action_id", 0, None)
        if action_id and action_id not in tested_set:
            tested.append(action_id)
            tested_set.add(action_id)

    untested = [action for action in available if action not in tested_set]
    return {"untested": untested, "tested": tested}


async def arc_get_causal_path(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    action_id = params.get("action_id")
    goal_id = params.get("goal_id")
    if not task_id:
        return _error("task_id is required")
    if not action_id:
        return _error("action_id is required")

    # B278: explicit relationship types with fixed-length hops — no
    # variable-length (`*N..M`) traversal, so the path cost stays bounded
    # and predictable. count(af) avoids `count(*)` (which would read as a
    # wildcard) while counting matched paths identically.
    if goal_id:
        query = (
            "MATCH (af:ActionFact {task_id: $tid, action_id: $aid})-[:DERIVED_FROM_FACT]->(ae:ActionEffect)"
            "<-[:MOVED_BY]-(ge:GridEntity)-[:REQUIRES_ENTITY]-(vc:VictoryCondition {task_id: $tid, condition_id: $gid}) "
            "RETURN count(af) as path_count, min(vc.confidence) as min_conf"
        )
        params_map = {"tid": task_id, "aid": action_id, "gid": goal_id}
    else:
        query = (
            "MATCH (af:ActionFact {task_id: $tid, action_id: $aid})-[:DERIVED_FROM_FACT]->(ae:ActionEffect)"
            "<-[:MOVED_BY]-(ge:GridEntity)-[:REQUIRES_ENTITY]-(vc:VictoryCondition {task_id: $tid}) "
            "RETURN count(af) as path_count, min(vc.confidence) as min_conf"
        )
        params_map = {"tid": task_id, "aid": action_id}

    result = db.execute(query, params_map)
    row = _first_row(result)
    path_count = _safe_int(_row_get(row, "path_count", 0, 0))
    return {
        "path_exists": path_count > 0,
        "path_length": 4 if path_count > 0 else 0,
        "path_confidence": _safe_float(_row_get(row, "min_conf", 1, 0.0)),
    }


async def arc_record_action_effect(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    action_id = params.get("action_id")
    step = params.get("step")
    if not task_id:
        return _error("task_id is required")
    if not action_id:
        return _error("action_id is required")
    if step is None:
        return _error("step is required")

    effect = params.get("effect") or {}
    effect_id = f"{task_id}_{action_id}_step{step}"
    await db.execute_write(
        "MERGE (ae:ActionEffect {effect_id: $eid}) "
        "SET ae.task_id = $tid, ae.action_id = $aid, ae.step = $step, "
        "    ae.n_cells_changed = $ncc, ae.apparent_effect = $eff, ae.created_at = current_timestamp()",
        {
            "eid": effect_id,
            "tid": task_id,
            "aid": action_id,
            "step": step,
            "ncc": effect.get("n_cells_changed", 0),
            "eff": effect.get("apparent_effect", "unknown"),
        },
    )

    fact_id = f"{task_id}_{action_id}"
    await db.execute_write(
        "MERGE (af:ActionFact {fact_id: $fid}) "
        "SET af.task_id = $tid, af.action_id = $aid, "
        "    af.observation_count = coalesce(af.observation_count, 0) + 1, "
        "    af.last_updated = current_timestamp()",
        {"fid": fact_id, "tid": task_id, "aid": action_id},
    )

    return {"ok": True, "status": "ok", "fact_id": fact_id, "effect_id": effect_id}


async def arc_get_entity_movement(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    step = params.get("step")
    if not task_id:
        return _error("task_id is required")
    if step is None:
        return _error("step is required")

    result = db.execute(
        "MATCH (ge:GridEntity {task_id: $tid})-[m:MOVED_BY]->(ae:ActionEffect {step: $step}) "
        "RETURN ge.entity_id, m.delta_row, m.delta_col",
        {"tid": task_id, "step": step},
    )

    entities = []
    for row in _iter_rows(result):
        delta_row = _safe_float(_row_get(row, "m.delta_row", 1, 0))
        delta_col = _safe_float(_row_get(row, "m.delta_col", 2, 0))
        # Derive distance_delta from row/col deltas (negative = moved closer to origin)
        import math
        distance_delta = math.sqrt(delta_row ** 2 + delta_col ** 2) if (delta_row or delta_col) else 0.0
        entities.append(
            {
                "id": _row_get(row, "ge.entity_id", 0, None),
                "delta_row": delta_row,
                "delta_col": delta_col,
                "moved_toward_goal": False,  # Requires goal position context to compute
                "distance_delta": round(distance_delta, 4),
            }
        )

    return {"entities": entities}


async def arc_get_goal_evidence(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    if not task_id:
        return _error("task_id is required")

    result = db.execute(
        "MATCH (vc:VictoryCondition {task_id: $tid}) "
        "OPTIONAL MATCH (vc)<-[s:INFERRED_FROM]-(h:Hypothesis) "
        "RETURN vc.condition_id, vc.condition_type, vc.confidence, "
        "       count(CASE WHEN h.status = 'active' THEN 1 END) as supports, "
        "       count(CASE WHEN h.status = 'demoted' THEN 1 END) as contradicts",
        {"tid": task_id},
    )

    goals = []
    for row in _iter_rows(result):
        goals.append(
            {
                "id": _row_get(row, "vc.condition_id", 0, None),
                "type": _row_get(row, "vc.condition_type", 1, None),
                "confidence": _safe_float(_row_get(row, "vc.confidence", 2, 0.0)),
                "supports": _safe_int(_row_get(row, "supports", 3, 0)),
                "contradicts": _safe_int(_row_get(row, "contradicts", 4, 0)),
            }
        )

    return {"goals": goals}


async def arc_classify_game_archetype(params: dict, db: KuzuClient, config: dict) -> dict:
    features = params.get("grid_features") or {}
    query_text = f"grid game {features.get('n_colors', 0)} colors {features.get('symmetry', 'none')} symmetry"
    try:
        from campy.brain.hippocampus.graph.embeddings import embed

        vector = embed(query_text)
        search = getattr(db, "vector_search", None)
        if search is None:
            return {"archetype": "unknown", "confidence": 0.0, "matching_concepts": []}
        results = search("Concept", "concept_embedding", vector, limit=3)
        concepts = []
        for row in results or []:
            node = row.get("node", {}) if isinstance(row, dict) else {}
            concepts.append({"name": node.get("text_raw", ""), "confidence": row.get("score", 0.0) if isinstance(row, dict) else 0.0})
        archetype = concepts[0]["name"] if concepts else "unknown"
        confidence = _safe_float(concepts[0]["confidence"] if concepts else 0.0)
        return {"archetype": archetype, "confidence": confidence, "matching_concepts": concepts}
    except Exception:
        return {"archetype": "unknown", "confidence": 0.0, "matching_concepts": []}


async def arc_confirm_hypothesis(params: dict, db: KuzuClient, config: dict) -> dict:
    hypothesis_id = params.get("hypothesis_id")
    if not hypothesis_id:
        return _error("hypothesis_id is required")

    evidence = params.get("evidence") or {}
    boost = min(0.1, _safe_float(evidence.get("weight"), 1.0) * 0.05)
    await db.execute_write(
        "MATCH (h:Hypothesis) WHERE h.id = $hid "
        "SET h.evidence_count = coalesce(h.evidence_count, 0) + 1, "
        "    h.confidence = CASE WHEN coalesce(h.confidence, 0.5) + $boost > 1.0 THEN 1.0 "
        "                        ELSE coalesce(h.confidence, 0.5) + $boost END",
        {"hid": hypothesis_id, "boost": boost},
    )

    result = db.execute(
        "MATCH (h:Hypothesis) WHERE h.id = $hid RETURN h.confidence",
        {"hid": hypothesis_id},
    )
    row = _first_row(result)
    new_confidence = _safe_float(_row_get(row, "h.confidence", 0, 0.0))
    return {"status": "ok", "hypothesis_id": hypothesis_id, "new_confidence": new_confidence, "falsified": False}


async def arc_contradict_hypothesis(params: dict, db: KuzuClient, config: dict) -> dict:
    hypothesis_id = params.get("hypothesis_id")
    if not hypothesis_id:
        return _error("hypothesis_id is required")

    evidence = params.get("evidence") or {}
    penalty = min(0.15, _safe_float(evidence.get("weight"), 1.0) * 0.1)
    await db.execute_write(
        "MATCH (h:Hypothesis) WHERE h.id = $hid "
        "SET h.evidence_count = coalesce(h.evidence_count, 0) + 1, "
        "    h.confidence = CASE WHEN coalesce(h.confidence, 0.5) - $penalty < 0.0 THEN 0.0 "
        "                        ELSE coalesce(h.confidence, 0.5) - $penalty END",
        {"hid": hypothesis_id, "penalty": penalty},
    )

    result = db.execute(
        "MATCH (h:Hypothesis) WHERE h.id = $hid RETURN h.confidence, h.status",
        {"hid": hypothesis_id},
    )
    row = _first_row(result)
    new_confidence = _safe_float(_row_get(row, "h.confidence", 0, 0.0))
    falsified = new_confidence < 0.1
    if falsified:
        await db.execute_write(
            "MATCH (h:Hypothesis) WHERE h.id = $hid SET h.status = 'demoted'",
            {"hid": hypothesis_id},
        )
    return {"status": "ok", "hypothesis_id": hypothesis_id, "new_confidence": new_confidence, "falsified": falsified}


async def arc_update_goal_confidence(params: dict, db: KuzuClient, config: dict) -> dict:
    goal_id = params.get("goal_id")
    if not goal_id:
        return _error("goal_id is required")

    new_confidence = _safe_float(params.get("new_confidence"), 0.0)
    has_progress = bool(params.get("has_meaningful_progress", False))
    current_result = db.execute(
        "MATCH (vc:VictoryCondition {condition_id: $gid}) RETURN vc.confidence",
        {"gid": goal_id},
    )
    current_row = _first_row(current_result)
    current = _safe_float(_row_get(current_row, "vc.confidence", 0, 0.0))
    gated_confidence = new_confidence
    if gated_confidence > current and not has_progress:
        gated_confidence = current

    await db.execute_write(
        "MATCH (vc:VictoryCondition {condition_id: $gid}) SET vc.confidence = $conf",
        {"gid": goal_id, "conf": gated_confidence},
    )

    return {"status": "ok", "goal_id": goal_id, "gated_confidence": gated_confidence}


async def arc_get_mechanic_priors(params: dict, db: KuzuClient, config: dict) -> dict:
    result = db.execute(
        "MATCH (m:ArcMechanic)-[:ARC_MECHANIC_HAS_ACTION_PATTERN]->(ap:ArcActionPattern) "
        "WHERE m.confidence > 0.3 "
        "RETURN m.mechanic_id, m.name, m.confidence, ap.signature, ap.action_set "
        "ORDER BY m.confidence DESC LIMIT 5",
        {},
    )

    mechanics = []
    for row in _iter_rows(result):
        mechanics.append(
            {
                "id": _row_get(row, "m.mechanic_id", 0, None),
                "name": _row_get(row, "m.name", 1, None),
                "confidence": _safe_float(_row_get(row, "m.confidence", 2, 0.0)),
                "action_signature": _row_get(row, "ap.signature", 3, None),
                "action_set": _row_get(row, "ap.action_set", 4, None),
            }
        )

    return {"mechanics": mechanics}


async def arc_check_action_gate(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    action_id = params.get("action_id")
    available = params.get("available_actions") or []
    if not task_id:
        return _error("task_id is required")
    if not action_id:
        return _error("action_id is required")

    result = db.execute(
        "MATCH (af:ActionFact {task_id: $tid, action_id: $aid}) "
        "RETURN af.confidence, af.value_status, COALESCE(af.falsified_count, 0), "
        "af.observation_count",
        {"tid": task_id, "aid": action_id},
    )
    row = _first_row(result)
    falsification_count = 0
    if row is not None:
        # B278: read the explicit falsification counter at index 2.
        falsification_count = _safe_int(_row_get(row, "falsified_count", 2, 0))

    untested_result = await arc_get_untested_actions({"task_id": task_id, "available_actions": available}, db, config)
    untested_available = len(untested_result.get("untested", [])) > 0

    go = True
    reason = "approved"
    if falsification_count >= 3 and untested_available:
        go = False
        reason = f"{action_id} falsified {falsification_count} times, untested alternatives exist"

    try:
        from campy.brain.basal_ganglia.action_selector import check_action_gate as general_gate

        general_result = await general_gate(db, action_id, task_id, domain="arc")
        if general_result.get("decision") == "no_go" and go:
            go = False
            reason = general_result.get("reason", "basal_ganglia_no_go")
    except Exception:
        pass

    return {
        "go": go,
        "reason": reason,
        "falsification_count": falsification_count,
        "reward_prediction_error": 0,
        "untested_available": untested_available,
    }


async def arc_record_reward_prediction_error(params: dict, db: KuzuClient, config: dict) -> dict:
    task_id = params.get("task_id")
    action_id = params.get("action_id")
    if not task_id:
        return _error("task_id is required")
    if not action_id:
        return _error("action_id is required")

    predicted = _safe_float(params.get("predicted_reward"), 0.0)
    actual = _safe_float(params.get("actual_reward"), 0.0)
    # Round to avoid float-noise (0.8 - 0.2 = 0.6000000000000001).
    error = round(actual - predicted, 6)

    fact_id = f"{task_id}_{action_id}"
    # ActionFact doesn't have RPE columns — update confidence and value_status instead.
    if error < -0.3:
        # Large negative RPE → reduce confidence, mark uncertain, and bump the
        # explicit falsification counter (B278). This is what closes the
        # evidence loop: a falsified action's count climbs here and is read
        # back by arc_check_action_gate / arc_get_action_evidence.
        await db.execute_write(
            "MATCH (af:ActionFact {fact_id: $fid}) "
            "SET af.confidence = CASE WHEN af.confidence > 0.1 THEN af.confidence - 0.1 ELSE 0.0 END, "
            "    af.falsified_count = COALESCE(af.falsified_count, 0) + 1, "
            "    af.value_status = CASE WHEN af.value_status = 'valuable' THEN 'uncertain' ELSE af.value_status END",
            {"fid": fact_id},
        )
    elif error > 0.3:
        # Large positive RPE → boost confidence
        await db.execute_write(
            "MATCH (af:ActionFact {fact_id: $fid}) "
            "SET af.confidence = CASE WHEN af.confidence < 0.9 THEN af.confidence + 0.1 ELSE 1.0 END",
            {"fid": fact_id},
        )

    # Also record via B277 general RPE tracker (writes to Plan nodes which have RPE columns)
    try:
        from campy.brain.basal_ganglia.reward_predictor import record_reward_prediction_error
        await record_reward_prediction_error(db, fact_id, predicted, actual)
    except Exception:
        pass

    return {
        "status": "ok",
        "prediction_error": error,
        "direction": "positive" if error > 0.1 else "negative" if error < -0.1 else "neutral",
    }


__all__ = [
    "arc_perceive_state",
    "arc_get_game_context",
    "arc_get_action_evidence",
    "arc_get_untested_actions",
    "arc_get_causal_path",
    "arc_record_action_effect",
    "arc_get_entity_movement",
    "arc_get_goal_evidence",
    "arc_classify_game_archetype",
    "arc_confirm_hypothesis",
    "arc_contradict_hypothesis",
    "arc_update_goal_confidence",
    "arc_get_mechanic_priors",
    "arc_check_action_gate",
    "arc_record_reward_prediction_error",
]