# B71 Plan — Centralize Adapter Tool Routing from tool_schemas.TOOLS

Card: B71
Priority: HIGH
Finding: R2-A2
Depends on: B70

## Summary

Replace hardcoded per-adapter tool name tuples with a shared, import-derived frozenset so new tools auto-propagate.

## Technical Approach

In each adapter, replace:
```python
if tool_name in ("notify_turn", "current_truth", "set_quest", ...):
```

With:
```python
from mcp_engine.tool_schemas import TOOLS
_ALL_TOOL_NAMES = frozenset(t["name"] for t in TOOLS)

# ...later in handler:
if tool_name in _ALL_TOOL_NAMES:
```

## Concrete File Changes

### 1–5. All 5 adapters (`adapters/*/adapter.py`)
- Add `from mcp_engine.tool_schemas import TOOLS` import
- Add module-level `_ALL_TOOL_NAMES = frozenset(t["name"] for t in TOOLS)`
- Replace `if tool_name in (...)` with `if tool_name in _ALL_TOOL_NAMES`
- Remove the hardcoded tuple

## Test Updates

- Add a test in `tests/test_adapters.py` that verifies `_ALL_TOOL_NAMES` matches `TOOL_HANDLERS.keys()`:
  ```python
  def test_adapter_tool_names_match_handlers():
      from mcp_engine.tool_schemas import TOOLS
      from mcp_engine.tools import TOOL_HANDLERS
      schema_names = {t["name"] for t in TOOLS}
      assert schema_names == set(TOOL_HANDLERS.keys())
  ```

## Acceptance Criteria

- No adapter file contains a hardcoded tool-name tuple > 3 items
- `rg "from mcp_engine.tool_schemas import TOOLS" adapters/` → 5 matches
- `pytest tests/test_adapters.py -q` passes

## Validation Commands

```bash
rg "from mcp_engine.tool_schemas import TOOLS" adapters/
rg -c "tool_name in (" adapters/  # should be 0 or minimal
pytest tests/test_adapters.py -q
```

## Risks

- If `tool_schemas.py` import fails (e.g., circular dependency), all adapters break at import time. Mitigate: the import is pure data (list of dicts) with no side effects.
