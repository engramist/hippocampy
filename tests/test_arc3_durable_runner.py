"""Tests for DurableARCRunner and loop worker robustness."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from benchmarks.ab_harness import ABTask, ABTaskResult, ABVariant, BenchmarkConfig
from benchmarks.arc3.submission import SubmissionRunner
from benchmarks.arc3.adapter import NoOpBrainClient
from agents.arc3.checkpoint import CheckpointManager
from agents.arc3.runner import DurableARCRunner


def _sample_tasks() -> list[ABTask]:
    tasks = [
        ABTask(task_id="task-1", category="c", prompt="p1"),
        ABTask(task_id="task-2", category="c", prompt="p2"),
    ]
    for task in tasks:
        setattr(task, "game_id", "g")
    return tasks


def _make_stub_harness() -> MagicMock:
    harness = MagicMock()
    harness.llm_client = None
    harness.serializer = MagicMock()
    harness.serializer._estimate_tokens.return_value = 1
    harness.config = BenchmarkConfig(name="dummy", parameters={"max_attempts_per_puzzle": 3})
    harness.mock_api = True
    harness._get_mock_initial_frame = MagicMock(return_value={"frame": [[[0]]]})
    harness._execute_mock_action = MagicMock(return_value=({"frame": [[[0]]]}, 1.0, True))
    return harness



@pytest.mark.asyncio
async def test_skips_completed_tasks(tmp_path):
    CheckpointManager.CHECKPOINT_DIR = tmp_path
    tasks = _sample_tasks()
    harness = _make_stub_harness()
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}})

    mgr = CheckpointManager("card-1")
    checkpoint = mgr.load_or_create(tasks)
    checkpoint.tasks["task-1"].status = "complete"
    checkpoint.tasks["task-1"].result = {"task_id": "task-1", "steps": 2, "runtime_seconds": 0}
    mgr.save(checkpoint)

    runner._run_puzzle = AsyncMock(return_value=(
        ABTaskResult(task_id="task-2", variant=ABVariant.SIDEQUESTS, correct=True, steps=1, tokens_input=1, tokens_output=1),
        0.1,
    ))

    results = await runner.run(tasks, "card-1")
    assert len(results) == 2
    runner._run_puzzle.assert_called_once()
    assert results[0]["task_id"] == "task-1"
    assert results[1]["task_id"] == "task-2"


@pytest.mark.asyncio
async def test_continues_after_task_failure(tmp_path):
    CheckpointManager.CHECKPOINT_DIR = tmp_path
    tasks = _sample_tasks()
    harness = _make_stub_harness()
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}})

    async def _side_effect(*_):
        raise RuntimeError("boom")

    success_result = ABTaskResult(
        task_id="task-2",
        variant=ABVariant.SIDEQUESTS,
        correct=True,
        steps=1,
        tokens_input=1,
        tokens_output=1,
    )

    runner._run_puzzle = AsyncMock(side_effect=[RuntimeError("boom"), (success_result, 0.2)])

    results = await runner.run(tasks, "card-2")
    assert len(results) == 1
    runner._run_puzzle.assert_called()
    mgr = CheckpointManager("card-2")
    mgr.CHECKPOINT_DIR = tmp_path
    cp = mgr.load_or_create(tasks)
    assert cp.tasks["task-1"].status == "failed"
    assert cp.tasks["task-2"].status == "complete"


@pytest.mark.asyncio
async def test_loop_worker_survives_error(monkeypatch):
    runner = SubmissionRunner()
    runner.db = MagicMock()
    runner.config = {"llm": {"provider": "ollama", "model": "test"}}

    fake_llm = MagicMock()
    monkeypatch.setattr("mcp_engine.llm.provider.create_llm_client", MagicMock(return_value=fake_llm))

    call_order = []

    async def _fake_run_loop(**kwargs):
        call_order.append(kwargs)
        if len(call_order) == 1:
            raise RuntimeError("boom")
        return True

    monkeypatch.setattr("mcp_engine.loop.orchestrator.run_loop", _fake_run_loop)

    worker = asyncio.create_task(runner._loop_worker([]))
    await runner.loop_queue.put(("id1", "text", "user", "session"))
    await runner.loop_queue.put(("id2", "text", "user", "session"))
    await asyncio.wait_for(runner.loop_queue.join(), timeout=2)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert len(call_order) == 2


@pytest.mark.asyncio
async def test_noop_client_all_methods():
    client = NoOpBrainClient()
    plan = await client.register_plan(goal="g", steps=["a"], session_id="s")
    assert plan["plan_id"] is None
    outcome = await client.report_outcome(plan_id="p", outcome="ok", valence=0.5, session_id="s")
    assert outcome["updated"] is False
    recalled = await client.recall_plans(goal_query="g", session_id="s", min_valence=0.0, limit=5)
    assert recalled["plans"] == []
    lessons = await client.recall_relevant_lessons(query="q", limit=5)
    assert lessons["lessons"] == []
    analogies = await client.analogical_search(query="q", current_quest_id="c", limit=5, min_similarity=0.7)
    assert analogies["results"] == []


@pytest.mark.asyncio
async def test_noop_client_branch_quest():
    client = NoOpBrainClient()
    result = await client.branch_quest(name="test", purpose="p", parent_quest_id="q")
    assert result["side_quest_id"] is None


@pytest.mark.asyncio
async def test_state_win_stops_puzzle(tmp_path):
    """When state is WIN, _run_puzzle should set success=True even with reward=0."""
    CheckpointManager.CHECKPOINT_DIR = tmp_path
    harness = _make_stub_harness()
    # Return frame with WIN state, reward=0, done=False to ensure state drives the outcome
    harness._execute_mock_action = MagicMock(
        return_value=({"frame": [[[0]]], "state": "WIN", "available_actions": []}, 0.0, False)
    )
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}})
    tasks = _sample_tasks()
    task = tasks[0]
    from agents.arc3.orchestrator import ARCOrchestrator
    from benchmarks.arc3.state_serializer import StateSerializerForARC
    orch = ARCOrchestrator(
        brain_client=NoOpBrainClient(),
        llm_client=None,
        session_id="s",
        serializer=StateSerializerForARC(),
        config={},
    )
    result, _ = await runner._run_puzzle(orch, task)
    assert result.correct is True


@pytest.mark.asyncio
async def test_state_game_over_retries_then_fails(tmp_path):
    """When state is GAME_OVER on every attempt, _run_puzzle retries then fails."""
    CheckpointManager.CHECKPOINT_DIR = tmp_path
    harness = _make_stub_harness()
    harness._execute_mock_action = MagicMock(
        return_value=({"frame": [[[0]]], "state": "GAME_OVER", "available_actions": []}, 0.0, False)
    )
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}, "max_retries_per_puzzle": 2})
    tasks = _sample_tasks()
    task = tasks[0]
    from agents.arc3.orchestrator import ARCOrchestrator
    from benchmarks.arc3.state_serializer import StateSerializerForARC
    orch = ARCOrchestrator(
        brain_client=NoOpBrainClient(),
        llm_client=None,
        session_id="s",
        serializer=StateSerializerForARC(),
        config={},
    )
    result, _ = await runner._run_puzzle(orch, task)
    assert result.correct is False
    assert "2 attempt" in result.response_text


@pytest.mark.asyncio
async def test_game_over_then_win_on_retry(tmp_path):
    """Agent fails first attempt with GAME_OVER, wins on second attempt."""
    CheckpointManager.CHECKPOINT_DIR = tmp_path
    harness = _make_stub_harness()
    # First call: GAME_OVER, second call: WIN
    harness._execute_mock_action = MagicMock(
        side_effect=[
            ({"frame": [[[0]]], "state": "GAME_OVER", "available_actions": []}, 0.0, False),
            ({"frame": [[[0]]], "state": "WIN", "available_actions": []}, 1.0, True),
        ]
    )
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}, "max_retries_per_puzzle": 3})
    tasks = _sample_tasks()
    task = tasks[0]
    from agents.arc3.orchestrator import ARCOrchestrator
    from benchmarks.arc3.state_serializer import StateSerializerForARC
    orch = ARCOrchestrator(
        brain_client=NoOpBrainClient(),
        llm_client=None,
        session_id="s",
        serializer=StateSerializerForARC(),
        config={},
    )
    result, _ = await runner._run_puzzle(orch, task)
    assert result.correct is True
    assert result.steps == 2  # one step per attempt


@pytest.mark.asyncio
async def test_run_calls_branch_quest_per_task(tmp_path):
    """Each puzzle should get its own branch_quest call."""
    CheckpointManager.CHECKPOINT_DIR = tmp_path
    tasks = _sample_tasks()
    harness = _make_stub_harness()
    brain = NoOpBrainClient()
    brain.branch_quest = AsyncMock(return_value={"side_quest_id": "sq-1"})
    runner = DurableARCRunner(harness, brain, config={"llm": {"model": "test"}})
    runner._run_puzzle = AsyncMock(return_value=(
        ABTaskResult(task_id="task-1", variant=ABVariant.SIDEQUESTS, correct=True, steps=1, tokens_input=1, tokens_output=1),
        0.1,
    ))
    await runner.run(tasks, "card-branch")
    assert brain.branch_quest.call_count == len(tasks)
