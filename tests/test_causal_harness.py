"""
Tests for synthetic causal reasoning benchmark harness.
"""

import pytest
import asyncio
from benchmarks.causal.harness import CausalHarness, CausalTaskResult
from benchmarks.causal import (
    generate_ama_bench_tasks,
    generate_memory_arena_tasks,
)
from benchmarks.causal.metrics import (
    compute_solve_rate,
    compute_constraint_consistency,
    compute_causal_chain_depth,
    aggregate_causal_metrics,
    compare_constraint_consistency,
    compare_solve_rates,
)
from benchmarks.harness import BenchmarkConfig
from benchmarks.ab_harness import ABVariant


class TestCausalTaskGeneration:
    """Test task generation for both synthetic task families."""

    def test_ama_bench_task_generation(self):
        """Test synthetic causal arithmetic task generation."""
        tasks = generate_ama_bench_tasks(num_tasks=5, seed=42)

        assert len(tasks) == 5
        for task in tasks:
            assert task.task_id.startswith("synthetic_causal_arithmetic_")
            assert task.category == "arithmetic_reasoning"
            assert len(task.constraints) >= 2
            assert len(task.causal_steps) >= 2
            assert task.expected_final_state is not None
            assert task.expected_solution is not None

    def test_memory_arena_task_generation(self):
        """Test synthetic capacity-constraints task generation."""
        tasks = generate_memory_arena_tasks(num_tasks=5, seed=42)

        assert len(tasks) == 5
        for task in tasks:
            assert task.task_id.startswith("synthetic_capacity_constraints_")
            assert task.category == "spatial_reasoning"
            assert len(task.constraints) >= 2
            assert len(task.causal_steps) >= 1
            assert task.state_variables is not None
            assert len(task.action_sequence) >= 1

    def test_task_determinism(self):
        """Test that tasks are generated deterministically with same seed."""
        tasks1 = generate_ama_bench_tasks(num_tasks=3, seed=42)
        tasks2 = generate_ama_bench_tasks(num_tasks=3, seed=42)

        for t1, t2 in zip(tasks1, tasks2):
            assert t1.task_id == t2.task_id
            assert t1.description == t2.description
            assert t1.constraints == t2.constraints

    def test_task_difficulty_variation(self):
        """Test that task difficulty varies across generated tasks."""
        ama_tasks = generate_ama_bench_tasks(num_tasks=9, seed=42)
        memory_tasks = generate_memory_arena_tasks(num_tasks=9, seed=42)

        # Difficulty is encoded in constraint count and causal depth
        ama_constraint_counts = [len(t.constraints) for t in ama_tasks]
        memory_constraint_counts = [len(t.constraints) for t in memory_tasks]

        # Should have variation (some tasks easier, some harder)
        assert len(set(ama_constraint_counts)) > 1
        assert len(set(memory_constraint_counts)) > 1


