"""Autonomous research simulation benchmark for regression tracking."""

import time
import random
from typing import Any, Dict, List

from benchmarks.harness import BenchmarkHarness, BenchmarkConfig, BenchmarkResult
from .hypothesis_tracker import HypothesisTracker
from .metrics import (
    compute_regression_metrics,
    compare_regression_rates,
)


class ResearchSimHarness(BenchmarkHarness):
    """Benchmark harness that simulates hypothesis testing workflows."""

    DEFAULT_HYPOTHESES: List[str] = [
        "Thermal Gradient Hypothesis",
        "Magnetic Eddy Theory",
        "Stratospheric Coupling Hypothesis",
        "Quantum Recurrence Model",
        "Biofilm Stimulus Hypothesis",
        "Calibration Drift Theory",
        "Symmetry Breaking Model",
    ]

    DEFAULT_TASKS: List[Dict[str, Any]] = [
        {"task_id": "heat_flux", "target": "Thermal Gradient Hypothesis"},
        {"task_id": "magnetics", "target": "Magnetic Eddy Theory"},
        {"task_id": "stratosphere", "target": "Stratospheric Coupling Hypothesis"},
        {"task_id": "quantum", "target": "Quantum Recurrence Model"},
        {"task_id": "biofilm", "target": "Biofilm Stimulus Hypothesis"},
        {"task_id": "calibration", "target": "Calibration Drift Theory"},
        {"task_id": "symmetry", "target": "Symmetry Breaking Model"},
        {"task_id": "revisit", "target": "Thermal Gradient Hypothesis"},
    ]

    VARIANT_OFFSET = {"baseline": 0, "sidequests": 1}

    def __init__(self, config: BenchmarkConfig) -> None:
        super().__init__(config)
        params = config.parameters
        self.seed = int(params.get("seed", 20260328))
        self.max_attempts_per_task = int(params.get("max_attempts_per_task", 3))
        self.hypotheses = list(params.get("hypotheses", self.DEFAULT_HYPOTHESES))
        self.tasks: List[Dict[str, Any]] = list(
            params.get("tasks", self.DEFAULT_TASKS)
        )

    async def setup(self) -> None:
        if not self.tasks:
            self.tasks = list(self.DEFAULT_TASKS)

    async def run(self) -> BenchmarkResult:
        start_time = time.perf_counter()
        baseline_metrics, baseline_tracker = self._simulate_variant("baseline")
        sidequests_metrics, sidequests_tracker = self._simulate_variant("sidequests")
        significance = compare_regression_rates(baseline_metrics, sidequests_metrics)
        metrics: Dict[str, Any] = {
            "baseline": baseline_metrics.to_dict(),
            "sidequests": sidequests_metrics.to_dict(),
            "regression_delta": baseline_metrics.regression_rate - sidequests_metrics.regression_rate,
            "statistical_significance": significance,
            "history": {
                "baseline": baseline_tracker.history(),
                "sidequests": sidequests_tracker.history(),
            },
        }
        duration = time.perf_counter() - start_time
        return BenchmarkResult(
            benchmark_name=self.config.name,
            success=True,
            duration=duration,
            metrics=metrics,
        )

    async def teardown(self) -> None:
        pass

    def _simulate_variant(self, variant: str):
        tracker = HypothesisTracker()
        rng = random.Random(self.seed + self.VARIANT_OFFSET.get(variant, 0))
        for task in self.tasks:
            attempts = 0
            while attempts < self.max_attempts_per_task:
                hypothesis = self._select_hypothesis(rng, tracker, variant)
                success = hypothesis == task["target"]
                tracker.record_attempt(hypothesis, task["task_id"], success)
                attempts += 1
                if success:
                    break
        metrics = compute_regression_metrics(
            variant,
            tracker.total_attempts(),
            tracker.failed_attempts(),
            tracker.regression_count(),
        )
        return metrics, tracker

    def _select_hypothesis(self, rng: random.Random, tracker: HypothesisTracker, variant: str) -> str:
        if variant == "baseline":
            failed = tracker.failed_hypotheses()
            if failed and rng.random() < 0.75:
                return rng.choice(failed)
            return rng.choice(self.hypotheses)
        candidates = [h for h in self.hypotheses if not tracker.has_failed_before(h)]
        if not candidates:
            candidates = self.hypotheses
        return rng.choice(candidates)
