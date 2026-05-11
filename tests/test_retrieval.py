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
    """Architecture invariant: rank by pathway_strength × confidence."""
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
async def test_current_truth_includes_raw_messages():
    """Fresh captured turns should be recallable before consolidation."""
    from mcp_engine.tools import current_truth

    message_node = {
        "message_id": "m-1",
        "text_raw": "Durable capture for Claude Code and VS Code is wired into the installer.",
        "pathway_strength": 0.2,
        "confidence": 0.5,
        "confidence_low": True,
        "archived": False,
    }
    db = MockVectorSearchDB({
        "message_emb_idx": [{"node": message_node, "score": 0.96}],
    })

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    result = await current_truth(
        {"query": "Claude Code VS Code installer capture", "session_id": "s1"},
        db, config,
    )

    assert result["results"][0]["node_id"] == "m-1"
    assert result["results"][0]["node_type"] == "Message"


@pytest.mark.asyncio
async def test_current_truth_uses_lesson_primary_key():
    """Lesson results should expose their stable lesson_id, not 'unknown'."""
    from mcp_engine.tools import current_truth

    lesson_node = {
        "lesson_id": "lesson-1",
        "text_raw": "Always repair stale Claude hook paths during setup.",
        "pathway_strength": 0.8,
        "confidence": 0.9,
        "confidence_low": False,
        "archived": False,
    }
    db = MockVectorSearchDB({
        "lesson_emb_idx": [{"node": lesson_node, "score": 0.90}],
    })

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    result = await current_truth(
        {"query": "repair Claude hook paths", "session_id": "s1"},
        db, config,
    )

    assert result["results"][0]["node_id"] == "lesson-1"
    assert result["results"][0]["node_type"] == "Lesson"


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
