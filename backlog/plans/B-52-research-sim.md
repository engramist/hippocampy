# B-52-research-sim — Autonomous Research Simulation Harness (Hypothesis Regression Rate)

**Card:** B52 | **Priority:** P11 | **Depends on:** B47 (harness)

## Summary
Build research environment where agent forms hypotheses and tests them autonomously. Measure hypothesis regression (repeating failed approaches)—SideQuests should reduce this via memory.

## Technical Approach

- Simulate research workflow: hypothesis → experiment → result evaluation
- Baseline: no memory, agent repeats hypotheses on subsequent tasks
- SideQuests: memory of tested hypotheses reduces redundant testing
- Metric: hypothesis regression rate (% of repeated failed approaches)

## Files to Create/Modify

- `benchmarks/research_sim/__init__.py`
- `benchmarks/research_sim/hypothesis_tracker.py` — hypothesis recording
- `benchmarks/research_sim/metrics.py` — regression analysis

## Acceptance Criteria

1. Research simulation generates reproducible hypothesis sequences
2. Hypothesis regression is quantified
3. Baseline shows high regression; SideQuests reduces it
4. Statistical significance of memory benefit is computed

## Notes

- Creative benchmark; tests SideQuests on self-directedness
- Directly validates "reduces repeated mistakes" design goal
