import pytest
import asyncio
from benchmarks.longcontext.harness import LongContextHarness
from benchmarks.harness import BenchmarkConfig
from benchmarks.ab_harness import ABVariant

@pytest.mark.asyncio
async def test_longcontext_harness_initialization():
    config = BenchmarkConfig(name="longcontext_test")
    harness = LongContextHarness(config)
    assert harness.config.name == "longcontext_test"
    assert len(harness.context_sizes) == 3
    assert 8192 in harness.context_sizes
    assert 32768 in harness.context_sizes
    assert 131072 in harness.context_sizes

@pytest.mark.asyncio
async def test_longcontext_harness_setup():
    config = BenchmarkConfig(name="longcontext_test")
    harness = LongContextHarness(config)
    await harness.setup()
    assert len(harness.tasks) > 0
    # Should have tasks for each context size
    sizes_with_tasks = set(t.target_context_size for t in harness.tasks)
    for size in harness.context_sizes:
        assert size in sizes_with_tasks

@pytest.mark.asyncio
async def test_longcontext_harness_run():
    config = BenchmarkConfig(name="longcontext_test")
    harness = LongContextHarness(config)
    await harness.setup()
    result = await harness.run()
    
    assert result.success is True
    assert "longcontext_eval" not in result.metrics # Wait, I named it summary in my implementation
    assert "summary" in result.metrics
    assert "context_sizes" in result.metrics
    
    summary = result.metrics["summary"]
    # 3 sizes * 2 variants = 6 entries
    assert len(summary) == 6
    
    # Check if SideQuests generally uses fewer tokens
    sq_tokens = [m["avg_tokens_used"] for m in summary if m["variant"] == "sidequests"]
    baseline_tokens = [m["avg_tokens_used"] for m in summary if m["variant"] == "baseline"]
    
    for sq, bl in zip(sq_tokens, baseline_tokens):
        # At large sizes, SideQuests should be much more efficient
        if bl > 10000:
            assert sq < bl

@pytest.mark.asyncio
async def test_longcontext_metrics_aggregation():
    from benchmarks.longcontext.metrics import aggregate_metrics
    results = [
        {"correct": True, "tokens_used": 100},
        {"correct": False, "tokens_used": 200},
        {"correct": True, "tokens_used": 150}
    ]
    metrics = aggregate_metrics(results, 8192, "baseline")
    assert metrics.accuracy == pytest.approx(0.666, rel=1e-2)
    assert metrics.avg_tokens_used == 150
    assert metrics.context_size == 8192
    assert metrics.variant == "baseline"
