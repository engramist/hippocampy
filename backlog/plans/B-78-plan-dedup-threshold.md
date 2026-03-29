# B78 Plan — Monitor Retrospective Plan Dedup Threshold

Card: B78
Priority: MEDIUM
Finding: R2-P2
Depends on: B68

## Summary

Add logging and configurability to the plan dedup threshold in sweep's retrospective plan inference.

## Technical Approach

1. Extract the hardcoded `0.90` similarity threshold to a config-read value
2. Add structured logging at the dedup decision point

## Concrete File Changes

### 1. `mcp_engine/sweep.py`
- Read threshold from config: `config.get("plan_dedup_threshold", 0.90)`
- Add `logger.info(f"Plan dedup: similarity={score:.3f}, threshold={thresh}, action={'reject' if score > thresh else 'accept'}")`

### 2. `sidequests.toml` (optional)
- Document the `plan_dedup_threshold` key in comments

## Test Updates

- Add `test_plan_dedup_threshold_configurable()` — mock config with threshold 0.95, verify stricter dedup

## Acceptance Criteria

- Threshold is config-driven
- Dedup decisions are logged
- `pytest tests/ -k sweep -q` passes

## Validation Commands

```bash
pytest tests/ -k sweep -q
```

## Risks

None — observability-only change plus config extraction.
