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
        "frame_hash": "abc123framehash",
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
        return json.dumps({"action_id": "ACTION1", "rationale": "mock"})


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
    assert "Spatial sketch 4x4" in content


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
    assert action["action_id"] == "ACTION1"


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
async def test_solve_updates_context(mock_brain, sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=MagicMock(),
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    # Mocking SolveEngine.solve is easier than setting up the whole state
    orchestrator.solve_engine.solve = AsyncMock(return_value=MagicMock(
        archetype=MagicMock(value="race"),
        archetype_confidence=0.8,
        object_roles={3: MagicMock(role=MagicMock(value="wall"), confidence=0.7)},
        victory_condition=MagicMock(
            condition_type=MagicMock(value="reach_goal"),
            description="reach exit",
            confidence=0.6
        ),
        active_chunk=MagicMock(
            description="move to exit",
            estimated_actions=["ACTION1"],
            progress_score=0.0,
            source="bfs"
        ),
        dissonance_detected=False,
        dissonance_reason="",
        strategy_summary="TEST SUMMARY"
    ))

    hyp_ctx = {"current_state_hash": "h1"}
    solve_ctx = await orchestrator.solve(sample_observation, hyp_ctx, step=5)

    assert solve_ctx["archetype"] == "race"
    assert solve_ctx["archetype_confidence"] == 0.8
    assert solve_ctx["victory_condition"]["type"] == "reach_goal"
    assert orchestrator._solve_context == solve_ctx

@pytest.mark.asyncio
async def test_act_includes_solve_section_in_prompt(mock_brain, sample_observation):
    mock_llm = MockLLM()
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=mock_llm,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._solve_context = {
        "archetype": "race",
        "archetype_confidence": 0.8,
        "strategy_summary": "TEST STRATEGY",
        "active_chunk": {"description": "chunk1", "progress": 0.5, "source": "bfs"}
    }
    
    memory_ctx = {"lessons": [], "memories": [], "analogies": []}
    await orchestrator.act(sample_observation, memory_ctx, step_num=1)
    
    prompt = mock_llm.last_messages[-1]["content"]
    assert "=== SOLVE CONTEXT ===" in prompt
    assert "ARCHETYPE: race" in prompt
    assert "ACTIVE CHUNK: chunk1" in prompt


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
        {"lessons": [{"text": "l"}], "memories": [], "analogies": [], "_triggered": True},
        step_history=[{"step": 1, "action_id": "ACTION1", "rationale": "r", "reward": 0.0, "done": False}],
        available_actions=["ACTION1", "ACTION6"],
    )
    assert "Available actions" in prompt
    assert "memory" in prompt.lower()
    assert "Step" in prompt
    assert "STATE" in prompt

