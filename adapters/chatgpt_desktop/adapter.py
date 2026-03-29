"""
adapters/chatgpt_desktop/adapter.py — ChatGPT Desktop MCP STDIO Adapter

Implements the MCP STDIO server for ChatGPT Desktop.
Forwards tool calls to the Brain Daemon via HTTP/SSE endpoint (B7).

Registration:
  sidequests setup --target chatgpt-desktop
  (registers as a STDIO server in ~/.chatgpt/config.json if supported,
   or provides the SSE URL for the ChatGPT 'Connector' model)

Acceptance Criteria (B7):
  1. python -m sidequests.adapters.chatgpt_desktop --stdio connects to SSE
  2. All 5+ MCP tools surfaced
  3. notify_turn, current_truth work end-to-end
"""

from __future__ import annotations
import asyncio
import json
import subprocess
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone
import httpx
from mcp_engine.tool_schemas import TOOLS

_ALL_TOOL_NAMES = frozenset(t["name"] for t in TOOLS)


# B3/B7 endpoint for Brain Daemon
BRAIN_URL     = "http://127.0.0.1:7799/mcp"
OFFLINE_QUEUE = Path.home() / ".sidequests" / "offline_queue.jsonl"

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


# Resolved at import time
_REPO_ROOT, _GIT_BRANCH = detect_git_context()

# ---------------------------------------------------------------------------
# MCP Tool definitions (what ChatGPT Desktop sees)
# ---------------------------------------------------------------------------

from mcp_engine.tool_schemas import TOOLS

# ---------------------------------------------------------------------------
# Brain HTTP client
# ---------------------------------------------------------------------------

_HTTP_TIMEOUT = 10.0
_TOKEN_LIMIT  = 128000  # GPT-4o class

async def _call_brain(method: str, params: dict) -> dict:
    """Send a JSON-RPC call to the Brain Daemon via HTTP. Returns the result dict."""
    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(BRAIN_URL, json=request)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP_{response.status_code}")
            
            resp_json = response.json()
            if "error" in resp_json:
                raise RuntimeError(resp_json["error"]["message"])
            return resp_json.get("result", {})
    except (httpx.RequestError, httpx.HTTPStatusError):
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


async def _replay_offline_queue() -> None:
    """Replay queued offline messages to the Brain Daemon."""
    if not OFFLINE_QUEUE.exists():
        return
    try:
        raw = OFFLINE_QUEUE.read_text()
        OFFLINE_QUEUE.unlink()
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            await _call_brain(entry["method"], entry["params"])
        except Exception:
            pass


def _inject_context(params: dict) -> dict:
    """Add available context signals to any tool params dict."""
    ctx = {**params}
    if _REPO_ROOT:
        ctx["repo_root"] = _REPO_ROOT
    if _GIT_BRANCH:
        ctx["git_branch"] = _GIT_BRANCH
    import os
    ctx.setdefault("workspace_path", os.getcwd())
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
    "When you form a multi-step strategy → register_plan(goal, steps, session_id)\n"
    "Before planning similar work → recall_plans(goal_query, session_id)\n"
    "After major steps or completion → report_outcome(plan_id, outcome, valence, session_id)\n"
    "Exploring a tangent? → branch_quest(name, purpose)\n"
    "After every response → notify_turn(role='assistant', content=<response>, session_id=<id>)\n"
    "When current_truth returns a panel_url field, include it as a markdown link: [View in Mission Control](url)"
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
        # Negotiate protocol version
        client_version = params.get("protocolVersion", "2024-11-05")
        return ok({
            "protocolVersion": client_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sidequests-brain-chatgpt", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok({"tools": TOOLS})

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
                if "DAEMON_OFFLINE" in str(e) or "HTTP_" in str(e):
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
                if "DAEMON_OFFLINE" in str(e) or "HTTP_" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text", "text": OFFLINE_FRAGMENT}]})
                return err(-32000, str(e))

        # --- all other tools ---
        if tool_name in _ALL_TOOL_NAMES:
            try:
                result = await _call_brain(tool_name, tool_input)
                _daemon_online = True
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e) or "HTTP_" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text",
                                            "text": '{"error": "daemon_offline"}'}]})
                return err(-32000, str(e))

        return err(-32601, f"Unknown tool: {tool_name}")

    return err(-32601, f"Unknown method: {method}")


async def main():
    """Read MCP JSON-RPC from stdin, write responses to stdout."""
    # Check if --stdio flag is present (required by some tools)
    # or just run it anyway as it's the only mode we support.
    
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
