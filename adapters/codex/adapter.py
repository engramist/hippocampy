"""
adapters/codex/adapter.py — Codex MCP STDIO Adapter (M8)

Implements the MCP STDIO server for OpenAI Codex CLI.
Forwards tool calls to the Brain Daemon via Unix socket (JSON-RPC 2.0).

Registration: add to ~/.codex/config.toml (or project .codex/config.toml):
  [mcp_servers.sidequests]
  command = "python"
  args = ["/path/to/adapters/codex/adapter.py"]

Identical protocol to the Claude Code adapter:
  - JSON-RPC 2.0 over STDIO
  - Forwards to Brain Daemon via Unix domain socket IPC
  - Git context injected into every tool call for MainQuest auto-resolution
  - 7 tools: notify_turn, current_truth, branch_quest, diff_since,
             get_open_loops, analogical_search, ingest_document

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
# MCP Tool definitions (what Codex sees)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "notify_turn",
        "description": (
            "Forward this turn to the Brain for background memory processing. "
            "Call after EVERY response. Response is instant — never blocks."
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
            "constraints, or architecture from the current project branch. "
            "Call before answering complex questions or making architectural choices."
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
            "Declare a SideQuest when exploring a tangent distinct from the "
            "main project goal. Returns side_quest_id for tracking."
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
            "given ISO timestamp. Use to sync context after a session gap."
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
            "Use to surface uncertain memory items for user review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "analogical_search",
        "description": (
            "Search across ALL historical MainQuests for similar decisions, "
            "constraints, and requirements. Use when starting a new project or "
            "feature that might benefit from past architectural patterns. "
            "Returns results attributed to their source project where possible."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":            {"type": "string"},
                "current_quest_id": {"type": "string",
                                     "description": "Exclude results from this quest."},
                "limit":            {"type": "integer", "default": 5},
                "min_similarity":   {"type": "number", "default": 0.70},
            },
            "required": ["query"],
        },
    },
    {
        "name": "ingest_document",
        "description": (
            "Ingest a local file into the Brain's knowledge graph. "
            "Chunks, embeds, and queues each segment for the Consolidation Loop. "
            "Idempotent: re-ingestion is skipped if the file hasn't changed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string",
                              "description": "Absolute path to the file to ingest."},
                "quest_id":  {"type": "string"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "explore_graph",
        "description": (
            "Traverse the knowledge graph from a known node. Use when current_truth "
            "returns a relevant node and you want to see what it connects to. "
            "Returns neighboring nodes and edges up to 3 hops."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_node_id":     {"type": "string",
                                      "description": "ID of the node to start from (from current_truth results)."},
                "relationship_type": {"type": "string",
                                      "description": "Filter to a specific edge type (e.g. REQUIRES, ENABLES)."},
                "direction":         {"type": "string",
                                      "enum": ["outgoing", "incoming", "both"],
                                      "default": "both"},
                "depth":             {"type": "integer", "default": 1,
                                      "description": "Traversal depth 1–3."},
            },
            "required": ["start_node_id"],
        },
    },
    {
        "name": "complete_quest",
        "description": (
            "Mark the current Quest as completed. Triggers lesson synthesis "
            "from confirmed artifacts. Completed quests feed cross-project analogical reasoning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "quest_id": {"type": "string",
                             "description": "The quest_id to mark completed."},
            },
            "required": ["quest_id"],
        },
    },
    {
        "name": "set_quest",
        "description": (
            "Explicitly bind this session to a named project/quest. "
            "Use when the user says 'this is about X' or starts a new project. "
            "Creates a new quest if the name doesn't match an existing one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id":  {"type": "string"},
                "quest_name":  {"type": "string",
                                "description": "Name of the quest to bind to."},
                "quest_id":    {"type": "string",
                                "description": "Optional: bind to a specific quest_id."},
            },
            "required": ["session_id", "quest_name"],
        },
    },
    {
        "name": "context_status",
        "description": (
            "Check the health of the current context window — token usage, "
            "loaded knowledge, and handoff suggestions. Use when context feels "
            "bloated or when starting a new session on an existing project."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    },
]

# ---------------------------------------------------------------------------
# Brain socket client
# ---------------------------------------------------------------------------

_SOCKET_TIMEOUT = 10.0

# Token limits per known model family (conservative estimates)
# Adapters can override via LLMProvider node in the graph
_TOKEN_LIMIT = 128000  # default (Codex/GPT-4 class)

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
            "serverInfo": {"name": "sidequests-brain-codex", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok({"tools": TOOLS})

    if method == "tools/call":
        tool_name  = params.get("name", "")
        tool_input = _inject_context(params.get("arguments", {}))

        # --- notify_turn ---
        if tool_name == "notify_turn":
            if not _daemon_online:
                _queue_offline("notify_turn", tool_input)
                return ok({"content": [{"type": "text",
                                        "text": '{"status": "queued_offline"}'}]})
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

        # --- all other tools: branch_quest, diff_since, get_open_loops,
        #                      analogical_search, ingest_document, explore_graph,
        #                      complete_quest, set_quest, context_status ---
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
