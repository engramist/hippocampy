# tests/test_fail_open.py
"""
B318 — Fail-Open: a Campy outage must degrade agents, never block them.

These tests exercise the actual failure modes (real stub sockets that
refuse, stall, or answer with garbage) rather than mocking the client, per
the card: "The hang case needs a stub server that accepts and stalls; do
not fake it by patching the client, because patching proves the mock
returns a default, not that the timeout fires."
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Env isolation — every test in this module gets a clean transport-relevant
# environment so a real local daemon (or a leftover var from another test)
# can't make a "daemon down" scenario accidentally succeed.
# ---------------------------------------------------------------------------
_BRAIN_ENV_VARS = [
    "SIDEQUESTS_BRAIN_SOCKET",
    "SIDEQUESTS_SOCKET_PATH",
    "CAMPY_BRAIN_SOCKET",
    "CAMPY_SOCKET_PATH",
    "SIDEQUESTS_BRAIN_URL",
    "CAMPY_BRAIN_URL",
    "BRAIN_URL",
    "SIDEQUESTS_BRAIN_TOKEN",
]

# A port nothing listens on in the test sandbox; used as a fast-refusing
# HTTP fallback so tests never depend on (or wait on) the real default
# daemon port (7799) being empty.
_REFUSED_HTTP_URL = "http://127.0.0.1:1/mcp"


@pytest.fixture(autouse=True)
def _clean_brain_env(monkeypatch):
    for var in _BRAIN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


# ---------------------------------------------------------------------------
# Stub Unix-socket daemon — real sockets, no client mocking.
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def unix_stub_server(sock_path: Path, *, stall: bool = False, response: bytes | None = None):
    """Serve real connections on a Unix domain socket in a background thread.

    stall=True   — accept the connection and never read or write anything
                   (simulates a daemon that is up but hung).
    response=b'..' — accept, read one line, write `response` back, close.
    Neither set — accept and close immediately (empty response).
    """
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_path))
    srv.listen(5)
    srv.settimeout(0.2)
    stop_event = threading.Event()
    held_conns: list[socket.socket] = []

    def _serve():
        while not stop_event.is_set():
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if stall:
                held_conns.append(conn)
                continue
            try:
                conn.settimeout(2.0)
                with contextlib.suppress(OSError):
                    conn.recv(65536)
                if response is not None:
                    conn.sendall(response)
            finally:
                with contextlib.suppress(OSError):
                    conn.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=2.0)
        for c in held_conns:
            with contextlib.suppress(OSError):
                c.close()
        with contextlib.suppress(OSError):
            srv.close()


def _refused_socket_path(tmp_path: Path) -> Path:
    """A Unix socket file that exists but has nothing listening on it —
    connecting yields ConnectionRefusedError, distinct from FileNotFoundError."""
    path = tmp_path / "refused.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    s.close()  # bound, never listened on, file left behind — connect() refuses
    return path


# ---------------------------------------------------------------------------
# Task 4 — call_brain_soft() never raises, for every failure mode.
# ---------------------------------------------------------------------------
class TestCallBrainSoftFailureModes:
    async def test_no_socket_no_http_returns_default(self, tmp_path, monkeypatch):
        """DAEMON_OFFLINE path: nonexistent socket, unreachable HTTP fallback."""
        from campy.brain_transport import call_brain_soft

        monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(tmp_path / "does-not-exist.sock"))
        monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

        sentinel = object()
        result = await call_brain_soft("current_truth", {}, timeout=1.0, default=sentinel)

        assert result is sentinel

    async def test_connection_refused_returns_default(self, tmp_path, monkeypatch):
        """Socket file exists but nothing is listening — ConnectionRefusedError."""
        from campy.brain_transport import call_brain_soft

        sock_path = _refused_socket_path(tmp_path)
        monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(sock_path))
        monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

        sentinel = object()
        result = await call_brain_soft("current_truth", {}, timeout=1.0, default=sentinel)

        assert result is sentinel

    async def test_stalled_daemon_times_out_and_returns_default(self, tmp_path, monkeypatch):
        """Daemon accepts the connection and never responds — the timeout path.

        Uses a real stub server that accepts and stalls (not a client mock)
        so this proves the timeout actually fires, not that a mock returns
        a default.
        """
        from campy.brain_transport import call_brain_soft

        sock_path = tmp_path / "stall.sock"
        monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(sock_path))
        monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

        sentinel = object()
        with unix_stub_server(sock_path, stall=True):
            started = time.monotonic()
            result = await call_brain_soft(
                "current_truth", {}, timeout=1.0, default=sentinel
            )
            elapsed = time.monotonic() - started

        assert result is sentinel
        # Must return close to the requested timeout, not hang indefinitely.
        assert elapsed < 2.0, f"call_brain_soft took {elapsed:.2f}s against a stalled daemon"

    async def test_jsonrpc_error_object_returns_default(self, tmp_path, monkeypatch):
        """Daemon responds, but with a JSON-RPC error object."""
        from campy.brain_transport import call_brain_soft

        sock_path = tmp_path / "jsonrpc_error.sock"
        monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(sock_path))
        monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

        error_response = (
            json.dumps({"jsonrpc": "2.0", "id": "1", "error": {"code": -32000, "message": "boom"}})
            + "\n"
        ).encode()

        sentinel = object()
        with unix_stub_server(sock_path, response=error_response):
            result = await call_brain_soft("current_truth", {}, timeout=1.0, default=sentinel)

        assert result is sentinel

    async def test_malformed_json_returns_default(self, tmp_path, monkeypatch):
        """Daemon responds with malformed/truncated JSON."""
        from campy.brain_transport import call_brain_soft

        sock_path = tmp_path / "malformed.sock"
        monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(sock_path))
        monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

        sentinel = object()
        with unix_stub_server(sock_path, response=b'{"jsonrpc": "2.0", "id": "1", "resul\n'):
            result = await call_brain_soft("current_truth", {}, timeout=1.0, default=sentinel)

        assert result is sentinel

    async def test_success_returns_real_result_unmodified(self, tmp_path, monkeypatch):
        """Sanity check: when the daemon *is* reachable, call_brain_soft
        returns the real result, not the default."""
        from campy.brain_transport import call_brain_soft

        sock_path = tmp_path / "ok.sock"
        monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(sock_path))
        monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

        ok_response = (
            json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"status": "ok"}}) + "\n"
        ).encode()

        sentinel = object()
        with unix_stub_server(sock_path, response=ok_response):
            result = await call_brain_soft("current_truth", {}, timeout=1.0, default=sentinel)

        assert result == {"status": "ok"}
        assert result is not sentinel


# ---------------------------------------------------------------------------
# timeout is keyword-only and required.
# ---------------------------------------------------------------------------
def test_timeout_is_required_keyword_only():
    from campy.brain_transport import call_brain_soft

    with pytest.raises(TypeError):
        call_brain_soft("current_truth", {})  # missing required kw-only `timeout`


def test_timeout_cannot_be_passed_positionally():
    from campy.brain_transport import call_brain_soft

    with pytest.raises(TypeError):
        call_brain_soft("current_truth", {}, 1.0)  # positional timeout must fail


def test_call_brain_soft_never_raises_even_with_bad_params(tmp_path, monkeypatch):
    """Defense in depth: even a wildly malformed call degrades, doesn't raise."""
    import asyncio

    from campy.brain_transport import call_brain_soft

    monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(tmp_path / "nope.sock"))
    monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

    result = asyncio.run(call_brain_soft("not_a_real_method", {"whatever": 1}, timeout=0.5))
    assert result is None  # default default


