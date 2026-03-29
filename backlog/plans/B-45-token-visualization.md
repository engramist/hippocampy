# B-45-token-visualization — Token Efficiency Measurement & Visualization

**Card:** B45 | **Priority:** P10 | **Depends on:** B44 (framing)

## Summary
Build dashboard for token consumption tracking across sessions. Visualize how load tracking and working memory reduce context bloat.

## Technical Approach

### Metrics Collection
- Track per-session: `token_estimate`, `loaded_node_count`, `injection_count`, `dedup_savings`
- Store in Session node: `token_estimate` (FLOAT), `dedup_tokens_saved` (INT)
- Background sweep computes dedup savings based on load history

### Dashboard Widget
- Add to Memory Control Panel: "Token Efficiency" card
- Show: tokens budgeted vs. consumed vs. saved
- Chart: token trend over session lifecycle
- Comparison: baseline (no dedup) vs. optimized (with load tracking)

### Detailed View
- Per-injection breakdown: node ID, tokens contributed, loaded status, dedup applied
- Hover tooltip: why node was demoted/included

## Files to Create/Modify

- `mcp_engine/working_memory.py` — add dedup_tokens_saved field computation
- `web/routes/metrics.py` — new endpoint for token metrics
- `web/static/token-dashboard.js` — visualization widget
- `tests/test_token_metrics.py` — verify calculations

## Acceptance Criteria

1. Token estimates are calculated and stored per session
2. Dedup savings are tracked (baseline token cost - actual cost)
3. Dashboard widget displays token metrics clearly
4. Chart shows improvement from load tracking over session lifetime
5. Detailed view breaks down token cost per node
6. Integration test: run session → token metrics update → dashboard reflects changes

## Notes

- Metrics should be non-intrusive; calculate as background task, not on-path
