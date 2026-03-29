"""
Metrics for causal reasoning benchmarks.

Measures:
- Solve rate: percentage of tasks solved correctly
- Constraint consistency: percentage of causal steps completed without constraint violations
- Causal chain depth: number of multi-step dependencies successfully maintained
"""

from __future__ import annotations

from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class CausalMetrics:
    """Aggregated metrics for causal reasoning evaluation."""
    variant: str  # "baseline" or "sidequests"
    solve_rate: float
    avg_steps_completed: float
    constraint_consistency: float  # 1.0 - (total_violations / total_possible_violations)
    avg_causal_chain_depth: float
    avg_memory_retrievals: float
    total_tasks: int
    succeeded: int
    failed: int


def compute_solve_rate(results: List[Any]) -> float:
    """Calculate percentage of tasks solved correctly."""
    if not results:
        return 0.0
    correct = sum(1 for r in results if r.correct)
    return correct / len(results)


def compute_constraint_consistency(results: List[Any]) -> float:
    """
    Calculate constraint consistency score.

    Constraint consistency = 1.0 - (total_violations / max_possible_violations)
    - max_possible_violations = sum of constraint counts across all tasks
    """
    if not results:
        return 1.0

    total_violations = sum(r.constraint_violations for r in results)
    # Each task's constraint count is estimated as (causal_chain_depth * 1.5) to account for interdependencies
    max_possible = sum(max(1, int(r.causal_chain_depth * 1.5)) for r in results)

    if max_possible == 0:
        return 1.0

    consistency = max(0.0, 1.0 - (total_violations / max_possible))
    return consistency


def compute_causal_chain_depth(results: List[Any]) -> float:
    """Calculate average causal chain depth successfully maintained."""
    if not results:
        return 0.0

    # Only count depths from correct solutions
    correct_results = [r for r in results if r.correct]
    if not correct_results:
        return 0.0

    avg_depth = sum(r.causal_chain_depth for r in correct_results) / len(correct_results)
    return avg_depth


def compute_avg_steps_completed(results: List[Any]) -> float:
    """Calculate average steps completed per task."""
    if not results:
        return 0.0
    return sum(r.steps_completed for r in results) / len(results)


def compute_avg_memory_retrievals(results: List[Any]) -> float:
    """Calculate average memory retrievals (SideQuests-specific metric)."""
    if not results:
        return 0.0
    return sum(r.memory_retrievals for r in results) / len(results)


def aggregate_causal_metrics(results: List[Any], variant: str) -> CausalMetrics:
    """Aggregate all metrics for a variant's results."""
    solve_rate = compute_solve_rate(results)
    constraint_consistency = compute_constraint_consistency(results)
    avg_causal_depth = compute_causal_chain_depth(results)
    avg_steps = compute_avg_steps_completed(results)
    avg_memory = compute_avg_memory_retrievals(results)

    correct = sum(1 for r in results if r.correct)
    failed = len(results) - correct

    return CausalMetrics(
        variant=variant,
        solve_rate=round(solve_rate, 4),
        avg_steps_completed=round(avg_steps, 2),
        constraint_consistency=round(constraint_consistency, 4),
        avg_causal_chain_depth=round(avg_causal_depth, 2),
        avg_memory_retrievals=round(avg_memory, 2),
        total_tasks=len(results),
        succeeded=correct,
        failed=failed,
    )


def compare_constraint_consistency(
    baseline_results: List[Any],
    sidequests_results: List[Any],
) -> Dict[str, Any]:
    """Compare constraint consistency between baseline and SideQuests."""
    baseline_consistency = compute_constraint_consistency(baseline_results)
    sidequests_consistency = compute_constraint_consistency(sidequests_results)

    delta = sidequests_consistency - baseline_consistency
    sidequests_advantage = delta > 0

    return {
        "baseline_consistency": round(baseline_consistency, 4),
        "sidequests_consistency": round(sidequests_consistency, 4),
        "consistency_delta": round(delta, 4),
        "sidequests_advantage": sidequests_advantage,
    }


def compare_solve_rates(baseline_results: List[Any], sidequests_results: List[Any]) -> Dict[str, Any]:
    """Compare solve rates between baseline and SideQuests."""
    baseline_rate = compute_solve_rate(baseline_results)
    sidequests_rate = compute_solve_rate(sidequests_results)

    delta = sidequests_rate - baseline_rate
    pct_delta = (delta / baseline_rate * 100) if baseline_rate > 0 else (100 if sidequests_rate > 0 else 0)

    return {
        "baseline_solve_rate": round(baseline_rate, 4),
        "sidequests_solve_rate": round(sidequests_rate, 4),
        "solve_rate_delta": round(delta, 4),
        "solve_rate_delta_pct": round(pct_delta, 1),
        "sidequests_advantage": sidequests_rate > baseline_rate,
    }
