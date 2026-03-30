"""Tests for the ARCOrchestrator agent."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from benchmarks.arc3.schema import ARC3Observation
from benchmarks.arc3.state_serializer import StateSerializerForARC
from agents.arc3.orchestrator import ARCOrchestrator


@pytest.fixture
def sample_observation() -> ARC3Observation:
    return {
        "dataset_id": "arc",
        "task_id": "task-1",
        "episode_num": 1,
        "step_num": 1,
        "grid": [[0, 1], [2, 0]],
        "colors": [{"value": 0, "count": 2}, {"value": 1, "count": 1}],
        "shapes": [],
        "available_actions": ["ACTION1", "ACTION2", "ACTION5"],
        "state": "NOT_FINISHED",
        "energy_estimate": 1.0,
    }


@pytest.fixture
def mock_brain() -> MagicMock:
    brain = MagicMock()
    brain.current_truth = AsyncMock(return_value={"results": ["ctx"]})
    brain.recall_relevant_lessons = AsyncMock(return_value={"lessons": [{"text": "lesson"}]})
    brain.analogical_search = AsyncMock(return_value={"results": [{"text_raw": "similar"}]})
    brain.recall_plans = AsyncMock(return_value={"plans": []})
    brain.register_plan = AsyncMock(return_value={"plan_id": "plan-a", "warnings": ["avoided"], "suggestions": []})
    brain.report_outcome = AsyncMock(return_value={"updated": True})
    brain.notify_turn = AsyncMock(return_value={"status": "queued"})
    return brain


class MockLLM:
    def __init__(self):
        self.last_messages = None

    def chat(self, messages):
        self.last_messages = messages
        return json.dumps({"action_id": "ACTION3", "rationale": "mock"})


@pytest.mark.asyncio
async def test_perceive_calls_all_memory_tools(mock_brain, sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    ctx = await orchestrator.perceive(sample_observation)
    mock_brain.current_truth.assert_called_once()
    mock_brain.recall_relevant_lessons.assert_called_once()
    mock_brain.analogical_search.assert_called_once()
    assert "lessons" in ctx and "memories" in ctx


@pytest.mark.asyncio
async def test_perceive_ingests_puzzle_structure(mock_brain, sample_observation):
    """perceive() should call notify_turn with puzzle structure before querying memory."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    await orchestrator.perceive(sample_observation)
    # First notify_turn call should be the puzzle structure ingestion
    first_call = mock_brain.notify_turn.call_args_list[0]
    content = first_call.kwargs["content"]
    assert "[PUZZLE STRUCTURE]" in content
    assert "task-1" in content
    assert "2x2" in content


