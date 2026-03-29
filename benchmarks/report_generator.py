import json
import os
import yaml
import hashlib
import time
from datetime import datetime

RESULTS_DIR = "benchmarks/results"
RESULTS_FILE = "benchmarks/results.json"
MODEL_EVAL_FILE = "benchmarks/model_eval_results.json"
THRESHOLDS_FILE = "benchmarks/thresholds.yaml"
REPORT_FILE = "benchmarks/RESULTS.md"
CHECKSUMS_FILE = "benchmarks/checksums.txt"

def get_checksum(file_path):
    if not os.path.exists(file_path):
        return "N/A"
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def get_git_version():
    try:
        import subprocess
        return subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('ascii').strip()
    except Exception:
        return "N/A"

def generate_report():
    # Load data
    with open(RESULTS_FILE, 'r') as f:
        results_data = json.load(f)
    
    with open(THRESHOLDS_FILE, 'r') as f:
        thresholds = yaml.safe_load(f)
    
    with open(MODEL_EVAL_FILE, 'r') as f:
        model_eval_data = json.load(f)

    # Prepare detailed results
    for res in results_data:
        benchmark_name = res['benchmark_name']
        with open(os.path.join(RESULTS_DIR, f"{benchmark_name}.json"), 'w') as f:
            json.dump(res, f, indent=2)

    # Start report
    report = []
    report.append("# SideQuests Benchmark Results Report")
    report.append(f"\n**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    report.append("\n## Executive Summary")
    report.append("SideQuests performance across all benchmarks. Comparison between baseline and augmented modes.")
    
    report.append("\n### Go/No-Go Status")
    report.append("| Benchmark | Metric | Threshold | Actual | Sig. (p-val) | Status |")
    report.append("|---|---|---|---|---|---|")
    
    for benchmark, criteria in thresholds.items():
        # Find result for this benchmark
        res = next((r for r in results_data if r['benchmark_name'] == benchmark), None)
        if res:
            actual = res['metrics'].get(criteria['metric'], "N/A")
            sig = res['metrics'].get("p_value", "N/A")
            
            threshold = criteria['threshold']
            operator = criteria['operator']
            
            if actual != "N/A":
                # Evaluation logic
                success = False
                if operator == ">":
                    success = actual > threshold
                elif operator == ">=":
                    success = actual >= threshold
                elif operator == "<":
                    success = actual < threshold
                elif operator == "<=":
                    success = actual <= threshold
                
                status = "✅ GO" if success else "❌ NO-GO"
                report.append(f"| {benchmark.upper()} | {criteria['metric']} | {operator} {threshold} | {actual} | {sig} | {status} |")
            else:
                report.append(f"| {benchmark.upper()} | {criteria['metric']} | {operator} {criteria['threshold']} | TBD | {sig} | PENDING |")
        else:
            report.append(f"| {benchmark.upper()} | {criteria['metric']} | {operator} {criteria['threshold']} | N/A | N/A | MISSING |")

    report.append("\n## Model Evaluation Breakdown")
    report.append("| Model | Accuracy | Avg Latency (ms) |")
    report.append("|---|---|---|")
    for model, metrics in model_eval_data.items():
        report.append(f"| {model} | {metrics['accuracy']:.2%} | {metrics['avg_latency_ms']:.1f} |")

    report.append("\n## Hardware & Setup")
    report.append("- **Compute Specs:** Local Machine (Ollama environment)")
    report.append(f"- **Git Version:** `{get_git_version()}`")
    report.append("- **Memory Limit:** 8.0 GB (configured)")
    report.append("- **CPU Limit:** 80% (configured)")
    report.append("- **LLM Provider:** Ollama")
    
    report.append("\n## Reproducibility")
    report.append("To reproduce these results, ensure the environment matches the checksums below and run:")
    report.append("```bash\npython benchmarks/runner.py --all\n```")
    
    checksums = []
    files_to_hash = [
        "benchmarks/runner.py",
        "benchmarks/harness.py",
        "benchmarks/ab_harness.py",
        "benchmarks/config.yaml",
        "benchmarks/results.json"
    ]
    
    report.append("\n### Artifact Checksums")
    report.append("| File | SHA-256 Checksum |")
    report.append("|---|---|")
    for f_path in files_to_hash:
        csum = get_checksum(f_path)
        report.append(f"| {f_path} | {csum} |")
        checksums.append(f"{csum}  {f_path}")
    
    # Write report
    with open(REPORT_FILE, 'w') as f:
        f.write("\n".join(report))
    
    # Write checksums file
    with open(CHECKSUMS_FILE, 'w') as f:
        f.write("\n".join(checksums))
    
    print(f"Report generated: {REPORT_FILE}")

if __name__ == "__main__":
    generate_report()
