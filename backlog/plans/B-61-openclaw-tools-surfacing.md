# B-61-openclaw-tools-surfacing — OpenClaw Extension: Tools Not Surfaced Without Manual Config

**Card:** B61 | **Priority:** P7 | **Depends on:** B41 (daemon auto-start)

## Summary
Ensure all MCP tools are automatically surfaced to OpenClaw agent sessions without requiring manual configuration. Tools should be discoverable immediately after plugin install.

## Technical Approach

- Verify `extensions/sidequests-brain/src/index.ts` exposes all 5+ tools in manifest
- Check that OpenClaw gateway properly registers tools with LLM
- Automate tool registration in plugin init/activation

### Tool Registration
- Ensure `api.registerTool()` is called for each tool in extension init
- Tool list: `notify_turn`, `current_truth`, `explore_graph`, `branch_quest`, `complete_quest`, etc.
- Verify each tool has proper schema and description

## Files to Create/Modify

- `extensions/sidequests-brain/src/index.ts` — verify all tool registrations
- `tests/test_openclaw_tool_surfacing.py` — automated tool discovery test

## Acceptance Criteria

1. After plugin install, all 5+ tools are visible in OpenClaw agent tool list
2. No manual activation/config required
3. Agent can call each tool without errors
4. Integration test: agent session → verify tool is available → call tool → success

## Notes

- Related to B28 (tool binding fix) — verify that fix is still in place
- Blockers resolved by B41 daemon auto-start
