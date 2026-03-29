# ARC-AGI-3 SideQuests Submission Artifact

This directory contains the final submission runner and compliance validation tools for the SideQuests memory-augmented agent in the ARC-AGI-3 contest.

## Contents

- `submission.py`: Main entry point for contest evaluators. Runs the memory-augmented agent on all puzzles.
- `pre_submit_check.py`: Automated compliance tool to verify offline status, model budgets, and output formats.
- `model_budget.yaml`: Resource constraints and model configuration.
- `offline_manifest.json`: Manifest for the offline submission bundle.
- `tasks_manifest.json`: Puzzle set to be solved.

## Quick Start (For Evaluators)

To run the full evaluation:

```bash
# 1. Initialize environment (if needed)
# pip install -r requirements.txt

# 2. Run the evaluation
python benchmarks/arc3/submission.py
```

Results will be exported to `submission_results.json` in the current directory.

## Compliance Verification

Before submitting, run the pre-submission check:

```bash
python benchmarks/arc3/pre_submit_check.py
```

## Architecture

SideQuests uses a "Gated Consolidation Loop" to maintain persistent memory across puzzles.
1. **Observation**: Each ARC step is normalized into a semantic narrative.
2. **Ingestion**: The narrative is stored in an embedded graph database (Kùzu).
3. **Consolidation**: A background process extracts "Concepts" and "Decisions" from the narrative.
4. **Retrieval**: Before choosing an action, the agent queries the brain for similar historical patterns.
5. **Action**: The agent makes an informed choice based on its current observation and recalled memory.
