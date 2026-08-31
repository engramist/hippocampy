"""ARC-specific MCP query tools for Agent v2.

These handlers stay on the existing ARC schema surface and return compact,
predictable dictionaries for the ARC-side adapter.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Iterable

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient


def _gateway(db) -> GraphGateway:
    """B363: same pattern as lessons.py's `_gateway()` -- wrap `db` in a
    GraphGateway bound to the shared registry so this one migrated query
    goes through the B314 chokepoint, without changing this file's other
    handlers' `db: KuzuClient` signature."""
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)


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
    disappeared_entities = params.get("disappeared_entities") or []
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

    # A175: entity_id is stable across steps for the same physical object
    # (client now sends real color_id/region_index, not always-default 0/0).
    # Read each entity's stored centroid *before* overwriting it, so a real
    # move can be detected and written as MOVED_BY once the effect node
    # exists below.
    moved: list[tuple[str, float, float]] = []
    for ent in entities:
        entity_id = f"{task_id}_e{ent.get('color_id', 0)}_{ent.get('region_index', 0)}"
        new_cr = ent.get("centroid_row")
        new_cc = ent.get("centroid_col")

        existing_result = db.execute(
            "MATCH (e:GridEntity {entity_id: $eid}) RETURN e.centroid_row, e.centroid_col",
            {"eid": entity_id},
        )
        existing_row = _first_row(existing_result)
        if existing_row is not None:
            old_cr = _row_get(existing_row, "e.centroid_row", 0, None)
            old_cc = _row_get(existing_row, "e.centroid_col", 1, None)
            if (
                old_cr is not None and old_cc is not None
                and new_cr is not None and new_cc is not None
                and (old_cr != new_cr or old_cc != new_cc)
            ):
                moved.append((entity_id, new_cr - old_cr, new_cc - old_cc))

        await db.execute_write(
            "MERGE (e:GridEntity {entity_id: $eid}) "
            "SET e.task_id = $tid, e.color_id = $cid, e.region_index = $ridx, "
            "    e.centroid_row = $cr, e.centroid_col = $cc, "
            "    e.pixel_count = $pc, e.inferred_role = $role, "
            "    e.last_updated_step = $step",
            {
                "eid": entity_id,
                "tid": task_id,
                "cid": ent.get("color_id"),
                "ridx": ent.get("region_index", 0),
                "cr": new_cr,
                "cc": new_cc,
                "pc": ent.get("pixel_count"),
                "role": ent.get("role", "unknown"),
                "step": step,
            },
        )

    effect_id = f"{task_id}_step{step}_effect"
    effect_written = False
    if params.get("action_taken"):
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
        effect_written = True
    elif moved:
        # A175: no explicit action_taken, but an entity genuinely moved this
        # call — still need an ActionEffect node to anchor MOVED_BY to.
        await db.execute_write(
            "MERGE (ae:ActionEffect {effect_id: $eid}) "
            "SET ae.task_id = $tid, ae.step = $step",
            {"eid": effect_id, "tid": task_id, "step": step},
        )
        effect_written = True

    for entity_id, delta_row, delta_col in moved:
        await db.execute_write(
            "MATCH (e:GridEntity {entity_id: $eid}), (ae:ActionEffect {effect_id: $aeid}) "
            "MERGE (e)-[m:MOVED_BY]->(ae) "
            "SET m.delta_row = $dr, m.delta_col = $dc",
            {"eid": entity_id, "aeid": effect_id, "dr": delta_row, "dc": delta_col},
        )

    # B372: ARC_AGI's A221 Finding 2 -- entities present last frame, absent
    # this frame. One EntityDisappearance row per (task_id, entity, step),
    # never merged/updated per-entity -- see schema.py's comment on why a
    # later reappearance doesn't touch or supersede this record. Naturally
    # does no write work when the list is empty (the common case).
    for ent in disappeared_entities:
        entity_id = f"{task_id}_e{ent.get('color_id', 0)}_{ent.get('region_index', 0)}"
        disappearance_id = f"{entity_id}_disappear_step{step}"
        await _gateway(db).run(
            "arc.record_entity_disappearance",
            did=disappearance_id, task=task_id, eid=entity_id,
            ridx=ent.get("region_index", 0), cid=ent.get("color_id"), step=step,
            cr=ent.get("centroid_row"), cc=ent.get("centroid_col"),
            pc=ent.get("pixel_count"),
        )
        await _gateway(db).run(
            "arc.link_entity_disappearance", eid=entity_id, did=disappearance_id,
        )

    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "entity_count": len(entities),
        "disappeared_count": len(disappeared_entities),
        "delta_from_previous": None,
        "action_taken": params.get("action_taken"),
        "effect_id": effect_id if effect_written else None,
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


