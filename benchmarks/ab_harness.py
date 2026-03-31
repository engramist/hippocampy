"""
A/B Evaluation Harness for SideQuests vs. Baseline

Implements the protocol defined in benchmarks/ab_contract.md
"""

import asyncio
import json
import hashlib
import time
import random
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import uuid

from benchmarks.harness import BenchmarkHarness, BenchmarkConfig, BenchmarkResult


class ABVariant(str, Enum):
    """A/B test variant."""
    BASELINE = "baseline"
    SIDEQUESTS = "sidequests"


@dataclass
class ABTask:
    """Represents a single task in A/B evaluation."""
    task_id: str
    category: str
    prompt: str
    expected_output: Optional[str] = None
    reference_solution: Optional[str] = None

    @property
    def prompt_hash(self) -> str:
        """SHA256 hash of task prompt."""
        return hashlib.sha256(self.prompt.encode()).hexdigest()


@dataclass
class ABTaskResult:
    """Result of executing a single task."""
    task_id: str
    variant: ABVariant
    correct: bool
    steps: int
    tokens_input: int
    tokens_output: int
    error_message: Optional[str] = None
    response_text: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    final_state: Optional[str] = None  # WIN, GAME_OVER, NOT_FINISHED
    final_observation: Optional[dict] = None  # Full observation with grid, state, etc.

    @property
    def total_tokens(self) -> int:
        return self.tokens_input + self.tokens_output


@dataclass
class ABTaskManifest:
    """Task manifest with checksums for reproducibility."""
    manifest_version: str = "1.0"
    global_seed: int = 42
    timestamp: str = ""
    tasks: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def task_set_hash(self) -> str:
        """SHA256 of concatenated task prompts."""
        task_prompts = "".join(t["prompt"] for t in self.tasks)
        return hashlib.sha256(task_prompts.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "manifest_version": self.manifest_version,
            "global_seed": self.global_seed,
            "timestamp": self.timestamp,
            "task_set_hash": self.task_set_hash,
            "tasks": self.tasks
        }


@dataclass
class ABRunMetadata:
    """Metadata for a single A/B run."""
    run_id: str
    variant: ABVariant
    timestamp: str
    seed: int
    model: str
    task_set_hash: str
    total_tasks: int
    succeeded: int
    failed: int
    total_tokens: int
    wall_time_seconds: float
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return asdict(self)


@dataclass
class ABComparison:
    """Results of comparing baseline vs. sidequests."""
    comparison_id: str
    timestamp: str
    baseline_run_id: str
    sidequests_run_id: str
    metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tasks_where_sidequests_helped: List[Dict[str, Any]] = field(default_factory=list)
    caveats: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return asdict(self)