class TestCausalMetrics:
    """Test metric calculation for causal reasoning."""

    def test_solve_rate_calculation(self):
        """Test solve rate metric."""
        results = [
            CausalTaskResult(
                task_id="task_1",
                variant=ABVariant.BASELINE,
                task_type="ama_bench",
                correct=True,
                steps_completed=3,
                constraint_violations=0,
                causal_chain_depth=3,
            ),
            CausalTaskResult(
                task_id="task_2",
                variant=ABVariant.BASELINE,
                task_type="ama_bench",
                correct=False,
                steps_completed=2,
                constraint_violations=1,
                causal_chain_depth=3,
            ),
            CausalTaskResult(
                task_id="task_3",
                variant=ABVariant.BASELINE,
                task_type="ama_bench",
                correct=True,
                steps_completed=3,
                constraint_violations=0,
                causal_chain_depth=3,
            ),
        ]

        rate = compute_solve_rate(results)
        assert rate == pytest.approx(0.666, rel=1e-2)

    def test_constraint_consistency_calculation(self):
        """Test constraint consistency metric."""
        results = [
            CausalTaskResult(
                task_id="task_1",
                variant=ABVariant.BASELINE,
                task_type="ama_bench",
                correct=True,
                steps_completed=3,
                constraint_violations=0,
                causal_chain_depth=3,
            ),
            CausalTaskResult(
                task_id="task_2",
                variant=ABVariant.BASELINE,
                task_type="ama_bench",
                correct=True,
                steps_completed=3,
                constraint_violations=2,
                causal_chain_depth=3,
            ),
        ]

        consistency = compute_constraint_consistency(results)
        # Total violations: 2, max possible per task ~ 4.5 (3 * 1.5)
        # max_possible = 4.5 + 4.5 = 9
        # consistency = 1.0 - (2 / 9) ≈ 0.777
        assert 0.7 < consistency <= 1.0

    def test_causal_chain_depth_calculation(self):
        """Test causal chain depth metric."""
        results = [
            CausalTaskResult(
                task_id="task_1",
                variant=ABVariant.SIDEQUESTS,
                task_type="memory_arena",
                correct=True,
                steps_completed=3,
                constraint_violations=0,
                causal_chain_depth=3,
            ),
            CausalTaskResult(
                task_id="task_2",
                variant=ABVariant.SIDEQUESTS,
                task_type="memory_arena",
                correct=True,
                steps_completed=4,
                constraint_violations=0,
                causal_chain_depth=4,
            ),
            CausalTaskResult(
                task_id="task_3",
                variant=ABVariant.SIDEQUESTS,
                task_type="memory_arena",
                correct=False,
                steps_completed=2,
                constraint_violations=2,
                causal_chain_depth=4,
            ),
        ]

        depth = compute_causal_chain_depth(results)
        # Only correct ones count: (3 + 4) / 2 = 3.5
        assert depth == pytest.approx(3.5, rel=1e-2)

    def test_aggregate_metrics(self):
        """Test aggregation of multiple metrics."""
        results = [
            CausalTaskResult(
                task_id="task_1",
                variant=ABVariant.SIDEQUESTS,
                task_type="ama_bench",
                correct=True,
                steps_completed=3,
                constraint_violations=0,
                causal_chain_depth=3,
                memory_retrievals=2,
            ),
            CausalTaskResult(
                task_id="task_2",
                variant=ABVariant.SIDEQUESTS,
                task_type="ama_bench",
                correct=False,
                steps_completed=2,
                constraint_violations=1,
                causal_chain_depth=3,
                memory_retrievals=1,
            ),
        ]

        metrics = aggregate_causal_metrics(results, "sidequests")

        assert metrics.variant == "sidequests"
        assert metrics.solve_rate == pytest.approx(0.5, rel=1e-2)
        assert metrics.total_tasks == 2
        assert metrics.succeeded == 1
        assert metrics.failed == 1
        assert metrics.avg_memory_retrievals == pytest.approx(1.5, rel=1e-2)

    def test_compare_constraint_consistency(self):
        """Test comparison of constraint consistency between variants."""
        baseline_results = [
            CausalTaskResult(
                task_id="task_1",
                variant=ABVariant.BASELINE,
                task_type="ama_bench",
                correct=True,
                steps_completed=3,
                constraint_violations=2,
                causal_chain_depth=3,
            ),
        ]

        sidequests_results = [
            CausalTaskResult(
                task_id="task_1",
                variant=ABVariant.SIDEQUESTS,
                task_type="ama_bench",
                correct=True,
                steps_completed=3,
                constraint_violations=0,
                causal_chain_depth=3,
            ),
        ]

        comparison = compare_constraint_consistency(baseline_results, sidequests_results)

        assert "baseline_consistency" in comparison
        assert "sidequests_consistency" in comparison
        assert "consistency_delta" in comparison
        assert comparison["sidequests_advantage"] is True
        assert comparison["sidequests_consistency"] > comparison["baseline_consistency"]

    def test_compare_solve_rates(self):
        """Test comparison of solve rates between variants."""
        baseline_results = [
            CausalTaskResult(
                task_id="task_1",
                variant=ABVariant.BASELINE,
                task_type="ama_bench",
                correct=False,
                steps_completed=2,
                constraint_violations=1,
                causal_chain_depth=3,
            ),
        ]

        sidequests_results = [
            CausalTaskResult(
                task_id="task_1",
                variant=ABVariant.SIDEQUESTS,
                task_type="ama_bench",
                correct=True,
                steps_completed=3,
                constraint_violations=0,
                causal_chain_depth=3,
            ),
        ]

        comparison = compare_solve_rates(baseline_results, sidequests_results)

        assert "baseline_solve_rate" in comparison
        assert "sidequests_solve_rate" in comparison
        assert comparison["sidequests_advantage"] is True