async def arc_get_entity_neighborhood(params: dict, db: KuzuClient, config: dict) -> dict:
    """B359: what does the graph already know about this specific entity,
    via A175's entity_ref/region_index correspondence.

    Hypotheses come from ENTITY_HYPOTHESIS (GridEntity -> Hypothesis),
    populated by arc_confirm_hypothesis/arc_contradict_hypothesis when
    those are called with entity_ref -- an optional param on both, so
    this can legitimately return an empty list for an entity nothing has
    been confirmed/contradicted against yet with entity context, not just
    for a nonexistent entity.

    Rules come from ENTITY_RULE (GridEntity -> Rule), populated by
    record_rule when called with entity_ref -- deliberately a separate key
    from "hypotheses", not merged in, even though both are live/falsified
    confidence-bearing claims: a confirmed/falsified causal Rule is a
    different epistemic category from a still-under-test Hypothesis (per
    joint design discussion with the ARC_AGI-side session, 2026-08-23),
    and Kuzu's rel tables are typed to a fixed FROM/TO node pair anyway so
    reusing ENTITY_HYPOTHESIS for Rule was never actually possible.

    Mechanics have no per-entity edge anywhere in this schema -- ArcMechanic
    only tracks which task_ids it's been observed in (source_task_ids),
    never a specific GridEntity. "mechanics" here is therefore task-scoped
    (live mechanics for this entity's game), not literal per-entity
    attribution -- the honest answer given what the schema actually
    models, not a fabricated finer granularity.
    """
    task_id = params.get("task_id")
    entity_ref = params.get("entity_ref")
    if not task_id:
        return _error("task_id is required")
    if entity_ref is None:
        return _error("entity_ref is required")

    hyp_result = db.execute(
        "MATCH (ge:GridEntity {task_id: $tid, region_index: $eref})-[:ENTITY_HYPOTHESIS]->(h:Hypothesis) "
        "WHERE h.status IS NULL OR h.status <> 'demoted' "
        "RETURN h.id, h.description, h.confidence, h.status",
        {"tid": task_id, "eref": entity_ref},
    )
    hypotheses = []
    for row in _iter_rows(hyp_result):
        hypotheses.append(
            {
                "hypothesis_id": _row_get(row, "h.id", 0, None),
                "claim": _row_get(row, "h.description", 1, None),
                "confidence": _safe_float(_row_get(row, "h.confidence", 2, 0.0)),
                "falsified": _row_get(row, "h.status", 3, None) == "demoted",
            }
        )

    mech_result = db.execute(
        "MATCH (m:ArcMechanic) WHERE m.source_task_ids CONTAINS $tid "
        "RETURN m.name, m.confidence "
        "ORDER BY m.confidence DESC",
        {"tid": task_id},
    )
    mechanics = []
    for row in _iter_rows(mech_result):
        mechanics.append(
            {
                "name": _row_get(row, "m.name", 0, None),
                "confidence": _safe_float(_row_get(row, "m.confidence", 1, 0.0)),
            }
        )

    rule_result = db.execute(
        "MATCH (ge:GridEntity {task_id: $tid, region_index: $eref})-[:ENTITY_RULE]->(r:Rule) "
        "WHERE r.falsified = false "
        "RETURN r.rule_id, r.action_family, r.from_color, r.to_color, r.confidence",
        {"tid": task_id, "eref": entity_ref},
    )
    rules = []
    for row in _iter_rows(rule_result):
        rules.append(
            {
                "rule_id": _row_get(row, "r.rule_id", 0, None),
                "action_family": _row_get(row, "r.action_family", 1, None),
                "from_color": _safe_int(_row_get(row, "r.from_color", 2, 0)),
                "to_color": _safe_int(_row_get(row, "r.to_color", 3, 0)),
                "confidence": _safe_float(_row_get(row, "r.confidence", 4, 0.0)),
                "falsified": False,
            }
        )

    return {"hypotheses": hypotheses, "rules": rules, "mechanics": mechanics}


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


