from __future__ import annotations

import time
from typing import List

from benchmarks.harness import BenchmarkHarness, BenchmarkResult

from . import SweCiTask, load_dataset, ensure_dataset_cached
from .metrics import compare_constraint_violation, compute_metrics


class SweCiBenchmark(BenchmarkHarness):
    """SWE-CI evaluation harness that compares baseline generations to SideQuests memory runs."""

    def __init__(self, config) -> None:
        super().__init__(config)
        self._tasks: List[SweCiTask] = []

    async def setup(self) -> None:
        dataset_path = ensure_dataset_cached()
        self._tasks = load_dataset(dataset_path)

    async def run(self) -> BenchmarkResult:
        start = time.perf_counter()
        baseline_metrics = compute_metrics(self._tasks, use_memory=False)
        memory_metrics = compute_metrics(self._tasks, use_memory=True)
        comparison = compare_constraint_violation(baseline_metrics, memory_metrics)

        result_metrics = {
            "baseline": baseline_metrics,
            "sidequests": memory_metrics,
            "memory_advantage": comparison["memory_advantage"],
            "violation_delta": comparison["violation_delta"],
        }

        return BenchmarkResult(
            benchmark_name=self.config.name,
            success=True,
            duration=time.perf_counter() - start,
            metrics=result_metrics,
        )

    async def teardown(self) -> None:
        return None
