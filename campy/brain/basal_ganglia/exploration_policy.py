"""Exploration vs exploitation policy.

Brain analogy: The basal ganglia balances habit (exploit known-good actions)
with novelty-seeking (explore untested actions). When all known actions
have been tried and confidence is low, switch to exploration.
"""
import logging

_logger = logging.getLogger(__name__)

STALE_ACTION_THRESHOLD = 3  # If same action repeated N times with no improvement → explore


async def should_explore(
    db,
    recent_actions: list[str],
    context_id: str = "",
) -> dict:
    """Decide whether to explore (try something new) or exploit (repeat known-good).
    
    Args:
        recent_actions: List of recent action descriptions (newest first)
        context_id: Optional quest/task context
    
    Returns:
        {"explore": bool, "reason": str, "staleness_score": float}
    """
    if not recent_actions:
        return {"explore": True, "reason": "no_history", "staleness_score": 1.0}
    
    # Check for repetition
    if len(recent_actions) >= STALE_ACTION_THRESHOLD:
        unique = set(recent_actions[:STALE_ACTION_THRESHOLD])
        if len(unique) == 1:
            return {
                "explore": True,
                "reason": f"repeated '{recent_actions[0]}' {STALE_ACTION_THRESHOLD} times",
                "staleness_score": 1.0,
            }
    
    # Check if recent actions had negative outcomes
    # (Query Plan nodes linked to these actions)
    try:
        negative_count = 0
        for action in recent_actions[:5]:
            result = db.vector_search(
                "Plan", "plan_embedding",
                _get_embedding(action), limit=1,
            )
            for row in result:
                plan = row.get("node", {})
                if (plan.get("prediction_error", 0) or 0) < -0.3:
                    negative_count += 1
        
        if negative_count >= 3:
            return {
                "explore": True,
                "reason": f"{negative_count}/5 recent actions had negative prediction error",
                "staleness_score": negative_count / 5.0,
            }
    except Exception:
        pass
    
    return {"explore": False, "reason": "current_strategy_working", "staleness_score": 0.0}


def _get_embedding(text: str) -> list[float]:
    try:
        from campy.brain.hippocampus.graph.embeddings import embed
        return embed(text)
    except Exception:
        return [0.0] * 384