async def _link_entity_hypothesis(
    db: KuzuClient, task_id: Any, entity_ref: Any, hypothesis_id: str, weight: float, step: Any
) -> None:
    """B359: record (or refresh) the ENTITY_HYPOTHESIS edge so
    arc_get_entity_neighborhood has something real to traverse. Only
    called when the caller actually supplied entity context -- most
    confirm/contradict calls won't (this stays optional, not a required
    param), and this repo has no other write path that ever populates
    this edge. `weight` tracks the hypothesis's current confidence at
    time of call, not a separate per-edge score; step is nullable."""
    if not task_id or entity_ref is None:
        return
    await db.execute_write(
        "MATCH (ge:GridEntity {task_id: $tid, region_index: $eref}), (h:Hypothesis {id: $hid}) "
        "WITH ge, h LIMIT 1 "
        "MERGE (ge)-[eh:ENTITY_HYPOTHESIS]->(h) "
        "SET eh.weight = $weight, eh.step = $step",
        {"tid": task_id, "eref": entity_ref, "hid": hypothesis_id, "weight": weight, "step": step},
    )


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

    await _link_entity_hypothesis(
        db, params.get("task_id"), params.get("entity_ref"), hypothesis_id,
        new_confidence, params.get("step"),
    )

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

    await _link_entity_hypothesis(
        db, params.get("task_id"), params.get("entity_ref"), hypothesis_id,
        new_confidence, params.get("step"),
    )

    return {"status": "ok", "hypothesis_id": hypothesis_id, "new_confidence": new_confidence, "falsified": falsified}


async def arc_update_goal_confidence(params: dict, db: KuzuClient, config: dict) -> dict:
    """B363: previously a bare read-only lookup on both the read and write
    queries, so a condition_id with no existing VictoryCondition node
    silently no-op'd while still returning {"status": "ok"} --
    arc_get_goal_evidence's own lookup then always saw zero rows for that
    task. The write now creates the node if it doesn't already exist (see
    arc.merge_victory_condition_confidence in queries/arc.py)."""
    goal_id = params.get("goal_id")
    if not goal_id:
        return _error("goal_id is required")
    task_id = params.get("task_id")
    if not task_id:
        return _error("task_id is required")

    new_confidence = _safe_float(params.get("new_confidence"), 0.0)
    has_progress = bool(params.get("has_meaningful_progress", False))
    current_result = db.execute(
        "MATCH (vc:VictoryCondition {condition_id: $gid}) RETURN vc.confidence",
        {"gid": goal_id},
    )
    current_row = _first_row(current_result)
    created = current_row is None
    current = _safe_float(_row_get(current_row, "vc.confidence", 0, 0.0))
    gated_confidence = new_confidence
    if gated_confidence > current and not has_progress:
        gated_confidence = current

    await _gateway(db).run(
        "arc.merge_victory_condition_confidence",
        gid=goal_id, tid=task_id, conf=gated_confidence,
    )

    return {
        "status": "ok",
        "goal_id": goal_id,
        "gated_confidence": gated_confidence,
        "created": created,
    }


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
        # Must match the write-trigger thresholds above (0.3), not an
        # independent threshold — otherwise direction claims a write
        # happened (e.g. "negative") for error magnitudes that never
        # actually reach the confidence/falsified_count SET branches.
        "direction": "positive" if error > 0.3 else "negative" if error < -0.3 else "neutral",
    }


async def record_transition(params: dict, db: KuzuClient, config: dict) -> dict:
    """A176: persist one observed color-transition histogram as a Transition
    node, linked to the GridEntity identified by entity_ref (A175's stable
    correspondence id) when non-null. One node per call, keyed by
    (task_id, action_id, step, entity_ref) — deliberately not merged/updated
    per (action_id, entity_ref), since get_entity_history needs the full
    per-step history to compute changed_count_total, not just the latest call.
    """
    task_id = params.get("task_id")
    step = params.get("step")
    action_id = params.get("action_id")
    if not task_id:
        return _error("task_id is required")
    if step is None:
        return _error("step is required")
    if not action_id:
        return _error("action_id is required")

    entity_ref = params.get("entity_ref")
    changed_count = _safe_int(params.get("changed_count"), 0)
    color_transitions = params.get("color_transitions") or []

    eref_key = entity_ref if entity_ref is not None else "none"
    transition_id = f"{task_id}_{action_id}_step{step}_{eref_key}"

    await db.execute_write(
        "MERGE (t:Transition {transition_id: $tid}) "
        "SET t.task_id = $task_id, t.step = $step, t.action_id = $aid, "
        "    t.entity_ref = $eref, t.changed_count = $cc, "
        "    t.color_transitions = $ct, t.created_at = current_timestamp()",
        {
            "tid": transition_id,
            "task_id": task_id,
            "step": step,
            "aid": action_id,
            "eref": entity_ref,
            "cc": changed_count,
            "ct": json.dumps(color_transitions, sort_keys=True, default=str),
        },
    )

    if entity_ref is not None:
        # A175's region_index is the stable per-task correspondence id — at
        # most one GridEntity should match; LIMIT 1 keeps this bounded and
        # deterministic if an edge case ever produces more than one.
        await db.execute_write(
            "MATCH (t:Transition {transition_id: $tid}), "
            "      (ge:GridEntity {task_id: $task_id, region_index: $eref}) "
            "WITH t, ge LIMIT 1 "
            "MERGE (t)-[:TRANSITION_OF]->(ge)",
            {"tid": transition_id, "task_id": task_id, "eref": entity_ref},
        )

    return {"ok": True, "transition_id": transition_id}


