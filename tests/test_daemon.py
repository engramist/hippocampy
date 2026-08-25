"""
Tests for brain_daemon.py — T3 coverage.
Tests _handle_connection JSON-RPC parsing, _dispatch routing,
and _loop_worker error handling.
"""

from __future__ import annotations
import asyncio
import json
import sys
import os
import types
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Stub out kuzu and uvicorn (not installed in test env)
# ---------------------------------------------------------------------------

def _stub_module(name):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    return sys.modules[name]

def _setup_stubs():
    # kuzu is not installed in the test environment — stub it out.
    # Do NOT stub uvicorn (it is installed and must be importable normally).
    if "kuzu" not in sys.modules:
        kuzu_mod = types.ModuleType("kuzu")
        class _DB:
            def __init__(self, *a, **kw): pass
        class _Conn:
            def __init__(self, *a, **kw): pass
            def execute(self, *a, **kw): return None
        kuzu_mod.Database = _DB
        kuzu_mod.Connection = _Conn
        sys.modules["kuzu"] = kuzu_mod

_setup_stubs()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daemon():
    """Construct a BrainDaemon with a minimal mock config and DB."""
    from brain_daemon import BrainDaemon

    class MockDB:
        def close(self): pass

    config = {
        "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
        "llm":        {"provider": "ollama", "model": "llama3.1:8b"},
        "pruning":    {"sweep_interval_seconds": 300},
        "web":        {"port": 7799},
    }

    daemon = BrainDaemon.__new__(BrainDaemon)
    daemon.config      = config
    daemon.db          = MockDB()
    daemon.running     = False
    daemon._llm_client = None
    daemon._centroids  = {}
    daemon._loop_queue = asyncio.Queue()
    return daemon


# ---------------------------------------------------------------------------
# _dispatch — JSON-RPC routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_unknown_method_returns_error():
    """_dispatch returns JSON-RPC -32601 for unknown method."""
    daemon = _make_daemon()
    response = await daemon._dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "nonexistent_method", "params": {}
    })
    assert "error" in response
    assert response["error"]["code"] == -32601
    assert response["id"] == 1


@pytest.mark.asyncio
async def test_dispatch_known_method_routes_to_handler(monkeypatch):
    """_dispatch calls the registered handler for a known method."""
    from campy.brain.thalamus.tools import TOOL_HANDLERS
    daemon = _make_daemon()

    called_with = {}

    async def fake_handler(params, db, config):
        called_with["params"] = params
        called_with["db"]     = db
        return {"status": "ok"}

    monkeypatch.setitem(TOOL_HANDLERS, "test_method", fake_handler)

    response = await daemon._dispatch({
        "jsonrpc": "2.0", "id": 5, "method": "test_method", "params": {"x": 1}
    })
    assert response["result"] == {"status": "ok"}
    assert response["id"] == 5
    assert called_with["params"] == {"x": 1}


@pytest.mark.asyncio
async def test_dispatch_handler_exception_returns_error(monkeypatch):
    """_dispatch wraps handler exceptions in -32000 JSON-RPC error."""
    from campy.brain.thalamus.tools import TOOL_HANDLERS
    daemon = _make_daemon()

    async def exploding_handler(params, db, config):
        raise ValueError("something went wrong")

    monkeypatch.setitem(TOOL_HANDLERS, "boom_method", exploding_handler)

    response = await daemon._dispatch({
        "jsonrpc": "2.0", "id": 9, "method": "boom_method", "params": {}
    })
    assert "error" in response
    assert response["error"]["code"] == -32000
    assert "something went wrong" in response["error"]["message"]


@pytest.mark.asyncio
async def test_dispatch_preserves_request_id():
    """_dispatch echoes back the request id in every response."""
    daemon = _make_daemon()
    for req_id in [1, "abc", None, 42]:
        response = await daemon._dispatch({
            "jsonrpc": "2.0", "id": req_id, "method": "nonexistent", "params": {}
        })
        assert response["id"] == req_id


# ---------------------------------------------------------------------------
# _handle_connection — JSON-RPC parsing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_connection_parse_error():
    """Malformed JSON returns parse error (-32700) without crashing."""
    daemon = _make_daemon()

    written = []

    class FakeWriter:
        def write(self, data): written.append(data)
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): pass

    async def fake_readline():
        return b"not valid json\n"

    reads = [b"not valid json\n", b""]  # second read returns EOF

    class FakeReader:
        _idx = 0
        async def readline(self):
            line = reads[FakeReader._idx]
            FakeReader._idx += 1
            return line

    await daemon._handle_connection(FakeReader(), FakeWriter())

    assert len(written) >= 1
    response = json.loads(written[0].decode())
    assert "error" in response
    assert response["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_handle_connection_valid_request_dispatched():
    """Valid JSON-RPC over the connection is dispatched and response sent."""
    from campy.brain.thalamus.tools import TOOL_HANDLERS
    daemon = _make_daemon()

    async def echo_handler(params, db, config):
        return {"echo": params.get("msg")}

    TOOL_HANDLERS["echo_test"] = echo_handler

    written = []

    class FakeWriter:
        def write(self, data): written.append(data)
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): pass

    request_line = json.dumps({
        "jsonrpc": "2.0", "id": 7, "method": "echo_test",
        "params": {"msg": "hello"}
    }).encode() + b"\n"

    reads = [request_line, b""]

    class FakeReader:
        _idx = 0
        async def readline(self):
            line = reads[FakeReader._idx]
            FakeReader._idx += 1
            return line

    try:
        await daemon._handle_connection(FakeReader(), FakeWriter())
    finally:
        TOOL_HANDLERS.pop("echo_test", None)

    assert len(written) >= 1
    response = json.loads(written[0].decode())
    assert response["result"]["echo"] == "hello"
    assert response["id"] == 7


