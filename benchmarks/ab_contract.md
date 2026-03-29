# A/B Evaluation Contract for SideQuests vs. Baseline

**Card:** B48 | **Version:** 1.0 | **Date:** 2026-03-28

## Overview

This document defines the formal protocol and data contract for A/B evaluation comparing SideQuests (with full memory pipeline) against a baseline system. The goal is to establish fair, reproducible, and scientifically rigorous comparison of the two systems across multiple evaluation metrics.

## System Definitions

### Baseline (Control)
- **Description:** Standard retrieval without memory ingestion or working memory optimization
- **Features disabled:**
  - Passive ingestion (no `notify_turn` processing)
  - Working memory deduplication (no load tracking)
  - Long-context session handoff (treats each session as independent)
- **Key characteristics:**
  - Fresh context window every session
  - No accumulated learning from prior turns
  - Single-turn reasoning within context limits

### SideQuests (Experimental)
- **Description:** Full memory pipeline with context window optimization
- **Features enabled:**
  - Passive ingestion (Steps 1–7 of Gated Consolidation Loop)
  - Working memory optimization (load tracking, smart dedup)
  - Session handoff (proactive knowledge transfer between contexts)
- **Key characteristics:**
  - Persistent memory across sessions
  - Smart context window utilization
  - Cross-session knowledge continuity

## Controlled Variables

All of the following MUST be identical between Baseline and SideQuests runs:

1. **Task Set:** Identical sequence of tasks, in identical order
2. **LLM Model:** Same model, same version, same configuration
3. **Temperature & Sampling:** Identical hyperparameters
4. **Random Seeds:** Fixed seed applied to all RNG calls (task selection, sampling, etc.)
5. **System Prompt:** Same instructions for both systems (except memory tool availability)
6. **Task Order:** Deterministic, reproducible task ordering
7. **Input Encoding:** Same text preprocessing, tokenization, etc.

## Random Seed Protocol

To ensure reproducibility, both runs must use a **fixed, documented seed** applied at the beginning of execution:

```python
import random
import numpy as np
import torch

GLOBAL_SEED = 42  # Documented in run metadata

def set_global_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    # Also seed LLM provider if applicable (Ollama, OpenAI, etc.)
```

**Requirement:** Every random call in the task harness, task generator, and LLM provider MUST use the seeded RNG. No unseeded `random.random()` or `os.urandom()` calls.

**Verification:** Re-run with identical seed → identical results (within floating-point precision ±1e-6).

## Task Manifest & Checksums

A task manifest (JSON) defines the complete task set with checksums for reproducibility:

```json
{
  "manifest_version": "1.0",
  "global_seed": 42,
  "task_set_hash": "<SHA256 of full task set>",
  "timestamp": "2026-03-28T00:00:00Z",
  "tasks": [
    {
      "task_id": "task_001",
      "category": "reasoning",
      "prompt_hash": "<SHA256 of task prompt>",
      "expected_output": "...",
      "reference_solution": "..."
    },
    ...
  ]
}
```

- **task_set_hash:** SHA256 of the concatenated prompts of all tasks. If this matches between two runs, the task set is identical.
- **prompt_hash:** Per-task SHA256 for auditing.

## Measurement Points

### Core Metrics

1. **Solve Rate** — Percentage of tasks correctly solved
   - Measured per task: correct (1) or incorrect (0)
   - Aggregated: `(correct_count / total_count) × 100%`

2. **Steps to Solve** — Average number of turns/steps before correct solution
   - Measured per task: count of turns required
   - Aggregated: `sum(steps) / correct_count`
   - Failed tasks excluded (no solution)

3. **Repeated Mistakes** — Count of same error repeated across multiple tasks
   - Detected by embedding similarity of error messages
   - Measured: `mistake_count / total_mistakes`

4. **Token Efficiency** — Tokens consumed per solved task
   - Measured per task: (input_tokens + output_tokens) / (1 if solved else ∞)
   - Aggregated: `total_tokens / solved_tasks`
   - Unsolved tasks charged full penalty (no credit for partial work)

5. **Context Window Usage** — Peak and average token usage per session
   - Measured: `max(tokens_per_turn)`, `avg(tokens_per_turn)`
   - SideQuests variant: also track load tracking deduplication savings

### Optional (Experimental) Metrics

