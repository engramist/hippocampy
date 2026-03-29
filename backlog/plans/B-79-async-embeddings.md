# B79 Plan — Wrap emb.embed() in asyncio.to_thread() in Orchestrator

Card: B79
Priority: MEDIUM
Finding: R2-O1
Depends on: None

## Summary

Wrap all synchronous `emb.embed()` calls in the orchestrator with `asyncio.to_thread()` to prevent event loop blocking.

## Technical Approach

Replace every `emb.embed(text)` call in `orchestrator.py` with:
```python
vec = await asyncio.to_thread(emb.embed, text)
```

## Concrete File Changes

### 1. `mcp_engine/loop/orchestrator.py`
- Find all `emb.embed()` calls
- Wrap each in `asyncio.to_thread()`
- Ensure import: `import asyncio` (likely already present)

## Test Updates

No new tests needed — existing orchestrator tests validate correctness. The change is mechanical (async wrapping).

## Acceptance Criteria

- No direct `emb.embed()` calls in async code paths
- `pytest tests/ -k orchestrator -q` passes

## Validation Commands

```bash
rg "emb.embed" mcp_engine/loop/orchestrator.py  # should show to_thread wrapping
pytest tests/ -k orchestrator -q
```

## Risks

- Minor overhead from thread dispatch (~0.1ms per call). Net positive: unblocks event loop for 5-20ms per embed call.