class ABHarness(BenchmarkHarness):
    """
    A/B evaluation harness for comparing SideQuests vs. baseline.

    Implements the protocol from benchmarks/ab_contract.md:
    - Fixed random seeds for reproducibility
    - Identical task sequences for both variants
    - Automated metrics collection
    - Standardized result format
    """

    def __init__(self, config: BenchmarkConfig, global_seed: int = 42):
        super().__init__(config)
        self.global_seed = global_seed
        self.tasks: List[ABTask] = []
        self.manifest: Optional[ABTaskManifest] = None
        self.baseline_results: List[ABTaskResult] = []
        self.sidequests_results: List[ABTaskResult] = []
        self._set_global_seed(global_seed)

    def _set_global_seed(self, seed: int) -> None:
        """
        Set global random seed for reproducibility.

        Applies seed to all RNG sources used in the harness.
        """
        random.seed(seed)
        np.random.seed(seed)
        # Note: torch seed would be set here if torch is used
        # torch.manual_seed(seed)

    def create_task_manifest(self, tasks: List[ABTask]) -> ABTaskManifest:
        """Create task manifest with checksums."""
        self.tasks = tasks
        manifest = ABTaskManifest(
            global_seed=self.global_seed,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            tasks=[
                {
                    "task_id": t.task_id,
                    "category": t.category,
                    "prompt": t.prompt,
                    "prompt_hash": t.prompt_hash,
                    "expected_output": t.expected_output,
                    "reference_solution": t.reference_solution,
                }
                for t in tasks
            ]
        )
        self.manifest = manifest
        return manifest

    async def setup(self) -> None:
        """Initialize benchmark-specific resources."""
        # Subclasses can override to set up task-specific resources
        pass

    async def run(self) -> BenchmarkResult:
        """
        Execute A/B comparison (not used directly; use run_variant instead).
        """
        return BenchmarkResult(
            benchmark_name=self.config.name,
            success=True,
            duration=0.0,
            metrics={}
        )

    async def teardown(self) -> None:
        """Clean up benchmark-specific resources."""
        pass

    async def run_variant(self, variant: ABVariant) -> Tuple[List[ABTaskResult], float]:
        """
        Run all tasks for a specific variant (baseline or sidequests).

        Returns:
            (task_results, wall_time_seconds)
        """
        if not self.tasks:
            raise ValueError("No tasks loaded. Call create_task_manifest first.")

        start_time = time.perf_counter()
        results = []

        for task in self.tasks:
            result = await self._execute_task(task, variant)
            results.append(result)

        wall_time = time.perf_counter() - start_time

        if variant == ABVariant.BASELINE:
            self.baseline_results = results
        else:
            self.sidequests_results = results

        return results, wall_time

    async def _execute_task(self, task: ABTask, variant: ABVariant) -> ABTaskResult:
        """
        Execute a single task and record results.

        Subclasses should override this to implement task execution logic.
        """
        # Placeholder: subclasses implement actual task execution
        await asyncio.sleep(0.1)
        return ABTaskResult(
            task_id=task.task_id,
            variant=variant,
            correct=True,
            steps=1,
            tokens_input=100,
            tokens_output=50,
            error_message=None,
            response_text="placeholder response"
        )

    def _compute_metrics(self, results: List[ABTaskResult]) -> Dict[str, Any]:
        """Compute all metrics for a set of results."""
        if not results:
            return {}

        # Solve rate
        correct_count = sum(1 for r in results if r.correct)
        solve_rate = correct_count / len(results) if results else 0.0

        # Steps to solve (only for correct results)
        correct_results = [r for r in results if r.correct]
        avg_steps = (sum(r.steps for r in correct_results) / len(correct_results)) if correct_results else 0.0

        # Token efficiency (tokens per solved task)
        total_tokens = sum(r.total_tokens for r in results)
        token_efficiency = total_tokens / correct_count if correct_count > 0 else float('inf')

        # Repeated mistakes detection (simplified: count same error messages)
        error_counts: Dict[str, int] = {}
        for r in results:
            if r.error_message:
                error_counts[r.error_message] = error_counts.get(r.error_message, 0) + 1

        repeated_mistakes = sum(1 for count in error_counts.values() if count > 1) / len(results) if results else 0.0

        return {
            "solve_rate": round(solve_rate, 4),
            "steps_to_solve": round(avg_steps, 2),
            "token_efficiency": round(token_efficiency, 2),
            "repeated_mistakes": round(repeated_mistakes, 4),
            "total_tokens": total_tokens,
            "succeeded": correct_count,
            "failed": len(results) - correct_count,
        }

    def generate_run_metadata(self, variant: ABVariant, wall_time: float) -> ABRunMetadata:
        """Generate metadata for a completed run."""
        results = self.baseline_results if variant == ABVariant.BASELINE else self.sidequests_results

        metrics = self._compute_metrics(results)

        return ABRunMetadata(
            run_id=str(uuid.uuid4()),
            variant=variant,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            seed=self.global_seed,
            model=self.config.parameters.get("model", "unknown"),
            task_set_hash=self.manifest.task_set_hash if self.manifest else "unknown",
            total_tasks=len(results),
            succeeded=metrics.get("succeeded", 0),
            failed=metrics.get("failed", 0),
            total_tokens=metrics.get("total_tokens", 0),
            wall_time_seconds=wall_time,
            config={k: v for k, v in self.config.parameters.items() if k != "tasks"}
        )

    async def run_ab_comparison(self) -> Tuple[ABComparison, ABRunMetadata, ABRunMetadata]:
        """
        Run full A/B comparison: baseline followed by sidequests.

        Returns:
            (comparison, baseline_metadata, sidequests_metadata)
        """
        # Reset seed before each variant to ensure reproducibility
        self._set_global_seed(self.global_seed)

        await self.setup()

        try:
            # Run baseline
            baseline_results, baseline_wall_time = await self.run_variant(ABVariant.BASELINE)
            baseline_metadata = self.generate_run_metadata(ABVariant.BASELINE, baseline_wall_time)

            # Reset seed before sidequests to ensure same initial state
            self._set_global_seed(self.global_seed)

            # Run sidequests
            sidequests_results, sidequests_wall_time = await self.run_variant(ABVariant.SIDEQUESTS)
            sidequests_metadata = self.generate_run_metadata(ABVariant.SIDEQUESTS, sidequests_wall_time)

            # Compare results
            comparison = self._compare_results(baseline_results, sidequests_results, baseline_metadata, sidequests_metadata)

            return comparison, baseline_metadata, sidequests_metadata

        finally:
            await self.teardown()

    def _compare_results(
        self,
        baseline: List[ABTaskResult],
        sidequests: List[ABTaskResult],
        baseline_meta: ABRunMetadata,
        sidequests_meta: ABRunMetadata
    ) -> ABComparison:
        """Generate comparison between baseline and sidequests."""
        baseline_metrics = self._compute_metrics(baseline)
        sidequests_metrics = self._compute_metrics(sidequests)

        # Calculate deltas
        metrics_dict = {}
        for key in ["solve_rate", "steps_to_solve", "token_efficiency", "repeated_mistakes"]:
            baseline_val = baseline_metrics.get(key, 0)
            sidequests_val = sidequests_metrics.get(key, 0)

            if baseline_val != 0:
                delta_pct = ((sidequests_val - baseline_val) / abs(baseline_val)) * 100
            elif sidequests_val != 0:
                # If baseline is 0 but sidequests is not, show infinity or large value
                delta_pct = float('inf') if sidequests_val > 0 else float('-inf')
            else:
                delta_pct = 0.0

            # Format delta for output
            if delta_pct == float('inf'):
                delta_str = "+inf%"
            elif delta_pct == float('-inf'):
                delta_str = "-inf%"
            else:
                delta_str = f"{delta_pct:+.1f}%"

            metrics_dict[key] = {
                "baseline": baseline_val,
                "sidequests": sidequests_val,
                "delta": delta_str,
                "delta_raw": round(sidequests_val - baseline_val, 4)
            }

        # Identify tasks where sidequests helped
        helped_tasks = []
        for b, s in zip(baseline, sidequests):
            if not b.correct and s.correct:
                helped_tasks.append({
                    "task_id": b.task_id,
                    "reason": "Baseline failed, SideQuests succeeded"
                })
            elif b.correct and s.correct and s.steps < b.steps:
                helped_tasks.append({
                    "task_id": b.task_id,
                    "reason": f"Fewer steps: {b.steps} → {s.steps}"
                })

        return ABComparison(
            comparison_id=str(uuid.uuid4()),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            baseline_run_id=baseline_meta.run_id,
            sidequests_run_id=sidequests_meta.run_id,
            metrics=metrics_dict,
            tasks_where_sidequests_helped=helped_tasks,
            caveats="A/B comparison completed. See task logs for detailed analysis."
        )

    def save_results(self, comparison: ABComparison, baseline_meta: ABRunMetadata, sidequests_meta: ABRunMetadata, output_dir: str = "benchmarks/results") -> None:
        """Save all A/B results and metadata."""
        import os
        os.makedirs(output_dir, exist_ok=True)

        # Save comparison
        comparison_path = os.path.join(output_dir, f"ab_comparison_{comparison.comparison_id}.json")
        with open(comparison_path, 'w') as f:
            json.dump(comparison.to_dict(), f, indent=2, default=str)

        # Save baseline metadata
        baseline_path = os.path.join(output_dir, f"baseline_{baseline_meta.run_id}.json")
        with open(baseline_path, 'w') as f:
            json.dump(baseline_meta.to_dict(), f, indent=2, default=str)

        # Save sidequests metadata
        sidequests_path = os.path.join(output_dir, f"sidequests_{sidequests_meta.run_id}.json")
        with open(sidequests_path, 'w') as f:
            json.dump(sidequests_meta.to_dict(), f, indent=2, default=str)

        # Save task manifest
        manifest_path = os.path.join(output_dir, f"manifest_{self.manifest.task_set_hash[:8]}.json")
        with open(manifest_path, 'w') as f:
            json.dump(self.manifest.to_dict(), f, indent=2, default=str)

        # Save detailed task results
        task_results_path = os.path.join(output_dir, f"task_results_{comparison.comparison_id}.json")
        task_results = []
        for b, s in zip(self.baseline_results, self.sidequests_results):
            task_results.append({
                "task_id": b.task_id,
                "baseline_correct": b.correct,
                "baseline_steps": b.steps,
                "baseline_tokens": {"input": b.tokens_input, "output": b.tokens_output},
                "sidequests_correct": s.correct,
                "sidequests_steps": s.steps,
                "sidequests_tokens": {"input": s.tokens_input, "output": s.tokens_output},
                "error_message": b.error_message or "none",
            })

        with open(task_results_path, 'w') as f:
            json.dump(task_results, f, indent=2, default=str)
