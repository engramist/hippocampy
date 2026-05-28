"""
Tests for B-11 — Lesson Artifact Node.
Verifies extraction, tool-based upsert, and retrieval.
"""

import sys
import os
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from campy.brain.temporal_lobe.loop.step7_5_lesson import extract_lessons
from campy.brain.thalamus.tools import upsert_lesson, recall_relevant_lessons

@pytest.mark.asyncio
async def test_extract_lessons_trigger(monkeypatch):
    """extract_lessons triggers on indicators and calls LLM."""
    db = MagicMock()
    db.execute_write = AsyncMock()
    
    llm = MagicMock()
    llm.achat = AsyncMock(return_value='[{"text": "Always use unit vectors for cosine similarity", "domain": "math", "type": "optimization"}]')
    
    config = {"embeddings": {"model": "mock-model"}}
    text = "We learned that we should always use unit vectors for cosine similarity."
    
    # Mock embedding
    from campy.brain.hippocampus.graph import embeddings as emb
    monkeypatch.setattr(emb, "embed", MagicMock(return_value=[0.1] * 384))

    count = await extract_lessons("msg-123", text, db, llm, config)
    
    assert count == 1
    llm.achat.assert_awaited_once()
    messages = llm.achat.await_args.args[0]
    assert messages[0]["role"] == "user"
    assert "Identify any domain-specific lessons or best practices" in messages[0]["content"]
    assert db.execute_write.called

@pytest.mark.asyncio
async def test_extract_lessons_no_trigger():
    """extract_lessons does nothing if no indicators found."""
    db = MagicMock()
    llm = MagicMock()
    
    config = {}
    text = "Just a normal message about the weather."
    
    count = await extract_lessons("msg-123", text, db, llm, config)
    
    assert count == 0
    assert not llm.chat.called

@pytest.mark.asyncio
async def test_upsert_lesson_tool(monkeypatch):
    """upsert_lesson tool creates a lesson node."""
    db = MagicMock()
    db.execute_write = AsyncMock()
    db.execute_read = AsyncMock(return_value=[])
    
    config = {"embeddings": {"model": "mock-model"}}
    params = {
        "text": "Never commit secrets",
        "domain": "security",
        "lesson_type": "mistake"
    }
    
    # Mock embedding
    from campy.brain.hippocampus.graph import embeddings as emb
    monkeypatch.setattr(emb, "embed", MagicMock(return_value=[0.2] * 384))

    result = await upsert_lesson(params, db, config)
    
    assert "lesson_id" in result
    assert result["status"] == "upserted"
    assert db.execute_write.called


@pytest.mark.asyncio
async def test_upsert_lesson_persists_scene_graph_metadata(monkeypatch):
    db = MagicMock()
    db.execute_write = AsyncMock()
    db.execute_read = AsyncMock(return_value=[])

    config = {"embeddings": {"model": "mock-model"}}
    params = {
        "text": "Pattern seen before",
        "domain": "arc",
        "lesson_type": "optimization",
        "scene_wl_hash": "wl:123",
        "archetype": "race",
        "progress_score": 0.65,
        "valence": 0.8,
    }

    from campy.brain.hippocampus.graph import embeddings as emb
    monkeypatch.setattr(emb, "embed", MagicMock(return_value=[0.2] * 384))

    await upsert_lesson(params, db, config)

    query, write_params = db.execute_write.await_args.args
    assert "scene_wl_hash" in query
    assert write_params["scene_wl_hash"] == "wl:123"
    assert write_params["archetype"] == "race"

@pytest.mark.asyncio
async def test_recall_relevant_lessons_domain():
    """recall_relevant_lessons fetches by domain."""
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.has_next.side_effect = [True, False]
    mock_result.get_next.return_value = ["less-1", "Use python 3.11", "optimization"]
    db.execute.return_value = mock_result
    
    params = {"domain": "python"}
    result = await recall_relevant_lessons(params, db, {})
    
    assert len(result["lessons"]) == 1
    assert result["lessons"][0]["text"] == "Use python 3.11"
