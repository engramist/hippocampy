"""
adapters/gemini_cli/adapter.py — Gemini CLI MCP STDIO Adapter

No hook system confirmed for Gemini CLI. Both user and assistant turns use notify_turn.
Otherwise identical to the Codex/Claude Desktop adapters.

Registration (added automatically by `sidequests setup`):
  Gemini CLI reads MCP servers from settings.json. Two common locations:
    ~/.gemini/settings.json
    ~/.config/gemini/settings.json

  Entry format:
    {
      "mcpServers": {
        "sidequests-brain": {
          "command": "python",
          "args": ["/abs/path/to/adapters/gemini_cli/adapter.py"]
        }
      }
    }

  Verify location with: gemini --help or check Gemini CLI docs.

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
# MCP Tool definitions (what Gemini CLI sees)
# ---------------------------------------------------------------------------

from mcp_engine.tool_schemas import TOOLS

# ---------------------------------------------------------------------------
# Brain socket client
# ---------------------------------------------------------------------------

_SOCKET_TIMEOUT = 10.0

# Token limits per known model family (conservative estimates)
# Adapters can override via LLMProvider node in the graph
_TOKEN_LIMIT = 1000000  # default (Gemini CLI models often have 1M+ context)


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
        line = await asyncio.wait_for(reader.readline(), timeout=_SOCKET_TIMEOUT)
        writer.close()
        await writer.wait_closed()
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(response["error"]["message"])
        return response.get("result", {})
    except (FileNotFoundError, ConnectionRefusedError, OSError, asyncio.TimeoutError):
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


def _inject_context(params: dict) -> dict:
    """Add available context signals to any tool params dict."""
    ctx = {**params}
    if _REPO_ROOT:
        ctx["repo_root"] = _REPO_ROOT
    if _GIT_BRANCH:
        ctx["git_branch"] = _GIT_BRANCH
    # workspace_path = CWD even without git (for hippocampus routing)
    import os
    ctx.setdefault("workspace_path", os.getcwd())
    # B18: Send token_limit so Brain can track context window size
    ctx.setdefault("token_limit", _TOKEN_LIMIT)
    return ctx

# ---------------------------------------------------------------------------
# MCP STDIO server
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_FRAGMENT = (
    "[SideQuest | Brain: ACTIVE]\n"
    "Project memory is active. Decisions and constraints are captured automatically.\n"
    "Before answering about past choices → current_truth\n"
    "Starting something that may resemble past work → analogical_search\n"
    "Exploring a tangent? → offer branch_quest\n"
    "LAST action of every turn → notify_turn(role='assistant', content=<response>, session_id=<id>)\n"
    "IMPORTANT: notify_turn is fire-and-forget. Call it exactly ONCE per turn. "
    "After it returns, STOP — no more text, reasoning, or tool calls.\n"
    "When current_truth returns a panel_url field, include it as a markdown link: [View in Mission Control](url)"
)

OFFLINE_FRAGMENT = "[SideQuest | Brain: OFFLINE — memory unavailable]"

_daemon_online = True


async def _replay_offline_queue() -> None:
    """Replay messages queued while the daemon was offline."""
    if not OFFLINE_QUEUE.exists():
        return
    try:
        lines = OFFLINE_QUEUE.read_text(encoding="utf-8").splitlines()
        if not lines:
            return
        OFFLINE_QUEUE.unlink()
        for line in lines:
            try:
                entry = json.loads(line)
                await _call_brain(entry["method"], entry["params"])
            except Exception:
                pass
    except Exception:
        pass


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
        # Negotiate protocol version — respond with whichever version the
        # client requested (Gemini CLI 0.34+ sends "2025-06-18").
        client_version = params.get("protocolVersion", "2024-11-05")
        return ok({
            "protocolVersion": client_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sidequests-brain-gemini", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok({"tools": TOOLS})

    # Gemini CLI probes resources/list during discovery — return empty list
    if method == "resources/list":
        return ok({"resources": []})

    if method == "prompts/list":
        return ok({"prompts": [{"name": "sidequests-system", "description": "SideQuests Brain instructions"}]})

    if method == "prompts/get":
        return ok({"description": "SideQuests Brain instructions",
                   "messages": [{"role": "user", "content": {"type": "text", "text": SYSTEM_PROMPT_FRAGMENT}}]})

    if method == "tools/call":
        tool_name  = params.get("name", "")
        tool_input = _inject_context(params.get("arguments", {}))

        # --- notify_turn ---
        if tool_name == "notify_turn":
            try:
                result = await _call_brain("notify_turn", tool_input)
                was_offline = not _daemon_online
                _daemon_online = True
                if was_offline:
                    await _replay_offline_queue()
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
            try:
                result = await _call_brain("current_truth", tool_input)
                was_offline = not _daemon_online
                _daemon_online = True
                if was_offline:
                    await _replay_offline_queue()
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text", "text": OFFLINE_FRAGMENT}]})
                return err(-32000, str(e))

        # --- all other tools ---
        if tool_name in ("branch_quest", "diff_since", "get_open_loops",
                         "analogical_search", "ingest_document", "explore_graph",
                         "complete_quest", "set_quest", "context_status"):
            try:
                result = await _call_brain(tool_name, tool_input)
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
