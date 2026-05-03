import pytest
import json
from pathlib import Path
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.schema import NODE_TABLES, REL_TABLES
from mcp_engine.tools import TOOL_HANDLERS

def _init_arc_schema(db: KuzuClient) -> None:
    tables = [
        "ArcMechanic", "ArcActionPattern", "ArcEffectPattern", 
        "ArcPrecondition", "ArcFailureMode", "ArcRecoveryPolicy"
    ]
    for table in tables:
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table} ({NODE_TABLES[table]})")
    for ddl in REL_TABLES:
        if any(rel in ddl for rel in (
            "ARC_MECHANIC_HAS_ACTION_PATTERN",
            "ARC_MECHANIC_CAUSES_EFFECT_PATTERN",
            "ARC_MECHANIC_REQUIRES",
            "ARC_MECHANIC_FAILS_AS",
            "ARC_FAILURE_RECOVERED_BY"
        )):
            db.execute(ddl)

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "brain.db")
    client = KuzuClient(db_path)
    _init_arc_schema(client)
    return client

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
