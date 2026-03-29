"""
Tests for A/B reproducibility protocol (B48 ab_contract.md)

Verifies:
1. Same seed → identical results
2. Metrics computation accuracy
3. Task manifest checksums
4. Comparison generation
"""

import pytest
import asyncio
import json
import os
import random
import numpy as np
from benchmarks.ab_harness import (
    ABHarness,
    ABTask,
    ABVariant,
    ABTaskResult,
    BenchmarkConfig
)


class DeterministicABHarness(ABHarness):
    """Test harness with deterministic task execution."""

    async def _execute_task(self, task: ABTask, variant: ABVariant) -> ABTaskResult:
        """Execute task with deterministic behavior based on seed and task_id."""
        # Use seeded RNG to determine task result
        task_hash = hash(task.task_id) % 1000
        r = random.Random(self.global_seed + task_hash)

        # Deterministically decide correctness
        correct = r.random() > 0.2  # 80% success rate

        # Deterministically decide steps
        steps = r.randint(1, 5)

        # Deterministically decide tokens
        tokens_input = r.randint(50, 200)
        tokens_output = r.randint(20, 100)

        error_msg = None
        if not correct:
            error_msg = f"Task {task.task_id}: error type {r.randint(1, 3)}"

        return ABTaskResult(
            task_id=task.task_id,
            variant=variant,
            correct=correct,
            steps=steps,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            error_message=error_msg,
            response_text=f"response to {task.task_id}"
        )


@pytest.fixture
def sample_tasks():
    """Create sample task set."""
    return [
        ABTask(
            task_id=f"task_{i:03d}",
            category="reasoning",
            prompt=f"Solve problem {i}",
            expected_output=f"Expected output for problem {i}",
            reference_solution=f"Reference solution for problem {i}"
        )
        for i in range(10)
    ]


@pytest.fixture
def ab_config():
    """Create benchmark config for A/B tests."""
    return BenchmarkConfig(
        name="ab_test",
        description="A/B test harness",
        timeout=300,
        parameters={"model": "test_model"}
    )


@pytest.mark.asyncio
async def test_deterministic_execution_same_seed(sample_tasks, ab_config):
    """Verify that same seed produces identical results."""
    harness1 = DeterministicABHarness(ab_config, global_seed=42)
    harness1.create_task_manifest(sample_tasks)

    harness2 = DeterministicABHarness(ab_config, global_seed=42)
    harness2.create_task_manifest(sample_tasks)

    # Run both harnesses
    comparison1, meta1_b, meta1_s = await harness1.run_ab_comparison()
    comparison2, meta2_b, meta2_s = await harness2.run_ab_comparison()

    # Results should be identical
    assert meta1_b.succeeded == meta2_b.succeeded
    assert meta1_b.total_tokens == meta2_b.total_tokens
    assert meta1_s.succeeded == meta2_s.succeeded
    assert meta1_s.total_tokens == meta2_s.total_tokens

    # Metrics should be identical
    for key in ["solve_rate", "steps_to_solve", "token_efficiency"]:
        assert comparison1.metrics[key]["baseline"] == comparison2.metrics[key]["baseline"]
        assert comparison1.metrics[key]["sidequests"] == comparison2.metrics[key]["sidequests"]


@pytest.mark.asyncio
async def test_different_seed_produces_different_results(ab_config):
    """Verify that different seeds produce different results."""
    # Create larger task set to ensure differences are likely
    tasks = [
        ABTask(
            task_id=f"task_{i:03d}",
            category="reasoning",
            prompt=f"Solve problem {i}",
        )
        for i in range(30)  # Larger set for better chance of difference
    ]

    harness1 = DeterministicABHarness(ab_config, global_seed=42)
    harness1.create_task_manifest(tasks)

    harness2 = DeterministicABHarness(ab_config, global_seed=99)
    harness2.create_task_manifest(tasks)

    comparison1, meta1_b, meta1_s = await harness1.run_ab_comparison()
    comparison2, meta2_b, meta2_s = await harness2.run_ab_comparison()

    # Results should differ (with very high probability with 30 tasks)
    # At least one should be different
    results_differ = (
        meta1_b.succeeded != meta2_b.succeeded or
        meta1_s.succeeded != meta2_s.succeeded or
        meta1_b.total_tokens != meta2_b.total_tokens or
        meta1_s.total_tokens != meta2_s.total_tokens
    )
    assert results_differ, "Different seeds should (very likely) produce different results"