def test_prompt_asks_for_decision_from_observed_effects(sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._hypothesis_context = {
        "action_coverage": {
            "tested_count": 1,
            "untested_count": 1,
            "untested_actions": ["ACTION2"],
            "initial_exploration_complete": False,
            "top_two_low_value": False,
        },
        "environment_bottleneck": {
            "type": "single_blocked_action",
            "action": "ACTION1",
            "times_seen": 2,
            "message": "Environment bottleneck: only ACTION1 is available and it is blocked/no-op after 2 observation(s).",
        },
        "action_facts": [
            {
                "id": "fact-ACTION1",
                "action": "ACTION1",
                "fact_type": "deterministic_effect",
                "description": "ACTION1 reliably produces localized_change",
                "consistency": 0.9,
                "value_status": "low_value",
                "evidence_count": 2,
                "support_steps": [1, 2],
            }
        ],
        "path_hypotheses": [
            {
                "actions": ["ACTION1", "ACTION2"],
                "description": "path ACTION1 -> ACTION2 ends in tentative_progress with avg_score 0.38",
                "confidence": 0.7,
                "value_status": "tentative",
                "support_steps": [1, 2],
            }
        ],
        "last_transition_effect": {
            "action": "ACTION1",
            "summary": "regional_change: 3 pixels changed in rows 0-0, cols 0-2",
            "meaningful_change_score": 0.42,
            "meaningful_change_label": "tentative_progress",
            "meaningful_change_reasons": ["novel_state", "visible_effect"],
            "zero_reward_streak": 2,
            "before_frame_hash": "beforehash1234",
            "after_frame_hash": "afterhash5678",
            "before_snapshot": {"coarse_map": "0 0\n0 0"},
            "after_snapshot": {"coarse_map": "1 1\n1 1"},
            "changed_region": {
                "row_range": [0, 1],
                "col_range": [0, 1],
                "before_crop": "0 0\n0 0",
                "after_crop": "1 1\n1 1",
            },
        },
        "observed_action_effects": [
            {
                "action": "ACTION1",
                "times_seen": 2,
                "avg_pixels_changed": 1.5,
                "avg_meaningful_change": 0.42,
                "no_change_count": 1,
                "no_progress_count": 0,
                "novel_state_count": 2,
                "reward_hits": 0,
                "zero_reward_streak": 2,
                "last_meaningful_label": "tentative_progress",
                "rank_score": 0.39,
                "retest_budget": 2,
                "over_retest_budget": False,
                "recent_diff": "regional_change: 3 pixels changed in rows 0-0, cols 0-2",
            },
            {
                "action": "ACTION2",
                "times_seen": 0,
                "avg_pixels_changed": 0.0,
                "avg_meaningful_change": 0.0,
                "no_change_count": 0,
                "no_progress_count": 0,
                "novel_state_count": 0,
                "reward_hits": 0,
                "zero_reward_streak": 0,
                "last_meaningful_label": "UNTESTED",
                "rank_score": 0.0,
                "retest_budget": 0,
                "over_retest_budget": False,
                "recent_diff": "UNTESTED",
            },
        ],
    }
    prompt = orchestrator.build_action_prompt(
        sample_observation,
        {"lessons": [], "memories": [], "analogies": [], "_triggered": False},
        step_history=[],
        available_actions=["ACTION1", "ACTION2"],
    )
    assert "ACTION FACTS" in prompt
    assert "PATH HYPOTHESES" in prompt
    assert "OBSERVED EFFECTS" in prompt
    assert "Treat action ids as opaque operators" in prompt
    assert "Choose the next valid action based on observed effects" in prompt
    assert "Start in an exploration phase" in prompt
    assert "strong_progress or tentative_progress" in prompt
    assert "tentative_progress" in prompt
    assert "After 2 consecutive zero-reward tentative steps" in prompt
    assert "ACTION2: UNTESTED" in prompt
    assert "zero_reward_streak 2" in prompt
    assert "Currently available but unobserved actions: ACTION2" in prompt
    assert "Exploration coverage: tested 1, untested 1" in prompt
    assert "PATH TENTATIVE" in prompt
    assert "ACTION1: DETERMINISTIC_EFFECT" in prompt
    assert "rank 0.39" in prompt
    assert "budget 2" in prompt
    assert "Board transition: beforeha -> afterhas" in prompt
    assert "Before board 4x4:" in prompt
    assert "After board 4x4:" in prompt
    assert "Changed region rows 0-1, cols 0-1" in prompt
    assert "Changed region before:" in prompt
    assert "Changed region after:" in prompt
    assert "Environment bottleneck: only ACTION1 is available and it is blocked/no-op after 2 observation(s)." in prompt


@pytest.mark.asyncio
async def test_hypothesize_write_trace_includes_saved_facts_and_paths(sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator.hypothesis_mgr.observe = MagicMock(
        return_value={
            "last_transition_effect": {
                "action": "ACTION1",
                "summary": "regional_change: 3 pixels changed",
                "meaningful_change_score": 0.42,
                "meaningful_change_label": "tentative_progress",
            },
            "action_facts": [
                {
                    "id": "fact-ACTION1",
                    "action": "ACTION1",
                    "fact_type": "deterministic_effect",
                    "description": "ACTION1 shifts the active region upward",
                    "consistency": 0.9,
                    "value_status": "tentative",
                    "evidence_count": 2,
                    "trend": {
                        "kind": "directional_drift",
                        "axis": "row",
                        "direction": "up",
                        "avg_delta": 1.0,
                        "samples": 2,
                        "stable_region": True,
                        "message": "upward drift by ~1.0 cell(s)/step within a stable region",
                    },
                    "support_steps": [1, 2],
                }
            ],
            "path_hypotheses": [
                {
                    "actions": ["ACTION1", "ACTION3"],
                    "description": "path ACTION1 -> ACTION3 preserves motion while changing region",
                    "confidence": 0.7,
                    "value_status": "tentative",
                    "support_steps": [1, 2],
                }
            ],
            "environment_bottleneck": {
                "type": "single_blocked_action",
                "action": "ACTION1",
                "times_seen": 2,
                "message": "Environment bottleneck: only ACTION1 is available and it is blocked/no-op after 2 observation(s).",
            },
        }
    )

    await orchestrator.hypothesize(sample_observation, "ACTION1", 2, transition_meta={})
    trace = orchestrator.consume_write_trace()

    assert trace[0]["kind"] == "hypothesis_update"
    detail = trace[0]["detail"]
    assert detail["saved_action_facts"][0]["action"] == "ACTION1"
    assert detail["saved_action_facts"][0]["fact_type"] == "deterministic_effect"
    assert detail["saved_action_facts"][0]["trend"]["direction"] == "up"
    assert detail["saved_path_hypotheses"][0]["actions"] == ["ACTION1", "ACTION3"]
    assert detail["saved_path_hypotheses"][0]["value_status"] == "tentative"
    assert detail["environment_bottleneck"]["type"] == "single_blocked_action"


def test_first_move_filters_memory_without_observation_match(sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    prompt = orchestrator.build_action_prompt(
        sample_observation,
        {"lessons": [], "memories": [{"text": "ACTION7"}], "analogies": [], "_triggered": True},
        step_history=[],
        available_actions=["ACTION1", "ACTION2", "ACTION5"],
    )
    assert "ACTION7" not in prompt
    assert "Matched memory" not in prompt


def test_first_move_keeps_matching_memory(sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    prompt = orchestrator.build_action_prompt(
        sample_observation,
        {"lessons": [], "memories": [{"text": "arc_eval_001 ACTION1 state NOT_FINISHED color 1"}], "analogies": [], "_triggered": True},
        step_history=[],
        available_actions=["ACTION1", "ACTION2", "ACTION5"],
    )
    assert "Matched memory" in prompt


def test_policy_override_forces_unexplored_action(sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._hypothesis_context = {
        "action_coverage": {
            "tested_count": 2,
            "untested_count": 2,
            "untested_actions": ["ACTION3", "ACTION4"],
            "initial_exploration_complete": False,
            "top_two_low_value": False,
        }
    }
    action = orchestrator._enforce_action_policy(
        {"action_id": "ACTION1", "rationale": "tentative_progress"},
        ["ACTION1", "ACTION2", "ACTION3", "ACTION4"],
    )
    assert action["action_id"] == "ACTION3"
    assert "exploration phase requires testing ACTION3" in action["rationale"]


def test_policy_override_broadens_exploration_after_decay(sample_observation):
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._hypothesis_context = {
        "action_coverage": {
            "tested_count": 4,
            "untested_count": 1,
            "untested_actions": ["ACTION4"],
            "initial_exploration_complete": False,
            "top_two_low_value": True,
        }
    }
    action = orchestrator._enforce_action_policy(
        {"action_id": "ACTION2", "rationale": "last low_value"},
        ["ACTION1", "ACTION2", "ACTION3", "ACTION4"],
    )
    assert action["action_id"] == "ACTION4"
    assert "ACTION4" in action["rationale"]


def test_select_ranked_action_prefers_best_under_budget():
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    selected = orchestrator._select_ranked_action([
        {"action": "ACTION1", "rank_score": 0.40, "times_seen": 3, "over_retest_budget": True},
        {"action": "ACTION2", "rank_score": 0.35, "times_seen": 1, "over_retest_budget": False},
        {"action": "ACTION3", "rank_score": 0.10, "times_seen": 0, "over_retest_budget": False},
    ])
    assert selected == "ACTION2"


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
async def test_act_rejects_unavailable_llm_action(mock_brain, sample_observation):
    class InvalidActionLLM:
        def __init__(self):
            self.last_messages = None

        def chat(self, messages):
            self.last_messages = messages
            return json.dumps({"action_id": "ACTION7", "rationale": "bad choice"})

    mock_llm = InvalidActionLLM()
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=mock_llm,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )

    memory_ctx = {"lessons": [], "memories": [], "analogies": []}
    action = await orchestrator.act(sample_observation, memory_ctx, step_num=1)

    assert action["action_id"] == "ACTION1"
    assert "Invalid LLM action" in action["rationale"]


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
        {"lessons": [], "memories": [], "analogies": [], "_triggered": False},
        step_history=[],
        available_actions=["ACTION1"],
    )
    assert "ENERGY" in prompt
    assert "42%" in prompt


# ── B89: Prompt Budget & Retrieval Budget Metrics ──────────────────────────


@pytest.mark.asyncio
async def test_retrieval_payload_size_tracked(mock_brain, sample_observation):
    """B89: perceive() should track retrieval payload sizes."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    await orchestrator.perceive(sample_observation)
    assert len(orchestrator._retrieval_payloads) == 1
    payload = orchestrator._retrieval_payloads[0]
    assert "total_size" in payload
    assert payload["total_size"] >= 0


@pytest.mark.asyncio
async def test_prompt_tokens_estimated_per_step(mock_brain, sample_observation):
    """B89: act() should estimate and track prompt tokens per step."""
    mock_llm = MockLLM()
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=mock_llm,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._reflex_context = {"warnings": [], "suggestions": []}
    memory_ctx = {"lessons": [], "memories": [], "analogies": [], "_retrieval_payload_size": 0}

    await orchestrator.act(sample_observation, memory_ctx, step_num=1)
    assert len(orchestrator._prompt_tokens_per_step) == 1
    assert orchestrator._prompt_tokens_per_step[0] > 0


@pytest.mark.asyncio
async def test_first_prompt_detail_level_tracked(mock_brain, sample_observation):
    """B89: First prompt should track whether it includes rich context."""
    mock_llm = MockLLM()
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=mock_llm,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._reflex_context = {"warnings": [], "suggestions": []}
    memory_ctx = {
        "lessons": [{"text": "lesson"}],  # Non-empty to trigger "rich"
        "memories": ["ctx"],
        "analogies": [],
        "_retrieval_payload_size": 100,
    }

    await orchestrator.act(sample_observation, memory_ctx, step_num=1)
    assert orchestrator._first_prompt_detail_level in ("rich", "compact")


@pytest.mark.asyncio
async def test_no_progress_step_count_incremented_on_zero_reward(mock_brain, sample_observation):
    """B89: record_step_result() should increment no_progress_step_count on zero reward."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    # Simulate a step being recorded
    orchestrator._step_history.append({"step": 1, "reward": None})

    orchestrator.record_step_result(reward=0.0, done=False)
    assert orchestrator._no_progress_step_count == 1

    orchestrator.record_step_result(reward=1.0, done=True)
    assert orchestrator._no_progress_step_count == 1  # Unchanged


def test_get_benchmark_metrics_returns_expected_fields():
    """B89: get_benchmark_metrics() should return all expected metric fields."""
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    # Populate some metrics
    orchestrator._prompt_tokens_per_step = [100, 120, 110]
    orchestrator._retrieval_payloads = [{"total_size": 1000}, {"total_size": 1200}]
    orchestrator._invalid_action_count = 1
    orchestrator._no_progress_step_count = 2
    orchestrator._first_prompt_detail_level = "rich"
    orchestrator._asked_for_decision_from_effects = True

    metrics = orchestrator.get_benchmark_metrics()

    assert "prompt_budget" in metrics
    assert "retrieval_budget" in metrics
    assert metrics["prompt_budget"]["avg_tokens_per_step"] == 110.0
    assert metrics["prompt_budget"]["invalid_action_count"] == 1
    assert metrics["prompt_budget"]["no_progress_step_count"] == 2
    assert metrics["prompt_budget"]["first_prompt_detail_level"] == "rich"
    assert metrics["retrieval_budget"]["retrieval_count"] == 2
    assert metrics["retrieval_budget"]["total_retrieval_size_bytes"] == 2200


# ── B90: Retrieval Trigger Tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieval_triggered_on_initial_bootstrap(mock_brain, sample_observation):
    """B90: perceive() at step=0 should always trigger retrieval."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    ctx = await orchestrator.perceive(sample_observation, step=0)

    assert orchestrator._retrieval_triggered is True
    assert ctx["_triggered"] is True
    assert len(orchestrator._retrieval_payloads) == 1
    mock_brain.current_truth.assert_called_once()
    mock_brain.recall_relevant_lessons.assert_called_once()
    mock_brain.analogical_search.assert_called_once()


@pytest.mark.asyncio
async def test_retrieval_skipped_when_no_trigger_fires(mock_brain, sample_observation):
    """B90: perceive() at step > 0 with no triggers should skip retrieval."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    # Set hypothesis context with no problematic conditions
    orchestrator._hypothesis_context = {
        "loop_detected": False,
        "action_coverage": {
            "tested_count": 1,
            "untested_count": 3,
            "top_two_low_value": False,
        },
        "observed_action_effects": [{"action": "ACTION1", "avg_meaningful_change": 0.5}],
    }
    orchestrator._no_progress_step_count = 0
    orchestrator._invalid_action_count = 0

    ctx = await orchestrator.perceive(sample_observation, step=5)

    assert orchestrator._retrieval_triggered is False
    assert ctx["_triggered"] is False
    assert len(orchestrator._retrieval_payloads) == 0
    mock_brain.current_truth.assert_not_called()
    mock_brain.recall_relevant_lessons.assert_not_called()
    mock_brain.analogical_search.assert_not_called()


@pytest.mark.asyncio
async def test_retrieval_triggered_on_loop_detection(mock_brain, sample_observation):
    """B90: perceive() should trigger retrieval when loop is detected."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._hypothesis_context = {
        "loop_detected": True,
        "loop_hash": "hash123",
        "action_coverage": {},
        "observed_action_effects": [],
    }

    ctx = await orchestrator.perceive(sample_observation, step=5)

    assert orchestrator._retrieval_triggered is True
    assert ctx["_triggered"] is True
    mock_brain.current_truth.assert_called_once()


@pytest.mark.asyncio
async def test_retrieval_triggered_on_no_progress(mock_brain, sample_observation):
    """B90: perceive() should trigger retrieval when no-progress streak persists."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._no_progress_step_count = 3
    orchestrator._consecutive_no_progress_steps = 3
    orchestrator._last_retrieval_step = -1
    orchestrator._hypothesis_context = {
        "loop_detected": False,
        "action_coverage": {},
        "observed_action_effects": [],
    }

    ctx = await orchestrator.perceive(sample_observation, step=5)

    assert orchestrator._retrieval_triggered is True
    assert ctx["_triggered"] is True
    mock_brain.current_truth.assert_called_once()


@pytest.mark.asyncio
async def test_retrieval_triggered_on_invalid_action_count(mock_brain, sample_observation):
    """B90: perceive() should trigger retrieval after an invalid action fallback."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._invalid_action_count = 1
    orchestrator._hypothesis_context = {
        "loop_detected": False,
        "action_coverage": {},
        "observed_action_effects": [],
    }

    ctx = await orchestrator.perceive(sample_observation, step=5)

    assert orchestrator._retrieval_triggered is True
    assert ctx["_triggered"] is True
    mock_brain.current_truth.assert_called_once()


@pytest.mark.asyncio
async def test_retrieval_triggered_on_top_two_low_value(mock_brain, sample_observation):
    """B90: perceive() should trigger retrieval when top actions decay to low_value."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._hypothesis_context = {
        "loop_detected": False,
        "action_coverage": {
            "tested_count": 2,
            "untested_count": 2,
            "top_two_low_value": True,
        },
        "observed_action_effects": [],
    }

    ctx = await orchestrator.perceive(sample_observation, step=5)

    assert orchestrator._retrieval_triggered is True
    assert ctx["_triggered"] is True
    mock_brain.current_truth.assert_called_once()


@pytest.mark.asyncio
async def test_retrieval_triggered_on_large_state_shift(mock_brain, sample_observation):
    """B90: perceive() should trigger retrieval when the latest change is large enough to invalidate assumptions."""
    orchestrator = ARCOrchestrator(
        brain_client=mock_brain,
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._hypothesis_context = {
        "loop_detected": False,
        "action_coverage": {},
        "observed_action_effects": [],
        "last_transition_effect": {
            "meaningful_change_score": 0.8,
            "pixels_changed": 40,
        },
    }

    ctx = await orchestrator.perceive(sample_observation, step=5)

    assert orchestrator._retrieval_triggered is True
    assert ctx["_triggered"] is True
    mock_brain.current_truth.assert_called_once()


def test_prompt_memory_section_excluded_when_not_triggered(sample_observation):
    """B90: build_action_prompt() should exclude MEMORY section when retrieval not triggered."""
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    # Memory context with _triggered=False (no retrieval)
    memory_ctx = {
        "lessons": [{"text": "this should not appear"}],
        "memories": [{"text": "also should not appear"}],
        "analogies": [],
        "_triggered": False,
    }

    prompt = orchestrator.build_action_prompt(
        sample_observation,
        memory_ctx,
        step_history=[],
        available_actions=["ACTION1", "ACTION2"],
    )

    assert "MEMORY:" not in prompt
    assert "this should not appear" not in prompt
    assert "also should not appear" not in prompt


def test_prompt_memory_section_included_when_triggered(sample_observation):
    """B90: build_action_prompt() should include MEMORY section when retrieval triggered."""
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    # Memory context with _triggered=True (retrieval happened)
    memory_ctx = {
        "lessons": [{"text": "important lesson"}],
        "memories": [{"text": "relevant memory"}],
        "analogies": [],
        "_triggered": True,
    }

    prompt = orchestrator.build_action_prompt(
        sample_observation,
        memory_ctx,
        step_history=[],
        available_actions=["ACTION1", "ACTION2"],
    )

    assert "MEMORY:" in prompt
    assert "important lesson" in prompt


def test_prompt_smaller_on_no_trigger_path(sample_observation):
    """B90: Prompt size should be smaller when retrieval is not triggered."""
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )

    # Prompt with no retrieval
    memory_ctx_no_trigger = {
        "lessons": [],
        "memories": [],
        "analogies": [],
        "_triggered": False,
    }
    prompt_no_trigger = orchestrator.build_action_prompt(
        sample_observation,
        memory_ctx_no_trigger,
        step_history=[],
        available_actions=["ACTION1", "ACTION2"],
    )

    # Prompt with retrieval
    memory_ctx_triggered = {
        "lessons": [{"text": "long lesson text that adds size to the prompt"}],
        "memories": [{"text": "long memory text that also adds size"}],
        "analogies": [{"text": "analogy text"}],
        "_triggered": True,
    }
    prompt_triggered = orchestrator.build_action_prompt(
        sample_observation,
        memory_ctx_triggered,
        step_history=[],
        available_actions=["ACTION1", "ACTION2"],
    )

    assert len(prompt_no_trigger) < len(prompt_triggered)


def test_prompt_instruction_includes_effect_summary(sample_observation):
    """B90: INSTRUCTION section should include observed effect summary."""
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    orchestrator._hypothesis_context = {
        "last_transition_effect": {
            "action": "ACTION1",
            "meaningful_change_label": "strong_progress",
            "meaningful_change_score": 0.85,
        }
    }

    memory_ctx = {"lessons": [], "memories": [], "analogies": [], "_triggered": False}
    prompt = orchestrator.build_action_prompt(
        sample_observation,
        memory_ctx,
        step_history=[],
        available_actions=["ACTION1", "ACTION2"],
    )

    assert "Last action ACTION1 caused strong_progress" in prompt
    assert "0.85" in prompt
    assert "What should you try next?" in prompt
    assert "Choose the next valid action based on observed effects" in prompt


def test_prompt_instruction_handles_no_prior_effects(sample_observation):
    """B90: INSTRUCTION should handle case when no prior effects exist."""
    orchestrator = ARCOrchestrator(
        brain_client=MagicMock(),
        llm_client=None,
        session_id="session",
        serializer=StateSerializerForARC(),
        config={},
    )
    # No hypothesis context, or no last_transition_effect
    orchestrator._hypothesis_context = None

    memory_ctx = {"lessons": [], "memories": [], "analogies": [], "_triggered": False}
    prompt = orchestrator.build_action_prompt(
        sample_observation,
        memory_ctx,
        step_history=[],
        available_actions=["ACTION1", "ACTION2"],
    )

    assert "No prior action effects recorded yet" in prompt
    assert "What should you try next?" in prompt
    assert "Choose the next valid action based on observed effects" in prompt
