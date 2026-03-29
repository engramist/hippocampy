import os
import json
import yaml
import pytest
from benchmarks.report_generator import generate_report

def test_report_generation(tmp_path, monkeypatch):
    # Setup mock files in a temporary directory
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    results_dir = bench_dir / "results"
    results_dir.mkdir()
    
    results_file = bench_dir / "results.json"
    model_eval_file = bench_dir / "model_eval_results.json"
    thresholds_file = bench_dir / "thresholds.yaml"
    report_file = bench_dir / "RESULTS.md"
    checksums_file = bench_dir / "checksums.txt"
    
    # Mock data
    results_data = [
        {
            "benchmark_name": "arc3",
            "success": True,
            "duration": 3600,
            "metrics": {
                "solve_rate_improvement": 0.08,
                "p_value": 0.042
            }
        }
    ]
    with open(results_file, 'w') as f:
        json.dump(results_data, f)
        
    model_eval_data = {
        "test-model": {
            "accuracy": 0.75,
            "avg_latency_ms": 100.0
        }
    }
    with open(model_eval_file, 'w') as f:
        json.dump(model_eval_data, f)
        
    thresholds_data = {
        "arc3": {
            "metric": "solve_rate_improvement",
            "threshold": 0.05,
            "operator": ">"
        }
    }
    with open(thresholds_file, 'w') as f:
        yaml.dump(thresholds_data, f)
        
    # Monkeypatch constants in report_generator
    import benchmarks.report_generator
    monkeypatch.setattr(benchmarks.report_generator, "RESULTS_DIR", str(results_dir))
    monkeypatch.setattr(benchmarks.report_generator, "RESULTS_FILE", str(results_file))
    monkeypatch.setattr(benchmarks.report_generator, "MODEL_EVAL_FILE", str(model_eval_file))
    monkeypatch.setattr(benchmarks.report_generator, "THRESHOLDS_FILE", str(thresholds_file))
    monkeypatch.setattr(benchmarks.report_generator, "REPORT_FILE", str(report_file))
    monkeypatch.setattr(benchmarks.report_generator, "CHECKSUMS_FILE", str(checksums_file))
    
    # Run generator
    generate_report()
    
    # Assertions
    assert report_file.exists()
    assert checksums_file.exists()
    assert (results_dir / "arc3.json").exists()
    
    with open(report_file, 'r') as f:
        content = f.read()
        assert "# SideQuests Benchmark Results Report" in content
        assert "ARC3" in content
        assert "✅ GO" in content
        assert "test-model" in content
        assert "75.00%" in content
