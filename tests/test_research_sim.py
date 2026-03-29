import pytest

from benchmarks.harness import BenchmarkConfig
from benchmarks.research_sim import ResearchSimHarness
from benchmarks.research_sim.metrics import RegressionMetrics, compare_regression_rates


@pytest.mark.asyncio
async def test_research_sim_hypotheses_are_reproducible():
    params = {"seed": 424242}
    config_a = BenchmarkConfig(name="research_repro_a", parameters=params)
    harness_a = ResearchSimHarness(config_a)
    await harness_a.setup()
    result_a = await harness_a.run()

    config_b = BenchmarkConfig(name="research_repro_b", parameters=params)
    harness_b = ResearchSimHarness(config_b)
    await harness_b.setup()
    result_b = await harness_b.run()

    assert result_a.metrics["history"]["baseline"] == result_b.metrics["history"]["baseline"]
    assert result_a.metrics["history"]["sidequests"] == result_b.metrics["history"]["sidequests"]


@pytest.mark.asyncio
async def test_research_sim_detects_memory_benefit():
    config = BenchmarkConfig(name="research_metrics", parameters={"seed": 98765})
    harness = ResearchSimHarness(config)
    await harness.setup()
    result = await harness.run()

    baseline = result.metrics["baseline"]
    sidequests = result.metrics["sidequests"]
    assert baseline["regression_rate"] >= 0.1
    assert baseline["regression_rate"] > sidequests["regression_rate"]
    assert "regression_count" in baseline
    assert "regression_count" in sidequests

    stats = result.metrics["statistical_significance"]
    assert 0.0 <= stats.get("p_value", 1.0) <= 1.0
    assert "z_score" in stats


def test_compare_regression_rates_handles_empty_failures():
    baseline = RegressionMetrics(
        variant="baseline",
        total_attempts=5,
        failed_attempts=0,
        regression_count=0,
        success_rate=1.0,
        regression_rate=0.0,
    )
    sidequests = RegressionMetrics(
        variant="sidequests",
        total_attempts=5,
        failed_attempts=0,
        regression_count=0,
        success_rate=1.0,
        regression_rate=0.0,
    )
    significance = compare_regression_rates(baseline, sidequests)
    assert significance["p_value"] == 1.0
    assert significance.get("reason") is not None
