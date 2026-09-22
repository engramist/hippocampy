"""B383 — MCP-facing wrapper for campy.brain.thalamus.handoff."""

from __future__ import annotations


async def generate_handoff(params: dict, db, config: dict) -> dict:
    """
    Generate a Handoff Artifact (markdown) for switching a task to a
    different model mid-session, so the new model doesn't start cold.

    params: {
        session_id (optional): str, default "unknown",
        quest_id (optional): str -- bypasses session->quest resolution,
        target_model_tier (optional): str, annotates the markdown header,
    }

    Returns:
    {
        quest_id: str,
        goal: str | None,
        decisions: list[dict],
        constraints: list[dict],
        negative_controls: list[str],
        task_graph_status: dict | None,
        files: list[dict],
        node_ids: list[str],
        markdown: str,
        latency_ms: float,
    }
    """
    from campy.brain.thalamus.handoff import generate_handoff as _generate_handoff

    session_id = (params.get("session_id") or "unknown").strip() or "unknown"
    quest_id = params.get("quest_id") or None
    target_model_tier = params.get("target_model_tier") or None

    return await _generate_handoff(
        db,
        session_id=session_id,
        quest_id=quest_id,
        target_model_tier=target_model_tier,
    )
