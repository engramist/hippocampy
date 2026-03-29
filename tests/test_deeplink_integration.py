"""
Tests for B15 Deep-link Handoff.

Validates that memory_link is injected into tool responses and that
the web server provides the necessary deep-link routes.
"""

from __future__ import annotations
import json
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Mock DB helpers
# ---------------------------------------------------------------------------

class SingleRowResult:
    def __init__(self, row):
        self._row = row
        self._read = False
    def has_next(self): return not self._read
    def get_next(self):
        self._read = True
        return self._row

class MultiRowResult:
    def __init__(self, rows):
        self._rows = list(rows)
        self._idx = 0
    def has_next(self): return self._idx < len(self._rows)
    def get_next(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row

class EmptyResult:
    def has_next(self): return False

class MockDB:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.writes = []
    def execute(self, q, p=None):
        for key, resp in self.responses.items():
            if key in q:
                if isinstance(resp, list):
                    # MultiRowResult expects a list of lists/tuples
                    return MultiRowResult(resp)
                return SingleRowResult(resp)
        return EmptyResult()
    async def execute_write(self, q, p=None):
        self.writes.append((q, p))
    def vector_search(self, table_name, index_name, query_vector, limit=10):
        if table_name in self.responses:
            return self.responses[table_name]
        return []

def make_client(db=None) -> TestClient:
    from web.server import create_app
    return TestClient(create_app(db or MockDB()))

# ---------------------------------------------------------------------------
# 1. Tool Response Injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_current_truth_injects_memory_link():
    """current_truth results include a memory_link for each node."""
    from mcp_engine.tools import current_truth
    
    # Mock node result for Decision table
    mock_node = {
        "decision_id": "did-123",
        "text_raw": "Use FastAPI for the web server",
        "confidence": 0.95,
        "pathway_strength": 1.2,
        "archived": False,
        "created_at": "2024-01-01T10:00:00"
    }
    
    db = MockDB({
        "Decision": [{"node": mock_node, "score": 0.9}],
        # _check_existing_binding expects a list for the row
        "Session": [["s1", "quest-1", "explicit", "locked"]],
        "MainQuest": [["quest-1", "Test Quest"]]
    })
    
    config = {
        "mission_control": {"base_url": "http://127.0.0.1:8001"},
        "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}
    }
    
    # Patch embeddings.embed to return a dummy vector
    import mcp_engine.graph.embeddings as emb
    original_embed = emb.embed
    emb.embed = lambda text, model_name=None: [0.1] * 384
    
    try:
        result = await current_truth(
            {"query": "web server", "session_id": "s1"},
            db, config
        )
        
        assert len(result["results"]) > 0
        node_res = result["results"][0]
        assert "memory_link" in node_res
        assert node_res["memory_link"] == "http://127.0.0.1:8001/memory/node/did-123"
        assert "panel_url" in result
        assert result["panel_url"] == "http://127.0.0.1:8001/memory?context=s1"
    finally:
        emb.embed = original_embed

@pytest.mark.asyncio
async def test_notify_turn_injects_memory_link_into_insights():
    """notify_turn insights include memory_link for new entities."""
    from mcp_engine.tools import notify_turn
    
    summary = json.dumps({
        "new_entities": [
            {"id": "cid-456", "type": "Concept", "text": "Deep-linking"}
        ]
    })
    
    db = MockDB({
        "last_loop_summary": [[summary]],
        "Session": [["s1", "quest-1", "explicit", "locked"]],
        "MainQuest": [["quest-1", "SideQuest Project"]]
    })
    
    config = {
        "mission_control": {"base_url": "http://127.0.0.1:8001"}
    }
    
    # Patch embeddings.embed
    import mcp_engine.graph.embeddings as emb
    original_embed = emb.embed
    emb.embed = lambda text, model_name=None: [0.1] * 384
    
    try:
        result = await notify_turn(
            {"role": "user", "content": "Tell me about deep-linking", "session_id": "s1"},
            db, config
        )
        
        assert "insights" in result
        ent = result["insights"]["new_entities"][0]
        assert "memory_link" in ent
        assert ent["memory_link"] == "http://127.0.0.1:8001/memory/node/cid-456"
    finally:
        emb.embed = original_embed

# ---------------------------------------------------------------------------
# 2. Web API Endpoints
# ---------------------------------------------------------------------------

def test_node_detail_page_returns_index_html():
    """GET /memory/node/{id} returns the SPA index.html."""
    client = make_client()
    r = client.get("/memory/node/did-123")
    assert r.status_code == 200
    assert "SideQuest" in r.text
    assert "<script>" in r.text

def test_api_node_returns_properties_and_neighbors():
    """GET /api/node/{id} returns node props and neighbors."""
    node_props = {
        "decision_id": "did-123",
        "text_raw": "Use FastAPI",
        "confidence": 0.95
    }
    neighbor_node = {
        "concept_id": "cid-789",
        "text_raw": "FastAPI"
    }
    
    class DetailDB:
        def execute(self, q, p=None):
            if "Decision" in q and "MATCH (n:Decision)" in q:
                if "MATCH (n:Decision)-[r]-(m)" in q:
                    return MultiRowResult([[neighbor_node, "Concept", "REIFIED_AS"]])
                return SingleRowResult([node_props])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    client = make_client(DetailDB())
    r = client.get("/api/node/did-123")
    assert r.status_code == 200
    data = r.json()
    
    assert data["id"] == "did-123"
    assert data["type"] == "Decision"
    assert data["properties"]["text_raw"] == "Use FastAPI"
    assert len(data["neighbors"]) == 1
    assert data["neighbors"][0]["id"] == "cid-789"
    assert data["neighbors"][0]["relation"] == "REIFIED_AS"

def test_api_node_not_found_returns_404():
    """GET /api/node/{id} returns 404 for missing node."""
    client = make_client() # EmptyDB
    r = client.get("/api/node/ghost-id")
    assert r.status_code == 404