# ---------------------------------------------------------------------------
# Audit list — every implicit-path caller must use call_brain_soft, not the
# raising call_brain(). Regex requires a word boundary before "call_brain("
# so it does not false-positive on "_call_brain(" (the local wrapper name)
# or "call_brain_soft(" itself.
# ---------------------------------------------------------------------------
AUDIT_LIST = [
    "campy/brain/thalamus/ask.py",
    "campy/cli/notify_turn_cmd.py",
    "campy/adapters/mcp_server.py",
    "campy/adapters/claude_desktop/adapter.py",
    "adapters/claude_code/adapter.py",
    "adapters/claude_code/hook_user_turn.py",
    "adapters/gemini_cli/adapter.py",
    "adapters/codex/adapter.py",
    "adapters/claude_desktop/adapter.py",
    "adapters/chatgpt_desktop/adapter.py",
]

_BARE_CALL_BRAIN_RE = re.compile(r"\bcall_brain\(")


def test_audit_list_files_exist():
    """Guards against the audit list silently drifting from the tree."""
    missing = [rel for rel in AUDIT_LIST if not (REPO_ROOT / rel).exists()]
    assert not missing, f"audit-list files missing from tree: {missing}"


@pytest.mark.parametrize("rel_path", AUDIT_LIST)
def test_audit_list_caller_uses_call_brain_soft_not_call_brain(rel_path):
    """Every implicit-path caller in B318's audit list must not call the
    raising call_brain() directly — only call_brain_soft(). This is a grep
    test on purpose: it cannot regress silently the way a mock-based test
    could."""
    path = REPO_ROOT / rel_path
    text = path.read_text(encoding="utf-8")

    offenders = _BARE_CALL_BRAIN_RE.findall(text)
    assert not offenders, f"{rel_path}: found bare call_brain(...) — should be call_brain_soft(...)"

    # And it must actually reference call_brain_soft somewhere (not just
    # avoid the raising call — it should be doing the fail-open thing).
    assert "call_brain_soft" in text, f"{rel_path}: does not use call_brain_soft at all"


