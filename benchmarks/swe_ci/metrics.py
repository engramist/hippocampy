from __future__ import annotations

from typing import Sequence

from . import SweCiTask

MetricResult = dict[str, float]
MEMORY_BONUS_FACTOR = 0.35


def compute_metrics(tasks: Sequence[SweCiTask], use_memory: bool) -> MetricResult:
    """Compute simple violation, rework, and quality metrics for the provided tasks."""
    seen_constraints: set[str] = set()
    total_violation = 0.0
    total_rework = 0.0
    total_quality = 0.0

    for task in tasks:
        base = max(0.0, min(1.0, task.difficulty))
        violation_discount = 0.0
        if use_memory and task.constraints:
            overlap = len(set(task.constraints) & seen_constraints)
            recall_ratio = overlap / len(task.constraints)
            violation_discount = base * MEMORY_BONUS_FACTOR * recall_ratio
        violation_prob = max(0.0, base - violation_discount)

        total_violation += violation_prob
        total_rework += 1.0 + violation_prob * 1.6
        total_quality += max(0.0, 1.0 - violation_prob * 0.9)

        seen_constraints.update(task.constraints)

    count = len(tasks)
    if count == 0:
        return {
            "constraint_violation_rate": 0.0,
            "rework_cycles": 0.0,
            "quality_score": 0.0,
        }

    return {
        "constraint_violation_rate": total_violation / count,
        "rework_cycles": total_rework / count,
        "quality_score": total_quality / count,
    }


def compare_constraint_violation(
    baseline_metrics: MetricResult, memory_metrics: MetricResult
) -> dict[str, float | bool]:
    delta = baseline_metrics["constraint_violation_rate"] - memory_metrics["constraint_violation_rate"]
    return {
        "violation_delta": delta,
        "memory_advantage": delta > 0,
    }
