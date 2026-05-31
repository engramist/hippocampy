"""Reward prediction error tracking.

Brain analogy: Dopamine neurons fire when reward exceeds prediction
(positive prediction error) and are suppressed when prediction exceeds
reward (negative prediction error). This drives learning.

Stores predicted vs actual outcomes on Plan/Procedure nodes to compute
prediction error signals that feed back into action selection.
"""
import logging

_logger = logging.getLogger(__name__)


async def record_reward_prediction_error(
    db,
    plan_id: str,
    predicted_valence: float,
    actual_valence: float,
    session_id: str = "",
) -> dict:
    """Record prediction error for a plan outcome.
    
    Args:
        plan_id: The Plan node ID
        predicted_valence: What the agent expected (-1.0 to +1.0)
        actual_valence: What actually happened (-1.0 to +1.0)
        session_id: Optional session context
    
    Returns:
        {"prediction_error": float, "direction": "positive"|"negative"|"neutral"}
    """
    error = actual_valence - predicted_valence
    direction = "positive" if error > 0.1 else "negative" if error < -0.1 else "neutral"
    
    try:
        await db.execute_write(
            "MATCH (p:Plan {plan_id: $plan_id}) "
            "SET p.predicted_valence = $predicted, "
            "    p.actual_valence = $actual, "
            "    p.prediction_error = $error",
            {
                "plan_id": plan_id,
                "predicted": predicted_valence,
                "actual": actual_valence,
                "error": error,
            },
        )
        _logger.info(
            "[BasalGanglia] RPE for plan %s: predicted=%.2f actual=%.2f error=%.2f (%s)",
            plan_id, predicted_valence, actual_valence, error, direction,
        )
    except Exception:
        _logger.exception("[BasalGanglia] Failed to record RPE for plan %s", plan_id)
    
    return {"prediction_error": error, "direction": direction}