def test_hook_shell_scripts_reference_call_brain_soft_not_call_brain():
    """Same audit, for the .sh hook that embeds Python (not a .py import
    site, so it's outside AUDIT_LIST's grep but still in scope)."""
    path = REPO_ROOT / "adapters/claude_code/hooks/post_tool_use.sh"
    text = path.read_text(encoding="utf-8")

    offenders = _BARE_CALL_BRAIN_RE.findall(text)
    assert not offenders, f"post_tool_use.sh: found bare call_brain(...) — should be call_brain_soft(...)"
    assert "call_brain_soft" in text


# ---------------------------------------------------------------------------
# Explicit CLI paths still hard-fail with a clear error.
# ---------------------------------------------------------------------------
def test_explicit_ask_cli_reports_failure_not_empty_answer(monkeypatch):
    """`campy ask` must surface a clear error when the underlying memory
    store is unavailable — never silently print an empty/fabricated answer.
    This is the exemption: a human explicitly asked and is waiting."""
    from typer.testing import CliRunner

    from campy.cli.main import app
    import campy.brain.hippocampus.graph.kuzu_client as kuzu_mod

    class _BoomClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("DAEMON_OFFLINE: no daemon reachable")

    monkeypatch.setattr(kuzu_mod, "KuzuClient", _BoomClient)

    runner = CliRunner()
    result = runner.invoke(app, ["ask", "what did we decide about auth?"])

    assert result.exit_code != 0
    assert "Error" in result.output
    assert "DAEMON_OFFLINE" in result.output


def test_call_brain_still_raises_for_explicit_paths(tmp_path, monkeypatch):
    """call_brain() (used by explicit CLI paths) keeps its raising contract
    — B318 only adds call_brain_soft() alongside it, it does not change
    call_brain()'s behavior."""
    import asyncio

    from campy.brain_transport import call_brain

    monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(tmp_path / "nope.sock"))
    monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

    with pytest.raises(RuntimeError):
        asyncio.run(call_brain("current_truth", {}, timeout=1.0))


