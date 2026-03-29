import asyncio
import yaml
import json
import os
from typing import List, Dict, Type
from benchmarks.harness import BenchmarkHarness, BenchmarkConfig, BenchmarkResult

class BenchmarkRunner:
    def __init__(self, config_path: str = "benchmarks/config.yaml"):
        self.config_path = config_path
        self.config_data = self._load_config()
        self.benchmarks: List[BenchmarkHarness] = []

    def _load_config(self) -> Dict:
        if not os.path.exists(self.config_path):
            # Return empty defaults if no config exists
            return {"global": {}, "benchmarks": []}
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def register_benchmark(self, harness_class: Type[BenchmarkHarness], benchmark_name: str):
        """Finds config for benchmark_name and registers its harness."""
        benchmark_configs = self.config_data.get("benchmarks", [])
        config_data = next((c for c in benchmark_configs if c["name"] == benchmark_name), None)
        
        if not config_data:
            # Fallback to defaults
            config_data = {"name": benchmark_name}

        # Merge with global defaults
        global_config = self.config_data.get("global", {})
        merged_config = {
            "name": config_data.get("name"),
            "description": config_data.get("description", ""),
            "timeout": config_data.get("timeout", global_config.get("timeout", 3600)),
            "memory_limit_gb": global_config.get("memory_limit_gb", 8.0),
            "cpu_limit_percent": global_config.get("cpu_limit_percent", 80.0),
            "parameters": config_data.get("parameters", {})
        }
        
        config = BenchmarkConfig(**merged_config)
        self.benchmarks.append(harness_class(config))

    async def run_all(self, parallel: bool = False) -> List[BenchmarkResult]:
        """Runs all registered benchmarks."""
        if parallel:
            results = await asyncio.gather(*(b.execute() for b in self.benchmarks))
        else:
            results = []
            for benchmark in self.benchmarks:
                result = await benchmark.execute()
                results.append(result)
        
        # Aggregate results
        self.save_results(list(results))
        return list(results)

    def save_results(self, results: List[BenchmarkResult], output_file: str = "benchmarks/results.json"):
        """Saves results in standardized JSON format."""
        data = []
        for r in results:
            data.append({
                "benchmark_name": r.benchmark_name,
                "success": r.success,
                "duration": r.duration,
                "metrics": r.metrics,
                "error": r.error,
                "timestamp": r.timestamp
            })
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
