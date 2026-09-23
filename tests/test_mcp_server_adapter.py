from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from campy import brain_transport
from campy.adapters import mcp_server


def test_socket_path_uses_env_override(monkeypatch):
    monkeypatch.setenv("SIDEQUESTS_BRAIN_SOCKET", "/tmp/sidequests-test/brain.sock")

    assert mcp_server._socket_path() == Path("/tmp/sidequests-test/brain.sock")


def test_socket_path_keeps_legacy_env_override(monkeypatch):
    monkeypatch.delenv("SIDEQUESTS_BRAIN_SOCKET", raising=False)
    monkeypatch.setenv("SIDEQUESTS_SOCKET_PATH", "/tmp/sidequests-legacy/brain.sock")

    assert mcp_server._socket_path() == Path("/tmp/sidequests-legacy/brain.sock")


@pytest.mark.asyncio
async def test_transport_falls_back_to_http_after_permission_denied(monkeypatch):
    async def fail_open(*args, **kwargs):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(asyncio, "open_unix_connection", fail_open)
    monkeypatch.setattr(brain_transport, "DEFAULT_SOCKET_PATH", Path("/blocked/brain.sock"))

    async def fake_http(url, method, params, timeout):
        return {"lesson_id": "lesson-1", "status": "upserted"}

    monkeypatch.setattr(brain_transport, "_call_http", fake_http)

    result = await brain_transport.call_brain("upsert_lesson", {"text": "probe"})

    assert result["lesson_id"] == "lesson-1"


@pytest.mark.asyncio
async def test_handle_mcp_request_surfaces_transport_errors(monkeypatch):
    async def fail_brain(method, params):
        raise RuntimeError("DAEMON_HTTP_ERROR: unauthorized")

    monkeypatch.setattr(mcp_server, "_call_brain", fail_brain)

    response = await mcp_server.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": "probe",
        "method": "tools/call",
        "params": {
            "name": "upsert_lesson",
            "arguments": {"text": "probe"},
        },
    })

    assert response["error"]["code"] == -32000
    assert "DAEMON_HTTP_ERROR" in response["error"]["message"]


# ---------------------------------------------------------------------------
# B449 — this adapter is an explicit external tool-call surface, not an
# implicit background path, so it must not use the short CAPTURE_TIMEOUT/
# CONTEXT_TIMEOUT budgets meant for hooks/context-injection.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["notify_turn", "ask"])
async def test_call_brain_uses_mcp_adapter_timeout_for_every_method(monkeypatch, method):
    """AC (B449): both a WRITE_METHODS member (`notify_turn`) and a
    non-write method (`ask`) go through call_brain_soft with
    MCP_ADAPTER_TIMEOUT — proving the old CAPTURE_TIMEOUT/CONTEXT_TIMEOUT
    split (2.0s / 3.0s) is gone, not just relabeled."""
    seen = {}

    async def fake_call_brain_soft(method, params, *, timeout, default):
        seen["timeout"] = timeout
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "call_brain_soft", fake_call_brain_soft)

    result = await mcp_server._call_brain(method, {})

    assert result == {"ok": True}
    assert seen["timeout"] == brain_transport.MCP_ADAPTER_TIMEOUT
    assert seen["timeout"] not in (2.0, 3.0)
