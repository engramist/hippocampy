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
    checkpoint.tasks["task-1"].result = {
        "task_id": "task-1",
        "steps": 2,
        "runtime_seconds": 0,
        "final_state": "WIN",
        "final_observation": {"grid": [[0]]},
    }
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
async def test_reruns_stale_completed_checkpoint_result(tmp_path):
    """A completed checkpoint without terminal payload should be re-run."""
    CheckpointManager.CHECKPOINT_DIR = tmp_path
    tasks = _sample_tasks()
    harness = _make_stub_harness()
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}})

    mgr = CheckpointManager("card-stale")
    checkpoint = mgr.load_or_create(tasks)
    checkpoint.tasks["task-1"].status = "complete"
    checkpoint.tasks["task-1"].result = {
        "task_id": "task-1",
        "steps": 2,
        "runtime_seconds": 0,
        # intentionally missing final_state/final_observation
    }
    mgr.save(checkpoint)

    run1 = ABTaskResult(
        task_id="task-1",
        variant=ABVariant.SIDEQUESTS,
        correct=True,
        steps=1,
        tokens_input=1,
        tokens_output=1,
        final_state="WIN",
        final_observation={"grid": [[1]]},
    )
    run2 = ABTaskResult(
        task_id="task-2",
        variant=ABVariant.SIDEQUESTS,
        correct=True,
        steps=1,
        tokens_input=1,
        tokens_output=1,
        final_state="WIN",
        final_observation={"grid": [[2]]},
    )
    runner._run_puzzle = AsyncMock(side_effect=[(run1, 0.1), (run2, 0.1)])

    results = await runner.run(tasks, "card-stale")

    assert runner._run_puzzle.call_count == 2
    assert [r["task_id"] for r in results] == ["task-1", "task-2"]
    assert results[0]["predictions"] == [[[1]]]


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


@pytest.mark.asyncio
async def test_real_api_path_uses_http_session(tmp_path):
    """When mock_api is false, the durable runner should call the HTTP session."""
    CheckpointManager.CHECKPOINT_DIR = tmp_path
    harness = _make_stub_harness()
    harness.mock_api = False
    harness._session = AsyncMock()
    harness._session.post = AsyncMock(
        side_effect=[
            MagicMock(
                json=MagicMock(return_value={"card_id": "card-123"}),
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                json=MagicMock(
                    return_value={"frame": [[[1]]], "state": "NOT_FINISHED", "guid": "guid-1"}
                ),
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                json=MagicMock(
                    return_value={"frame": [[[1]]], "state": "WIN", "guid": "guid-2"}
                ),
                raise_for_status=MagicMock(),
            ),
        ]
    )
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}})
    task = _sample_tasks()[0]

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
    assert harness._session.post.await_count == 3
    harness._get_mock_initial_frame.assert_not_called()
    assert result.steps == 1


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


