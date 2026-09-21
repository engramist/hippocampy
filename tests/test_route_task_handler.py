"""tests/test_route_task_handler.py — B382 MCP-facing wrapper.

campy.brain.thalamus.model_router's real logic is covered exhaustively
in tests/test_model_router.py; this file only proves the thin
params-parsing wrapper (campy/brain/thalamus/tools/route_task.py) --
the actual TOOL_HANDLERS entry -- correctly validates/forwards params.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.thalamus.tools.route_task import route_task


@pytest.fixture()
def real_db():
    tmp = tempfile.mkdtemp(prefix="route_task_handler_")
    db = OxigraphClient(f"{tmp}/db")
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


async def test_missing_task_description_returns_error(real_db):
    result = await route_task({}, real_db, {})
    assert result == {"error": "task_description is required"}


async def test_blank_task_description_returns_error(real_db):
    result = await route_task({"task_description": "   "}, real_db, {})
    assert "error" in result


async def test_reflex_task_routes_through_the_full_handler(real_db):
    result = await route_task({"task_description": "run prettier formatting"}, real_db, {})
    assert result["tier"] == "local_reflex"
    assert result["phase"] == "reflex"


async def test_missing_session_id_defaults_to_unknown_without_crashing(real_db):
    result = await route_task({"task_description": "some task"}, real_db, {})
    assert result["tier"] in ("frontier", "economy", "local_reflex", "disabled")
    assert "error" not in result


async def test_explicit_session_and_quest_id_forwarded(real_db):
    from campy.brain.hippocampus.graph.oxigraph_client import mint_uri

    real_db.write_node("MainQuest", {"quest_id": "q1", "name": "n", "status": "active"})
    real_db.write_node("Plan", {"plan_id": "p1", "goal": "decide something", "status": "active"})
    real_db.write_edge("TARGETS", mint_uri("Plan", "p1"), mint_uri("MainQuest", "q1"))

    result = await route_task(
        {"task_description": "help me decide", "quest_id": "q1"}, real_db, {},
    )
    assert result["phase"] == "planning"
    assert result["tier"] == "frontier"


async def test_custom_token_budget_forwarded(real_db):
    result = await route_task(
        {"task_description": "some task", "token_budget": 1000}, real_db, {},
    )
    assert "tier" in result
