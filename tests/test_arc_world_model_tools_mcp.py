import pytest
import json
from pathlib import Path
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.thalamus.tools import TOOL_HANDLERS

# B427: migrated off KuzuClient. publish_mechanic_summary/recall_mechanic_priors
# are fully GraphGateway-routed, and OxigraphClient needs no CREATE TABLE step
# at all (the manual _init_arc_schema() DDL this test used to run -- kept in
# sync with schema.py by hand -- is simply unnecessary now).

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "brain.db")
    return OxigraphClient(db_path)

@pytest.mark.asyncio
async def test_mcp_list_includes_arc_tools(db):
    # Verify TOOL_HANDLERS has them
    assert "publish_mechanic_summary" in TOOL_HANDLERS
    assert "recall_mechanic_priors" in TOOL_HANDLERS

@pytest.mark.asyncio
async def test_publish_mechanic_mcp_route(db):
    handler = TOOL_HANDLERS["publish_mechanic_summary"]
    params = {
        "summary": {
            "name": "MCP Test",
            "action_set_signature": "SIG1",
            "confidence": 0.8
        }
    }
    res = await handler(params, db, {})
    assert res["ok"] is True
    assert "mechanic_id" in res

@pytest.mark.asyncio
async def test_recall_mechanic_mcp_route(db):
    # First publish something
    pub_handler = TOOL_HANDLERS["publish_mechanic_summary"]
    await pub_handler({
        "summary": {
            "name": "Recall Test",
            "action_set_signature": "SIG2",
            "confidence": 0.9
        }
    }, db, {})
    
    # Then recall
    recall_handler = TOOL_HANDLERS["recall_mechanic_priors"]
    res = await recall_handler({
        "signature": {"action_set": "SIG2"}
    }, db, {})
    
    assert len(res["results"]) == 1
    assert res["results"][0]["name"] == "Recall Test"
