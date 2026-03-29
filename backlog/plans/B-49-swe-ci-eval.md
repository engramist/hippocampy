# B-49-swe-ci-eval — SWE-CI Evaluation Card (Maintainability Under Evolution)

**Card:** B49 | **Priority:** P11 | **Depends on:** B47 (harness)

## Summary
Build evaluation harness for SWE-CI benchmark (code generation with evolving constraints). Tests whether SideQuests memory enables better handling of accumulated constraints.

## Technical Approach

- Use public SWE-CI dataset (or subset for quick iteration)
- Run baseline and SideQuests variants
- Measure: constraint violation rate, rework cycles, code quality metrics
- Post-analyze: does memory of prior constraints reduce violations in new tasks?

## Files to Create/Modify

- `benchmarks/swe_ci/__init__.py`
- `benchmarks/swe_ci/harness.py` — SWE-CI specific setup
- `benchmarks/swe_ci/metrics.py` — evaluation metrics
- `tests/test_swe_ci_integration.py` — end-to-end validation

## Acceptance Criteria

1. SWE-CI harness downloads/caches dataset
2. Baseline and SideQuests runs are executed
3. Constraint violation rates are compared
4. Results show memory benefit (if any)

## Notes

- Instantiation of generic A/B contract (B48)
- May require custom LLM for code tasks