@pytest.mark.asyncio
async def test_metrics_computation_accuracy(sample_tasks, ab_config):
    """Verify metrics are computed correctly."""
    harness = DeterministicABHarness(ab_config, global_seed=42)
    harness.create_task_manifest(sample_tasks)

    _, baseline_meta, sidequests_meta = await harness.run_ab_comparison()

    # Verify basic properties
    assert baseline_meta.total_tasks == 10
    assert sidequests_meta.total_tasks == 10
    assert baseline_meta.succeeded + baseline_meta.failed == 10
    assert sidequests_meta.succeeded + sidequests_meta.failed == 10

    # Verify token counts are positive
    assert baseline_meta.total_tokens > 0
    assert sidequests_meta.total_tokens > 0

    # Verify solve rate is between 0 and 1
    solve_rate = baseline_meta.succeeded / baseline_meta.total_tasks
    assert 0 <= solve_rate <= 1


@pytest.mark.asyncio
async def test_task_manifest_checksum_consistency(sample_tasks, ab_config):
    """Verify task manifest checksums are consistent."""
    harness1 = DeterministicABHarness(ab_config, global_seed=42)
    manifest1 = harness1.create_task_manifest(sample_tasks)

    harness2 = DeterministicABHarness(ab_config, global_seed=42)
    manifest2 = harness2.create_task_manifest(sample_tasks)

    # Same tasks should have same hash
    assert manifest1.task_set_hash == manifest2.task_set_hash

    # Verify hash is deterministic
    assert isinstance(manifest1.task_set_hash, str)
    assert len(manifest1.task_set_hash) == 64  # SHA256 hex length


@pytest.mark.asyncio
async def test_task_manifest_checksum_changes_with_tasks(ab_config):
    """Verify that changing task content changes checksum."""
    tasks_v1 = [
        ABTask(task_id="task_001", category="reasoning", prompt="Problem 1"),
        ABTask(task_id="task_002", category="reasoning", prompt="Problem 2"),
    ]

    tasks_v2 = [
        ABTask(task_id="task_001", category="reasoning", prompt="Problem 1 modified"),
        ABTask(task_id="task_002", category="reasoning", prompt="Problem 2"),
    ]

    harness1 = DeterministicABHarness(ab_config)
    manifest1 = harness1.create_task_manifest(tasks_v1)

    harness2 = DeterministicABHarness(ab_config)
    manifest2 = harness2.create_task_manifest(tasks_v2)

    # Different task content → different hash
    assert manifest1.task_set_hash != manifest2.task_set_hash


@pytest.mark.asyncio
async def test_comparison_identifies_improvements(ab_config):
    """Verify comparison correctly identifies where SideQuests helped."""
    # Create simple tasks
    tasks = [
        ABTask(task_id="task_001", category="reasoning", prompt="Problem 1"),
        ABTask(task_id="task_002", category="reasoning", prompt="Problem 2"),
    ]

    harness = DeterministicABHarness(ab_config, global_seed=42)
    harness.create_task_manifest(tasks)

    # Manually inject results to test comparison logic
    harness.baseline_results = [
        ABTaskResult(
            task_id="task_001",
            variant=ABVariant.BASELINE,
            correct=False,
            steps=2,
            tokens_input=100,
            tokens_output=50,
            error_message="failed"
        ),
        ABTaskResult(
            task_id="task_002",
            variant=ABVariant.BASELINE,
            correct=True,
            steps=3,
            tokens_input=100,
            tokens_output=50,
            error_message=None
        ),
    ]

    harness.sidequests_results = [
        ABTaskResult(
            task_id="task_001",
            variant=ABVariant.SIDEQUESTS,
            correct=True,  # Improved!
            steps=1,
            tokens_input=80,
            tokens_output=40,
            error_message=None
        ),
        ABTaskResult(
            task_id="task_002",
            variant=ABVariant.SIDEQUESTS,
            correct=True,
            steps=2,  # Improved!
            tokens_input=80,
            tokens_output=40,
            error_message=None
        ),
    ]

    baseline_meta = harness.generate_run_metadata(ABVariant.BASELINE, 1.0)
    sidequests_meta = harness.generate_run_metadata(ABVariant.SIDEQUESTS, 1.0)

    comparison = harness._compare_results(
        harness.baseline_results,
        harness.sidequests_results,
        baseline_meta,
        sidequests_meta
    )

    # Verify improvements detected
    assert len(comparison.tasks_where_sidequests_helped) >= 1
    task_ids = [t["task_id"] for t in comparison.tasks_where_sidequests_helped]
    assert "task_001" in task_ids or "task_002" in task_ids