@pytest.mark.asyncio
async def test_plan_registers_and_captures_reflex(mock_brain, sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    memory_context = {}
    plan = await orchestrator.plan(sample_observation, memory_context)
    assert orchestrator._plan_id == "plan-a"
    assert "avoided" in orchestrator._reflex_context["warnings"][0]
    assert plan["plan_id"] == "plan-a"


@pytest.mark.asyncio
async def test_act_injects_memory_and_reflex_into_prompt(mock_brain, sample_observation):
    mock_llm = MockLLM()
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=mock_llm,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._reflex_context = {"warnings": ["don't do that"], "suggestions": ["try this"]}
    memory_ctx = {"lessons": [{"text": "lesson"}], "memories": ["ctx"], "analogies": []}
    action = await orchestrator.act(sample_observation, memory_ctx, step_num=1)
    assert mock_llm.last_messages is not None
    prompt = mock_llm.last_messages[-1]["content"]
    assert "WARNING" in prompt or "GOLDEN PATH" in prompt
    mock_brain.notify_turn.assert_called()
    assert action["action_id"] == "ACTION3"


@pytest.mark.asyncio
async def test_evaluate_reports_positive_outcome(mock_brain, sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._plan_id = "pid"
    await orchestrator.evaluate(True, steps_taken=2, max_steps=10, final_observation=sample_observation)
    call = mock_brain.report_outcome.call_args
    assert call is not None
    assert call.kwargs["valence"] > 0.5


@pytest.mark.asyncio
async def test_evaluate_reports_negative_on_failure(mock_brain, sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._plan_id = "pid"
    await orchestrator.evaluate(False, steps_taken=10, max_steps=10, final_observation=sample_observation)
    call = mock_brain.report_outcome.call_args
    assert call is not None
    assert call.kwargs["valence"] < 0


def test_reward_to_valence_correct_fast():
    assert ARCOrchestrator.reward_to_valence(True, 1, 10) == 1.0


def test_reward_to_valence_correct_slow():
    v = ARCOrchestrator.reward_to_valence(True, 9, 10)
    assert 0.3 <= v <= 0.5


def test_reward_to_valence_failed():
    assert ARCOrchestrator.reward_to_valence(False, 10, 10) == -0.5


def test_prompt_contains_memory_reflex_plan_history(sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._plan_steps = ["step one", "step two"]
    orchestrator._reflex_context = {"warnings": ["bad"], "suggestions": ["good"]}
    prompt = orchestrator.build_action_prompt(
        sample_observation,
        {"lessons": [{"text": "l"}], "memories": [], "analogies": []},
        step_history=[{"step": 1, "action_id": "ACTION1", "rationale": "r", "reward": 0.0, "done": False}],
        available_actions=["ACTION1", "ACTION6"],
    )
    assert "Available actions" in prompt
    assert "memory" in prompt.lower()
    assert "Step" in prompt
    assert "STATE" in prompt


@pytest.mark.asyncio
async def test_act_uses_available_actions_from_observation(mock_brain, sample_observation):
    """act() should read available_actions from the observation, not hardcode ACTION1-7."""
    mock_llm = MockLLM()
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=mock_llm,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    memory_ctx = {"lessons": [], "memories": [], "analogies": []}
    action = await orchestrator.act(sample_observation, memory_ctx, step_num=1)
    prompt = mock_llm.last_messages[-1]["content"]
    # Observation has ACTION1, ACTION2, ACTION5 — not all 7
    assert "ACTION1" in prompt
    assert "ACTION5" in prompt
    assert "ACTION3" not in prompt  # not in available_actions


@pytest.mark.asyncio
async def test_api_knowledge_ingestion(mock_brain):
    """ingest_api_knowledge should push all chunks into SideQuests."""
    from agents.arc3.api_knowledge import ingest_api_knowledge, API_KNOWLEDGE_CHUNKS
    count = await ingest_api_knowledge(mock_brain, "session-1")
    assert count == len(API_KNOWLEDGE_CHUNKS)
    assert mock_brain.notify_turn.call_count == len(API_KNOWLEDGE_CHUNKS)
    # Verify chunks are tagged
    first_call = mock_brain.notify_turn.call_args_list[0]
    assert "ARC-AGI-3 API Contract" in first_call.kwargs["content"]


def test_reset_for_retry_clears_plan_keeps_history():
    """reset_for_retry should clear the plan but keep step history."""
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._plan_id = "plan-1"
    orchestrator._reflex_context = {"warnings": ["bad"]}
    orchestrator._plan_steps = ["step one"]
    orchestrator._step_history = [{"step": 1, "action_id": "ACTION1", "rationale": "r", "reward": 0.0, "done": False}]

    orchestrator.reset_for_retry(1)

    assert orchestrator._plan_id is None
    assert orchestrator._reflex_context is None
    assert orchestrator._plan_steps == []
    # History should still have the original step + a GAME_OVER sentinel
    assert len(orchestrator._step_history) == 2
    assert orchestrator._step_history[-1]["action_id"] == "GAME_OVER"
    assert orchestrator._step_history[-1]["reward"] == -1.0


def test_prompt_includes_energy(sample_observation):
    """The action prompt should include energy level."""
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    sample_observation["energy_estimate"] = 0.42
    prompt = orchestrator.build_action_prompt(
        sample_observation,
        {"lessons": [], "memories": [], "analogies": []},
        step_history=[],
        available_actions=["ACTION1"],
    )
    assert "ENERGY" in prompt
    assert "42%" in prompt
