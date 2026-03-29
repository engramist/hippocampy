from __future__ import annotations

import json

import pytest

from benchmarks.harness import BenchmarkConfig
from benchmarks.swe_ci import SweCiTask, ensure_dataset_cached
from benchmarks.swe_ci.harness import SweCiBenchmark
from benchmarks.swe_ci.metrics import compute_metrics, compare_constraint_violation


def test_dataset_cache_falls_back_to_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "benchmarks.swe_ci.httpx.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("simulated failure")),
    )
    cache_path = ensure_dataset_cached(cache_root=tmp_path)
    assert cache_path.exists()
    data = json.loads(cache_path.read_text())
    assert isinstance(data, list)
    assert len(data) >= 1


def test_metrics_reflect_memory_advantage():
    tasks = [
        SweCiTask("one", "first", ["no loops"], 0.5),
        SweCiTask("two", "second", ["no loops", "no recursion"], 0.4),
        SweCiTask("three", "third", ["no recursion"], 0.3),
    ]
    baseline = compute_metrics(tasks, use_memory=False)
    memory = compute_metrics(tasks, use_memory=True)
    comparison = compare_constraint_violation(baseline, memory)

    assert baseline["constraint_violation_rate"] >= memory["constraint_violation_rate"]
    assert comparison["memory_advantage"]


@pytest.mark.asyncio
async def test_swe_ci_benchmark_reports_memory_advantage():
    config = BenchmarkConfig(name="swe-ci-e2e", timeout=10)
    harness = SweCiBenchmark(config)

    result = await harness.execute()
    assert result.success
    metrics = result.metrics
    assert metrics["memory_advantage"] is True
    assert metrics["sidequests"]["constraint_violation_rate"] < metrics["baseline"]["constraint_violation_rate"]
    assert isinstance(metrics["violation_delta"], float)
