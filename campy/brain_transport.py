"""Shared client transport for adapters talking to the HippoCampy daemon."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from campy.paths import get_daemon_socket_path, runtime_dir

DEFAULT_SOCKET_PATH = get_daemon_socket_path()
DEFAULT_HTTP_URL = "http://127.0.0.1:7799/mcp"

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# B318 — Fail-open timeout budgets by surface.
#
# See docs/ecosystem-rules.md "Fail-open" for the contract. Every implicit
# (agent-triggered, not human-typed) call site must state its own budget —
# there is deliberately no shared default, because a shared default is how
# the 10-second-per-tool-call hook path happened in the first place.
#
# Non-Python callers (the `.sh` hooks) cannot import these constants; they
# encode the same numbers via `timeout N` (coreutils) and a comment pointing
# back to this table. Keep the two in sync.
# ---------------------------------------------------------------------------
HOOK_TIMEOUT = 1.0
"""pre_tool_use / post_tool_use hooks — fires per tool call."""

CONTEXT_TIMEOUT = 3.0
"""Session start / context injection — fires once per session."""

CAPTURE_TIMEOUT = 2.0
"""Capture / write paths (notify_turn and friends) — fire-and-forget."""

CLI_TIMEOUT = 30.0
"""Explicit CLI (`campy ask`, `campy recall`) — user asked, user waits."""


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


# ---------------------------------------------------------------------------
# B318 — Fail-open soft-failure bookkeeping.
#
# call_brain_soft() never raises, so the only way a human finds out memory
# has been degraded for a while is if something records it. This is a small
# JSON state file (not KuzuDB — the daemon that would write to Kuzu is
# exactly the thing that might be down) that `campy doctor` and the activity
# feed read back. Best-effort throughout: bookkeeping must never itself be
# a reason a caller fails.
# ---------------------------------------------------------------------------
_SOFT_FAILURE_STATE_FILENAME = "fail_open_state.json"


def _soft_failure_state_path() -> Path:
    return runtime_dir() / _SOFT_FAILURE_STATE_FILENAME


def read_soft_failure_state() -> dict[str, Any]:
    """Return the current consecutive-soft-failure bookkeeping state.

    Always returns a dict, defaulting to zero failures when the state file
    is missing or unreadable — this is read by `campy doctor`, which must
    not itself fail just because the state file hasn't been created yet.
    """
    default: dict[str, Any] = {
        "consecutive_failures": 0,
        "last_method": None,
        "last_error": None,
        "updated_at": None,
    }
    try:
        path = _soft_failure_state_path()
        if not path.exists():
            return default
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default
        default.update(data)
        return default
    except Exception:
        return default


def _write_soft_failure_state(
    count: int, *, last_method: str | None = None, last_error: str | None = None
) -> None:
    import datetime as _datetime

    try:
        path = _soft_failure_state_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {
            "consecutive_failures": count,
            "last_method": last_method,
            "last_error": last_error,
            "updated_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        # State bookkeeping is observability only; never break the caller.
        pass


def _record_soft_success() -> None:
    try:
        if read_soft_failure_state().get("consecutive_failures", 0):
            _write_soft_failure_state(0)
    except Exception:
        pass


def _record_soft_failure(method: str, error: BaseException) -> int:
    try:
        count = int(read_soft_failure_state().get("consecutive_failures", 0)) + 1
    except Exception:
        count = 1
    error_text = f"{type(error).__name__}: {error}"
    _write_soft_failure_state(count, last_method=method, last_error=error_text)
    try:
        from campy.brain.brainstem.activity_log import emit_activity

        emit_activity(
            "soft_failure",
            method=method,
            status="degraded",
            lane="degraded",
            details={"consecutive_failures": count, "error": error_text},
        )
    except Exception:
        pass
    return count


async def call_brain_soft(
    method: str,
    params: dict[str, Any],
    *,
    timeout: float,
    default: Any = None,
) -> Any:
    """Fail-open wrapper around `call_brain()`.

    Returns `default` on ANY failure — unreachable daemon, timeout, HTTP
    error, JSON-RPC error object, malformed/truncated response. Logs at
    DEBUG (not WARNING: an offline daemon is a normal state for a local
    install, and warn-level noise on every tool call trains users to ignore
    logs). Never raises.

    `timeout` is keyword-only and required — no default. Forcing each call
    site to state its own budget is the point; a shared default is how the
    10-second-per-tool-call hook path happened. See the timeout-budget
    constants above (HOOK_TIMEOUT, CONTEXT_TIMEOUT, CAPTURE_TIMEOUT,
    CLI_TIMEOUT) for the values each surface should pass.

    This is for implicit paths — recall, context injection, hooks, capture
    — that the agent didn't explicitly ask for. Explicit user-invoked CLI
    commands (`campy ask`, `campy recall`, `campy doctor`) should keep using
    `call_brain()` directly so the user gets a real error.
    """
    try:
        result = await call_brain(method, params, timeout=timeout)
    except Exception as exc:
        _logger.debug(
            "call_brain_soft: %s failed (%s: %s) — degrading to default",
            method,
            type(exc).__name__,
            exc,
        )
        _record_soft_failure(method, exc)
        return default
    _record_soft_success()
    return result
