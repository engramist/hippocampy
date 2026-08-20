# SideQuest Brain — Benchmark Setup Matrix

This matrix defines the environmental requirements for local benchmark execution.

| Benchmark | Python Version | Docker Required | Disk Space (Est) | GPU Recommended | Env Vars Required |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **SWE-CI (Internal Sample)** | 3.11+ | No | 1 GB | No | none |
| **Synthetic Long-Context Needle** | 3.10+ | No | 1 GB | No | `OPENAI_API_KEY` or `OLLAMA_BASE` (optional) |
| **Synthetic Causal Arithmetic** | 3.11+ | No | 1 GB | No | none |
| **Synthetic Capacity Constraints** | 3.11+ | No | 1 GB | No | none |
| **AutoResearch** | 3.11+ | No | 1 GB | No | `SIM_SEED` |

## Detail Notes

### SWE-CI (Internal Sample)
- Uses the checked-in sample dataset (`benchmarks/swe_ci/data/swe_ci_sample.json`).
- No external repo cloning is required for the default run.

### Synthetic Long-Context Needle
- Generated tasks are synthetic and lightweight by default (5 per context size).
- External large-scale LoCoBench data is not loaded by this harness.

### Synthetic Causal Arithmetic
- Generated locally from deterministic seeds.

### Synthetic Capacity Constraints
- Generated locally from deterministic seeds.

### AutoResearch (B52)
- **Isolation:** Must use `git worktree` or temporary directory. Do not run in project root.
- **Harness:** Python-based `benchmarks/autoresearch/harness.py`.
