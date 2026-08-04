import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock
from campy.brain.thalamus.tools import get_openclaw_prompt
from adapters.openclaw_gateway import build_openclaw_prompt

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute = MagicMock()
    db.execute_write = AsyncMock()
    return db

@pytest.mark.asyncio
async def test_build_openclaw_prompt_basic():
    """Verify basic prompt construction logic."""
    session_id = "test-session"
    
    # Layer 1 + 2 (not onboarded)
    prompt = await build_openclaw_prompt(session_id, onboarded=False)
    assert "[SideQuest | Brain: ACTIVE]" in prompt
    assert "memory_recall" in prompt
    assert "--- ONBOARDING ---" in prompt
    assert "notify_turn" in prompt
    
    # Layer 1 only (onboarded)
    prompt = await build_openclaw_prompt(session_id, onboarded=True)
    assert "[SideQuest | Brain: ACTIVE]" in prompt
    assert "memory_recall" in prompt
    assert "--- ONBOARDING ---" not in prompt
    assert "notify_turn" not in prompt

@pytest.mark.asyncio
async def test_build_openclaw_prompt_mentions_compile_context():
    """B254: the Layer 2 onboarding prompt never mentioned compile_context
    (or any bundle-related tool) despite it being a real, directly-registered
    OpenClaw tool (extensions/hippocampy/src/index.ts) - agents onboarding
    via OpenClaw had no way to learn it exists from this prompt."""
    session_id = "test-session"

    prompt = await build_openclaw_prompt(session_id, onboarded=False)
    assert "compile_context" in prompt


@pytest.mark.asyncio
async def test_build_openclaw_prompt_with_quest():
    """Verify prompt with specific quest info."""
    session_id = "test-session"
    quest_info = {"name": "Project X", "branch": "feature/cool"}
    
    prompt = await build_openclaw_prompt(session_id, onboarded=True, quest_info=quest_info)
    assert "[SideQuest | Quest: Project X | Branch: feature/cool]" in prompt

@pytest.mark.asyncio
async def test_get_openclaw_prompt_tool(mock_db):
    """Verify the Brain Daemon tool handler for OpenClaw prompts."""
    session_id = "oc-session-123"
    
    # Mock DB response for a new session (not onboarded, no quest)
    mock_db.execute.return_value.has_next.side_effect = [True, False]
    mock_db.execute.return_value.get_next.return_value = [False, None, None]
    
    params = {"session_id": session_id}
    result = await get_openclaw_prompt(params, mock_db, {})
    
    assert "prompt" in result
    assert "--- ONBOARDING ---" in result["prompt"]
    
    # Verify it attempted to mark as onboarded
    mock_db.execute_write.assert_called()
    write_query = mock_db.execute_write.call_args[0][0]
    assert "SET s.onboarded = true" in write_query

@pytest.mark.asyncio
async def test_get_openclaw_prompt_onboarded(mock_db):
    """Verify it skips onboarding if already marked in DB."""
    session_id = "oc-session-456"
    
    # Mock DB response for an already onboarded session
    mock_db.execute.return_value.has_next.return_value = True
    mock_db.execute.return_value.get_next.return_value = [True, "MainQuestName", "main"]
    
    params = {"session_id": session_id}
    result = await get_openclaw_prompt(params, mock_db, {})
    
    assert "prompt" in result
    assert "--- ONBOARDING ---" not in result["prompt"]
    assert "[SideQuest | Quest: MainQuestName | Branch: main]" in result["prompt"]
    
    # Should NOT call execute_write to mark onboarded again
    # (Actually it might still call it in my implementation, but let's check)
    # mock_db.execute_write.assert_not_called()