async def get_entity_history(params: dict, db: KuzuClient, config: dict) -> dict:
    """A176: what has happened to this entity across the game so far."""
    task_id = params.get("task_id")
    if not task_id:
        return _error("task_id is required")
    entity_ref = params.get("entity_ref")
    if entity_ref is None:
        return _error("entity_ref is required")

    result = db.execute(
        "MATCH (t:Transition {task_id: $tid, entity_ref: $eref}) "
        "RETURN t.action_id, t.step, t.color_transitions, t.changed_count "
        "ORDER BY t.step",
        {"tid": task_id, "eref": entity_ref},
    )

    transitions = []
    total = 0
    for row in _iter_rows(result):
        raw_ct = _row_get(row, "t.color_transitions", 2, None)
        try:
            color_transitions = json.loads(raw_ct) if raw_ct else []
        except Exception:
            color_transitions = []
        transitions.append(
            {
                "action_id": _row_get(row, "t.action_id", 0, None),
                "step": _safe_int(_row_get(row, "t.step", 1, 0)),
                "color_transitions": color_transitions,
            }
        )
        total += _safe_int(_row_get(row, "t.changed_count", 3, 0))

    return {"transitions": transitions, "changed_count_total": total}


async def _link_entity_rule(
    db: KuzuClient, task_id: Any, entity_ref: Any, rule_id: str, weight: float, step: Any
) -> None:
    """B359 follow-up: analog of _link_entity_hypothesis for Rule -- a
    genuinely different node type (a confirmed/falsified causal claim, not
    a still-under-test belief), kept on its own edge type (ENTITY_RULE)
    rather than folded into ENTITY_HYPOTHESIS. Only called when the caller
    supplied entity context; optional, not required."""
    if not task_id or entity_ref is None:
        return
    await db.execute_write(
        "MATCH (ge:GridEntity {task_id: $tid, region_index: $eref}), (r:Rule {rule_id: $rid}) "
        "WITH ge, r LIMIT 1 "
        "MERGE (ge)-[er:ENTITY_RULE]->(r) "
        "SET er.weight = $weight, er.step = $step",
        {"tid": task_id, "eref": entity_ref, "rid": rule_id, "weight": weight, "step": step},
    )