@pytest.mark.asyncio
async def test_handle_connection_survives_reset_on_drain():
    """B362: a client that disconnects while a response is in flight must not
    produce an unhandled exception -- writer.drain() raising ConnectionResetError
    should end the connection cleanly, not propagate."""
    daemon = _make_daemon()

    class FakeWriter:
        def write(self, data): pass
        async def drain(self): raise ConnectionResetError("Connection lost")
        def close(self): pass
        async def wait_closed(self): pass

    request_line = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "context_status", "params": {}
    }).encode() + b"\n"

    reads = [request_line, b""]

    class FakeReader:
        _idx = 0
        async def readline(self):
            line = reads[FakeReader._idx]
            FakeReader._idx += 1
            return line

    # Must return normally -- no exception should escape.
    await daemon._handle_connection(FakeReader(), FakeWriter())


@pytest.mark.asyncio
async def test_handle_connection_survives_broken_pipe_on_close():
    """B362: the cleanup path's writer.close()/wait_closed() can also raise on
    an already-broken socket -- that must not propagate either."""
    daemon = _make_daemon()

    class FakeWriter:
        def write(self, data): pass
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): raise BrokenPipeError("Broken pipe")

    request_line = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "context_status", "params": {}
    }).encode() + b"\n"

    reads = [request_line, b""]

    class FakeReader:
        _idx = 0
        async def readline(self):
            line = reads[FakeReader._idx]
            FakeReader._idx += 1
            return line

    # Must return normally -- no exception should escape.
    await daemon._handle_connection(FakeReader(), FakeWriter())


# ---------------------------------------------------------------------------
# _loop_worker — error isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_worker_continues_after_error(monkeypatch):
    """One bad message does not kill the loop worker — next message still processed."""
    daemon = _make_daemon()

    processed = []

    async def mock_run_loop(message_id, text, db, llm_client, config, centroids, role="user", session_id="unknown", precomputed=None):
        if text == "bad":
            raise RuntimeError("simulated loop failure")
        processed.append(message_id)
        return {
            "entities_found": 0, "relations_found": 0,
            "concepts_stored": 0, "noise_count": 0,
        }

    import campy.brain.temporal_lobe.loop.orchestrator as orch_module
    monkeypatch.setattr(orch_module, "run_loop", mock_run_loop)

    # Use run_loop from brain_daemon import
    import brain_daemon as bd_module
    monkeypatch.setattr(bd_module, "run_loop", mock_run_loop)

    # Enqueue bad message then good message (5-tuples: message_id, text, role, session_id, precomputed)
    await daemon._loop_queue.put(("msg-bad", "bad", "user", "s1", None))
    await daemon._loop_queue.put(("msg-good", "good text", "user", "s1", None))

    # Run worker in background task, cancel it after both messages processed
    task = asyncio.create_task(daemon._loop_worker())
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert "msg-good" in processed


# ---------------------------------------------------------------------------
# _periodic_restart — B342 fragmentation-mitigation self-restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_periodic_restart_calls_shutdown_after_interval(monkeypatch):
    """B342: after the configured interval (+/- jitter), the task calls
    self.shutdown() so launchd's KeepAlive can bring up a fresh process."""
    daemon = _make_daemon()

    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    # 0.0001h = 0.36s, plus up to +/-10% jitter -- still fast for a unit test.
    await daemon._periodic_restart(0.0001)

    assert shutdown_calls == [True]


@pytest.mark.asyncio
async def test_periodic_restart_applies_jitter(monkeypatch):
    """B342: actual delay should vary run to run within the documented
    +/-10% jitter band, not fire at exactly the nominal interval every time."""
    daemon = _make_daemon()
    monkeypatch.setattr(daemon, "shutdown", lambda: None)

    interval_hours = 0.0001
    nominal_seconds = interval_hours * 3600

    observed = []
    real_sleep = asyncio.sleep

    async def spy_sleep(delay):
        observed.append(delay)
        await real_sleep(0)  # don't actually wait in the test

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    await daemon._periodic_restart(interval_hours)

    assert len(observed) == 1
    delay = observed[0]
    assert nominal_seconds * 0.9 <= delay <= nominal_seconds * 1.1


# ---------------------------------------------------------------------------
# _periodic_footprint_watchdog — B354 footprint/swap-aware safety net
# ---------------------------------------------------------------------------