def test_submission_row_includes_debug_fields():
    harness = _make_stub_harness()
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}})

    row = runner._submission_row_from_result(
        {
            "game_id": "live-game-123",
            "task_id": "arc_eval_001",
            "correct": False,
            "runtime_seconds": 12.34,
            "steps": 2,
            "tokens_input": 10,
            "tokens_output": 3,
            "final_state": "NOT_FINISHED",
            "final_observation": {"grid": [[1, 2], [3, 4]]},
            "bootstrap_write_trace": [
                {
                    "phase": "bootstrap",
                    "kind": "notify_turn",
                    "summary": "ingested structure",
                }
            ],
            "final_write_trace": [
                {
                    "phase": "finalization",
                    "kind": "report_outcome",
                    "summary": "plan plan-1 outcome=failed valence=-0.70",
                }
            ],
            "debug_steps": [
                {
                    "step": 1,
                    "state_before": "NOT_STARTED",
                    "board_before": {
                        "frame_hash": "before123",
                        "rows": 2,
                        "cols": 2,
                        "top_colors": [{"value": 1, "count": 2}],
                        "coarse_map": "1 1\n1 1",
                    },
                    "available_actions": ["ACTION1", "ACTION6"],
                    "prompt": "prompt 1",
                    "action_id": "ACTION1",
                    "rationale": "test move",
                    "reward": 0.0,
                    "done": False,
                    "state_after": "NOT_FINISHED",
                    "board_after": {
                        "frame_hash": "after123",
                        "rows": 2,
                        "cols": 2,
                        "top_colors": [{"value": 2, "count": 2}],
                        "coarse_map": "2 2\n2 2",
                    },
                    "write_trace": [
                        {
                            "phase": "step-1",
                            "kind": "hypothesis_update",
                            "summary": "ACTION1 -> tentative_progress (score 0.41); facts=1 paths=1",
                            "detail": {
                                "saved_action_facts": [
                                    {
                                        "action": "ACTION1",
                                        "fact_type": "deterministic_effect",
                                        "value_status": "tentative",
                                        "trend": {
                                            "kind": "directional_drift",
                                            "axis": "col",
                                            "direction": "left",
                                            "avg_delta": 1.0,
                                        },
                                    }
                                ],
                                "saved_path_hypotheses": [
                                    {
                                        "actions": ["ACTION1", "ACTION2"],
                                        "value_status": "tentative",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )

    assert row["game_id"] == "live-game-123"
    assert row["task_id"] == "arc_eval_001"
    assert row["correct"] is False
    assert row["steps"] == 2
    assert "final_grid" not in row
    assert row["bootstrap_write_trace"][0]["kind"] == "notify_turn"
    assert row["predictions"] == [[[1, 2], [3, 4]]]
    assert row["progress_log"][0]["action_id"] == "ACTION1"
    assert row["progress_log"][0]["board_before"]["frame_hash"] == "before123"
    assert row["progress_log"][0]["board_after"]["frame_hash"] == "after123"
    assert row["progress_log"][0]["write_trace"][0]["kind"] == "hypothesis_update"
    assert row["progress_log"][0]["write_trace"][0]["detail"]["saved_action_facts"][0]["action"] == "ACTION1"
    assert row["progress_log"][0]["write_trace"][0]["detail"]["saved_action_facts"][0]["trend"]["direction"] == "left"
    assert row["progress_log"][0]["write_trace"][0]["detail"]["saved_path_hypotheses"][0]["actions"] == ["ACTION1", "ACTION2"]
    assert row["prompt_trace"][0]["prompt"] == "prompt 1"
    assert row["confidence"] == [0.0]
    assert row["final_write_trace"][0]["kind"] == "report_outcome"


# ── B89: Benchmark Metrics ──────────────────────────────────────────────


def test_submission_row_includes_benchmark_metrics():
    """B89: _submission_row_from_result should include benchmark_metrics in metadata."""
    harness = _make_stub_harness()
    runner = DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}})

    result = {
        "task_id": "task-1",
        "game_id": "game-1",
        "steps": 5,
        "correct": True,
        "tokens_input": 1000,
        "tokens_output": 200,
        "runtime_seconds": 10.5,
        "final_state": "WIN",
        "final_observation": {"grid": [[0, 1]]},
        "benchmark_metrics": {
            "prompt_budget": {
                "total_steps": 5,
                "avg_tokens_per_step": 120.0,
                "max_tokens_per_step": 150,
                "min_tokens_per_step": 100,
                "first_prompt_detail_level": "rich",
                "asked_for_decision_from_effects": True,
                "invalid_action_count": 0,
                "no_progress_step_count": 1,
            },
            "retrieval_budget": {
                "retrieval_count": 1,
                "total_retrieval_size_bytes": 1500,
                "avg_retrieval_size_bytes": 1500,
            },
        },
    }

    row = runner._submission_row_from_result(result)
    assert "metadata" in row
    assert "benchmark_metrics" in row["metadata"]
    assert row["metadata"]["benchmark_metrics"]["prompt_budget"]["avg_tokens_per_step"] == 120.0
    assert row["metadata"]["benchmark_metrics"]["retrieval_budget"]["retrieval_count"] == 1
