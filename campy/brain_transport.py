"""Shared client transport for adapters talking to the HippoCampy daemon."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from campy.paths import get_daemon_socket_path

DEFAULT_SOCKET_PATH = get_daemon_socket_path()
DEFAULT_HTTP_URL = "http://127.0.0.1:7799/mcp"


def socket_path() -> Path:
    """Return the preferred daemon socket path."""
    configured = (
        os.environ.get("SIDEQUESTS_BRAIN_SOCKET")
        or os.environ.get("SIDEQUESTS_SOCKET_PATH")
        or os.environ.get("CAMPY_BRAIN_SOCKET")
        or os.environ.get("CAMPY_SOCKET_PATH")
    )
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_SOCKET_PATH


def brain_url() -> str:
    """Return the preferred daemon HTTP MCP endpoint."""
    return (
        os.environ.get("SIDEQUESTS_BRAIN_URL")
        or os.environ.get("CAMPY_BRAIN_URL")
        or os.environ.get("BRAIN_URL")
        or DEFAULT_HTTP_URL
    )


def _candidate_sockets() -> list[Path]:
    configured = (
        os.environ.get("SIDEQUESTS_BRAIN_SOCKET")
        or os.environ.get("SIDEQUESTS_SOCKET_PATH")
        or os.environ.get("CAMPY_BRAIN_SOCKET")
        or os.environ.get("CAMPY_SOCKET_PATH")
    )
    if configured:
        return [Path(configured).expanduser()]
    uid = os.getuid() if hasattr(os, "getuid") else "user"
    return [
        DEFAULT_SOCKET_PATH,
        Path(f"/tmp/campy-{uid}.sock"),
        Path(f"/tmp/sidequests-{uid}.sock"),
    ]


def _jsonrpc_request(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }


async def _call_socket(
    socket_file: Path,
    method: str,
    params: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = _jsonrpc_request(method, params)
    reader, writer = await asyncio.open_unix_connection(str(socket_file))
    try:
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    finally:
        writer.close()
        await writer.wait_closed()

    response = json.loads(line)
    if "error" in response:
        raise RuntimeError(response["error"]["message"])
    return response.get("result", {})


def _call_http_sync(
    url: str,
    method: str,
    params: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request_body = _jsonrpc_request(
        "tools/call",
        {"name": method, "arguments": params},
    )
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("SIDEQUESTS_BRAIN_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Sidequests-Token"] = token

    req = urllib.request.Request(
        url,
        data=json.dumps(request_body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode()

    payload = json.loads(raw)
    if "error" in payload:
        raise RuntimeError(payload["error"]["message"])

    result = payload.get("result", {})
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list) and content:
        text = content[0].get("text") if isinstance(content[0], dict) else None
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {"text": text}
    return result if isinstance(result, dict) else {}


async def _call_http(
    url: str,
    method: str,
    params: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    return await asyncio.to_thread(_call_http_sync, url, method, params, timeout)


async def call_brain(method: str, params: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    """
    Call the Brain daemon using the most portable available endpoint.

    Resolution order:
    1. Explicit SIDEQUESTS_BRAIN_URL/BRAIN_URL HTTP endpoint.
    2. Explicit or default Unix socket path.
    3. Localhost Streamable HTTP endpoint.
    """
    if os.environ.get("SIDEQUESTS_BRAIN_URL") or os.environ.get("BRAIN_URL"):
        try:
            return await _call_http(brain_url(), method, params, timeout)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"DAEMON_HTTP_ERROR: {brain_url()} returned HTTP {e.code}: {e.reason}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(f"DAEMON_HTTP_ERROR: cannot reach {brain_url()}: {e}")

    socket_errors: list[str] = []
    for candidate in _candidate_sockets():
        try:
            return await _call_socket(candidate, method, params, timeout)
        except (FileNotFoundError, ConnectionRefusedError, asyncio.TimeoutError) as e:
            socket_errors.append(f"{candidate}: {type(e).__name__}: {e}")
        except PermissionError as e:
            socket_errors.append(f"{candidate}: PermissionError: {e}")
        except OSError as e:
            socket_errors.append(f"{candidate}: OSError: {e}")

    try:
        return await _call_http(brain_url(), method, params, timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"DAEMON_HTTP_ERROR: {brain_url()} returned HTTP {e.code}: {e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        details = "; ".join(socket_errors) or "no socket candidates"
        raise RuntimeError(
            f"DAEMON_OFFLINE: socket transports failed ({details}); "
            f"HTTP fallback failed ({brain_url()}: {e})"
        )
