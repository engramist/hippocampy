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
    from mcp_engine.tools import TOOL_HANDLERS
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
    from mcp_engine.tools import TOOL_HANDLERS
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
    from mcp_engine.tools import TOOL_HANDLERS
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


# ---------------------------------------------------------------------------
# _loop_worker — error isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_worker_continues_after_error(monkeypatch):
    """One bad message does not kill the loop worker — next message still processed."""
    daemon = _make_daemon()

    processed = []

    async def mock_run_loop(message_id, text, db, llm_client, config, centroids, role="user", session_id="unknown"):
        if text == "bad":
            raise RuntimeError("simulated loop failure")
        processed.append(message_id)
        return {
            "entities_found": 0, "relations_found": 0,
            "concepts_stored": 0, "noise_count": 0,
        }

    import mcp_engine.loop.orchestrator as orch_module
    monkeypatch.setattr(orch_module, "run_loop", mock_run_loop)

    # Use run_loop from brain_daemon import
    import brain_daemon as bd_module
    monkeypatch.setattr(bd_module, "run_loop", mock_run_loop)

    # Enqueue bad message then good message (4-tuples: message_id, text, role, session_id)
    await daemon._loop_queue.put(("msg-bad", "bad", "user", "s1"))
    await daemon._loop_queue.put(("msg-good", "good text", "user", "s1"))

    # Run worker in background task, cancel it after both messages processed
    task = asyncio.create_task(daemon._loop_worker())
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert "msg-good" in processed
