from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sidequests import brain_transport
from sidequests.adapters import mcp_server


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
