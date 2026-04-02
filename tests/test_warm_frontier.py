import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from mcp_engine.warm_frontier import compute_warm_frontier, get_warm_nodes
from mcp_engine.tools import notify_turn, current_truth
from mcp_engine.graph.kuzu_client import KuzuClient

@pytest.fixture
def db():
    mock = MagicMock(spec=KuzuClient)
    mock.execute_write = AsyncMock()
    return mock

@pytest.mark.asyncio
async def test_warm_frontier_activation_and_retrieval():
    """
    Test that notify_turn activates nodes and current_truth prefers them.
    """
    db = MagicMock(spec=KuzuClient)
    db.execute_write = AsyncMock()
    session_id = "test_session_b91"
    
    # 1. Mock vector_search to return some nodes
    mock_node = {
        "concept_id": "c1",
        "text_raw": "Test Concept",
        "confidence": 1.0,
        "pathway_strength": 1.0,
        "archived": False
    }
    db.vector_search.return_value = [{"node": mock_node, "score": 0.9}]
    
    # Mock execute to return nothing for neighbors initially
    db.execute.return_value.has_next.return_value = False

    # 2. Call notify_turn (which calls compute_warm_frontier)
    # We need to mock emb.embed too
    with MagicMock() as mock_emb:
        import mcp_engine.graph.embeddings as emb
        original_embed = emb.embed
        emb.embed = MagicMock(return_value=[0.1]*384)
        
        params = {
            "role": "user",
            "content": "activating message",
            "session_id": session_id
        }
        
        await notify_turn(params, db, {"embeddings": {"model": "mock"}})
        
        # Verify compute_warm_frontier was called (it would have called vector_search)
        assert db.vector_search.called
        
        # Verify WARM_NODE relationship was created
        write_calls = db.execute_write.call_args_list
        warm_node_called = any("WARM_NODE" in str(call[0][0]) for call in write_calls)
        assert warm_node_called
        
        # 3. Test retrieval preference in current_truth
        db.vector_search.reset_mock()
        db.vector_search.return_value = [
            {"node": {"concept_id": "c1", "text_raw": "c1", "confidence": 1.0, "pathway_strength": 1.0}, "score": 0.8},
            {"node": {"concept_id": "c2", "text_raw": "c2", "confidence": 1.0, "pathway_strength": 1.0}, "score": 0.85}
        ]
        
        # Mock get_warm_nodes inside current_truth
        def mock_execute(query, params=None):
            m = MagicMock()
            if "WARM_NODE" in query:
                m.has_next.side_effect = [True, False]
                m.get_next.return_value = ["c1", 0.9]
            else:
                m.has_next.return_value = False
            return m
            
        db.execute = MagicMock(side_effect=mock_execute)
        
        search_params = {
            "query": "search query",
            "session_id": session_id,
            "limit": 5
        }
        
        response = await current_truth(search_params, db, {"embeddings": {"model": "mock"}})
        results = response["results"]
        
        # c1 should win due to warm boost (even though similarity 0.8 < 0.85)
        assert results[0]["node_id"] == "c1"
        assert results[0]["activation_score"] == 0.9
        
        emb.embed = original_embed

@pytest.mark.asyncio
async def test_spread_activation():
    """Test that activation spreads to neighbors."""
    db = MagicMock(spec=KuzuClient)
    db.execute_write = AsyncMock()
    
    # Seed node c1 with high score
    db.vector_search.return_value = [{"node": {"concept_id": "c1", "archived": False}, "score": 1.1}]
    
    # Mock neighbors for c1 -> c2 via REIFIED_AS
    def mock_execute(query, params=None):
        m = MagicMock()
        if "REIFIED_AS" in query and params and params.get("id") == "c1":
            m.has_next.side_effect = [True, False]
            m.get_next.return_value = ["c2"]
        else:
            m.has_next.return_value = False
        return m
    db.execute = MagicMock(side_effect=mock_execute)
    
    from mcp_engine.warm_frontier import compute_warm_frontier
    await compute_warm_frontier(db, "session1", [0.1]*384)
    
    # Verify both c1 and c2 were activated
    write_calls = db.execute_write.call_args_list
    activated_ids = []
    for call in write_calls:
        if "WARM_NODE" in str(call[0][0]) and "nid" in call[0][1]:
            activated_ids.append(call[0][1]["nid"])
            
    assert "c1" in activated_ids
    assert "c2" in activated_ids
