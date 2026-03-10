"""
adapters/claude_code/adapter.py — Claude Code MCP STDIO Adapter

Implements the MCP STDIO server that Claude Code talks to.
Forwards tool calls to the Brain Daemon via Unix socket (JSON-RPC 2.0).

Run by Claude Code as: python adapter.py
Registered in .mcp.json at project root by `sidequests setup`.

M5: Detects git repo root + branch at startup; injects into every tool call
so the Brain can resolve the correct MainQuest automatically.

Error/Degraded Mode:
  Scenario A (daemon down): returns OFFLINE status on current_truth,
    queues notify_turn to ~/.sidequests/offline_queue.jsonl for replay.
  Scenario B (Ollama down): Brain handles internally (confidence_low storage).
"""

from __future__ import annotations
import asyncio
import json
import subprocess
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

SOCKET_PATH   = Path.home() / ".sidequests" / "brain.sock"
OFFLINE_QUEUE = Path.home() / ".sidequests" / "offline_queue.jsonl"

# ---------------------------------------------------------------------------
# Git context detection (runs once at adapter startup)
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str = ".") -> str:
    """Run a git command, return stdout stripped. Returns '' on failure."""
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def detect_git_context() -> tuple[str, str]:
    """
    Detect the git repo root and current branch for the adapter's working directory.
    Returns (repo_root, git_branch). Both may be empty strings if not in a git repo.
    """
    repo_root  = _run_git(["rev-parse", "--show-toplevel"])
    git_branch = _run_git(["branch", "--show-current"])
    return repo_root, git_branch


# Resolved at import time — same for the lifetime of this adapter process
_REPO_ROOT, _GIT_BRANCH = detect_git_context()

# ---------------------------------------------------------------------------
# MCP Tool definitions (what Claude Code sees)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "notify_turn",
        "description": (
            "Forward this turn to the Brain for background processing. "
            "Call after EVERY response — do not skip. Response is instant."
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
            "Retrieve relevant memory before answering about past decisions, "
            "constraints, or architecture. Call before answering complex questions."
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
    {
        "name": "branch_quest",
        "description": (
            "Declare a SideQuest when you are about to explore a tangent that "
            "is distinct from the main project goal. Returns a side_quest_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":            {"type": "string"},
                "purpose":         {"type": "string"},
                "parent_quest_id": {"type": "string"},
            },
            "required": ["name", "purpose"],
        },
    },
    {
        "name": "diff_since",
        "description": (
            "Return decisions, constraints, and requirements created since a "
            "given ISO timestamp. Use to sync after a gap in sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since_iso": {"type": "string"},
                "limit":     {"type": "integer", "default": 20},
            },
            "required": ["since_iso"],
        },
    },
    {
        "name": "get_open_loops",
        "description": (
            "Return concepts awaiting confirmation (soft-lock items). "
            "Use to surface uncertain memory for user review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
            },
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
        "ts":     datetime.now(timezone.utc).isoformat(),
        "method": method,
        "params": params,
    }
    with open(OFFLINE_QUEUE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _inject_git_context(params: dict) -> dict:
    """Add repo_root + git_branch to any tool params dict."""
    return {**params, "repo_root": _REPO_ROOT, "git_branch": _GIT_BRANCH}

# ---------------------------------------------------------------------------
# MCP STDIO server
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_FRAGMENT = (
    "[SideQuest | Brain: ACTIVE]\n"
    "Decisions and constraints are captured automatically in the background.\n"
    "Before answering about past choices or architecture → current_truth\n"
    "Exploring a tangent? → branch_quest(name, purpose)\n"
    "After every response → notify_turn(role='assistant', content=<response>, session_id=<id>)"
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
        return None

    if method == "tools/list":
        return ok({"tools": TOOLS})

    if method == "tools/call":
        tool_name  = params.get("name", "")
        tool_input = _inject_git_context(params.get("arguments", {}))

        # --- notify_turn ---
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

        # --- current_truth ---
        if tool_name == "current_truth":
            if not _daemon_online:
                return ok({"content": [{"type": "text", "text": OFFLINE_FRAGMENT}]})
            try:
                result = await _call_brain("current_truth", tool_input)
                _daemon_online = True
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text", "text": OFFLINE_FRAGMENT}]})
                return err(-32000, str(e))

        # --- branch_quest ---
        if tool_name == "branch_quest":
            try:
                result = await _call_brain("branch_quest", tool_input)
                _daemon_online = True
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text",
                                            "text": '{"error": "daemon_offline"}'}]})
                return err(-32000, str(e))

        # --- diff_since ---
        if tool_name == "diff_since":
            try:
                result = await _call_brain("diff_since", tool_input)
                _daemon_online = True
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text",
                                            "text": '{"error": "daemon_offline"}'}]})
                return err(-32000, str(e))

        # --- get_open_loops ---
        if tool_name == "get_open_loops":
            try:
                result = await _call_brain("get_open_loops", tool_input)
                _daemon_online = True
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text",
                                            "text": '{"error": "daemon_offline"}'}]})
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
