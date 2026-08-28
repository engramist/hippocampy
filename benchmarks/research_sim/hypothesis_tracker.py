from dataclasses import dataclass
from typing import Any, Dict, List


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
    """Tracker that records hypothesis outcomes and regression indicators.

    B366: `_failed_hypotheses` used to be a `Set[str]`. `_select_hypothesis`'s
    baseline branch does `rng.choice(list(self._failed_hypotheses))` -- a
    seeded `Random.choice()` deterministically picks an *index*, but which
    hypothesis string sits at that index depended on `set`'s iteration
    order, which for strings depends on Python's per-process hash
    randomization (`PYTHONHASHSEED`, random by default). So the exact same
    "fixed" RNG seed produced a genuinely different sequence of choices
    across different process invocations (e.g. different CI runs), while
    being perfectly stable *within* a single run -- exactly the "flaky
    across runs, never within one" signature this card investigated.
    Reproduced directly: PYTHONHASHSEED=12 (among others) reliably
    recreates the exact CI failure (baseline regression_rate
    0.6363636363636364 vs sidequests' 0.65). Fixed by using a `dict` (keys
    only, insertion-ordered since Python 3.7) instead of a `set` --
    `failed_hypotheses()` is now a pure function of the seeded RNG's
    actual sequence of decisions, with no incidental dependency on hash
    seed.
    """

    def __init__(self) -> None:
        self._attempts: List[HypothesisAttempt] = []
        self._failed_hypotheses: Dict[str, None] = {}

    def record_attempt(self, hypothesis: str, task_id: str, success: bool) -> None:
        """Capture an attempt and whether it re-uses a known failed hypothesis."""
        repeated_failure = not success and hypothesis in self._failed_hypotheses
        if not success:
            self._failed_hypotheses[hypothesis] = None
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
