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

    def vector_search(self, index_name, embedding, limit):
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
    """D4 fix: rank = pathway_strength * confidence when both > 0."""
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

    # strong_node has rank = 0.9*0.95 = 0.855; weak_node has rank = 0.1*0.1 = 0.01
    # strong_node should rank first despite lower similarity score
    ids = [r["node_id"] for r in result["results"]]
    assert ids[0] == "strong-1"


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
