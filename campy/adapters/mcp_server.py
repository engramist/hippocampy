"""
sidequests/adapters/mcp_server.py — Generic MCP STDIO Adapter for Campy.

This module acts as a bridge between standard MCP clients (which use stdio)
and the HippoCampy Daemon (which uses a Unix domain socket).

It is used by Smithery and other MCP-compatible tools to interact with
the Brain memory system.
"""

from __future__ import annotations
import asyncio
import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from campy.brain_transport import call_brain, socket_path
from campy.paths import get_daemon_socket_path, runtime_dir

SOCKET_PATH   = get_daemon_socket_path()
OFFLINE_QUEUE = runtime_dir() / "offline_queue.jsonl"

# ---------------------------------------------------------------------------
# Git context detection
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
# MCP Tool definitions
# ---------------------------------------------------------------------------

from campy.brain.thalamus.tool_schemas import TOOLS

# ---------------------------------------------------------------------------
# Brain socket client
# ---------------------------------------------------------------------------

_SOCKET_TIMEOUT = 10.0
_TOKEN_LIMIT    = 200000  # Default conservative limit


def _socket_path() -> Path:
    """Return the daemon socket path, allowing sandbox-safe overrides."""
    return socket_path()


async def _call_brain(method: str, params: dict) -> dict:
    """Send a JSON-RPC call to the Brain Daemon socket. Returns the result dict."""
    return await call_brain(method, params, timeout=_SOCKET_TIMEOUT)


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
    ctx.setdefault("workspace_path", os.getcwd())
    ctx.setdefault("token_limit", _TOKEN_LIMIT)
    return ctx

# ---------------------------------------------------------------------------
# MCP STDIO server
# ---------------------------------------------------------------------------

OFFLINE_FRAGMENT = "[Campy | Brain: OFFLINE - memory unavailable]"

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
                pass  # best-effort replay
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
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "campy-mcp", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok({"tools": TOOLS})

    if method == "tools/call":
        tool_name  = params.get("name", "")
        tool_input = _inject_context(params.get("arguments", {}))

        # --- Known tools ---
        try:
            result = await _call_brain(tool_name, tool_input)
            was_offline = not _daemon_online
            _daemon_online = True
            if was_offline:
                await _replay_offline_queue()
            
            # Special handling for notify_turn (return JSON string)
            if tool_name == "notify_turn":
                 return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            
            # Special handling for current_truth (standard content response)
            return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
        except RuntimeError as e:
            if "DAEMON_OFFLINE" in str(e):
                _daemon_online = False
                if tool_name == "notify_turn":
                    _queue_offline("notify_turn", tool_input)
                    return ok({"content": [{"type": "text",
                                            "text": '{"status": "queued_offline"}'}]})
                return ok({"content": [{"type": "text", "text": OFFLINE_FRAGMENT}]})
            return err(-32000, str(e))

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
