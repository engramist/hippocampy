import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
import campy.brain.temporal_lobe.warm_frontier as warm_frontier
from campy.brain.temporal_lobe.warm_frontier import compute_warm_frontier, get_warm_nodes
from campy.brain.thalamus.tools import notify_turn, current_truth
import campy.brain.thalamus.tools as tools_mod
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient

@pytest.fixture
def db():
    mock = MagicMock(spec=OxigraphClient)
    mock.execute_write = AsyncMock()
    return mock

@pytest.mark.asyncio
async def test_warm_frontier_activation_and_retrieval():
    """
    Test that notify_turn activates nodes and current_truth prefers them.
    """
    db = MagicMock(spec=OxigraphClient)
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
        import campy.brain.hippocampus.graph.embeddings as emb
        original_embed = emb.embed
        original_tools_embed = tools_mod.emb.embed
        stub_embed = MagicMock(return_value=[0.1] * 384)
        emb.embed = stub_embed
        tools_mod.emb.embed = stub_embed
        
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
        tools_mod.emb.embed = original_tools_embed

@pytest.mark.asyncio
async def test_spread_activation():
    """Test that activation spreads to neighbors."""
    db = MagicMock(spec=OxigraphClient)
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
    
    from campy.brain.temporal_lobe.warm_frontier import compute_warm_frontier
    await compute_warm_frontier(db, "session1", [0.1]*384)
    
    # Verify both c1 and c2 were activated
    write_calls = db.execute_write.call_args_list
    activated_ids = []
    for call in write_calls:
        if "WARM_NODE" in str(call[0][0]) and "nid" in call[0][1]:
            activated_ids.append(call[0][1]["nid"])
            
    assert "c1" in activated_ids
    assert "c2" in activated_ids


@pytest.mark.asyncio
async def test_supernode_safeguard_caps_neighbors(monkeypatch):
    """B375: a hub with >SUPERNODE_DEGREE_THRESHOLD neighbors is capped to
    the top SUPERNODE_TOP_N by pathway_strength, not spread across all of them."""
    call_count = {"n": 0}

    class FakeGateway:
        async def run(self, qname, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # One giant hub with 60 distinct neighbors, strengths 0..59.
                return [(f"n{i}", float(i)) for i in range(60)]
            return []

    monkeypatch.setattr(warm_frontier, "get_gateway", lambda db: FakeGateway())

    neighbors = await warm_frontier._get_artifact_neighbors(
        db=object(), node_id="hub", table="Concept"
    )

    assert len(neighbors) == warm_frontier.SUPERNODE_TOP_N
    kept_ids = {nid for nid, _table in neighbors}
    assert kept_ids == {f"n{i}" for i in range(55, 60)}


@pytest.mark.asyncio
async def test_supernode_safeguard_config_override(monkeypatch):
    """B375 gap 3: [retrieval.warm_frontier] config values must actually
    reach _get_artifact_neighbors via compute_warm_frontier, not just sit
    in campy.toml/config.py unused."""
    db = MagicMock(spec=OxigraphClient)
    db.execute_write = AsyncMock()

    db.vector_search.return_value = [
        {"node": {"concept_id": "seed", "archived": False}, "score": 1.0}
    ]

    call_count = {"n": 0}

    class FakeGateway:
        async def run(self, qname, **kwargs):
            call_count["n"] += 1
            if "warm_neighbor" in qname and call_count["n"] == 1:
                # 10 distinct neighbors - below the default threshold (50)
                # but above a config-lowered threshold of 5.
                return [(f"n{i}", float(i)) for i in range(10)]
            return []

        async def run_sync_placeholder(self):
            pass

    fake_gw = FakeGateway()
    monkeypatch.setattr(warm_frontier, "get_gateway", lambda db: fake_gw)

    config = {
        "retrieval": {
            "warm_frontier": {
                "supernode_degree_threshold": 5,
                "supernode_top_n": 2,
            }
        }
    }

    await warm_frontier.compute_warm_frontier(db, "session-cfg", [0.1] * 384, config)

    # With the config-lowered threshold, only 2 (not 10) neighbors should
    # have contributed WARM_NODE writes beyond the seed itself.
    write_calls = db.execute_write.call_args_list
    written_ids = {
        call[0][1]["nid"] for call in write_calls if "WARM_NODE" in str(call[0][0])
    }
    neighbor_ids_written = written_ids - {"seed"}
    assert len(neighbor_ids_written) <= 2


@pytest.mark.asyncio
async def test_no_safeguard_below_threshold(monkeypatch):
    """A node with a normal (small) degree keeps all its neighbors, unmodified."""
    call_count = {"n": 0}

    class FakeGateway:
        async def run(self, qname, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [(f"n{i}", float(i)) for i in range(10)]
            return []

    monkeypatch.setattr(warm_frontier, "get_gateway", lambda db: FakeGateway())

    neighbors = await warm_frontier._get_artifact_neighbors(
        db=object(), node_id="normal", table="Concept"
    )

    assert len(neighbors) == 10
