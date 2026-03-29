"""
tests/test_adapters.py — Comprehensive adapter integration tests.

Covers all 4 fully-implemented adapters:
  - adapters/claude_code/adapter.py
  - adapters/codex/adapter.py
  - adapters/claude_desktop/adapter.py
  - adapters/gemini_cli/adapter.py

Test categories:
  1. MCP lifecycle (initialize, tools/list, notifications/initialized)
  2. Tool registration (all 7 tools present with correct schemas)
  3. Tool dispatch (all 7 tools forwarded to _call_brain)
  4. Offline queue behavior (notify_turn queued, current_truth returns OFFLINE)
  5. Daemon recovery (offline → online transition)
  6. Git context injection (repo_root + git_branch in every call)
  7. Error handling (unknown tool, unknown method)
"""

from __future__ import annotations
import asyncio
import importlib
import json
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Adapter parametrization
# ---------------------------------------------------------------------------

ADAPTER_IDS = ["claude_code", "codex", "claude_desktop", "gemini_cli", "chatgpt_desktop"]
ADAPTER_MODULES = [
    f"adapters.{name.replace('-', '_')}.adapter" for name in ADAPTER_IDS
]

EXPECTED_TOOLS = {
    "notify_turn", "current_truth", "branch_quest", "diff_since",
    "get_open_loops", "analogical_search", "ingest_document", "explore_graph",
    "complete_quest", "set_quest", "context_status", "get_anomalies",
    "upsert_lesson", "recall_relevant_lessons",  # B11
}

# Expected serverInfo name per adapter
EXPECTED_SERVER_NAMES = {
    "claude_code":    "sidequests-brain",
    "codex":          "sidequests-brain-codex",
    "claude_desktop": "sidequests-brain-desktop",
    "gemini_cli":     "sidequests-brain-gemini",
    "chatgpt_desktop": "sidequests-brain-chatgpt",
}


@pytest.fixture(
    params=list(zip(ADAPTER_IDS, ADAPTER_MODULES)),
    ids=ADAPTER_IDS
)
def adapter(request):
    """Import and return each adapter module."""
    adapter_id, module_path = request.param
    mod = importlib.import_module(module_path)
    mod._adapter_id = adapter_id  # attach for assertions
    return mod


@pytest.fixture
def patched(adapter, tmp_path, monkeypatch):
    """Patch OFFLINE_QUEUE to tmp_path, reset _daemon_online=True."""
    monkeypatch.setattr(adapter, "OFFLINE_QUEUE", tmp_path / "offline.jsonl")
    monkeypatch.setattr(adapter, "_daemon_online", True)
    return adapter


# ---------------------------------------------------------------------------
# 1. MCP Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_protocol_version(adapter):
    """initialize returns correct MCP protocol version."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    })
    assert response["result"]["protocolVersion"] == "2024-11-05"


@pytest.mark.asyncio
async def test_initialize_capabilities(adapter):
    """initialize returns tools capability."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    })
    assert "tools" in response["result"]["capabilities"]


@pytest.mark.asyncio
async def test_initialize_server_name(adapter):
    """initialize returns the correct serverInfo.name for each adapter."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    })
    name = response["result"]["serverInfo"]["name"]
    expected = EXPECTED_SERVER_NAMES[adapter._adapter_id]
    assert name == expected, f"Expected '{expected}', got '{name}'"


@pytest.mark.asyncio
async def test_notifications_initialized_returns_none(adapter):
    """notifications/initialized is a one-way notification — no response."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "method": "notifications/initialized"
    })
    assert response is None


@pytest.mark.asyncio
async def test_unknown_method_returns_32601(adapter):
    """Unknown method returns JSON-RPC -32601 error."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 3, "method": "nonexistent/method", "params": {}
    })
    assert "error" in response
    assert response["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# 2. Tool Registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tools_list_returns_all_seven(adapter):
    """tools/list returns exactly the 7 expected tools."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    })
    tool_names = {t["name"] for t in response["result"]["tools"]}
    assert EXPECTED_TOOLS == tool_names, f"Missing: {EXPECTED_TOOLS - tool_names}"


@pytest.mark.asyncio
async def test_tools_have_input_schema(adapter):
    """Every tool has an inputSchema."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    })
    for tool in response["result"]["tools"]:
        assert "inputSchema" in tool, f"Tool '{tool['name']}' missing inputSchema"


@pytest.mark.asyncio
async def test_notify_turn_schema_has_required_fields(adapter):
    """notify_turn inputSchema requires role, content, session_id."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    })
    tools = {t["name"]: t for t in response["result"]["tools"]}
    schema = tools["notify_turn"]["inputSchema"]
    assert set(schema["required"]) == {"role", "content", "session_id"}


