"""
Tests for the Claude Code MCP adapter (adapters/claude_code/adapter.py).
T8 fix: was a stub with no test functions.
"""

import asyncio
import json
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# handle_mcp_request — lifecycle messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_returns_protocol_version():
    """MCP initialize handshake returns correct protocol version."""
    from adapters.claude_code.adapter import handle_mcp_request
    response = await handle_mcp_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    })
    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in response["result"]["capabilities"]


@pytest.mark.asyncio
async def test_tools_list_contains_notify_turn():
    """tools/list returns at minimum notify_turn and current_truth."""
    from adapters.claude_code.adapter import handle_mcp_request
    response = await handle_mcp_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    })
    tool_names = [t["name"] for t in response["result"]["tools"]]
    assert "notify_turn" in tool_names
    assert "current_truth" in tool_names


@pytest.mark.asyncio
async def test_unknown_method_returns_error():
    """Unknown method returns JSON-RPC -32601 error."""
    from adapters.claude_code.adapter import handle_mcp_request
    response = await handle_mcp_request({
        "jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}
    })
    assert "error" in response
    assert response["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_notifications_initialized_returns_none():
    """notifications/initialized is a one-way notification — no response."""
    from adapters.claude_code.adapter import handle_mcp_request
    response = await handle_mcp_request({
        "jsonrpc": "2.0", "method": "notifications/initialized"
    })
    assert response is None


# ---------------------------------------------------------------------------
# Offline queue behavior
# ---------------------------------------------------------------------------

def test_queue_offline_writes_jsonl(tmp_path, monkeypatch):
    """_queue_offline writes a JSONL entry to the offline queue file."""
    import adapters.claude_code.adapter as adapter_module
    monkeypatch.setattr(adapter_module, "OFFLINE_QUEUE", tmp_path / "offline.jsonl")

    adapter_module._queue_offline("notify_turn", {"role": "user", "content": "hello"})

    lines = (tmp_path / "offline.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["method"] == "notify_turn"
    assert entry["params"]["role"] == "user"


def test_queue_offline_appends_multiple(tmp_path, monkeypatch):
    """Multiple _queue_offline calls append separate JSONL lines."""
    import adapters.claude_code.adapter as adapter_module
    monkeypatch.setattr(adapter_module, "OFFLINE_QUEUE", tmp_path / "offline.jsonl")

    adapter_module._queue_offline("notify_turn", {"content": "msg1"})
    adapter_module._queue_offline("notify_turn", {"content": "msg2"})

    lines = (tmp_path / "offline.jsonl").read_text().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# notify_turn — daemon offline path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_turn_queues_when_daemon_offline(tmp_path, monkeypatch):
    """When daemon is offline, notify_turn queues the message and returns gracefully."""
    import adapters.claude_code.adapter as adapter_module
    monkeypatch.setattr(adapter_module, "OFFLINE_QUEUE", tmp_path / "offline.jsonl")
    monkeypatch.setattr(adapter_module, "_daemon_online", True)

    # Patch _call_brain to raise DAEMON_OFFLINE
    async def fake_call_brain(method, params):
        raise RuntimeError("DAEMON_OFFLINE")
    monkeypatch.setattr(adapter_module, "_call_brain", fake_call_brain)

    response = await adapter_module.handle_mcp_request({
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {
            "name": "notify_turn",
            "arguments": {"role": "user", "content": "test", "session_id": "s1"}
        }
    })

    # Should return ok with queued_offline status (not an error)
    assert "result" in response
    result_text = response["result"]["content"][0]["text"]
    assert "queued_offline" in result_text

    # Offline queue should have one entry
    lines = (tmp_path / "offline.jsonl").read_text().splitlines()
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# Git context detection
# ---------------------------------------------------------------------------

def test_detect_git_context_returns_strings():
    """detect_git_context always returns two strings (may be empty outside git)."""
    from adapters.claude_code.adapter import detect_git_context
    root, branch = detect_git_context()
    assert isinstance(root, str)
    assert isinstance(branch, str)
