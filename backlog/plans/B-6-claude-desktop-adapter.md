# B-6-claude-desktop-adapter — Claude Desktop Adapter (Full)

**Card:** B6 | **Priority:** P3 | **Depends on:** B1 (setup CLI)

## Summary
Create a dedicated Claude Desktop adapter, effectively a renamed copy of the Claude Code adapter with appropriate server naming. Claude Desktop users need a first-class adapter entry point.

## Technical Approach

### File Structure
- Copy `adapters/claude_code/adapter.py` to `adapters/claude_desktop/adapter.py`
- Modify serverInfo.name from "sidequests-brain" to "sidequests-brain-desktop"
- Keep all tool signatures and behavior identical
- Both adapters use the same Brain Daemon (Unix socket connection)

### CLI Registration
- Update `sidequests setup --target claude-desktop` in CLI
- Register entry in `~/Library/Application Support/Claude/claude_desktop_config.json`
- Server entry: `{"command": "python", "args": ["-m", "sidequests.adapters.claude_desktop"]}`

## Files to Create/Modify

- `adapters/claude_desktop/__init__.py`
- `adapters/claude_desktop/adapter.py` — copied from claude_code, serverInfo.name updated
- Update `sidequests/cli/register.py` — add claude_desktop registration handler
- Add tests: `tests/test_adapter_claude_desktop.py` (same tests as claude_code)

## Acceptance Criteria

1. `adapters/claude_desktop/adapter.py` exists and can be imported without error
2. `python -m sidequests.adapters.claude_desktop --stdio` initializes successfully
3. `tools/list` call returns identical tool surface to claude_code adapter
4. `notify_turn`, `current_truth`, `explore_graph` work identically
5. Claude Desktop can initialize the adapter from config
6. `sidequests setup --target claude-desktop` registers adapter in correct config file
7. No behavioral difference from Claude Code adapter in tool execution

## Notes

- This is a 90% code-reuse card — minimal new logic
- Keep adapters loosely coupled; any shared logic should go to `adapters/__init__.py`