def _vmmap_ok(footprint_mb):
    return {
        "footprint_mb": footprint_mb, "footprint_raw": f"{footprint_mb}M",
        "small_resident": None, "small_swapped": None, "error": None,
    }


def _vmmap_fail(error="vmmap unavailable"):
    return {
        "footprint_mb": None, "footprint_raw": None,
        "small_resident": None, "small_swapped": None, "error": error,
    }


def _fake_vmmap_sequence(values):
    """Yields each dict in `values` in order, then keeps repeating the last
    one -- so a test doesn't need to size the sequence exactly to how many
    checks the loop performs before it returns or is cancelled."""
    it = iter(values)
    state = {"last": values[0] if values else _vmmap_fail("sequence exhausted")}

    def _fake(pid=None):
        try:
            state["last"] = next(it)
        except StopIteration:
            pass
        return state["last"]

    return _fake


@pytest.mark.asyncio
async def test_footprint_watchdog_no_breach_never_restarts(monkeypatch):
    """B354: footprint staying within threshold of baseline never triggers
    a restart."""
    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    import brain_daemon as bd_module
    fake = _fake_vmmap_sequence([_vmmap_ok(200), _vmmap_ok(210), _vmmap_ok(220), _vmmap_ok(215)])
    monkeypatch.setattr(bd_module, "_vmmap_parsed", fake)

    task = asyncio.create_task(
        daemon._periodic_footprint_watchdog(
            check_interval_seconds=0.01, growth_threshold_mb=500, consecutive_breaches_required=3
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert shutdown_calls == []


@pytest.mark.asyncio
async def test_footprint_watchdog_single_breach_resets_and_does_not_trigger(monkeypatch):
    """B354: a breach that doesn't repeat on the next check does not
    trigger a restart -- debounce must reset on a non-breaching check."""
    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    import brain_daemon as bd_module
    # baseline=100; one breach at 700 (+600 > 500 threshold), then back
    # under (150, +50) for the rest of the run.
    fake = _fake_vmmap_sequence([_vmmap_ok(100), _vmmap_ok(700), _vmmap_ok(150), _vmmap_ok(150)])
    monkeypatch.setattr(bd_module, "_vmmap_parsed", fake)

    task = asyncio.create_task(
        daemon._periodic_footprint_watchdog(
            check_interval_seconds=0.01, growth_threshold_mb=500, consecutive_breaches_required=3
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert shutdown_calls == []


@pytest.mark.asyncio
async def test_footprint_watchdog_consecutive_breaches_trigger_restart(monkeypatch):
    """B354: N consecutive breaches (not just one) call shutdown exactly
    once, and the task returns on its own without needing cancellation."""
    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    import brain_daemon as bd_module
    # baseline=100; three consecutive breaches, all well above the threshold.
    fake = _fake_vmmap_sequence([_vmmap_ok(100), _vmmap_ok(700), _vmmap_ok(710), _vmmap_ok(720)])
    monkeypatch.setattr(bd_module, "_vmmap_parsed", fake)

    await asyncio.wait_for(
        daemon._periodic_footprint_watchdog(
            check_interval_seconds=0.01, growth_threshold_mb=500, consecutive_breaches_required=3
        ),
        timeout=2.0,
    )

    assert shutdown_calls == [True]


@pytest.mark.asyncio
async def test_footprint_watchdog_baseline_failure_disables_watchdog(monkeypatch):
    """B354: if a startup baseline can't be established, the watchdog
    returns quietly instead of looping or crashing -- _periodic_restart
    keeps running regardless, this task just becomes a no-op."""
    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    import brain_daemon as bd_module
    fake = _fake_vmmap_sequence([_vmmap_fail("vmmap not found")])
    monkeypatch.setattr(bd_module, "_vmmap_parsed", fake)

    await asyncio.wait_for(
        daemon._periodic_footprint_watchdog(
            check_interval_seconds=0.01, growth_threshold_mb=500, consecutive_breaches_required=3
        ),
        timeout=1.0,
    )

    assert shutdown_calls == []


@pytest.mark.asyncio
async def test_footprint_watchdog_transient_check_failure_is_skipped_not_fatal(monkeypatch):
    """B354: a single failed vmmap check mid-run is skipped -- neither
    counted as a breach nor allowed to reset an in-progress breach streak
    -- and breach counting resumes normally on the next successful check."""
    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    import brain_daemon as bd_module
    # baseline=100; breach, a transient vmmap failure in between, then two
    # more breaches -> 3 real breaches recorded, restart fires despite the
    # failure sitting in the middle of the streak.
    fake = _fake_vmmap_sequence([
        _vmmap_ok(100), _vmmap_ok(700), _vmmap_fail("transient"), _vmmap_ok(710), _vmmap_ok(720),
    ])
    monkeypatch.setattr(bd_module, "_vmmap_parsed", fake)

    await asyncio.wait_for(
        daemon._periodic_footprint_watchdog(
            check_interval_seconds=0.01, growth_threshold_mb=500, consecutive_breaches_required=3
        ),
        timeout=2.0,
    )

    assert shutdown_calls == [True]
