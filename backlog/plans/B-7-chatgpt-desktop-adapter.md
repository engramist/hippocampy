# B-7-chatgpt-desktop-adapter — ChatGPT Desktop Adapter (Stub → Full)

**Card:** B7 | **Priority:** P3 | **Depends on:** B3 (SSE endpoint)

## Summary
Complete the ChatGPT Desktop adapter from stub to full implementation. ChatGPT Desktop users need the same tool access as Claude users.

## Technical Approach

### Adapter Pattern
- Follow same pattern as Claude Desktop/Code adapters
- Use SSE endpoint (B3) for ChatGPT connection
- Tools: `notify_turn`, `current_truth`, `explore_graph` (same as others)

### Server Entry Point
- `adapters/chatgpt_desktop/adapter.py` — similar to claude_desktop
- Register via `sidequests setup --target chatgpt-desktop`

### SSE Client Delegation
- ChatGPT Desktop adapter forwards MCP calls to `http://127.0.0.1:8000/sse/mcp`
- Existing SSE endpoint from B3 handles all routing
- Minimal adapter code — mostly HTTP client logic

## Files to Create/Modify

- `adapters/chatgpt_desktop/__init__.py`
- `adapters/chatgpt_desktop/adapter.py` — SSE-based MCP client
- Update `sidequests/cli/register.py` — add chatgpt_desktop registration
- `tests/test_adapter_chatgpt_desktop.py`

## Acceptance Criteria

1. `python -m sidequests.adapters.chatgpt_desktop --stdio` initializes and connects to SSE endpoint
2. All 5+ MCP tools are surfaced to ChatGPT Desktop sessions
3. `notify_turn`, `current_truth` work end-to-end
4. `sidequests setup --target chatgpt-desktop` registers adapter
5. ChatGPT Desktop can load and use adapter without manual configuration
6. Integration test: ChatGPT notifies turn → brain receives it → current_truth retrieves memory

## Notes

- ChatGPT Desktop may require special config path — verify actual location
- Test with actual ChatGPT Desktop client if available
