import json
from unittest.mock import MagicMock

from agents.arc3.failure_taxonomy import FailureTaxonomy, classify_failure
from agents.arc3.runner import DurableARCRunner
from benchmarks.arc3.adapter import NoOpBrainClient


def _make_runner() -> DurableARCRunner:
    harness = MagicMock()
    harness.mock_api = True
    return DurableARCRunner(harness, NoOpBrainClient(), config={"llm": {"model": "test"}})


def test_classify_failure_timeout():
    result = classify_failure(TimeoutError("LLM request timed out after 30s"))
    assert result is FailureTaxonomy.LLM_TIMEOUT


def test_classify_failure_parse_error():
    err = json.JSONDecodeError("Expecting value", "{", 0)
    result = classify_failure(err)
    assert result is FailureTaxonomy.LLM_PARSE_ERROR


def test_classify_failure_api_error():
    result = classify_failure(RuntimeError("400 Bad Request from ARC API"))
    assert result is FailureTaxonomy.API_ERROR


def test_classify_failure_budget_exceeded():
    result = classify_failure(error_message="Budget exhausted ($0.02)", budget_exhausted=True)
    assert result is FailureTaxonomy.BUDGET_EXCEEDED


def test_classify_failure_stuck_in_loop():
    result = classify_failure(
        error_message="Max attempts reached across all retries",
        final_state="NOT_FINISHED",
        max_steps_reached=True,
        no_progress_steps=20,
        loop_detected=True,
    )
    assert result is FailureTaxonomy.STUCK_IN_LOOP


def test_classify_failure_max_steps_reached():
    result = classify_failure(
        error_message="Max attempts reached across all retries",
        final_state="NOT_FINISHED",
        max_steps_reached=True,
        no_progress_steps=3,
    )
    assert result is FailureTaxonomy.MAX_STEPS_REACHED


def test_classify_failure_crash_fallback():
    result = classify_failure(RuntimeError("boom"))
    assert result is FailureTaxonomy.CRASH


def test_classify_failure_strategy_exhausted_without_exception():
    result = classify_failure(exc=None, final_state="GAME_OVER")
    assert result is FailureTaxonomy.STRATEGY_EXHAUSTED


def test_submission_row_includes_failure_class():
    runner = _make_runner()
    row = runner._submission_row_from_result(
        {
            "task_id": "task-1",
            "game_id": "game-1",
            "correct": False,
            "steps": 10,
            "tokens_input": 1,
            "tokens_output": 2,
            "runtime_seconds": 1.2,
            "final_state": "NOT_FINISHED",
            "error_message": "Max attempts reached across all retries",
            "failure_class": FailureTaxonomy.MAX_STEPS_REACHED.value,
        }
    )

    assert row["failure_class"] == FailureTaxonomy.MAX_STEPS_REACHED.value
    assert row["metadata"]["failure_class"] == FailureTaxonomy.MAX_STEPS_REACHED.value