async def record_rule(params: dict, db: KuzuClient, config: dict) -> dict:
    """A177 (+ A179's fingerprint field): bookkeeping over deterministic
    candidate signatures already extracted client-side. For each signature,
    find a live (unfalsified) Rule for this task_id + action_family +
    from_color: same to_color -> confirm (bump confidence); different
    to_color -> falsify; no match -> create.

    B359 follow-up: optional top-level entity_ref links every rule this
    call touches to that entity via ENTITY_RULE, for
    arc_get_entity_neighborhood's "rules" field."""
    task_id = params.get("task_id")
    step = params.get("step")
    if not task_id:
        return _error("task_id is required")
    if step is None:
        return _error("step is required")

    fingerprint = params.get("fingerprint")
    signatures = params.get("candidate_signatures") or []
    entity_ref = params.get("entity_ref")

    results = []
    for sig in signatures:
        action_family = sig.get("action_family")
        from_color = sig.get("from_color")
        to_color = sig.get("to_color")
        if not action_family or from_color is None or to_color is None:
            continue

        existing_result = db.execute(
            "MATCH (r:Rule {task_id: $tid, action_family: $af, from_color: $fc}) "
            "WHERE r.falsified = false "
            "RETURN r.rule_id, r.to_color, r.confidence",
            {"tid": task_id, "af": action_family, "fc": from_color},
        )
        existing_row = _first_row(existing_result)

        if existing_row is None:
            rule_id = f"{task_id}_{action_family}_{from_color}_{to_color}_{step}"
            await db.execute_write(
                "MERGE (r:Rule {rule_id: $rid}) "
                "SET r.task_id = $tid, r.action_family = $af, r.from_color = $fc, "
                "    r.to_color = $tc, r.fingerprint = $fp, r.confidence = 0.5, "
                "    r.falsified = false, r.created_step = $step",
                {
                    "rid": rule_id, "tid": task_id, "af": action_family, "fc": from_color,
                    "tc": to_color, "fp": fingerprint, "step": step,
                },
            )
            results.append({"rule_id": rule_id, "status": "created"})
            await _link_entity_rule(db, task_id, entity_ref, rule_id, 0.5, step)
            continue

        existing_rule_id = _row_get(existing_row, "r.rule_id", 0, None)
        existing_to_color = _row_get(existing_row, "r.to_color", 1, None)
        existing_confidence = _safe_float(_row_get(existing_row, "r.confidence", 2, 0.5))

        if existing_to_color == to_color:
            new_confidence = min(1.0, existing_confidence + 0.1)
            await db.execute_write(
                "MATCH (r:Rule {rule_id: $rid}) "
                "SET r.confidence = $conf, r.fingerprint = coalesce(r.fingerprint, $fp)",
                {"rid": existing_rule_id, "conf": new_confidence, "fp": fingerprint},
            )
            results.append({"rule_id": existing_rule_id, "status": "confirmed"})
            await _link_entity_rule(db, task_id, entity_ref, existing_rule_id, new_confidence, step)
        else:
            await db.execute_write(
                "MATCH (r:Rule {rule_id: $rid}) SET r.falsified = true",
                {"rid": existing_rule_id},
            )
            results.append({"rule_id": existing_rule_id, "status": "falsified"})
            await _link_entity_rule(db, task_id, entity_ref, existing_rule_id, existing_confidence, step)

    return {"ok": True, "results": results}


async def get_rules_for_action(params: dict, db: KuzuClient, config: dict) -> dict:
    """A177: live (unfalsified) rules relevant to this action."""
    task_id = params.get("task_id")
    action_id = params.get("action_id")
    if not task_id:
        return _error("task_id is required")
    if not action_id:
        return _error("action_id is required")

    result = db.execute(
        "MATCH (r:Rule {task_id: $tid, action_family: $af}) "
        "WHERE r.falsified = false "
        "RETURN r.rule_id, r.from_color, r.to_color, r.confidence, r.falsified",
        {"tid": task_id, "af": action_id},
    )

    rules = []
    for row in _iter_rows(result):
        rules.append(
            {
                "rule_id": _row_get(row, "r.rule_id", 0, None),
                "from_color": _safe_int(_row_get(row, "r.from_color", 1, 0)),
                "to_color": _safe_int(_row_get(row, "r.to_color", 2, 0)),
                "confidence": _safe_float(_row_get(row, "r.confidence", 3, 0.0)),
                "falsified": bool(_row_get(row, "r.falsified", 4, False)),
            }
        )

    return {"rules": rules}


async def get_transferred_rules(params: dict, db: KuzuClient, config: dict) -> dict:
    """A179: live rules from OTHER task_ids whose recorded fingerprint
    matches — deliberately cross-game only, not self-referential (A164's
    existing per-game scoping via get_rules_for_action already covers
    in-game evidence)."""
    task_id = params.get("task_id")
    fingerprint = params.get("fingerprint")
    if not task_id:
        return _error("task_id is required")
    if not fingerprint:
        return _error("fingerprint is required")

    result = db.execute(
        "MATCH (r:Rule {fingerprint: $fp}) "
        "WHERE r.task_id <> $tid AND r.falsified = false "
        "RETURN r.rule_id, r.confidence, r.task_id",
        {"fp": fingerprint, "tid": task_id},
    )

    rules = []
    for row in _iter_rows(result):
        rules.append(
            {
                "rule_id": _row_get(row, "r.rule_id", 0, None),
                "confidence": _safe_float(_row_get(row, "r.confidence", 1, 0.0)),
                "source_game_id": _row_get(row, "r.task_id", 2, None),
            }
        )

    return {"rules": rules}


_TERMINAL_THREAD_STATES = {"satisfied", "exhausted"}


