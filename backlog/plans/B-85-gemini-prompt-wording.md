# B85 Plan — Fix Gemini CLI "LAST action" Prompt Wording

Card: B85
Priority: LOW
Finding: R2-AD1
Depends on: None

## Summary

Fix misleading prompt wording in Gemini CLI adapter.

## Concrete File Changes

### 1. `adapters/gemini_cli/adapter.py`
- Find: "LAST action of every turn → notify_turn" (or similar)
- Replace with: "Call notify_turn at the end of every turn"

## Test Updates

None needed — prompt string change.

## Acceptance Criteria

- No "LAST action" in adapter prompt text
- `pytest tests/test_adapters.py -q` passes

## Validation Commands

```bash
rg "LAST action" adapters/
pytest tests/test_adapters.py -q
```

## Risks

None.
