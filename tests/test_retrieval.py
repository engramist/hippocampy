"""
Tests for current_truth retrieval (tools.py).
T8 fix: was a stub with no test functions.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(node_id, text, pathway_strength=0.8, confidence=0.9,
               archived=False, confidence_low=False):
    return {
        "concept_id": node_id,
        "text_raw": text,
        "pathway_strength": pathway_strength,
        "confidence": confidence,
        "confidence_low": confidence_low,
        "archived": archived,
    }


class MockVectorSearchDB:
    """Returns controlled vector search results per table."""
    def __init__(self, results_by_index: dict):
        self._results = results_by_index  # {index_name: [{"node": ..., "score": ...}]}

    def vector_search(self, table_name, index_name, embedding, limit):
        return self._results.get(index_name, [])


# ---------------------------------------------------------------------------
# current_truth tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_current_truth_empty_query():
    """Empty query returns empty results immediately."""
    from mcp_engine.tools import current_truth
    result = await current_truth({"query": "", "session_id": "s1"}, None, {})
    assert result["results"] == []


@pytest.mark.asyncio
async def test_current_truth_excludes_archived():
    """Archived nodes are never returned in current_truth results."""
    from mcp_engine.tools import current_truth

    archived_node = _make_node("arc-1", "archived concept", archived=True)
    db = MockVectorSearchDB({
        "concept_emb_idx": [{"node": archived_node, "score": 0.95}],
    })

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    result = await current_truth(
        {"query": "archived concept", "session_id": "s1"},
        db, config
    )
    node_ids = [r["node_id"] for r in result["results"]]
    assert "arc-1" not in node_ids


@pytest.mark.asyncio
async def test_current_truth_rank_formula():
    """B31 fix: balanced ranking — similarity (50%) + strength (30%) + recency (20%).
    
    With balanced ranking, a highly similar weak node should beat a less-similar
    strong node. This prevents stale high-strength nodes from dominating results
    when the user's query closely matches a newer, weaker node.
    """
    from mcp_engine.tools import current_truth

    strong_node = _make_node("strong-1", "strong concept",
                             pathway_strength=0.9, confidence=0.95)
    weak_node = _make_node("weak-1", "weak concept",
                           pathway_strength=0.1, confidence=0.1)

    db = MockVectorSearchDB({
        "concept_emb_idx": [
            {"node": weak_node, "score": 0.99},   # high similarity, weak node
            {"node": strong_node, "score": 0.70},  # lower similarity, strong node
        ],
    })

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    result = await current_truth(
        {"query": "concept", "session_id": "s1"},
        db, config
    )

    # B31: With balanced ranking formula:
    # weak_node:   sim=0.99*0.5 + strength_norm(0.01/3)*0.3 + recency*0.2 ≈ 0.50 + 0.001 + 0.2 = 0.70
    # strong_node: sim=0.70*0.5 + strength_norm(0.855/3)*0.3 + recency*0.2 ≈ 0.35 + 0.086 + 0.2 = 0.64
    # High-similarity weak node should rank first (the user's query is about THIS concept)
    ids = [r["node_id"] for r in result["results"]]
    assert ids[0] == "weak-1"


@pytest.mark.asyncio
async def test_current_truth_includes_concepts():
    """D6 fix: Concept nodes appear in current_truth results."""
    from mcp_engine.tools import current_truth

    concept_node = _make_node("c-1", "Kùzu database",
                              pathway_strength=0.8, confidence=0.9)
    db = MockVectorSearchDB({
        "concept_emb_idx": [{"node": concept_node, "score": 0.88}],
    })

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    result = await current_truth(
        {"query": "Kùzu", "session_id": "s1"},
        db, config
    )

    types = [r["node_type"] for r in result["results"]]
    assert "Concept" in types


@pytest.mark.asyncio
async def test_current_truth_confidence_low_flag_preserved():
    """confidence_low flag is passed through to caller so LLM can flag uncertainty."""
    from mcp_engine.tools import current_truth

    tentative_node = _make_node("t-1", "tentative concept",
                                pathway_strength=0.6, confidence=0.7,
                                confidence_low=True)
    db = MockVectorSearchDB({
        "concept_emb_idx": [{"node": tentative_node, "score": 0.80}],
    })

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    result = await current_truth(
        {"query": "tentative", "session_id": "s1"},
        db, config
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["confidence_low"] is True


@pytest.mark.asyncio
async def test_current_truth_panel_url_default():
    """B15: current_truth includes panel_url pointing to Mission Control thinking tab."""
    from mcp_engine.tools import current_truth

    concept_node = _make_node("c-2", "some concept", pathway_strength=0.8, confidence=0.9)
    db = MockVectorSearchDB({
        "concept_emb_idx": [{"node": concept_node, "score": 0.85}],
    })

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    result = await current_truth(
        {"query": "some concept", "session_id": "s1"},
        db, config
    )

    # panel_url present and points to thinking tab (no quest_id in params)
    assert "panel_url" in result
    assert "127.0.0.1:7800" in result["panel_url"]
    assert result["panel_url"].startswith("http://")


@pytest.mark.asyncio
async def test_current_truth_panel_url_custom_base():
    """B15: mission_control.base_url config is respected."""
    from mcp_engine.tools import current_truth

    concept_node = _make_node("c-3", "custom base concept", pathway_strength=0.8, confidence=0.9)
    db = MockVectorSearchDB({
        "concept_emb_idx": [{"node": concept_node, "score": 0.85}],
    })

    config = {
        "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
        "mission_control": {"base_url": "http://10.0.0.5:7800"},
    }
    result = await current_truth(
        {"query": "custom base concept", "session_id": "s1"},
        db, config
    )

    assert "panel_url" in result
    assert result["panel_url"].startswith("http://10.0.0.5:7800")


@pytest.mark.asyncio
async def test_current_truth_panel_url_board_when_quest_id():
    """B15: panel_url points to /board when quest_id is in params."""
    from mcp_engine.tools import current_truth

    concept_node = _make_node("c-4", "quest concept", pathway_strength=0.8, confidence=0.9)
    db = MockVectorSearchDB({
        "concept_emb_idx": [{"node": concept_node, "score": 0.85}],
    })

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    result = await current_truth(
        {"query": "quest concept", "session_id": "s1", "quest_id": "abc123"},
        db, config
    )

    assert "panel_url" in result
    assert "/board" in result["panel_url"]
