
import pytest
import pytest_asyncio
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_engine.tools import current_truth

# Check for embeddings availability
try:
    from mcp_engine.graph.embeddings import embed as _embed_check
    _embed_check("test")
    EMBEDDINGS_AVAILABLE = True
except Exception:
    EMBEDDINGS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

class MockResult:
    def __init__(self, rows):
        self.rows = rows
        self.pos = 0
    def has_next(self):
        return self.pos < len(self.rows)
    def get_next(self):
        row = self.rows[self.pos]
        self.pos += 1
        return row

class MockDB:
    """Returns controlled vector search and query results."""
    def __init__(self, results_by_index: dict):
        self._results = results_by_index  # {index_name: [{"node": ..., "score": ...}]}

    def vector_search(self, table_name, index_name, embedding, limit):
        return self._results.get(index_name, [])
    
    def execute(self, query, params=None):
        # Resolve via Session → WORKING_ON → MainQuest
        if "WORKING_ON" in query:
            return MockResult([])
        # get_loaded_node_ids
        if "[:LOADED]->" in query:
            return MockResult([])
        # get_session_token_state
        if "token_estimate" in query:
            return MockResult([[0, 128000, 0]])
        # check LOADED edge already exists (track_loaded)
        if "MATCH (s:Session {session_id: $sid})-[l:LOADED]->" in query:
            return MockResult([])
        return MockResult([])

    async def execute_write(self, query, params=None):
        """No-op for tests."""
        pass

def _make_node(node_id, text, pathway_strength=0.8, confidence=0.9,
               archived=False, confidence_low=False):
    return {
        "concept_id": node_id,
        "text_raw": text,
        "pathway_strength": pathway_strength,
        "confidence": confidence,
        "confidence_low": confidence_low,
        "archived": archived,
        "created_at": "2026-01-01T00:00:00.000"
    }

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.skipif(not EMBEDDINGS_AVAILABLE, reason="embeddings not available")
async def test_cross_session_artifact_is_retrievable():
    """Test 1: A Concept node written by session A is returned by current_truth for session B."""
    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    node = _make_node("test-decision-001", "We decided to use Streamable HTTP for MCP transport",
                      pathway_strength=0.85, confidence=0.90)
    
    db = MockDB({
        "concept_emb_idx": [{"node": node, "score": 0.9}],
    })
    
    result = await current_truth(
        {
            "query": "What transport protocol did we choose?",
            "session_id": "session-B-fresh-001",  # different from session A
            "scope": "both",
            "limit": 5,
        },
        db,
        config,
    )
    
    assert len(result["results"]) >= 1
    top = result["results"][0]
    assert "Streamable HTTP" in top["text_raw"]
    assert top["similarity"] > 0.5
    assert top["confidence_low"] is False
    assert top["node_id"] == "test-decision-001"

@pytest.mark.asyncio
@pytest.mark.skipif(not EMBEDDINGS_AVAILABLE, reason="embeddings not available")
async def test_cross_session_archived_node_excluded():
    """Test 2: An archived node from session A does NOT appear in session B's results."""
    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    node = _make_node("test-decision-001", "We decided to use Streamable HTTP for MCP transport",
                      archived=True)
    
    db = MockDB({
        "concept_emb_idx": [{"node": node, "score": 0.9}],
    })
    
    result = await current_truth(
        {
            "query": "What transport protocol did we choose?",
            "session_id": "session-B-fresh-002",
            "scope": "both",
            "limit": 5,
        },
        db,
        config,
    )
    
    node_ids = [r["node_id"] for r in result["results"]]
    assert "test-decision-001" not in node_ids

@pytest.mark.asyncio
@pytest.mark.skipif(not EMBEDDINGS_AVAILABLE, reason="embeddings not available")
async def test_cross_session_confidence_low_node_is_included_but_flagged():
    """Test 3: A confidence_low node from session A IS returned but flagged."""
    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    node = _make_node("test-decision-001", "We decided to use Streamable HTTP for MCP transport",
                      pathway_strength=0.3, confidence=0.4, confidence_low=True)
    
    db = MockDB({
        "concept_emb_idx": [{"node": node, "score": 0.9}],
    })
    
    result = await current_truth(
        {
            "query": "What transport protocol did we choose?",
            "session_id": "session-B-fresh-003",
            "scope": "both",
            "limit": 5,
        },
        db,
        config,
    )
    
    nodes = [r for r in result["results"] if "Streamable HTTP" in r.get("text_raw", "")]
    assert len(nodes) >= 1
    assert nodes[0]["confidence_low"] is True

def test_auto_recall_scope_is_both():
    """Test 4: Source-inspection to ensure auto-recall uses scope: 'both'."""
    src = Path("extensions/sidequests-brain/src/index.ts").read_text()
    
    # Find the before_agent_start handler block (preAgentEvent)
    assert 'OPENCLAW_EVENT_CONTRACT.preAgentEvent' in src
    
    # Locate the api.on call for preAgentEvent
    api_on_idx = src.find('api.on(OPENCLAW_EVENT_CONTRACT.preAgentEvent')
    assert api_on_idx != -1
    
    handler_block = src[api_on_idx:api_on_idx + 1000]
    
    # Must use scope: "both" so fresh sessions get global results
    assert 'scope: "both"' in handler_block or '"scope": "both"' in handler_block
    assert '"current_truth"' in handler_block
