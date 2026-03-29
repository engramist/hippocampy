"""
tests/test_adapter_claude_desktop.py — Dedicated tests for Claude Desktop adapter.

Ensures it can be run as `python -m sidequests.adapters.claude_desktop`
and returns the correct serverInfo name.
"""

from __future__ import annotations
import asyncio
import json
import pytest
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sidequests.adapters.claude_desktop.adapter as adapter

@pytest.fixture
def patched(tmp_path, monkeypatch):
    """Patch OFFLINE_QUEUE to tmp_path, reset _daemon_online=True."""
    monkeypatch.setattr(adapter, "OFFLINE_QUEUE", tmp_path / "offline.jsonl")
    monkeypatch.setattr(adapter, "_daemon_online", True)
    return adapter

@pytest.mark.asyncio
async def test_initialize_server_name(patched):
    """initialize returns the correct serverInfo.name."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    })
    assert response["result"]["serverInfo"]["name"] == "sidequests-brain-desktop"

@pytest.mark.asyncio
async def test_tools_list(patched):
    """tools/list returns the expected tools."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    })
    tools = [t["name"] for t in response["result"]["tools"]]
    assert "notify_turn" in tools
    assert "current_truth" in tools
    assert "explore_graph" in tools

@pytest.mark.asyncio
async def test_token_limit(patched):
    """_TOKEN_LIMIT is 200,000 for Claude Desktop."""
    assert adapter._TOKEN_LIMIT == 200000

@pytest.mark.asyncio
async def test_system_prompt(patched):
    """prompts/get returns the system prompt fragment."""
    response = await adapter.handle_mcp_request({
        "jsonrpc": "2.0", "id": 3, "method": "prompts/get", "params": {"name": "sidequests-system"}
    })
    content = response["result"]["messages"][0]["content"]["text"]
    assert "[SideQuest | Brain: ACTIVE]" in content
