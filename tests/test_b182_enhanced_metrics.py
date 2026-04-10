import pytest

from benchmarks.ab_harness import ABHarness, ABTaskResult, ABVariant, BenchmarkConfig, ABRunMetadata


@pytest.fixture
def harness() -> ABHarness:
    return ABHarness(BenchmarkConfig(name="b182-metrics", parameters={}))


def test_compute_metrics_reports_four_quality_dimensions(harness: ABHarness):
    results = [
        ABTaskResult(
            task_id="task-1",
            variant=ABVariant.BASELINE,
            correct=True,
            steps=2,
            tokens_input=100,
            tokens_output=50,
            attempts=1,
            cost_usd=0.02,
            invalid_action_count=0,
            dissonance_triggered=False,
            judge_verdict={"composite_score": 4.0, "reasoning_score": 4, "archetype": "copy"},
        ),
        ABTaskResult(
            task_id="task-2",
            variant=ABVariant.BASELINE,
            correct=False,
            steps=4,
            tokens_input=120,
            tokens_output=60,
            error_message="stuck",
            failure_class="stuck_in_loop",
            attempts=2,
            cost_usd=0.03,
            invalid_action_count=2,
            dissonance_triggered=True,
            judge_verdict={"composite_score": 3.5, "reasoning_score": 2, "archetype": "copy"},
        ),
        ABTaskResult(
            task_id="task-3",
            variant=ABVariant.BASELINE,
            correct=False,
            steps=1,
            tokens_input=50,
            tokens_output=20,
            error_message="timeout",
            failure_class="llm_timeout",
            attempts=1,
            cost_usd=0.01,
            invalid_action_count=1,
            dissonance_triggered=False,
            judge_verdict={"composite_score": 1.0, "reasoning_score": 1, "archetype": "transform"},
        ),
    ]

    metrics = harness._compute_metrics(results)

    assert set(metrics["quality_dimensions"].keys()) == {
        "effectiveness",
        "efficiency",
        "robustness",
        "safety_alignment",
    }
    assert len(metrics["quality_dimensions"]["effectiveness"]) >= 3
    assert len(metrics["quality_dimensions"]["efficiency"]) >= 3
    assert len(metrics["quality_dimensions"]["robustness"]) >= 3
    assert len(metrics["quality_dimensions"]["safety_alignment"]) >= 3

    assert metrics["solve_rate"] == pytest.approx(0.3333, rel=1e-3)
    assert metrics["judge_score_avg"] == pytest.approx(2.83, rel=1e-3)
    assert metrics["near_miss_rate"] == pytest.approx(0.3333, rel=1e-3)
    assert metrics["judge_score_by_archetype"]["copy"] == pytest.approx(3.75, rel=1e-3)

    assert metrics["avg_steps_per_solve"] == 2.0
    assert metrics["avg_tokens_per_solve"] == 150.0
    assert metrics["avg_cost_per_solve"] == 0.02
    assert metrics["tokens_per_step"] == pytest.approx(57.14, rel=1e-3)
    assert metrics["cost_per_step"] == pytest.approx(0.0086, rel=1e-3)

    assert metrics["timeout_rate"] == pytest.approx(0.3333, rel=1e-3)
    assert metrics["loop_stuck_rate"] == pytest.approx(0.3333, rel=1e-3)
    assert metrics["retry_rate"] == pytest.approx(0.3333, rel=1e-3)

    assert metrics["invalid_action_rate"] == pytest.approx(0.4286, rel=1e-3)
    assert metrics["dissonance_trigger_rate"] == pytest.approx(0.3333, rel=1e-3)
    assert metrics["hallucination_rate"] == pytest.approx(0.3333, rel=1e-3)


def test_compute_metrics_returns_na_when_optional_signals_are_missing(harness: ABHarness):
    results = [
        ABTaskResult(
            task_id="task-1",
            variant=ABVariant.BASELINE,
            correct=True,
            steps=1,
            tokens_input=10,
            tokens_output=5,
        ),
        ABTaskResult(
            task_id="task-2",
            variant=ABVariant.BASELINE,
            correct=False,
            steps=2,
            tokens_input=10,
            tokens_output=5,
            error_message="failed",
        ),
    ]

    metrics = harness._compute_metrics(results)

    assert metrics["judge_score_avg"] == "N/A"
    assert metrics["near_miss_rate"] == "N/A"
    assert metrics["avg_cost_per_solve"] == "N/A"
    assert metrics["crash_rate"] == "N/A"
    assert metrics["invalid_action_rate"] == "N/A"
    assert metrics["dissonance_trigger_rate"] == "N/A"
    assert metrics["hallucination_rate"] == "N/A"


def test_compare_results_includes_deltas_for_new_metrics(harness: ABHarness):
    baseline = [
        ABTaskResult(
            task_id="task-1",
            variant=ABVariant.BASELINE,
            correct=False,
            steps=4,
            tokens_input=100,
            tokens_output=50,
            error_message="loop",
            failure_class="stuck_in_loop",
            attempts=2,
            cost_usd=0.04,
            invalid_action_count=2,
            dissonance_triggered=True,
            judge_verdict={"composite_score": 3.0, "reasoning_score": 1, "archetype": "copy"},
        )
    ]
    sidequests = [
        ABTaskResult(
            task_id="task-1",
            variant=ABVariant.SIDEQUESTS,
            correct=True,
            steps=2,
            tokens_input=80,
            tokens_output=40,
            attempts=1,
            cost_usd=0.01,
            invalid_action_count=0,
            dissonance_triggered=False,
            judge_verdict={"composite_score": 4.0, "reasoning_score": 4, "archetype": "copy"},
        )
    ]

    baseline_meta = ABRunMetadata(
        run_id="baseline-run",
        variant=ABVariant.BASELINE,
        timestamp="2026-01-01T00:00:00Z",
        seed=42,
        model="test-model",
        task_set_hash="hash",
        total_tasks=1,
        succeeded=0,
        failed=1,
        total_tokens=150,
        wall_time_seconds=1.0,
    )
    sidequests_meta = ABRunMetadata(
        run_id="sidequests-run",
        variant=ABVariant.SIDEQUESTS,
        timestamp="2026-01-01T00:00:01Z",
        seed=42,
        model="test-model",
        task_set_hash="hash",
        total_tasks=1,
        succeeded=1,
        failed=0,
        total_tokens=120,
        wall_time_seconds=1.0,
    )

    comparison = harness._compare_results(baseline, sidequests, baseline_meta, sidequests_meta)

    assert "avg_cost_per_solve" in comparison.metrics
    assert comparison.metrics["avg_cost_per_solve"]["baseline"] == "N/A"
    assert comparison.metrics["avg_cost_per_solve"]["sidequests"] == 0.01
    assert comparison.metrics["avg_cost_per_solve"]["delta"] == "N/A"

    assert comparison.metrics["invalid_action_rate"]["delta_raw"] < 0
    assert comparison.metrics["dissonance_trigger_rate"]["delta_raw"] < 0
    assert comparison.metrics["hallucination_rate"]["delta_raw"] < 0
    assert comparison.metrics["judge_score_by_archetype"]["delta_raw"]["copy"] == pytest.approx(1.0, rel=1e-3)
