"""
adapters/claude_desktop/adapter.py — Claude Desktop MCP STDIO Adapter

Implements the MCP STDIO server that Claude Desktop talks to.
Forwards tool calls to the Brain Daemon via Unix socket (JSON-RPC 2.0).

Run by Claude Desktop as: python -m campy.adapters.claude_desktop
Registered in ~/Library/Application Support/Claude/claude_desktop_config.json by `campy setup`.
"""

from __future__ import annotations
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from campy.brain_transport import call_brain
from campy.paths import get_daemon_socket_path, runtime_dir
from mcp_engine.tool_schemas import TOOLS

_ALL_TOOL_NAMES = frozenset(t["name"] for t in TOOLS)

SOCKET_PATH   = get_daemon_socket_path()
OFFLINE_QUEUE = runtime_dir() / "offline_queue.jsonl"

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
# MCP Tool definitions (what Claude Desktop sees)
# ---------------------------------------------------------------------------

from mcp_engine.tool_schemas import TOOLS

# ---------------------------------------------------------------------------
# Brain socket client
# ---------------------------------------------------------------------------

_SOCKET_TIMEOUT = 10.0  # W4: read/write timeout in seconds

# Token limits per known model family (conservative estimates)
# Adapters can override via LLMProvider node in the graph
_TOKEN_LIMIT = 200000  # default (Claude Desktop Sonnet 3.5)


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
    # workspace_path = git root if available, else CWD (B86)
    import os
    ctx.setdefault("workspace_path", _REPO_ROOT or os.getcwd())
    # B18: Send token_limit so Brain can track context window size
    ctx.setdefault("token_limit", _TOKEN_LIMIT)
    return ctx

# ---------------------------------------------------------------------------
# MCP STDIO server
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_FRAGMENT = (
    "[SideQuest | Brain: ACTIVE]\n"
    "Decisions and constraints are captured automatically in the background.\n"
    "Before answering about past choices or architecture → current_truth\n"
    "When you form a multi-step strategy → register_plan(goal, steps, session_id)\n"
    "Before planning similar work → recall_plans(goal_query, session_id)\n"
    "After major steps or completion → report_outcome(plan_id, outcome, valence, session_id)\n"
    "Exploring a tangent? → branch_quest(name, purpose)\n"
    "After every response → notify_turn(role='assistant', content=<response>, session_id=<id>)\n"
    "When current_truth returns a panel_url field, include it as a markdown link: [View in Mission Control](url)"
)

OFFLINE_FRAGMENT = "[SideQuest | Brain: OFFLINE — memory unavailable]"

_daemon_online = True


async def _replay_offline_queue() -> None:
    """
    W5 fix: replay messages queued while the daemon was offline.
    Called after a successful brain call confirms the daemon is back online.
    """
    if not OFFLINE_QUEUE.exists():
        return
    try:
        lines = OFFLINE_QUEUE.read_text(encoding="utf-8").splitlines()
        if not lines:
            return
        OFFLINE_QUEUE.unlink()  # clear queue before replaying (idempotent)
        for line in lines:
            try:
                entry = json.loads(line)
                await _call_brain(entry["method"], entry["params"])
            except Exception:
                pass  # best-effort replay — don't re-queue failed replays
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
        # Negotiate protocol version — echo back whatever the client requests
        client_version = params.get("protocolVersion", "2024-11-05")
        return ok({
            "protocolVersion": client_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "campy-desktop", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok({"tools": TOOLS})

    # Some MCP clients probe resources/list during discovery — return empty
    if method == "resources/list":
        return ok({"resources": []})

    if method == "prompts/list":
        return ok({"prompts": [{"name": "sidequests-system", "description": "HippoCampy instructions"}]})

    if method == "prompts/get":
        return ok({"description": "HippoCampy instructions",
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
                # W3 + W5 fix: replay queued messages when daemon comes back online.
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
            # W3 fix: always attempt the call even when _daemon_online is False
            # so the adapter can recover from offline state on its own.
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
                    return ok({"content": [{"type": "text",
                                            "text": OFFLINE_FRAGMENT}]})
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

        # --- analogical_search ---
        if tool_name == "analogical_search":
            try:
                result = await _call_brain("analogical_search", tool_input)
                _daemon_online = True
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except RuntimeError as e:
                if "DAEMON_OFFLINE" in str(e):
                    _daemon_online = False
                    return ok({"content": [{"type": "text",
                                            "text": '{"error": "daemon_offline"}'}]})
                return err(-32000, str(e))

        # --- ingest_document, explore_graph, complete_quest, set_quest, context_status,
        #     register_plan, report_outcome, recall_plans (and future tools) ---
        if tool_name in _ALL_TOOL_NAMES:
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
