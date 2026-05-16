# B81 Plan — Verify OpenClaw 31 Tool Aliases vs 17 Tool Handlers

Card: B81
Priority: MEDIUM
Finding: R2-OC1
Depends on: None

## Summary

Audit all tool registrations in the OpenClaw extension, verify they map to valid TOOL_HANDLERS, and remove invalid aliases.

## Technical Approach

1. Extract all tool names registered in `index.ts` (grep for `registerTool` or tool registration calls)
2. Compare against `TOOL_HANDLERS.keys()` from `mcp_engine/tools/__init__.py`
3. For aliases (e.g., `memory_recall` → `current_truth`), verify the mapping target exists
4. Remove aliases whose targets don't exist in TOOL_HANDLERS

## Concrete File Changes

### 1. `extensions/hippocampy/src/index.ts`
- Audit each tool registration
- Remove or comment out registrations that don't map to a valid TOOL_HANDLERS key
- Add `// Alias: maps to <handler_name>` comments for alias tools

### 2. `docs/tool-catalog.md`
- Update OpenClaw section if alias mapping is documented

## Test Updates

- Add `tests/test_extension_aliases.py` test that reads `index.ts` and verifies all tool names map to TOOL_HANDLERS keys (if not already covered by existing test)

## Acceptance Criteria

- No orphan aliases in index.ts
- All registered tools resolve to valid handlers
- Extension compiles without errors

## Validation Commands

```bash
cd extensions/hippocampy && npm run build
pytest tests/test_extension_aliases.py -q
```

## Risks

- Removing aliases may break agents that have learned to call them by the old name. Document removed aliases in a migration note.
