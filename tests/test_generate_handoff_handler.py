"""tests/test_generate_handoff_handler.py — B383 MCP-facing wrapper.

campy.brain.thalamus.handoff's real logic is covered exhaustively in
tests/test_handoff.py; this file only proves the thin params-parsing
wrapper (campy/brain/thalamus/tools/generate_handoff.py) -- the actual
TOOL_HANDLERS entry -- correctly validates/forwards params.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient, mint_uri
from campy.brain.thalamus.tools.generate_handoff import generate_handoff


@pytest.fixture()
def real_db():
    tmp = tempfile.mkdtemp(prefix="generate_handoff_handler_")
    db = OxigraphClient(f"{tmp}/db")
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


async def test_no_params_returns_cold_start_artifact(real_db):
    result = await generate_handoff({}, real_db, {})
    assert result["quest_id"] == ""
    assert "markdown" in result
    assert "error" not in result


async def test_explicit_quest_id_forwarded(real_db):
    db = real_db
    db.write_node("MainQuest", {"quest_id": "q1", "name": "n", "status": "active"})
    db.write_node("Plan", {"plan_id": "p1", "goal": "explicit quest goal", "status": "active"})
    db.write_edge("TARGETS", mint_uri("Plan", "p1"), mint_uri("MainQuest", "q1"))

    result = await generate_handoff({"quest_id": "q1"}, db, {})

    assert result["quest_id"] == "q1"
    assert result["goal"] == "explicit quest goal"


async def test_target_model_tier_annotates_markdown(real_db):
    result = await generate_handoff({"target_model_tier": "local-llama"}, real_db, {})
    assert "local-llama" in result["markdown"]


async def test_missing_session_id_defaults_to_unknown_without_crashing(real_db):
    result = await generate_handoff({}, real_db, {})
    assert "error" not in result
    assert isinstance(result["markdown"], str)
