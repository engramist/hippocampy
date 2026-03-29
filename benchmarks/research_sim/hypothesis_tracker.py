from dataclasses import dataclass
from typing import Any, Dict, List, Set


@dataclass
class HypothesisAttempt:
    """Record of a single hypothesis attempt in the research sim."""

    hypothesis: str
    task_id: str
    success: bool
    repeated_failure: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis": self.hypothesis,
            "task_id": self.task_id,
            "success": self.success,
            "repeated_failure": self.repeated_failure,
        }


class HypothesisTracker:
    """Tracker that records hypothesis outcomes and regression indicators."""

    def __init__(self) -> None:
        self._attempts: List[HypothesisAttempt] = []
        self._failed_hypotheses: Set[str] = set()

    def record_attempt(self, hypothesis: str, task_id: str, success: bool) -> None:
        """Capture an attempt and whether it re-uses a known failed hypothesis."""
        repeated_failure = not success and hypothesis in self._failed_hypotheses
        if not success:
            self._failed_hypotheses.add(hypothesis)
        attempt = HypothesisAttempt(
            hypothesis=hypothesis,
            task_id=task_id,
            success=success,
            repeated_failure=repeated_failure,
        )
        self._attempts.append(attempt)

    def has_failed_before(self, hypothesis: str) -> bool:
        return hypothesis in self._failed_hypotheses

    def total_attempts(self) -> int:
        return len(self._attempts)

    def failed_attempts(self) -> int:
        return sum(1 for attempt in self._attempts if not attempt.success)

    def regression_count(self) -> int:
        return sum(1 for attempt in self._attempts if attempt.repeated_failure)

    def history(self) -> List[Dict[str, Any]]:
        return [attempt.to_dict() for attempt in self._attempts]

    def failed_hypotheses(self) -> List[str]:
        return list(self._failed_hypotheses)
