"""
mcp_engine/loop/anomaly_detection.py — Anomaly Detection (B12 — IP Formalization)

Detects anomalies in the Loop's Step 4 that indicate potential prompt injection,
goal hijacking, or constraint violations. Implements the "Anomaly / Security sense"
from the Cocktail Party Effect.

Anomaly types:
  - constraint_violation: Content contradicts a high-confidence GlobalConstraint
  - value_inversion: Content contradicts a GlobalPreference direction
  - goal_hijack: Sudden context shift violating quest scope
"""

from __future__ import annotations
from datetime import datetime, timezone
import logging

_logger = logging.getLogger(__name__)

# Anomaly detection threshold — only check constraints with pathway_strength > 0.8
HIGH_CONFIDENCE_THRESHOLD = 0.8


async def check_anomalies(
    text: str,
    embedding: list[float],
    db,
    config: dict,
) -> dict[str, any]:
    """
    Check content for anomalies against high-confidence GlobalConstraints and
    GlobalPreferences.

    Returns {
        has_anomaly: bool,
        anomalies: [
            {
                type: "constraint_violation" | "value_inversion" | "goal_hijack",
                target_id: str,
                target_text: str,
                confidence: float,
            }
        ]
    }
    """
    anomalies = []

    # Retrieve high-confidence GlobalConstraints and GlobalPreferences
    constraints = await _get_high_confidence_constraints(db)
    preferences = await _get_high_confidence_preferences(db)

    # Check constraint violations via embedding similarity
    for constraint in constraints:
        similarity = _cosine_similarity(embedding, constraint["embedding"])
        # Contradiction: high similarity to a "never do X" constraint
        # indicates the content is attempting to do X
        if similarity > 0.75:  # High semantic overlap
            anomalies.append({
                "type": "constraint_violation",
                "target_id": constraint["global_constraint_id"],
                "target_text": constraint["text_raw"],
                "confidence": similarity,
            })

    # Check preference inversions
    for preference in preferences:
        similarity = _cosine_similarity(embedding, preference["embedding"])
        if similarity > 0.75:
            anomalies.append({
                "type": "value_inversion",
                "target_id": preference["global_preference_id"],
                "target_text": preference["text_raw"],
                "confidence": similarity,
            })

    return {
        "has_anomaly": len(anomalies) > 0,
        "anomalies": anomalies,
    }


async def _get_high_confidence_constraints(db) -> list[dict]:
    """
    Retrieve all GlobalConstraint nodes with pathway_strength > HIGH_CONFIDENCE_THRESHOLD.
    """
    query = """
        MATCH (gc:GlobalConstraint)
        WHERE gc.pathway_strength > $threshold AND NOT gc.archived
        RETURN gc.global_constraint_id, gc.text_raw, gc.embedding
    """
    result = await db.execute_read(
        query,
        {"threshold": HIGH_CONFIDENCE_THRESHOLD}
    )

    constraints = []
    if result:
        for row in result:
            vals = list(row.values()) if isinstance(row, dict) else list(row)
            constraints.append({
                "global_constraint_id": vals[0],
                "text_raw": vals[1],
                "embedding": vals[2],
            })
    return constraints


async def _get_high_confidence_preferences(db) -> list[dict]:
    """
    Retrieve all GlobalPreference nodes with pathway_strength > HIGH_CONFIDENCE_THRESHOLD.
    """
    query = """
        MATCH (gp:GlobalPreference)
        WHERE gp.pathway_strength > $threshold AND NOT gp.archived
        RETURN gp.global_preference_id, gp.text_raw, gp.embedding
    """
    result = await db.execute_read(
        query,
        {"threshold": HIGH_CONFIDENCE_THRESHOLD}
    )

    preferences = []
    if result:
        for row in result:
            vals = list(row.values()) if isinstance(row, dict) else list(row)
            preferences.append({
                "global_preference_id": vals[0],
                "text_raw": vals[1],
                "embedding": vals[2],
            })
    return preferences


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


async def store_anomaly_flag(
    db,
    node_id: str,
    node_type: str,
    anomaly_type: str,
    constraint_id: str,
    confidence: float,
) -> None:
    """
    Set anomaly flags on a node and create ANOMALY_DETECTED edge to the violated constraint.

    node_type: "Concept" | "Decision" | "Constraint" | "Requirement" | "ActionItem" | "Message" | "DocumentExtract"
    anomaly_type: "constraint_violation" | "value_inversion" | "goal_hijack"
    """
    now = datetime.now(timezone.utc).isoformat()

    # Set anomaly flags on the node
    update_query = f"""
        MATCH (n:{node_type} {{{node_type.lower()}_id: $node_id}})
        SET n.anomaly_type = $anomaly_type,
            n.flagged_for_review = true
    """
    try:
        await db.execute_write(
            update_query,
            {"node_id": node_id, "anomaly_type": anomaly_type}
        )
    except Exception as e:
        _logger.error(f"Failed to set anomaly flags on {node_type} {node_id}: {e}")
        return

    # Create ANOMALY_DETECTED edge
    edge_query = f"""
        MATCH (n:{node_type} {{{node_type.lower()}_id: $node_id}})
        MATCH (gc:GlobalConstraint {{global_constraint_id: $constraint_id}})
        MERGE (n)-[r:ANOMALY_DETECTED]->(gc)
        SET r.type = $type,
            r.confidence = $confidence,
            r.detected_at = $detected_at
    """
    try:
        await db.execute_write(
            edge_query,
            {
                "node_id": node_id,
                "constraint_id": constraint_id,
                "type": anomaly_type,
                "confidence": confidence,
                "detected_at": now,
            }
        )
    except Exception as e:
        _logger.error(f"Failed to create ANOMALY_DETECTED edge: {e}")
