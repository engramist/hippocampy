"""Action selection — Go/No-Go gating based on graph evidence.

Brain analogy: The basal ganglia's direct pathway (Go) and indirect
pathway (No-Go) compete to select or suppress actions based on
accumulated reward history.

General Campy use: Should we inject a Procedure/Lesson? (Has it helped before?)
ARC agent use: Should we take this grid action? (Has it been falsified?)
"""
import logging
from typing import Optional

_logger = logging.getLogger(__name__)

# Thresholds
FALSIFICATION_THRESHOLD = 3      # Suppress action after N contradictions
MIN_CONFIDENCE_FOR_GO = 0.3      # Below this → No-Go
EXPLORATION_STALENESS = 5        # After N identical actions → explore


async def check_action_gate(
    db,
    action_description: str,
    context_id: str = "",
    domain: str = "general",
) -> dict:
    """Go/No-Go decision for a proposed action.
    
    Returns:
        {
            "decision": "go" | "no_go" | "explore",
            "confidence": float,
            "reason": str,
            "contradictions": int,
            "supporting_evidence": int,
        }
    """
    # Query related Procedures/Lessons for this action
    contradictions = 0
    supporting = 0
    
    try:
        # Check for falsified/avoidance Procedures matching this action
        # B279: vector_search scores are true cosine similarity.
        result = db.vector_search(
            "Procedure", "procedure_embedding",
            _get_embedding(action_description), limit=5,
        )
        for row in result:
            proc = row.get("node", {})
            if proc.get("archetype") == "avoidance":
                contradictions += 1
            elif (proc.get("success_rate", 0) or 0) > 0.6:
                supporting += 1
            elif (proc.get("success_rate", 0) or 0) < 0.4:
                contradictions += 1
    except Exception:
        _logger.debug("[BasalGanglia] action gate query failed, defaulting to Go")
        return {"decision": "go", "confidence": 0.5, "reason": "query_failed",
                "contradictions": 0, "supporting_evidence": 0}
    
    # Go/No-Go decision
    if contradictions >= FALSIFICATION_THRESHOLD:
        return {
            "decision": "no_go",
            "confidence": min(1.0, contradictions * 0.2),
            "reason": f"falsified {contradictions} times",
            "contradictions": contradictions,
            "supporting_evidence": supporting,
        }
    
    if supporting > contradictions:
        return {
            "decision": "go",
            "confidence": min(1.0, supporting * 0.15 + 0.3),
            "reason": f"{supporting} supporting procedures",
            "contradictions": contradictions,
            "supporting_evidence": supporting,
        }
    
    return {
        "decision": "explore",
        "confidence": 0.5,
        "reason": "insufficient evidence",
        "contradictions": contradictions,
        "supporting_evidence": supporting,
    }


def _get_embedding(text: str) -> list[float]:
    """Get embedding for action text. Uses the shared embedder."""
    try:
        from campy.brain.hippocampus.graph.embeddings import embed
        return embed(text)
    except Exception:
        return [0.0] * 384  # Fallback zero vector
