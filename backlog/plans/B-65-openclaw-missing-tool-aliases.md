# B-65-openclaw-missing-tool-aliases — Register Missing Tools in OpenClaw Extension

**Card:** B65 | **Priority:** P8 | **Depends on:** B61 (tools surfacing)

## Summary
Complete tool alias registration in OpenClaw extension for any missing or newly added tools. Ensures all tools are reachable under their canonical names and common aliases.

## Technical Approach

- Audit all MCP tools in `mcp_engine/tools.py`
- Ensure each is registered with primary name + aliases in OpenClaw manifest
- Common aliases: `memory_search` (for `current_truth`), `memory_get` (alternate), etc.
- Update `extensions/sidequests-brain/src/index.ts` tool registry

### Tool Aliases

| Primary Name | Aliases |
|---|---|
| `current_truth` | `memory_search`, `memory_recall` |
| `notify_turn` | `memory_ingest`, `record_turn` |
| `explore_graph` | `traverse_graph`, `explore_memory` |
| `complete_quest` | `finish_quest` |
| `branch_quest` | `create_subquest` |

## Files to Create/Modify

- `extensions/sidequests-brain/src/index.ts` — add tool alias mappings
- `tests/test_openclaw_tool_aliases.py` — verify all aliases resolve correctly

## Acceptance Criteria

1. All MCP tools are registered with primary name
2. Common aliases are registered and resolve to correct tool
3. Agent can call tools by either primary name or alias
4. No alias collisions or conflicts
5. Integration test: call `memory_search` → resolves to `current_truth`

## Notes

- B24 and B65 are related (both about tool aliases) — verify no duplication
