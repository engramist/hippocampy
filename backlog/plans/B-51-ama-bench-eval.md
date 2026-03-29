# B-51-ama-bench-eval — AMA-Bench + MemoryArena Card (Causality and Interdependent State)

**Card:** B51 | **Priority:** P11 | **Depends on:** B47 (harness)

## Summary
Build evaluation for AMA-Bench and MemoryArena (causal reasoning + state dependency). Tests SideQuests on tasks requiring multi-step causal chains and interdependent constraints.

## Technical Approach

- AMA-Bench: multi-step arithmetic reasoning with shared constraints
- MemoryArena: spatial/abstract state with interdependent updates
- Measure: solve rate, constraint consistency, causal chain depth
- SideQuests advantage: maintains constraint consistency across steps via memory retrieval

## Files to Create/Modify

- `benchmarks/causal/__init__.py`
- `benchmarks/causal/harness.py` — AMA-Bench + MemoryArena harness
- `benchmarks/causal/metrics.py`

## Acceptance Criteria

1. AMA-Bench and MemoryArena tasks load correctly
2. Causal chain depth is tracked
3. Constraint violations are detected
4. SideQuests shows better constraint consistency

## Notes

- Tests core SideQuests value: multi-hop causal reasoning and constraint propagation
