"""
mcp_engine/tools.py — MCP Tool Implementations

Implements the Brain Daemon side of all MCP tools.
The IPC server in brain_daemon.py dispatches JSON-RPC calls here.

M2 tools (implement at M2):
  notify_turn(role, content, session_id)
    - Called by LLM after every assistant turn (and user turns on M8 adapters)
    - Queues content for async Loop processing
    - Returns {"status": "queued"} immediately — never blocks the LLM session
    - User turns from Claude Code arrive via UserPromptSubmit hook, not this tool

  current_truth(query, session_id, scope, limit)
    - Embeds query, runs vector search across active artifact nodes
    - Graph traversal 1–2 hops from hits
    - Ranks by pathway_strength × confidence
    - Returns top-N results with provenance

M5 tools (implement at M5):
  branch_quest(name, description)
  complete_quest(quest_id)
  diff_since(since_session_id, scope)
  get_open_loops(scope, limit)
"""

# TODO M2: implement notify_turn, current_truth
# TODO M5: implement branch_quest, complete_quest, diff_since, get_open_loops