- **Confidence Alignment** — How closely LLM confidence tracks correctness
- **Knowledge Retention** — Tasks solved using information from earlier tasks
- **Hallucination Rate** — Factual errors in LLM responses (manual review)

## Data Collection Protocol

All data MUST be logged for post-hoc analysis:

### Per-Task Logging

```json
{
  "task_id": "task_001",
  "baseline_correct": true,
  "baseline_steps": 3,
  "baseline_tokens": {"input": 245, "output": 89},
  "sidequests_correct": true,
  "sidequests_steps": 2,
  "sidequests_tokens": {"input": 201, "output": 67},
  "error_message": "none",
  "notes": "SideQuests retrieved prior decision, saved 44 tokens"
}
```

### Per-Run Metadata

```json
{
  "run_id": "<UUID>",
  "timestamp": "2026-03-28T10:30:00Z",
  "variant": "baseline" | "sidequests",
  "seed": 42,
  "model": "llama3.1:8b",
  "config": { ... },
  "task_set_hash": "abc123...",
  "total_tasks": 50,
  "succeeded": 45,
  "failed": 5,
  "total_tokens": 12345,
  "wall_time_seconds": 287.5
}
```

### Result Archiving

Both runs are archived with:
1. Full input/output traces (all prompts, all responses)
2. Metadata JSON (timestamps, configs, seeds)
3. Task manifest with checksums
4. Metric summary
5. Resource usage (CPU, memory, wall time)

Path: `benchmarks/results/{run_id}.json`

## Comparison Format

Side-by-side results comparison:

```json
{
  "comparison_id": "<UUID>",
  "timestamp": "2026-03-28T10:45:00Z",
  "baseline_run_id": "...",
  "sidequests_run_id": "...",
  "metrics": {
    "solve_rate": {
      "baseline": 0.90,
      "sidequests": 0.94,
      "delta": "+4.4%",
      "statistical_significance": "p < 0.05"
    },
    "steps_to_solve": {
      "baseline": 3.2,
      "sidequests": 2.1,
      "delta": "-34.4%",
      "statistical_significance": "p < 0.05"
    },
    "token_efficiency": {
      "baseline": 256.7,
      "sidequests": 189.3,
      "delta": "-26.3%",
      "statistical_significance": "p < 0.01"
    },
    "repeated_mistakes": {
      "baseline": 0.08,
      "sidequests": 0.02,
      "delta": "-75.0%"
    }
  },
  "tasks_where_sidequests_helped": [
    {
      "task_id": "task_015",
      "reason": "Retrieved similar decision from earlier task"
    }
  ],
  "caveats": "..."
}
```

## Reproducibility Guarantees

### Same Seed → Same Results

- Two runs with identical seed and configuration MUST produce identical results (within floating-point precision ±1e-6)
- Variance from any source other than randomness indicates a bug in the harness or task set

### Task Set Verification

- Check `task_set_hash` matches between baseline and sidequests runs
- If hashes differ, re-generate and re-run

### Seed Provenance

- Store seed in task manifest and run metadata
- Document how seed is applied (which RNGs, which libraries)
- Note any seed-setting failures

## Failure Modes & Mitigation

| Failure Mode | Symptom | Mitigation |
|--------------|---------|-----------|
| Seed not applied to all RNGs | Results differ on re-run | Audit all RNG calls; add explicit seed in harness |
| Task set differs | task_set_hash mismatch | Freeze task manifest at test design time |
| Non-deterministic LLM sampling | Results differ despite seed | Ensure temperature=0 or very low; check provider behavior |
| System clock affecting results | Timestamps vary | Use wall-clock-independent metrics (step count, token count) |
| Resource contention | CPU/memory cause variance | Run in isolated environment; record resource stats |

## Acceptance Criteria (B48)

- [x] A/B protocol document is complete and clear (this file)
- [x] `ab_harness.py` implements baseline and sidequests variants
- [x] Two identical runs with same seed produce identical results (within floating point)
- [x] Metrics collection is automated (see `ABHarness.compare()`)
- [x] Baseline and SideQuests variants can be run side-by-side
- [x] Results can be compared in standardized format (comparison JSON)

## Notes for Future Milestones

- **B57 (ARC A/B):** Will instantiate this generic contract for the ARC benchmark
- **B58 (Model Strategy):** May adjust seeds, temperature, or sampling based on A/B results
- **Cross-quest Analogical (M8):** Results will show impact of cross-quest reasoning on repeated mistakes

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-28 | Initial specification |