async def _link_thread_anchor(
    db: KuzuClient, task_id: Any, thread_id: str, anchor_ref: Any, anchor_type: str
) -> None:
    """B369: best-effort ANCHORED_ON edge, mirroring `_link_entity_hypothesis`
    above -- silently no-ops if the target node doesn't exist yet (e.g. a
    "goal" anchor referencing a Hypothesis not yet created). Two separate
    rel tables (ANCHORED_ON_ENTITY / ANCHORED_ON_GOAL), not one polymorphic
    edge -- see schema.py's comment on why."""
    if anchor_type == "entity":
        try:
            entity_ref_int = int(anchor_ref)
        except (TypeError, ValueError):
            return
        await _gateway(db).run(
            "arc.link_thread_to_entity_anchor",
            tid=thread_id, task=task_id, eref=entity_ref_int,
        )
    elif anchor_type == "goal":
        await _gateway(db).run(
            "arc.link_thread_to_goal_anchor",
            tid=thread_id, hid=str(anchor_ref),
        )


async def arc_start_or_resume_thread(params: dict, db: KuzuClient, config: dict) -> dict:
    """B369/A201: read-or-create an InvestigationThread for ARC_AGI's
    trajectory Annatar (docs/handoff/B278-investigation-thread-schema.md).

    Only this one tool is implemented -- arc_write_thread_state/
    arc_write_cycle/arc_confirm_cycle and the Attempt/Cycle nodes from the
    full design spec are deliberately out of scope here (see backlog/B369.md).
    Without them, `last_cycle` is always null and a resumed thread's state
    can only ever be whatever it was created with -- an honest, documented
    interim gap, not a bug.

    thread_id is a deterministic composite key
    (f"{task_id}::{anchor_type}::{anchor_ref}"), giving the spec's required
    O(1) primary-key resume lookup without a separate index.

    A thread found in a terminal state (satisfied/exhausted) is reopened
    -- reset to "exploring" and returned as a fresh (non-resumed) start on
    the same anchor, rather than either resuming a dead thread or minting
    a new thread_id that would break the deterministic-key invariant for
    future lookups on this same anchor. This is a judgment call the spec
    doesn't spell out explicitly; documented here and in backlog/B369.md.
    """
    task_id = params.get("task_id")
    anchor_ref = params.get("anchor_ref")
    anchor_type = params.get("anchor_type")
    if not task_id:
        return _error("task_id is required")
    if anchor_ref is None:
        return _error("anchor_ref is required")
    if anchor_type not in ("goal", "entity"):
        return _error("anchor_type must be 'goal' or 'entity'")

    thread_id = f"{task_id}::{anchor_type}::{anchor_ref}"

    rows = await _gateway(db).run("arc.fetch_investigation_thread_state", tid=thread_id)

    if rows:
        current_state = rows[0].get("t.state") or "exploring"
        if current_state not in _TERMINAL_THREAD_STATES:
            await _link_thread_anchor(db, task_id, thread_id, anchor_ref, anchor_type)
            return {
                "thread_id": thread_id, "state": current_state,
                "resumed": True, "last_cycle": None,
            }
        # Terminal -- reopen as a fresh investigation on the same anchor
        # rather than minting a new thread_id (see docstring above).
        await _gateway(db).run("arc.reopen_investigation_thread", tid=thread_id)
        await _link_thread_anchor(db, task_id, thread_id, anchor_ref, anchor_type)
        return {
            "thread_id": thread_id, "state": "exploring",
            "resumed": False, "last_cycle": None,
        }

    await _gateway(db).run(
        "arc.create_investigation_thread",
        tid=thread_id, task=task_id, aref=str(anchor_ref), atype=anchor_type,
    )
    await _link_thread_anchor(db, task_id, thread_id, anchor_ref, anchor_type)
    return {
        "thread_id": thread_id, "state": "exploring",
        "resumed": False, "last_cycle": None,
    }


__all__ = [
    "arc_perceive_state",
    "arc_get_game_context",
    "arc_get_action_evidence",
    "arc_get_untested_actions",
    "arc_get_causal_path",
    "arc_record_action_effect",
    "arc_get_entity_movement",
    "arc_get_entity_neighborhood",
    "arc_get_goal_evidence",
    "arc_classify_game_archetype",
    "arc_confirm_hypothesis",
    "arc_contradict_hypothesis",
    "arc_update_goal_confidence",
    "arc_get_mechanic_priors",
    "arc_check_action_gate",
    "arc_record_reward_prediction_error",
    "record_transition",
    "get_entity_history",
    "record_rule",
    "get_rules_for_action",
    "get_transferred_rules",
    "arc_start_or_resume_thread",
]