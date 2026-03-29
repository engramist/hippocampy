import pytest
import asyncio
import os
import json
from benchmarks.harness import BenchmarkHarness, BenchmarkConfig, BenchmarkResult
from benchmarks.runner import BenchmarkRunner

class MockBenchmark(BenchmarkHarness):
    async def setup(self) -> None:
        self.setup_called = True

    async def run(self) -> BenchmarkResult:
        await asyncio.sleep(0.1)  # Simulate some work
        return BenchmarkResult(
            benchmark_name=self.config.name,
            success=True,
            duration=0.1,
            metrics={"accuracy": 0.95}
        )

    async def teardown(self) -> None:
        self.teardown_called = True

@pytest.mark.asyncio
async def test_benchmark_harness_execution():
    config = BenchmarkConfig(name="test_bench", timeout=1)
    harness = MockBenchmark(config)
    
    result = await harness.execute()
    
    assert result.success is True
    assert result.benchmark_name == "test_bench"
    assert result.metrics["accuracy"] == 0.95
    assert harness.setup_called is True
    assert harness.teardown_called is True

@pytest.mark.asyncio
async def test_benchmark_harness_timeout():
    class SlowBenchmark(MockBenchmark):
        async def run(self) -> BenchmarkResult:
            await asyncio.sleep(2)
            return await super().run()

    config = BenchmarkConfig(name="slow_bench", timeout=1)
    harness = SlowBenchmark(config)
    
    result = await harness.execute()
    
    assert result.success is False
    assert "timed out" in result.error

@pytest.mark.asyncio
async def test_benchmark_runner():
    runner = BenchmarkRunner()
    runner.register_benchmark(MockBenchmark, "arc3")
    
    results = await runner.run_all()
    
    assert len(results) == 1
    assert results[0].benchmark_name == "arc3"
    assert os.path.exists("benchmarks/results.json")
    
    with open("benchmarks/results.json", 'r') as f:
        data = json.load(f)
        assert data[0]["benchmark_name"] == "arc3"
    
    # Cleanup
    if os.path.exists("benchmarks/results.json"):
        os.remove("benchmarks/results.json")

@pytest.mark.asyncio
async def test_benchmark_runner_parallel():
    runner = BenchmarkRunner()
    runner.register_benchmark(MockBenchmark, "arc3")
    runner.register_benchmark(MockBenchmark, "longcontext")
    
    results = await runner.run_all(parallel=True)
    
    assert len(results) == 2
    assert results[0].benchmark_name == "arc3"
    assert results[1].benchmark_name == "longcontext"
