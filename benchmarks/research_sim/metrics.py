from dataclasses import dataclass
import math
from typing import Any, Dict


@dataclass
class RegressionMetrics:
    variant: str
    total_attempts: int
    failed_attempts: int
    regression_count: int
    success_rate: float
    regression_rate: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant": self.variant,
            "total_attempts": self.total_attempts,
            "failed_attempts": self.failed_attempts,
            "regression_count": self.regression_count,
            "success_rate": self.success_rate,
            "regression_rate": self.regression_rate,
        }


def compute_regression_metrics(
    variant: str, total_attempts: int, failed_attempts: int, regression_count: int
) -> RegressionMetrics:
    success_rate = (total_attempts - failed_attempts) / total_attempts if total_attempts else 0.0
    regression_rate = regression_count / failed_attempts if failed_attempts else 0.0
    return RegressionMetrics(
        variant=variant,
        total_attempts=total_attempts,
        failed_attempts=failed_attempts,
        regression_count=regression_count,
        success_rate=success_rate,
        regression_rate=regression_rate,
    )


def _normal_cdf(value: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def compare_regression_rates(
    baseline: RegressionMetrics, sidequests: RegressionMetrics
) -> Dict[str, Any]:
    if baseline.failed_attempts == 0 or sidequests.failed_attempts == 0:
        return {
            "p_value": 1.0,
            "z_score": 0.0,
            "reason": "Insufficient failures to compute significance",
            "baseline_rate": baseline.regression_rate,
            "sidequests_rate": sidequests.regression_rate,
        }

    pooled_failures = baseline.failed_attempts + sidequests.failed_attempts
    pooled_regressions = baseline.regression_count + sidequests.regression_count
    pooled_rate = pooled_regressions / pooled_failures
    variance = pooled_rate * (1 - pooled_rate)
    denom = variance * (1 / baseline.failed_attempts + 1 / sidequests.failed_attempts)
    se = math.sqrt(denom) if denom > 0 else 0.0
    if se == 0:
        z_score = 0.0
    else:
        z_score = (baseline.regression_rate - sidequests.regression_rate) / se
    p_value = 2 * (1 - _normal_cdf(abs(z_score)))
    return {
        "p_value": max(0.0, min(1.0, p_value)),
        "z_score": z_score,
        "baseline_rate": baseline.regression_rate,
        "sidequests_rate": sidequests.regression_rate,
        "pooled_rate": pooled_rate,
    }
