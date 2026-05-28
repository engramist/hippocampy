"""ARC mechanic memory tools for graph-backed memory.

B226 adds publish_mechanic_summary for durable graph-native storage of ARC mechanics.
B227 adds recall_mechanic_priors for bounded graph retrieval.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger(__name__)

ARC_DOMAINS = "arc,arc_agi,mechanic,world-model"
SUMMARY_LIMIT = 2000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _record_hash(value: Any) -> str:
    return hashlib.sha256(_normalized_json(value).encode("utf-8")).hexdigest()


def _compact(value: Any, limit: int = SUMMARY_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = _normalized_json(value)
    text = " ".join(text.split())
    return text[:limit]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


async def publish_mechanic_summary(params: dict, db, config: dict) -> dict:
    """Publish an ARC mechanic summary to graph memory.

    Accepted params:
    {
      "summary": {
        "id": "mech-...", (optional)
        "name": "...",
        "task_id": "...",
        "action_set_signature": "...",
        "hypotheses": [...],
        "effects": [...],
        "confidence": 0.8,
        "terminal_relevance": 0.0,
        "coordinate_relevance": 0.0,
        "failure_modes": [...],
        "recovery_policies": [...]
      },
      "async_dispatch": true
    }
    """
    summary_data = params.get("summary", {})
    if not summary_data:
        return {"ok": False, "error": "summary is required"}

    now = _now_iso()

    # 1. Identify/Normalize Mechanic
    explicit_id = summary_data.get("id")
    action_set = summary_data.get("action_set_signature", "unknown")
    
    if explicit_id:
        mech_id = explicit_id
    else:
        # Stable ID from signature fields
        sig_str = f"{action_set}:{summary_data.get('name', '')}:{summary_data.get('task_id', '')}"
        mech_id = f"mech-{hashlib.sha256(sig_str.encode()).hexdigest()[:24]}"

    source_task_id = summary_data.get("task_id", "")
    
    # 2. Upsert ArcMechanic
    await db.execute_write(
        """
        MERGE (m:ArcMechanic {mechanic_id: $mechanic_id})
        ON CREATE SET m.created_at = $now,
                      m.evidence_count = 0,
                      m.contradiction_count = 0
        SET m.name = $name,
            m.signature = $signature,
            m.confidence = $confidence,
            m.terminal_relevance = $terminal_relevance,
            m.coordinate_relevance = $coordinate_relevance,
            m.source_task_ids = CASE 
                WHEN m.source_task_ids IS NULL OR m.source_task_ids = '' THEN $task_id
                WHEN m.source_task_ids CONTAINS $task_id THEN m.source_task_ids
                ELSE m.source_task_ids + ',' + $task_id
            END,
            m.evidence_count = m.evidence_count + 1,
            m.domain = $domain,
            m.summary = $summary,
            m.updated_at = $now
        """,
        {
            "mechanic_id": mech_id,
            "name": summary_data.get("name", "Unnamed Mechanic"),
            "signature": action_set,
            "confidence": _safe_float(summary_data.get("confidence"), 0.5),
            "terminal_relevance": _safe_float(summary_data.get("terminal_relevance")),
            "coordinate_relevance": _safe_float(summary_data.get("coordinate_relevance")),
            "task_id": source_task_id,
            "domain": ARC_DOMAINS,
            "summary": _compact(summary_data, 1000),
            "now": now,
        },
    )

    # 3. Action Patterns
    # Note: Summary might have multiple hypothesis/actions. 
    # For now, we treat hypotheses as candidates for ArcActionPattern.
    hypotheses = summary_data.get("hypotheses", [])
    if isinstance(hypotheses, dict): # Handle single dict if passed
        hypotheses = [hypotheses]
        
    for hyp in hypotheses:
        if not isinstance(hyp, dict):
            continue
        
        hyp_sig = hyp.get("signature") or _record_hash(hyp)[:16]
        pattern_id = f"act-pat-{hyp_sig}"
        
        await db.execute_write(
            """
            MERGE (p:ArcActionPattern {pattern_id: $pattern_id})
            SET p.signature = $signature,
                p.action_set = $action_set,
                p.action_count = $action_count,
                p.summary = $summary
            """,
            {
                "pattern_id": pattern_id,
                "signature": hyp_sig,
                "action_set": action_set,
                "action_count": _safe_int(hyp.get("action_count")),
                "summary": _compact(hyp, 500),
            }
        )
        
        await db.execute_write(
            """
            MATCH (m:ArcMechanic {mechanic_id: $mechanic_id})
            MATCH (p:ArcActionPattern {pattern_id: $pattern_id})
            MERGE (m)-[r:ARC_MECHANIC_HAS_ACTION_PATTERN]->(p)
            SET r.confidence = $confidence,
                r.evidence_count = COALESCE(r.evidence_count, 0) + 1
            """,
            {
                "mechanic_id": mech_id,
                "pattern_id": pattern_id,
                "confidence": _safe_float(hyp.get("confidence"), 0.5),
            }
        )

    # 4. Effect Patterns
    effects = summary_data.get("effects", [])
    if isinstance(effects, dict):
        effects = [effects]
        
    for eff in effects:
        if not isinstance(eff, dict):
            continue
            
        eff_sig = eff.get("signature") or _record_hash(eff)[:16]
        pattern_id = f"eff-pat-{eff_sig}"
        
        await db.execute_write(
            """
            MERGE (p:ArcEffectPattern {pattern_id: $pattern_id})
            SET p.signature = $signature,
                p.effect_class = $effect_class,
                p.terminal_trend = $terminal_trend,
                p.object_progress = $object_progress,
                p.summary = $summary
            """,
            {
                "pattern_id": pattern_id,
                "signature": eff_sig,
                "effect_class": str(eff.get("effect_class", "unknown")),
                "terminal_trend": str(eff.get("terminal_trend", "unknown")),
                "object_progress": _safe_float(eff.get("object_progress")),
                "summary": _compact(eff, 500),
            }
        )
        
        await db.execute_write(
            """
            MATCH (m:ArcMechanic {mechanic_id: $mechanic_id})
            MATCH (p:ArcEffectPattern {pattern_id: $pattern_id})
            MERGE (m)-[r:ARC_MECHANIC_CAUSES_EFFECT_PATTERN]->(p)
            SET r.confidence = $confidence,
                r.evidence_count = COALESCE(r.evidence_count, 0) + 1
            """,
            {
                "mechanic_id": mech_id,
                "pattern_id": pattern_id,
                "confidence": _safe_float(eff.get("confidence"), 0.5),
            }
        )

    # 5. Preconditions
    preconditions = summary_data.get("preconditions", [])
    for pre in preconditions:
        if not isinstance(pre, dict):
            continue
        pre_sig = pre.get("signature") or _record_hash(pre)[:16]
        pre_id = f"pre-{pre_sig}"
        await db.execute_write(
            """
            MERGE (p:ArcPrecondition {precondition_id: $pre_id})
            SET p.kind = $kind, p.signature = $signature, p.summary = $summary
            """,
            {"pre_id": pre_id, "kind": str(pre.get("kind", "")), "signature": pre_sig, "summary": _compact(pre, 400)}
        )
        await db.execute_write(
            """
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})
            MATCH (p:ArcPrecondition {precondition_id: $pre_id})
            MERGE (m)-[r:ARC_MECHANIC_REQUIRES]->(p)
            SET r.confidence = $confidence
            """,
            {"mech_id": mech_id, "pre_id": pre_id, "confidence": _safe_float(pre.get("confidence"), 1.0)}
        )

    # 6. Failure Modes and Recovery Policies
    failures = summary_data.get("failure_modes", [])
    # failure_modes can be list of strings or list of dicts
    for fail in failures:
        fail_data = fail if isinstance(fail, dict) else {"name": str(fail)}
        fail_sig = fail_data.get("signature") or _record_hash(fail_data)[:16]
        fail_id = f"fail-{fail_sig}"
        
        await db.execute_write(
            """
            MERGE (f:ArcFailureMode {failure_mode_id: $fail_id})
            SET f.name = $name, f.signature = $signature, f.summary = $summary
            """,
            {"fail_id": fail_id, "name": str(fail_data.get("name", "")), "signature": fail_sig, "summary": _compact(fail_data, 400)}
        )
        await db.execute_write(
            """
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})
            MATCH (f:ArcFailureMode {failure_mode_id: $fail_id})
            MERGE (m)-[r:ARC_MECHANIC_FAILS_AS]->(f)
            SET r.evidence_count = COALESCE(r.evidence_count, 0) + 1
            """,
            {"mech_id": mech_id, "fail_id": fail_id}
        )
        
        # Recovery policies for this failure
        policies = fail_data.get("recovery_policies", [])
        for pol in policies:
            pol_data = pol if isinstance(pol, dict) else {"name": str(pol)}
            pol_id = f"pol-{_record_hash(pol_data)[:24]}"
            await db.execute_write(
                """
                MERGE (p:ArcRecoveryPolicy {recovery_policy_id: $pol_id})
                SET p.name = $name, p.summary = $summary, p.confidence = $confidence
                """,
                {"pol_id": pol_id, "name": str(pol_data.get("name", "")), "summary": _compact(pol_data, 400), "confidence": _safe_float(pol_data.get("confidence"), 0.5)}
            )
            await db.execute_write(
                """
                MATCH (f:ArcFailureMode {failure_mode_id: $fail_id})
                MATCH (p:ArcRecoveryPolicy {recovery_policy_id: $pol_id})
                MERGE (f)-[r:ARC_FAILURE_RECOVERED_BY]->(p)
                SET r.confidence = $confidence
                """,
                {"fail_id": fail_id, "pol_id": pol_id, "confidence": _safe_float(pol_data.get("confidence"), 0.5)}
            )

    return {
        "ok": True,
        "mechanic_id": mech_id,
        "status": "upserted",
    }


async def recall_mechanic_priors(params: dict, db, config: dict) -> dict:
    """Retrieve ARC mechanic priors from graph memory.

    Accepted params:
    {
      "signature": {
        "action_set": "...",
        "archetype": "...",
        "effect_class": "...",
        "terminal_trend": "...",
        "coordinate_relevance": "...",
        "failure_signal": "..."
      },
      "limit": 5,
      "min_confidence": 0.0
    }
    """
    sig = params.get("signature") or {}
    limit = _safe_int(params.get("limit"), 5)
    min_confidence = _safe_float(params.get("min_confidence"), 0.0)

    # 1. Base query: Filter mechanics by confidence and action_set if present
    where_clauses = ["m.confidence >= $min_confidence"]
    query_params = {"min_confidence": min_confidence, "limit": limit}

    if sig.get("action_set"):
        where_clauses.append("m.signature = $action_set")
        query_params["action_set"] = str(sig["action_set"])

    where_str = " AND ".join(where_clauses)

    query = f"""
    MATCH (m:ArcMechanic)
    WHERE {where_str}
    RETURN m.mechanic_id, m.name, m.confidence, m.signature, m.summary, m.source_task_ids, m.updated_at
    ORDER BY m.confidence DESC, m.updated_at DESC
    LIMIT $limit
    """

    results = []
    rows = await db.execute_read(query, query_params)
    for row in rows:
        # row is a dict when using execute_read
        mech = {
            "id": row.get("m.mechanic_id"),
            "name": row.get("m.name"),
            "confidence": row.get("m.confidence"),
            "signature": row.get("m.signature"),
            "summary": row.get("m.summary"),
            "source_task_ids": row.get("m.source_task_ids", "").split(",") if row.get("m.source_task_ids") else [],
            "updated_at": row.get("m.updated_at"),
            "action_patterns": [],
            "effect_patterns": [],
            "failure_modes": [],
            "recovery_policies": []
        }
        results.append(mech)

    if not results:
        return {"results": [], "query_signature": sig, "limit": limit}

    # 2. For each result, expand 1-hop patterns
    for mech in results:
        # Action patterns
        ap_rows = await db.execute_read(
            """
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})-[:ARC_MECHANIC_HAS_ACTION_PATTERN]->(p:ArcActionPattern)
            RETURN p.signature, p.action_set, p.action_count, p.summary
            """,
            {"mech_id": mech["id"]}
        )
        for ap_row in ap_rows:
            mech["action_patterns"].append({
                "signature": ap_row.get("p.signature"),
                "action_set": ap_row.get("p.action_set"),
                "action_count": ap_row.get("p.action_count"),
                "summary": ap_row.get("p.summary")
            })

        # Effect patterns
        ep_rows = await db.execute_read(
            """
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})-[:ARC_MECHANIC_CAUSES_EFFECT_PATTERN]->(p:ArcEffectPattern)
            RETURN p.signature, p.effect_class, p.terminal_trend, p.object_progress, p.summary
            """,
            {"mech_id": mech["id"]}
        )
        for ep_row in ep_rows:
            mech["effect_patterns"].append({
                "signature": ep_row.get("p.signature"),
                "effect_class": ep_row.get("p.effect_class"),
                "terminal_trend": ep_row.get("p.terminal_trend"),
                "object_progress": ep_row.get("p.object_progress"),
                "summary": ep_row.get("p.summary")
            })

        # Failures and Recoveries
        fail_rows = await db.execute_read(
            """
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})-[:ARC_MECHANIC_FAILS_AS]->(f:ArcFailureMode)
            OPTIONAL MATCH (f)-[:ARC_FAILURE_RECOVERED_BY]->(pol:ArcRecoveryPolicy)
            RETURN f.name, f.signature, f.summary, pol.name, pol.summary, pol.confidence
            """,
            {"mech_id": mech["id"]}
        )
        fail_map = {}
        for f_row in fail_rows:
            f_name = f_row.get("f.name")
            if not f_name:
                continue
            if f_name not in fail_map:
                fail_map[f_name] = {
                    "name": f_name,
                    "signature": f_row.get("f.signature"),
                    "summary": f_row.get("f.summary"),
                    "recovery_policies": []
                }
            if f_row.get("pol.name"):  # policy name (from OPTIONAL MATCH)
                fail_map[f_name]["recovery_policies"].append({
                    "name": f_row.get("pol.name"),
                    "summary": f_row.get("pol.summary"),
                    "confidence": f_row.get("pol.confidence")
                })
        mech["failure_modes"] = list(fail_map.values())

    return {
        "results": results,
        "query_signature": sig,
        "limit": limit
    }
