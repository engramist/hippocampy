# B-48-ab-contract — SideQuests A/B Evaluation Contract (Protocol-Correct)

**Card:** B48 | **Priority:** P11 | **Depends on:** B47 (harness)

## Summary
Define A/B evaluation protocol and contract for SideQuests vs. baseline. Ensures fair comparison and reproducibility.

## Technical Approach

### A/B Setup
- **Baseline:** standard retrieval, no passive ingestion, no working memory dedup
- **SideQuests:** full pipeline with memory retrieval + working memory optimization
- Fixed random seeds for both runs
- Identical task set and metrics

### Protocol
- Both agents see identical sequence of tasks
- Controlled variables: model, task order, temperature
- Measurement points: solve rate, steps to solve, repeated mistakes, token efficiency
- Data collection: all outputs logged for post-hoc analysis

### Reproducibility
- Seed freezing for all RNG calls
- Task manifest with checksums
- Result archiving with full input/output traces

## Files to Create/Modify

- `benchmarks/ab_contract.md` — specification document (not code)
- `benchmarks/ab_harness.py` — A/B test harness (code implementation)
- `tests/test_ab_reproducibility.py` — verify deterministic runs

## Acceptance Criteria

1. A/B protocol document is clear and complete
2. Two identical runs with same seed produce identical results (within floating point)
3. Metrics collection is automated
4. Baseline and SideQuests variants can be run side-by-side
5. Results can be compared in standardized format

## Notes

- Primarily a documentation/protocol card
- Code is mostly harness glue
- B57 (ARC A/B) will instantiate this generic contract
