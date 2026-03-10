"""
adapters/claude_code/adapter.py — Claude Code MCP STDIO Adapter

Implements the MCP STDIO server that Claude Code talks to.
Forwards tool calls to the Brain Daemon via Unix socket (JSON-RPC 2.0).

Run by Claude Code as: python adapter.py
Registered in .mcp.json at project root by `sidequests setup`.

Error/Degraded Mode:
  Scenario A (daemon down): returns OFFLINE status on current_truth,
    queues notify_turn to ~/.sidequests/offline_queue.jsonl for replay.
  Scenario B (Ollama down): Brain handles internally (confidence_low storage).
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

SOCKET_PATH    = Path.home() / ".sidequests" / "brain.sock"
OFFLINE_QUEUE  = Path.home() / ".sidequests" / "offline_queue.jsonl"

# ---------------------------------------------------------------------------
# MCP Tool definitions (what Claude Code sees)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "notify_turn",
        "description": (
            "Forward this turn to the Brain for background processing. "
            "Call after every response — do not skip. "
            "Response is always instant."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "role":       {"type": "string", "enum": ["user", "assistant"]},
                "content":    {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["role", "content", "session_id"],
        },
    },
    {
        "name": "current_truth",
        "description": (
            "Retrieve relevant memory before answering architecture or "
            "past decision questions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":      {"type": "string"},
                "session_id": {"type": "string"},
                "scope":      {"type": "string", "enum": ["branch", "global", "both"],
                               "default": "branch"},
                "limit":      {"type": "integer", "default": 10},
            },
            "required": ["query", "session_id"],
        },
    },
]

# ---------------------------------------------------------------------------
# Brain socket client
# ---------------------------------------------------------------------------

async def _call_brain(method: str, params: dict) -> dict:
    """Send a JSON-RPC call to the Brain Daemon socket. Returns the result dict."""
    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }
    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        writer.close()
        await writer.wait_closed()
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(response["error"]["message"])
        return response.get("result", {})
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        raise RuntimeError("DAEMON_OFFLINE")


def _queue_offline(method: str, params: dict) -> None:
    """Write failed call to local queue for replay when daemon reconnects."""
    OFFLINE_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "params": params,
    }
    with open(OFFLINE_QUEUE, "a") as f:
        f.write(json.dumps(entry) + "\n")

# ---------------------------------------------------------------------------
# MCP STDIO server
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_FRAGMENT = (
    "[SideQuest | Brain: ACTIVE]\n"
    "The Brain is capturing decisions and constraints automatically.\n"
    "Before answering about past choices or architecture → current_truth\n"
    "Exploring a tangent? → offer branch_quest\n"
    "After every response → notify_turn(role='assistant', content=<your response>, session_id=<id>)"
)

OFFLINE_FRAGMENT = "[SideQuest | Brain: OFFLINE — memory unavailable]"

_daemon_online = True


async def handle_mcp_request(request: dict) -> dict:
    """Route an MCP JSON-RPC request to the correct handler."""
    global _daemon_online
    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}

    # MCP lifecycle
    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sidequests-brain", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        return None  # notification — no response needed

    if method == "tools/list":
        return ok({"tools": TOOLS})

    if method == "tools/call":
        tool_name  = params.get("name", "")
        tool_input = params.get("arguments", {})

        if tool_name == "notify_turn":
            try:
                result = await _call_brain("notify_turn", tool_input)
                _daemon_online = True
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e):
                    _daemon_online = False
                    _queue_offline("notify_turn", tool_input)
                    return ok({"content": [{"type": "text",
                                            "text": '{"status": "queued_offline"}'}]})
                return err(-32000, str(e))

        if tool_name == "current_truth":
            if not _daemon_online:
                return ok({"content": [{"type": "text",
                                         "text": OFFLINE_FRAGMENT}]})
            try:
                result = await _call_brain("current_truth", tool_input)
                _daemon_online = True
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text",
                                            "text": OFFLINE_FRAGMENT}]})
                return err(-32000, str(e))

        return err(-32601, f"Unknown tool: {tool_name}")

    return err(-32601, f"Unknown method: {method}")


async def main():
    """Read MCP JSON-RPC from stdin, write responses to stdout."""
    loop = asyncio.get_running_loop()

    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            request = json.loads(line.decode())
            response = await handle_mcp_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            pass
        except Exception as e:
            error = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": str(e)}}
            sys.stdout.write(json.dumps(error) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