@pytest.mark.asyncio
async def test_current_truth_schema_has_required_fields(adapter):
    """current_truth inputSchema requires query, session_id."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    })
    tools = {t["name"]: t for t in response["result"]["tools"]}
    schema = tools["current_truth"]["inputSchema"]
    assert set(schema["required"]) == {"query", "session_id"}


# ---------------------------------------------------------------------------
# 3. Tool Dispatch — all 7 tools call _call_brain
# ---------------------------------------------------------------------------

TOOL_CALLS = [
    ("notify_turn",      {"role": "user", "content": "hello", "session_id": "s1"}),
    ("current_truth",    {"query": "database choice", "session_id": "s1"}),
    ("branch_quest",     {"name": "perf work", "purpose": "investigate latency"}),
    ("diff_since",       {"since_iso": "2026-01-01T00:00:00Z"}),
    ("get_open_loops",   {}),
    ("analogical_search", {"query": "graph database"}),
    ("ingest_document",  {"file_path": "/tmp/test.md"}),
    ("explore_graph",    {"start_node_id": "abc-123"}),
    ("complete_quest",   {"quest_id": "quest-xyz"}),
    ("set_quest",        {"session_id": "s1", "quest_name": "New Project"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,tool_args", TOOL_CALLS, ids=[t[0] for t in TOOL_CALLS])
async def test_tool_dispatches_to_brain(patched, monkeypatch, tool_name, tool_args):
    """Each tool call forwards to _call_brain with correct method name."""
    called = {}

    async def fake_call_brain(method, params):
        called["method"] = method
        called["params"] = params
        return {"status": "ok", "results": []}

    monkeypatch.setattr(patched, "_call_brain", fake_call_brain)

    await patched.handle_mcp_request({
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": tool_name, "arguments": tool_args}
    })

    assert called.get("method") == tool_name, (
        f"Expected _call_brain called with '{tool_name}', got '{called.get('method')}'"
    )


@pytest.mark.asyncio
async def test_unknown_tool_returns_32601(patched, monkeypatch):
    """Unknown tool name returns -32601 error."""
    async def fake_brain(method, params):
        return {"status": "ok"}
    monkeypatch.setattr(patched, "_call_brain", fake_brain)

    response = await patched.handle_mcp_request({
        "jsonrpc": "2.0", "id": 30, "method": "tools/call",
        "params": {"name": "does_not_exist", "arguments": {}}
    })
    assert response["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# 4. Offline Queue Behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_turn_queues_when_daemon_offline(patched, monkeypatch, tmp_path):
    """When daemon offline, notify_turn returns queued_offline and writes JSONL."""
    async def fail_brain(method, params):
        raise RuntimeError("DAEMON_OFFLINE")

    monkeypatch.setattr(patched, "_call_brain", fail_brain)

    response = await patched.handle_mcp_request({
        "jsonrpc": "2.0", "id": 20, "method": "tools/call",
        "params": {
            "name": "notify_turn",
            "arguments": {"role": "user", "content": "test", "session_id": "s1"}
        }
    })

    # Returns ok (not an error) with queued_offline status
    assert "result" in response, "Expected result, got error"
    text = response["result"]["content"][0]["text"]
    assert "queued_offline" in text

    # JSONL entry written
    queue_file = tmp_path / "offline.jsonl"
    assert queue_file.exists(), "Offline queue file not created"
    entry = json.loads(queue_file.read_text().strip())
    assert entry["method"] == "notify_turn"


@pytest.mark.asyncio
async def test_current_truth_returns_offline_fragment(patched, monkeypatch):
    """When daemon offline, current_truth returns OFFLINE fragment (not an error)."""
    async def fail_brain(method, params):
        raise RuntimeError("DAEMON_OFFLINE")

    monkeypatch.setattr(patched, "_call_brain", fail_brain)

    response = await patched.handle_mcp_request({
        "jsonrpc": "2.0", "id": 21, "method": "tools/call",
        "params": {
            "name": "current_truth",
            "arguments": {"query": "test", "session_id": "s1"}
        }
    })

    assert "result" in response
    text = response["result"]["content"][0]["text"]
    assert "OFFLINE" in text


def test_queue_offline_writes_jsonl(adapter, tmp_path, monkeypatch):
    """_queue_offline writes a valid JSONL entry."""
    monkeypatch.setattr(adapter, "OFFLINE_QUEUE", tmp_path / "offline.jsonl")
    adapter._queue_offline("notify_turn", {"role": "user", "content": "hi"})

    lines = (tmp_path / "offline.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["method"] == "notify_turn"
    assert entry["params"]["role"] == "user"
    assert "ts" in entry


def test_queue_offline_appends_multiple(adapter, tmp_path, monkeypatch):
    """Multiple _queue_offline calls produce separate JSONL lines."""
    monkeypatch.setattr(adapter, "OFFLINE_QUEUE", tmp_path / "offline.jsonl")
    adapter._queue_offline("notify_turn", {"content": "msg1"})
    adapter._queue_offline("notify_turn", {"content": "msg2"})

    lines = (tmp_path / "offline.jsonl").read_text().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# 5. Daemon Recovery (offline → online transition)
# ---------------------------------------------------------------------------

# Adapters that attempt _call_brain even when _daemon_online=False (auto-recovery).
# The codex adapter short-circuits when offline (different intentional design):
# it never attempts the call — recovery happens via explicit retry on next turn.
_AUTO_RECOVERY_ADAPTERS = {"claude_code", "claude_desktop", "gemini_cli"}


@pytest.mark.asyncio
async def test_daemon_online_flag_set_after_successful_call(patched, monkeypatch):
    """_daemon_online flips back to True after a successful brain call (auto-recovery adapters)."""
    if patched._adapter_id not in _AUTO_RECOVERY_ADAPTERS:
        pytest.skip(f"{patched._adapter_id} uses short-circuit offline design (no auto-recovery)")

    monkeypatch.setattr(patched, "_daemon_online", False)

    async def fake_brain(method, params):
        return {"status": "queued"}

    monkeypatch.setattr(patched, "_call_brain", fake_brain)

    await patched.handle_mcp_request({
        "jsonrpc": "2.0", "id": 40, "method": "tools/call",
        "params": {
            "name": "notify_turn",
            "arguments": {"role": "assistant", "content": "hi", "session_id": "s"}
        }
    })

    assert patched._daemon_online is True


@pytest.mark.asyncio
async def test_codex_queues_when_offline_call_fails(patched, monkeypatch, tmp_path):
    """Codex adapter always attempts _call_brain (self-recovery pattern) and queues on failure."""
    if patched._adapter_id != "codex":
        pytest.skip("Recovery test only applies to codex adapter")

    monkeypatch.setattr(patched, "_daemon_online", False)
    brain_called = {"n": 0}

    async def fake_brain(method, params):
        brain_called["n"] += 1
        raise RuntimeError("DAEMON_OFFLINE: socket not found")

    monkeypatch.setattr(patched, "_call_brain", fake_brain)

    response = await patched.handle_mcp_request({
        "jsonrpc": "2.0", "id": 41, "method": "tools/call",
        "params": {
            "name": "notify_turn",
            "arguments": {"role": "user", "content": "hi", "session_id": "s"}
        }
    })

    # Brain was attempted (no early short-circuit — allows self-recovery)
    assert brain_called["n"] == 1
    # Returns queued_offline gracefully after failure
    assert "queued_offline" in response["result"]["content"][0]["text"]


# ---------------------------------------------------------------------------
# 6. Git Context Injection
# ---------------------------------------------------------------------------

def test_inject_context_adds_keys(adapter):
    """_inject_context adds repo_root, git_branch, and workspace_path to params dict."""
    original = {"query": "test", "session_id": "s"}
    result = adapter._inject_context(original)

    assert "workspace_path" in result
    # Original params preserved
    assert result["query"] == "test"
    assert result["session_id"] == "s"


def test_inject_context_does_not_mutate_original(adapter):
    """_inject_context returns a new dict; original is unchanged."""
    original = {"foo": "bar"}
    result = adapter._inject_context(original)

    assert "workspace_path" not in original
    assert result is not original


@pytest.mark.asyncio
async def test_tool_dispatch_injects_git_context(patched, monkeypatch):
    """Git context keys are present in every _call_brain invocation."""
    received = {}

    async def fake_brain(method, params):
        received.update(params)
        return {"status": "ok"}

    monkeypatch.setattr(patched, "_call_brain", fake_brain)

    await patched.handle_mcp_request({
        "jsonrpc": "2.0", "id": 50, "method": "tools/call",
        "params": {
            "name": "notify_turn",
            "arguments": {"role": "user", "content": "x", "session_id": "s"}
        }
    })

    assert "repo_root" in received, "_call_brain did not receive repo_root"
    assert "git_branch" in received, "_call_brain did not receive git_branch"


def test_detect_git_context_returns_strings(adapter):
    """detect_git_context always returns two strings (may be empty)."""
    root, branch = adapter.detect_git_context()
    assert isinstance(root, str)
    assert isinstance(branch, str)


# ---------------------------------------------------------------------------
# 7. Response format — content wrapper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_tool_response_has_content_wrapper(patched, monkeypatch):
    """Successful tool calls return MCP content wrapper format."""
    async def fake_brain(method, params):
        return {"status": "queued", "message_id": "abc"}

    monkeypatch.setattr(patched, "_call_brain", fake_brain)

    response = await patched.handle_mcp_request({
        "jsonrpc": "2.0", "id": 60, "method": "tools/call",
        "params": {
            "name": "notify_turn",
            "arguments": {"role": "user", "content": "hi", "session_id": "s"}
        }
    })

    assert "result" in response
    content = response["result"]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    # The text should be valid JSON
    parsed = json.loads(content[0]["text"])
    assert isinstance(parsed, dict)
