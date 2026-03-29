# B-50-longcontext-eval — LoCoBench Evaluation Card (Long-Context Degradation)

**Card:** B50 | **Priority:** P11 | **Depends on:** B47 (harness)

## Summary
Build LoCoBench evaluation harness. Tests whether SideQuests memory mitigates long-context degradation (loss of information in deep context windows).

## Technical Approach

- Use LoCoBench dataset (needles-in-haystack, multi-span retrieval tasks)
- Run baseline with increasing context sizes (8K, 32K, 128K tokens)
- Run SideQuests with memory retrieval (smaller effective context)
- Measure: accuracy vs. context size, token efficiency

## Files to Create/Modify

- `benchmarks/longcontext/__init__.py`
- `benchmarks/longcontext/harness.py`
- `benchmarks/longcontext/metrics.py`

## Acceptance Criteria

1. LoCoBench harness loads and runs tasks at multiple context sizes
2. Baseline accuracy degradation is visible
3. SideQuests memory retrieval provides alternative (smaller, targeted) context
4. Results show memory helps or stays neutral (doesn't hurt baseline)

## Notes

- Specifically targets long-context LLM weakness
- Clear story: "SideQuests' memory is a retrieval solution to long-context problem"
