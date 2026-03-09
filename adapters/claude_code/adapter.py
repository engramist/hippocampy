"""
adapters/claude_code/adapter.py — Claude Code Adapter

Two-part adapter for Claude Code (Phase 0):

Part 1 — Hook config (written by `sidequests setup` to ~/.claude/settings.json):
  UserPromptSubmit hook: shell script that forwards user message to Brain socket.
  Zero LLM involvement. Truly passive for user turns.

  Hook payload sent to Brain socket:
    {"role": "user", "content": "<prompt text>", "session_id": "<session_id>"}

Part 2 — MCP server (this file):
  Registered in .mcp.json at project root by `sidequests setup`.
  Exposes MCP tools to Claude Code:
    M2: notify_turn, current_truth
    M5: branch_quest, complete_quest, diff_since, get_open_loops

  notify_turn called by LLM after every assistant response.
  Forwards to Brain socket and returns {"status": "queued"} immediately.

IPC: JSON-RPC 2.0 over Unix domain socket at ~/.sidequests/brain.sock

Error/degraded mode:
  Scenario A (daemon down): modify injected fragment to [SideQuest OFFLINE],
    return graceful error on current_truth, queue notify_turn to local flat file.
  Scenario B (Ollama down): Brain handles gracefully — confidence_low storage.

M2 scope: implement MCP server + notify_turn + current_truth + hook config writer.
"""

# TODO M2: implement MCP STDIO server
# TODO M2: implement IPC client (connect to Brain socket)
# TODO M2: implement notify_turn handler
# TODO M2: implement current_truth handler
