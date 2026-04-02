
import pytest
import time
import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from agents.arc3.runner import DurableARCRunner
from benchmarks.ab_harness import ABTask, ABVariant
from benchmarks.arc3.adapter import NoOpBrainClient

@pytest.mark.asyncio
async def test_b130_logging_requirements():
    # Setup stub harness and runner
    harness = MagicMock()
    harness.mock_api = True
    harness.llm_client = AsyncMock()
    harness.serializer = MagicMock()
    harness.serializer._estimate_tokens.return_value = 10
    
    # B130: properly setup config to avoid MagicMock in numeric comparisons
    harness.config = MagicMock()
    harness.config.parameters = {"max_attempts_per_puzzle": 5}
    
    # Mock initial frame
    harness._get_mock_initial_frame.return_value = {
        "frame": [[0]], "guid": "g1", "state": "NOT_FINISHED", "available_actions": ["ACTION1"]
    }
    # Mock action to succeed then end
    harness._execute_mock_action.return_value = (
        {"frame": [[1]], "guid": "g2", "state": "WIN", "available_actions": []}, 1.0, True
    )

    runner = DurableARCRunner(harness, NoOpBrainClient(), config={
        "llm": {"model": "gpt-4o"},
        "max_retries_per_puzzle": 1,
        "max_steps_per_puzzle": 5
    })
    task = ABTask(task_id="b130-test", category="test", prompt="p")
    setattr(task, "game_id", "game-b130")

    # Mock orchestrator behavior
    with patch("agents.arc3.runner.ARCOrchestrator") as mock_orch_cls:
        mock_orch = mock_orch_cls.return_value
        mock_orch.perceive = AsyncMock(return_value={})
        mock_orch.plan = AsyncMock(return_value={})
        mock_orch.hypothesize = AsyncMock(return_value={})
        mock_orch.solve = AsyncMock(return_value={})
        mock_orch.act = AsyncMock(return_value={"action_id": "ACTION1"})
        mock_orch.evaluate = AsyncMock(return_value={})
        mock_orch.hypothesis_mgr.distill_to_brain = AsyncMock()
        mock_orch.set_write_trace_context = MagicMock()
        mock_orch.consume_write_trace.return_value = []
        mock_orch._step_history = [{
            "step": 1,
            "action_id": "ACTION1",
            "solve_context": {"archetype": "test"},
            "timestamp_iso": "2026-04-02T12:00:00Z",
            "elapsed_mmss": "00:01"
        }]
        mock_orch.get_benchmark_metrics.return_value = {}
        mock_orch._plan_id = "p1"
        
        # B130: avoid JSON serialization error by mocking CheckpointManager
        with patch("agents.arc3.runner.CheckpointManager") as mock_mgr_cls:
            mock_mgr = mock_mgr_cls.return_value
            mock_mgr.load_or_create.return_value = MagicMock(tasks={})
            
            # Run the puzzle
            results = await runner.run([task], "card-b130")
    
    assert len(results) == 1
    res = results[0]
    ledger = res["sidequests_ledger"]
    
    # 1. Verify arc_api_io presence and structure
    arc_calls = [e for e in ledger if e["call_type"] == "arc_api_action"]
    assert len(arc_calls) >= 2 # RESET and ACTION1
    
    for i, call in enumerate(arc_calls):
        assert "arc_api_io" in call
        io = call["arc_api_io"]
        assert "request" in io
        assert "response" in io
        assert "call_seq" in io
        # 2. call_seq monotonicity
        assert io["call_seq"] == i + 1
        
        # 3. Timestamp and elapsed formatting
        assert "timestamp_iso" in call
        assert "elapsed_mmss" in call
        assert "Z" in call["timestamp_iso"]
        assert ":" in call["elapsed_mmss"]

    # 4. Submission metadata Renaming
    assert "submission_metadata" in res
    meta = res["submission_metadata"]
    assert "created_at" in meta
    assert "submission_id" in meta
    assert meta["environment"]["arc_api_endpoint"] == "mock-harness"

@pytest.mark.asyncio
async def test_b130_failure_path_logging():
    harness = MagicMock()
    harness.mock_api = False # trigger real session path
    harness._session = AsyncMock()
    harness.config = MagicMock()
    harness.config.parameters = {"max_attempts_per_puzzle": 5}
    
    # Mock /api/scorecard/open to succeed
    harness._session.post.side_effect = [
        MagicMock(json=lambda: {"card_id": "c1"}, raise_for_status=lambda: None), # scorecard/open
        RuntimeError("API Timeout") # RESET fails
    ]

    runner = DurableARCRunner(harness, NoOpBrainClient(), config={
        "llm": {"model": "gpt-4o"},
        "max_retries_per_puzzle": 1,
        "max_steps_per_puzzle": 5
    })
    task = ABTask(task_id="b130-fail", category="test", prompt="p")
    setattr(task, "game_id", "game-fail")

    # We expect the runner to catch or propagate, but _ledger should still have the failure
    with pytest.raises(RuntimeError, match="API Timeout"):
        await runner._run_puzzle(MagicMock(), task)
    
    ledger = runner._ledger
    fail_call = [e for e in ledger if e["call_type"] == "arc_api_action" and e["arc_api_io"]["response"]["received"] is False]
    assert len(fail_call) == 1
    io = fail_call[0]["arc_api_io"]
    assert io["response"]["error"]["error_type"] == "RuntimeError"
    assert "API Timeout" in io["response"]["error"]["error_message"]