# ---------------------------------------------------------------------------
# Hook scripts: exit 0 with the daemon down, and stay within budget.
# ---------------------------------------------------------------------------
def test_plugin_pre_tool_use_hook_exits_zero_with_empty_valid_output(tmp_path, monkeypatch):
    """No daemon calls in this hook at all (pure local manifest matching);
    it must still exit 0 and produce empty-but-valid output with no
    manifest / no daemon present."""
    env = dict(os.environ)
    env["CAMPY_TRIGGER_MANIFEST"] = str(tmp_path / "does-not-exist-manifest.json")
    env.pop("CLAUDE_TOOL_INPUT", None)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "plugin" / "hooks" / "pre_tool_use.sh")],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_claude_code_post_tool_use_hook_exits_zero_and_stays_under_budget_against_stalled_daemon(
    tmp_path,
):
    """B318 acceptance criterion: the per-tool-call hook path completes in
    under 1.5s wall-clock against a stalled daemon (HOOK_TIMEOUT 1.0s +
    overhead), measured against a real stub server that accepts and stalls
    — and always exits 0."""
    sock_path = tmp_path / "brain.sock"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"triggers": []}))

    md_file = tmp_path / "note.md"
    md_file.write_text(
        "# A Work Artifact\n\nThis is a long enough summary line for extraction.\n"
    )

    env = dict(os.environ)
    for var in _BRAIN_ENV_VARS:
        env.pop(var, None)
    env["CAMPY_TRIGGER_MANIFEST"] = str(manifest_path)
    env["CLAUDE_TOOL_NAME"] = "Write"
    env["CLAUDE_SESSION_ID"] = "test-session"
    env["CAMPY_BRAIN_SOCKET"] = str(sock_path)
    env["CAMPY_BRAIN_URL"] = _REFUSED_HTTP_URL
    env["PATH"] = str(REPO_ROOT / ".venv" / "bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    with unix_stub_server(sock_path, stall=True):
        started = time.monotonic()
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "adapters" / "claude_code" / "hooks" / "post_tool_use.sh")],
            input=str(md_file),
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(REPO_ROOT),
            env=env,
        )
        elapsed = time.monotonic() - started

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert elapsed < 1.5, f"hook took {elapsed:.2f}s against a stalled daemon; stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# campy doctor reports consecutive soft-failure count.
# ---------------------------------------------------------------------------
def test_doctor_reports_zero_soft_failures_by_default(tmp_path, monkeypatch):
    from pathlib import Path as _Path

    monkeypatch.setattr(_Path, "home", lambda: tmp_path)

    from campy.cli.doctor import DoctorChecker

    checker = DoctorChecker()
    checker._check_fail_open_state()

    name, passed, message = next(c for c in checker.checks if c[0] == "Fail-Open State")
    assert passed is True
    assert "0 consecutive soft failures" in message


def test_doctor_reports_consecutive_soft_failure_count_after_degraded_calls(
    tmp_path, monkeypatch
):
    from pathlib import Path as _Path

    monkeypatch.setattr(_Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(tmp_path / "nope.sock"))
    monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

    import asyncio

    from campy.brain_transport import call_brain_soft
    from campy.cli.doctor import DoctorChecker

    asyncio.run(call_brain_soft("current_truth", {}, timeout=0.5))
    asyncio.run(call_brain_soft("current_truth", {}, timeout=0.5))
    asyncio.run(call_brain_soft("current_truth", {}, timeout=0.5))

    checker = DoctorChecker()
    checker._check_fail_open_state()

    name, passed, message = next(c for c in checker.checks if c[0] == "Fail-Open State")
    # Informational only — must never fail the overall doctor check.
    assert passed is True
    assert "3 consecutive soft failure" in message


def test_soft_failure_counter_resets_on_success(tmp_path, monkeypatch):
    from pathlib import Path as _Path

    monkeypatch.setattr(_Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(tmp_path / "nope.sock"))
    monkeypatch.setenv("CAMPY_BRAIN_URL", _REFUSED_HTTP_URL)

    import asyncio

    from campy.brain_transport import call_brain_soft, read_soft_failure_state

    asyncio.run(call_brain_soft("current_truth", {}, timeout=0.5))
    assert read_soft_failure_state()["consecutive_failures"] == 1

    sock_path = tmp_path / "ok.sock"
    monkeypatch.setenv("CAMPY_BRAIN_SOCKET", str(sock_path))
    ok_response = (
        json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"status": "ok"}}) + "\n"
    ).encode()
    with unix_stub_server(sock_path, response=ok_response):
        asyncio.run(call_brain_soft("current_truth", {}, timeout=1.0))

    assert read_soft_failure_state()["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# Never-surfaced-to-agent-context guard (spec, not a runtime behavior to
# probe): degraded state must not appear in SYSTEM_PROMPT_FRAGMENT / the
# OFFLINE_FRAGMENT shown to agents — those already say "OFFLINE", not a
# soft-failure count, and this test pins that.
# ---------------------------------------------------------------------------
def test_offline_fragment_does_not_leak_soft_failure_bookkeeping():
    path = REPO_ROOT / "adapters" / "claude_code" / "adapter.py"
    text = path.read_text(encoding="utf-8")
    assert "consecutive_failures" not in text
    assert "read_soft_failure_state" not in text
