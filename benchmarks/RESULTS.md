# SideQuests Benchmark Results Report

**Generated on:** 2026-03-28 10:46:52

## Executive Summary
SideQuests performance across all benchmarks. Comparison between baseline and augmented modes.

### Go/No-Go Status
| Benchmark | Metric | Threshold | Actual | Sig. (p-val) | Status |
|---|---|---|---|---|---|
| ARC3 | solve_rate_improvement | > 0.05 | 0.08 | 0.042 | ✅ GO |
| LONGCONTEXT | long_context_accuracy_improvement | >= 0.0 | 0.05 | 0.015 | ✅ GO |
| SWE_CI | constraint_compliance_improvement | > 0.0 | 0.12 | 0.008 | ✅ GO |
| AMA | hypothesis_regression | < 0.0 | -0.05 | 0.033 | ✅ GO |

## Model Evaluation Breakdown
| Model | Accuracy | Avg Latency (ms) |
|---|---|---|
| qwen2.5:3b | 68.42% | 931.6 |
| llama3.2:3b | 60.53% | 975.1 |
| qwen2.5:1.5b | 65.79% | 979.1 |
| phi3.5 | 65.79% | 785.7 |
| llama3.1:8b | 63.16% | 1410.5 |

## Hardware & Setup
- **Compute Specs:** Local Machine (Ollama environment)
- **Git Version:** `d54ddc62f71e53b44b8a9a9324d6b24d98dd1ae9`
- **Memory Limit:** 8.0 GB (configured)
- **CPU Limit:** 80% (configured)
- **LLM Provider:** Ollama

## Reproducibility
To reproduce these results, ensure the environment matches the checksums below and run:
```bash
python benchmarks/runner.py --all
```

### Artifact Checksums
| File | SHA-256 Checksum |
|---|---|
| benchmarks/runner.py | 249c76ddb98008f717dc58db958c9a8344f6df873397f68b70c89e3f88c30d12 |
| benchmarks/harness.py | 72c908c5c35d2af00fc48ed732a17e20279d9837e01a7a59a46270afd38bb08d |
| benchmarks/ab_harness.py | e033546964982d89400cc2716c821f675643d9585abd874ed3e395b9053a48d4 |
| benchmarks/config.yaml | f6c04df7865724d9f5cf3898c723fd64265c7d571f88f57b0e540c46068d3ae0 |
| benchmarks/results.json | 03b777789469891f97a923583b0a009d4db0d71f207c60321261aa4b928fd351 |