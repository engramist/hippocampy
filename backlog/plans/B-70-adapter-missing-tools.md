# B70 Plan — Add 4 Missing Tools to ALL Adapter Pass-Through Lists

Card: B70
Priority: CRITICAL
Finding: R2-A1
Depends on: None

## Summary

Add `upsert_lesson`, `recall_relevant_lessons`, `get_anomalies`, and `get_openclaw_prompt` to the tool-routing allow-list tuple in all 5 adapters.

## Technical Approach

Each adapter has a block like:
```python
if tool_name in ("notify_turn", "current_truth", "set_quest", ...):
```

Add the 4 missing tool names to each tuple.

## Concrete File Changes

### 1. `adapters/claude_code/adapter.py`
- Locate the `if tool_name in (...)` tuple
- Add: `"upsert_lesson"`, `"recall_relevant_lessons"`, `"get_anomalies"`, `"get_openclaw_prompt"`

### 2. `adapters/claude_desktop/adapter.py`
- Same change as above

### 3. `adapters/codex/adapter.py`
- Same change as above

### 4. `adapters/chatgpt_desktop/adapter.py`
- Same change as above

### 5. `adapters/gemini_cli/adapter.py`
- Same change as above

### 6. `docs/tool-catalog.md`
- Update the Adapter Compatibility Matrix: change ❌ to ✅ for all 4 tools across all adapters

## Test Updates

No new tests needed — existing `tests/test_adapters.py` should cover tool routing.

## Acceptance Criteria

- `rg -n "upsert_lesson" adapters/` → 5 matches (one per adapter)
- `rg -n "recall_relevant_lessons" adapters/` → 5 matches
- `rg -n "get_anomalies" adapters/` → 5 matches
- `rg -n "get_openclaw_prompt" adapters/` → 5 matches
- `pytest tests/test_adapters.py -q` passes

## Validation Commands

```bash
rg -n "upsert_lesson|recall_relevant_lessons|get_anomalies|get_openclaw_prompt" adapters/
pytest tests/test_adapters.py -q
```

## Risks

None — purely additive string changes.