@pytest.mark.asyncio
async def test_causal_harness_initialization():
    """Test CausalHarness initialization."""
    config = BenchmarkConfig(name="causal_test")
    harness = CausalHarness(config)

    assert harness.config.name == "causal_test"
    assert len(harness.ama_bench_tasks) == 0
    assert len(harness.memory_arena_tasks) == 0
    assert harness.baseline_results["synthetic_causal_arithmetic"] == []
    assert harness.sidequests_results["synthetic_capacity_constraints"] == []


@pytest.mark.asyncio
async def test_causal_harness_setup():
    """Test CausalHarness setup."""
    config = BenchmarkConfig(
        name="causal_test",
        parameters={
            "num_ama_bench_tasks": 5,
            "num_memory_arena_tasks": 3,
        }
    )
    harness = CausalHarness(config)
    await harness.setup()

    assert len(harness.ama_bench_tasks) == 5
    assert len(harness.memory_arena_tasks) == 3


@pytest.mark.asyncio
async def test_causal_harness_run():
    """Test CausalHarness full execution."""
    config = BenchmarkConfig(
        name="causal_test",
        parameters={
            "num_ama_bench_tasks": 3,
            "num_memory_arena_tasks": 3,
        }
    )
    harness = CausalHarness(config)
    await harness.setup()
    result = await harness.run()

    assert result.success is True
    assert result.benchmark_name == "causal_test"
    assert "baseline" in result.metrics
    assert "sidequests" in result.metrics
    assert "comparison" in result.metrics
    assert "task_counts" in result.metrics

    # Check task counts
    assert result.metrics["task_counts"]["synthetic_causal_arithmetic"] == 3
    assert result.metrics["task_counts"]["synthetic_capacity_constraints"] == 3


@pytest.mark.asyncio
async def test_causal_harness_baseline_vs_sidequests():
    """Test that SideQuests shows better constraint consistency than baseline."""
    config = BenchmarkConfig(
        name="causal_test",
        parameters={
            "num_ama_bench_tasks": 5,
            "num_memory_arena_tasks": 5,
        }
    )
    harness = CausalHarness(config)
    await harness.setup()
    result = await harness.run()

    baseline_consistency = result.metrics["baseline"]["constraint_consistency"]
    sidequests_consistency = result.metrics["sidequests"]["constraint_consistency"]

    # SideQuests should maintain better constraint consistency
    assert sidequests_consistency >= baseline_consistency

    # Check solve rate advantage
    comparison = result.metrics["comparison"]
    assert comparison["sidequests_advantage"]["better_constraint_consistency"] is True


@pytest.mark.asyncio
async def test_task_results_structure():
    """Test that task results have expected structure."""
    config = BenchmarkConfig(
        name="causal_test",
        parameters={
            "num_ama_bench_tasks": 2,
            "num_memory_arena_tasks": 2,
        }
    )
    harness = CausalHarness(config)
    await harness.setup()
    await harness.run()

    # Check baseline results
    all_baseline = (
        harness.baseline_results["synthetic_causal_arithmetic"]
        + harness.baseline_results["synthetic_capacity_constraints"]
    )
    assert len(all_baseline) == 4

    for result in all_baseline:
        assert hasattr(result, "task_id")
        assert hasattr(result, "variant")
        assert hasattr(result, "task_type")
        assert hasattr(result, "correct")
        assert hasattr(result, "steps_completed")
        assert hasattr(result, "constraint_violations")
        assert hasattr(result, "causal_chain_depth")
        assert result.variant == ABVariant.BASELINE

    # Check sidequests results
    all_sidequests = (
        harness.sidequests_results["synthetic_causal_arithmetic"]
        + harness.sidequests_results["synthetic_capacity_constraints"]
    )
    assert len(all_sidequests) == 4

    for result in all_sidequests:
        assert result.variant == ABVariant.SIDEQUESTS
        assert result.memory_retrievals >= 0


@pytest.mark.asyncio
async def test_memory_arena_improves_over_baseline():
    """Test that MemoryArena tasks show SideQuests improvement."""
    config = BenchmarkConfig(
        name="causal_test",
        parameters={
            "num_ama_bench_tasks": 0,
            "num_memory_arena_tasks": 10,
        }
    )
    harness = CausalHarness(config)
    await harness.setup()
    result = await harness.run()

    # MemoryArena tasks with spatial state should show strong SideQuests advantage
    baseline_consistency = result.metrics["baseline"]["constraint_consistency"]
    sidequests_consistency = result.metrics["sidequests"]["constraint_consistency"]

    # SideQuests should be notably better for memory-dependent tasks
    delta = sidequests_consistency - baseline_consistency
    assert delta >= 0
