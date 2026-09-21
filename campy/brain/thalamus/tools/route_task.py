"""B382 — MCP-facing wrapper for campy.brain.thalamus.model_router."""

from __future__ import annotations


async def route_task(params: dict, db, config: dict) -> dict:
    """
    Recommend whether a task should go to a frontier or economy/local
    model, based on the calling session's graph state (open Plans vs. a
    locked-in TaskGraph). Advisory only -- never calls a cloud model
    itself.

    params: {
        task_description (required): str,
        session_id (optional): str, default "unknown",
        quest_id (optional): str -- bypasses session->quest resolution,
        token_budget (optional): int, default 4000,
    }

    Returns:
    {
        tier: str,
        provider: str | None,
        recommended_model: str | None,
        phase: str | None,
        rationale: str,
        context_bundle: dict | None,
        latency_ms: float,
    }
    """
    from campy.brain.thalamus.model_router import route_task as _route_task

    task_description = (params.get("task_description") or "").strip()
    if not task_description:
        return {"error": "task_description is required"}

    session_id = (params.get("session_id") or "unknown").strip() or "unknown"
    quest_id = params.get("quest_id") or None
    token_budget = int(params.get("token_budget") or 4000)

    return await _route_task(
        db,
        config,
        task_description,
        session_id=session_id,
        quest_id=quest_id,
        token_budget=token_budget,
    )
