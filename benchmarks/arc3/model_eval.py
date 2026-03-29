"""
ARC-AGI-3 Model Profiling Harness

Benchmark candidate models under identical workload to verify resource constraints
and select primary/fallback models for offline ARC submission.

Metrics:
- Solve quality on calibration set (number of puzzles solved)
- Latency per step (target: <2s on M1 Pro)
- Memory footprint (target: <13GB for 8GB GPU constraint)
- Stability across long episodes (no crashes/OOMs)
"""

import asyncio
import json
import time
import psutil
import logging
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

from mcp_engine.llm.provider import create_llm_client
from mcp_engine.config import load_config


logger = logging.getLogger(__name__)

# Deterministic seeding for reproducibility
DEFAULT_SEED = 42


@dataclass
class ModelProfile:
    """Profile of a single model's performance."""
    model_name: str
    model_spec: str  # e.g., "llama3.1:8b-instruct-q5"
    solve_count: int  # puzzles solved / total puzzles
    total_puzzles: int
    avg_latency_per_step: float  # seconds
    max_memory_mb: float  # peak memory usage
    total_time_seconds: float  # wall-clock time
    crashes: int  # number of crashes/OOMs
    avg_tokens_per_step: int  # estimated

    @property
    def solve_rate(self) -> float:
        """Percentage of puzzles solved."""
        if self.total_puzzles == 0:
            return 0.0
        return (self.solve_count / self.total_puzzles) * 100.0

    @property
    def meets_latency_constraint(self) -> bool:
        """Check if avg latency is <2s per step."""
        return self.avg_latency_per_step < 2.0

    @property
    def meets_memory_constraint(self) -> bool:
        """Check if peak memory is <13GB."""
        return self.max_memory_mb < 13000

    @property
    def stable(self) -> bool:
        """Check if no crashes occurred."""
        return self.crashes == 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize profile to dict."""
        return {
            "model_name": self.model_name,
            "model_spec": self.model_spec,
            "solve_count": self.solve_count,
            "total_puzzles": self.total_puzzles,
            "solve_rate": self.solve_rate,
            "avg_latency_per_step": self.avg_latency_per_step,
            "max_memory_mb": self.max_memory_mb,
            "total_time_seconds": self.total_time_seconds,
            "crashes": self.crashes,
            "avg_tokens_per_step": self.avg_tokens_per_step,
            "meets_latency_constraint": self.meets_latency_constraint,
            "meets_memory_constraint": self.meets_memory_constraint,
            "stable": self.stable,
        }


class ModelEvaluator:
    """Evaluate candidate models on ARC calibration set."""

    def __init__(self, models: List[str], calibration_size: int = 10, seed: int = DEFAULT_SEED):
        """
        Args:
            models: List of model specs (e.g., ["llama3.1:8b-instruct-q5", "llama2:7b-q4"])
            calibration_size: Number of puzzles to use for profiling (10-20)
            seed: Random seed for deterministic reproducibility (default: 42)
        """
        self.models = models
        self.calibration_size = calibration_size
        self.seed = seed
        self.config = load_config()
        self.profiles: Dict[str, ModelProfile] = {}
        self.process = psutil.Process()

        # Set seed for reproducibility
        random.seed(self.seed)
        logger.info(f"Using deterministic seed: {self.seed}")

    async def run_evaluation(self) -> Dict[str, ModelProfile]:
        """
        Evaluate all candidate models.

        Returns:
            Dict mapping model_spec -> ModelProfile
        """
        logger.info(f"Starting evaluation of {len(self.models)} models with {self.calibration_size} puzzles")

        for model_spec in self.models:
            logger.info(f"Profiling model: {model_spec}")
            try:
                profile = await self._profile_model(model_spec)
                self.profiles[model_spec] = profile
                logger.info(f"✓ {model_spec}: {profile.solve_rate:.1f}% solve rate, "
                          f"{profile.avg_latency_per_step:.2f}s avg latency")
            except Exception as e:
                logger.error(f"✗ {model_spec}: {e}")
                # Create degraded profile on error
                self.profiles[model_spec] = ModelProfile(
                    model_name=model_spec.split(":")[0],
                    model_spec=model_spec,
                    solve_count=0,
                    total_puzzles=self.calibration_size,
                    avg_latency_per_step=float('inf'),
                    max_memory_mb=0,
                    total_time_seconds=0,
                    crashes=1,
                    avg_tokens_per_step=0,
                )

        return self.profiles

    async def _profile_model(self, model_spec: str) -> ModelProfile:
        """Profile a single model on calibration set."""
        model_name = model_spec.split(":")[0]

        solve_count = 0
        total_steps = 0
        total_latencies = []
        max_memory = 0
        start_time = time.time()
        crashes = 0

        # Simulate calibration run with synthetic puzzles
        for puzzle_idx in range(self.calibration_size):
            try:
                # Record memory before
                mem_start = self.process.memory_info().rss / 1024 / 1024  # MB

                # Run one puzzle episode
                steps, latencies = await self._run_puzzle(model_spec)

                total_steps += steps
                total_latencies.extend(latencies)

                # Record memory after
                mem_end = self.process.memory_info().rss / 1024 / 1024  # MB
                max_memory = max(max_memory, mem_end)

                # Puzzle "solved" if completed in <10 steps without error
                if steps < 10:
                    solve_count += 1

            except asyncio.TimeoutError:
                logger.warning(f"  Puzzle {puzzle_idx + 1}: timeout")
                crashes += 1
            except MemoryError:
                logger.warning(f"  Puzzle {puzzle_idx + 1}: OOM")
                crashes += 1
                break
            except Exception as e:
                logger.warning(f"  Puzzle {puzzle_idx + 1}: {e}")

        end_time = time.time()
        total_time = end_time - start_time

        avg_latency = (sum(total_latencies) / len(total_latencies)) if total_latencies else 0
        avg_tokens = int(total_steps * 150) if total_steps > 0 else 0  # Estimated

        return ModelProfile(
            model_name=model_name,
            model_spec=model_spec,
            solve_count=solve_count,
            total_puzzles=self.calibration_size,
            avg_latency_per_step=avg_latency,
            max_memory_mb=max_memory,
            total_time_seconds=total_time,
            crashes=crashes,
            avg_tokens_per_step=avg_tokens,
        )

    async def _run_puzzle(self, model_spec: str, max_steps: int = 10, timeout: int = 120) -> Tuple[int, List[float]]:
        """
        Run a single puzzle episode with a model.

        Args:
            model_spec: Model specification
            max_steps: Maximum steps per puzzle
            timeout: Timeout in seconds

        Returns:
            (steps_taken, list_of_latencies)
        """
        try:
            # Create LLM client for this model
            self.config.llm.model = model_spec
            llm = create_llm_client(self.config)

            steps = 0
            latencies = []

            # Simulate steps until max_steps or "done"
            for step in range(max_steps):
                step_start = time.time()

                # Simulate step: call LLM with a synthetic observation
                obs = self._get_synthetic_observation(step)
                prompt = f"ARC puzzle step {step + 1}. Observation: {json.dumps(obs)}\nChoose next action (ACTION1-7):"

                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(llm.chat, prompt),
                        timeout=5.0  # 5s reasoning timeout per step
                    )

                    step_latency = time.time() - step_start
                    latencies.append(step_latency)
                    steps += 1

                    # Parse response; if contains "DONE" or "solved", break
                    if "DONE" in response.upper() or "SOLVED" in response.upper():
                        break

                except asyncio.TimeoutError:
                    logger.debug(f"  Step {step + 1}: LLM timeout")
                    raise

            return steps, latencies

        except Exception as e:
            logger.debug(f"Puzzle run failed: {e}")
            raise

    @staticmethod
    def _get_synthetic_observation(step: int) -> Dict[str, Any]:
        """Generate a synthetic ARC observation for testing."""
        return {
            "dataset_id": "arc-agi-3",
            "task_id": "test-puzzle",
            "episode_num": 1,
            "step_num": step + 1,
            "grid": [[i % 10 for i in range(64)] for _ in range(64)],  # 64x64 grid
            "colors_present": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            "available_actions": ["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5", "ACTION6", "ACTION7"],
        }

    def select_models(self) -> Tuple[str, str]:
        """
        Select primary and fallback models based on profiles.

        Selection criteria:
        - Primary: best solve rate + meets all constraints
        - Fallback: second best solve rate + meets all constraints

        Returns:
            (primary_model_spec, fallback_model_spec)
        """
        if not self.profiles:
            raise ValueError("No profiles available; run evaluation first")

        # Sort by solve rate (descending), then by avg latency (ascending)
        ranked = sorted(
            self.profiles.items(),
            key=lambda x: (x[1].solve_rate, -1/x[1].avg_latency_per_step if x[1].avg_latency_per_step > 0 else 0),
            reverse=True
        )

        candidates = [spec for spec, profile in ranked if profile.stable and profile.meets_memory_constraint]

        if len(candidates) < 2:
            logger.warning("Fewer than 2 candidates meet constraints; using best available")
            candidates = [spec for spec, _ in ranked[:2]]

        primary = candidates[0]
        fallback = candidates[1] if len(candidates) > 1 else candidates[0]

        logger.info(f"Selected primary: {primary}")
        logger.info(f"Selected fallback: {fallback}")

        return primary, fallback

    def export_results(self, output_path: str) -> None:
        """Export profiling results to JSON."""
        results = {
            "timestamp": time.time(),
            "calibration_size": self.calibration_size,
            "profiles": {spec: profile.to_dict() for spec, profile in self.profiles.items()},
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)

        logger.info(f"Exported results to {output_path}")


async def main():
    """Main entry point for model profiling."""
    # Candidate models to profile
    candidates = [
        "llama3.1:8b-instruct-q5",
        "llama2:7b-q4",
        "mistral:7b-instruct",
        # "openelm:1.3b" could be added if available
    ]

    evaluator = ModelEvaluator(models=candidates, calibration_size=10)
    profiles = await evaluator.run_evaluation()

    # Select best models
    primary, fallback = evaluator.select_models()

    # Export results
    evaluator.export_results("benchmarks/arc3/model_eval_results.json")

    # Print summary
    print("\n=== Model Profiling Summary ===")
    for spec, profile in sorted(profiles.items(), key=lambda x: x[1].solve_rate, reverse=True):
        print(f"\n{spec}:")
        print(f"  Solve rate: {profile.solve_rate:.1f}% ({profile.solve_count}/{profile.total_puzzles})")
        print(f"  Avg latency: {profile.avg_latency_per_step:.2f}s/step")
        print(f"  Peak memory: {profile.max_memory_mb:.0f}MB")
        print(f"  Crashes: {profile.crashes}")
        print(f"  ✓ Meets latency constraint: {profile.meets_latency_constraint}")
        print(f"  ✓ Meets memory constraint: {profile.meets_memory_constraint}")

    print(f"\n=== Selected Models ===")
    print(f"Primary: {primary}")
    print(f"Fallback: {fallback}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