@pytest.mark.asyncio
async def test_metrics_delta_calculation(ab_config):
    """Verify delta calculation in comparison."""
    tasks = [
        ABTask(task_id="task_001", category="reasoning", prompt="Problem 1"),
    ]

    harness = DeterministicABHarness(ab_config)
    harness.create_task_manifest(tasks)

    # Manual results: 50% baseline, 100% sidequests
    harness.baseline_results = [
        ABTaskResult(
            task_id="task_001",
            variant=ABVariant.BASELINE,
            correct=False,
            steps=2,
            tokens_input=100,
            tokens_output=50,
            error_message="failed"
        ),
    ]

    harness.sidequests_results = [
        ABTaskResult(
            task_id="task_001",
            variant=ABVariant.SIDEQUESTS,
            correct=True,
            steps=1,
            tokens_input=80,
            tokens_output=40,
            error_message=None
        ),
    ]

    baseline_meta = harness.generate_run_metadata(ABVariant.BASELINE, 1.0)
    sidequests_meta = harness.generate_run_metadata(ABVariant.SIDEQUESTS, 1.0)

    comparison = harness._compare_results(
        harness.baseline_results,
        harness.sidequests_results,
        baseline_meta,
        sidequests_meta
    )

    # Verify solve rate delta
    assert "solve_rate" in comparison.metrics
    assert comparison.metrics["solve_rate"]["baseline"] == 0.0
    assert comparison.metrics["solve_rate"]["sidequests"] == 1.0
    # When going from 0 to non-zero, should show infinity
    assert "inf" in comparison.metrics["solve_rate"]["delta"]


def test_task_result_total_tokens():
    """Verify token computation in ABTaskResult."""
    result = ABTaskResult(
        task_id="test",
        variant=ABVariant.BASELINE,
        correct=True,
        steps=1,
        tokens_input=100,
        tokens_output=50,
        error_message=None
    )

    assert result.total_tokens == 150


def test_task_prompt_hash():
    """Verify task prompt hashing."""
    task1 = ABTask(
        task_id="task_001",
        category="reasoning",
        prompt="Problem 1"
    )

    task2 = ABTask(
        task_id="task_001",
        category="reasoning",
        prompt="Problem 1"
    )

    task3 = ABTask(
        task_id="task_001",
        category="reasoning",
        prompt="Problem 2"
    )

    # Same prompt → same hash
    assert task1.prompt_hash == task2.prompt_hash

    # Different prompt → different hash
    assert task1.prompt_hash != task3.prompt_hash

    # Hash is 64-char hex (SHA256)
    assert len(task1.prompt_hash) == 64
    assert all(c in "0123456789abcdef" for c in task1.prompt_hash)


@pytest.mark.asyncio
async def test_save_results_creates_files(sample_tasks, ab_config, tmp_path):
    """Verify results are saved to disk correctly."""
    harness = DeterministicABHarness(ab_config, global_seed=42)
    harness.create_task_manifest(sample_tasks)

    comparison, baseline_meta, sidequests_meta = await harness.run_ab_comparison()

    # Save to temp directory
    output_dir = str(tmp_path)
    harness.save_results(comparison, baseline_meta, sidequests_meta, output_dir=output_dir)

    # Verify files were created
    files = os.listdir(output_dir)
    assert len(files) >= 4  # comparison, baseline, sidequests, manifest, task_results

    # Verify JSON structure
    comparison_files = [f for f in files if f.startswith("ab_comparison_")]
    assert len(comparison_files) > 0

    with open(os.path.join(output_dir, comparison_files[0]), 'r') as f:
        comparison_data = json.load(f)
        assert "metrics" in comparison_data
        assert "baseline_run_id" in comparison_data
        assert "sidequests_run_id" in comparison_data
