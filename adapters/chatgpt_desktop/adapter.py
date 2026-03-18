"""
adapters/chatgpt_desktop/adapter.py — ChatGPT Desktop Connector

ChatGPT Desktop connects via the MCP-over-SSE transport built into the
Brain Daemon's web server (B3). This file is NOT a standalone adapter —
the SSE endpoint at http://127.0.0.1:7799/sse handles everything.

Registration instructions (no file config required):
  1. Ensure the Brain Daemon is running: `sidequests start` (or it auto-starts via launchd)
  2. Open ChatGPT Desktop → Settings → Apps → Add Connector
  3. Paste: http://127.0.0.1:7799/sse
  4. All 7 tools are automatically available (notify_turn, current_truth, etc.)

This stub is intentionally minimal — the SSE endpoint in web/server.py
replaces a standalone STDIO adapter for ChatGPT Desktop.

To verify the SSE endpoint is running:
  curl -N http://127.0.0.1:7799/sse
  # Should respond with: event: endpoint\\ndata: /mcp?connection_id=<uuid>\\n\\n

Fallback: if ChatGPT Desktop ever adds STDIO MCP support, copy
adapters/codex/adapter.py and change serverInfo.name to
"sidequests-brain-chatgpt".
"""

# SSE endpoint in web/server.py handles ChatGPT Desktop.
# No standalone STDIO adapter needed (B7 decision: eliminated by B3 SSE).
