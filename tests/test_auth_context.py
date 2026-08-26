"""
tests/test_auth_context.py — B315: Principal derivation and threading.

Three layers, matching the card's acceptance criteria:

  1. Pure-function tests for `campy.brain.auth` — Principal.require(),
     TransportContext's structural no-request-params guarantee,
     LocalSingleUserResolver, and a fake non-local resolver proving the
     PrincipalResolver seam works for a non-local tenant.
  2. `campy.brain_daemon.BrainDaemon._dispatch` tests — the forbidden-key
     guard (every key in FORBIDDEN_PARAM_KEYS, individually), the WARNING
     log, and both directions of `_WANTS_PRINCIPAL` threading (a handler
     that opts in receives `principal`; one that does not still works
     unchanged).
  3. One real-Kùzu integration test proving `upsert_lesson` attributes a
     written Lesson's `source` to a non-local principal's
     "<client>:<subject_id>" — the same pattern
     tests/test_idempotent_writes.py uses for lessons.py.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from campy.brain.auth import (
    FORBIDDEN_PARAM_KEYS,
    KNOWN_SCOPES,
    LocalSingleUserResolver,
    Principal,
    TransportContext,
    TRANSPORT_CONTEXT_FIELDS,
)

# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


def _make_principal(**overrides) -> Principal:
    fields = dict(
        subject_id="u1", tenant_id="t1", workspace_id="w1",
        scopes=frozenset({"memory.read"}), client="test-client",
        session_id=None, derived_from="test",
    )
    fields.update(overrides)
    return Principal(**fields)


def test_require_raises_permission_error_for_missing_scope():
    p = _make_principal(scopes=frozenset({"memory.read"}))
    with pytest.raises(PermissionError):
        p.require("memory.write")


def test_require_returns_none_when_scope_held():
    p = _make_principal(scopes=frozenset({"memory.read", "memory.write"}))
    assert p.require("memory.write") is None


def test_principal_is_frozen():
    p = _make_principal()
    with pytest.raises(Exception):
        p.tenant_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TransportContext — structural guarantee: no request-param-shaped field
# ---------------------------------------------------------------------------


def test_transport_context_has_no_request_param_fields():
    ctx = TransportContext(transport="unix-socket", peer_credential="unix:3")
    assert TRANSPORT_CONTEXT_FIELDS == {"transport", "peer_credential", "headers"}
    # None of the forbidden principal-shaped keys leak in as a field name.
    assert not (TRANSPORT_CONTEXT_FIELDS & FORBIDDEN_PARAM_KEYS)
    assert "params" not in TRANSPORT_CONTEXT_FIELDS
    assert ctx.transport == "unix-socket"


def test_transport_context_defaults_have_no_params_leak():
    ctx = TransportContext(transport="http")
    assert ctx.peer_credential is None
    assert ctx.headers is None


# ---------------------------------------------------------------------------
# LocalSingleUserResolver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_resolver_returns_real_principal_not_none():
    resolver = LocalSingleUserResolver()
    principal = await resolver.resolve(TransportContext(transport="unix-socket"))
    assert principal is not None
    assert isinstance(principal, Principal)
    assert principal.tenant_id == "local"
    assert principal.workspace_id == "local"
    assert principal.derived_from == "local-single-user"
    assert principal.scopes == KNOWN_SCOPES


@pytest.mark.asyncio
async def test_local_resolver_principal_holds_every_known_scope():
    resolver = LocalSingleUserResolver()
    principal = await resolver.resolve(TransportContext(transport="unix-socket"))
    for scope in KNOWN_SCOPES:
        assert principal.require(scope) is None  # does not raise


# ---------------------------------------------------------------------------
# Fake non-local resolver — proves the PrincipalResolver seam works for a
# tenant other than "local" without building a real cloud resolver.
# ---------------------------------------------------------------------------


class _FakeCloudResolver:
    """Stands in for B325's IAMPrincipalResolver in tests that only need
    to prove the *seam* — that a resolver other than LocalSingleUserResolver
    can produce a Principal with a different tenant/workspace, and that
    the rest of the system (dispatch, capture) treats it identically."""

    async def resolve(self, transport_ctx: TransportContext) -> Principal:
        return Principal(
            subject_id="svc-account-123",
            tenant_id="acme-corp",
            workspace_id="acme-prod",
            scopes=KNOWN_SCOPES,
            client="agentcore",
            session_id=None,
            derived_from="fake-cloud",
        )


@pytest.mark.asyncio
async def test_fake_cloud_resolver_yields_different_tenant():
    resolver = _FakeCloudResolver()
    principal = await resolver.resolve(TransportContext(transport="http"))
    assert principal.tenant_id != "local"
    assert principal.tenant_id == "acme-corp"
    assert principal.workspace_id == "acme-prod"
    assert principal.derived_from != "local-single-user"


# ---------------------------------------------------------------------------
# BrainDaemon._dispatch — forbidden-key guard + principal threading
# ---------------------------------------------------------------------------


def _make_daemon():
    """Construct a campy.brain_daemon.BrainDaemon without opening a real DB
    or starting the event loop machinery — same `__new__` + manual attribute
    pattern tests/test_daemon.py uses for the legacy root brain_daemon.py."""
    from campy.brain_daemon import BrainDaemon

    class MockDB:
        def close(self):
            pass

    daemon = BrainDaemon.__new__(BrainDaemon)
    daemon.config = {}
    daemon.db = MockDB()
    daemon.running = False
    daemon._llm_client = None
    daemon._centroids = {}
    daemon._loop_queue = None
    daemon._principal_resolver = LocalSingleUserResolver()
    daemon._router = None  # B316: falls back to self.db, matching pre-B316 behavior
    return daemon


@pytest.mark.parametrize("key", sorted(FORBIDDEN_PARAM_KEYS))
@pytest.mark.asyncio
async def test_dispatch_rejects_every_forbidden_param_key(key, monkeypatch, caplog):
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    principal = await daemon._principal_resolver.resolve(TransportContext(transport="unix-socket"))

    called = {"ran": False}

    async def handler(params, db, config):
        called["ran"] = True
        return {"should": "not run"}

    monkeypatch.setitem(bd.TOOL_HANDLERS, "guarded_test_method", handler)

    with caplog.at_level(logging.WARNING):
        response = await daemon._dispatch(
            {"jsonrpc": "2.0", "id": 3, "method": "guarded_test_method",
             "params": {key: "forged-value"}},
            principal,
        )

    assert "error" in response
    assert response["error"]["code"] == -32602
    assert key in response["error"]["message"]
    assert called["ran"] is False, "handler must never run when a forbidden key is present"
    assert any(
        key in record.getMessage() and principal.subject_id in record.getMessage()
        for record in caplog.records if record.levelno == logging.WARNING
    ), "rejection must be logged at WARNING with the subject_id"


@pytest.mark.asyncio
async def test_dispatch_allows_request_without_forbidden_keys(monkeypatch):
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    principal = await daemon._principal_resolver.resolve(TransportContext(transport="unix-socket"))

    async def handler(params, db, config):
        return {"ok": True, "params": params}

    monkeypatch.setitem(bd.TOOL_HANDLERS, "clean_test_method", handler)

    response = await daemon._dispatch(
        {"jsonrpc": "2.0", "id": 4, "method": "clean_test_method",
         "params": {"text": "hello"}},
        principal,
    )
    assert response["result"] == {"ok": True, "params": {"text": "hello"}}


@pytest.mark.asyncio
async def test_dispatch_threads_principal_to_opted_in_handler(monkeypatch):
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    principal = await daemon._principal_resolver.resolve(TransportContext(transport="unix-socket"))

    received = {}

    async def wants_principal(params, db, config, *, principal):
        received["principal"] = principal
        return {"ok": True}

    monkeypatch.setitem(bd.TOOL_HANDLERS, "wants_principal_test_method", wants_principal)
    monkeypatch.setattr(
        bd, "_WANTS_PRINCIPAL", bd._WANTS_PRINCIPAL | {"wants_principal_test_method"}
    )

    response = await daemon._dispatch(
        {"jsonrpc": "2.0", "id": 5, "method": "wants_principal_test_method", "params": {}},
        principal,
    )
    assert response["result"] == {"ok": True}
    assert received["principal"] is principal


@pytest.mark.asyncio
async def test_dispatch_handler_without_principal_still_works_unchanged(monkeypatch):
    """Regression guard for the ~57 handlers that have not adopted `principal`
    yet — _dispatch must call them exactly as it did before this card."""
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    principal = await daemon._principal_resolver.resolve(TransportContext(transport="unix-socket"))

    async def no_principal_handler(params, db, config):
        return {"echo": params.get("msg")}

    monkeypatch.setitem(bd.TOOL_HANDLERS, "no_principal_test_method", no_principal_handler)
    assert "no_principal_test_method" not in bd._WANTS_PRINCIPAL

    response = await daemon._dispatch(
        {"jsonrpc": "2.0", "id": 6, "method": "no_principal_test_method",
         "params": {"msg": "hi"}},
        principal,
    )
    assert response["result"] == {"echo": "hi"}


@pytest.mark.asyncio
async def test_dispatch_unknown_method_still_returns_error_with_principal():
    daemon = _make_daemon()
    principal = await daemon._principal_resolver.resolve(TransportContext(transport="unix-socket"))
    response = await daemon._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "nonexistent_method", "params": {}},
        principal,
    )
    assert response["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# BrainDaemon._handle_connection — B362 connection-reset handling.
#
# The fix originally landed on the wrong file (the legacy root
# brain_daemon.py, dead code per this module's own `_make_daemon()`
# docstring — not what `campy-daemon` actually ships/runs). Re-landed here,
# on the real module, with the same regression coverage.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_connection_survives_reset_on_drain():
    """B362: a client that disconnects while a response is in flight must not
    produce an unhandled exception -- writer.drain() raising ConnectionResetError
    should end the connection cleanly, not propagate."""
    import json as _json

    daemon = _make_daemon()

    class FakeWriter:
        def write(self, data): pass
        async def drain(self): raise ConnectionResetError("Connection lost")
        def close(self): pass
        async def wait_closed(self): pass
        def get_extra_info(self, name): return None

    request_line = _json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
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
    import json as _json

    daemon = _make_daemon()

    class FakeWriter:
        def write(self, data): pass
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): raise BrokenPipeError("Broken pipe")
        def get_extra_info(self, name): return None

    request_line = _json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
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
# BrainDaemon._periodic_footprint_watchdog — B354, ported from the root
# brain_daemon.py (which never shipped) as part of B365's reconciliation.
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
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    fake = _fake_vmmap_sequence([_vmmap_ok(200), _vmmap_ok(210), _vmmap_ok(220), _vmmap_ok(215)])
    monkeypatch.setattr(bd, "_vmmap_parsed", fake)

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
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    # baseline=100; one breach at 700 (+600 > 500 threshold), then back
    # under (150, +50) for the rest of the run.
    fake = _fake_vmmap_sequence([_vmmap_ok(100), _vmmap_ok(700), _vmmap_ok(150), _vmmap_ok(150)])
    monkeypatch.setattr(bd, "_vmmap_parsed", fake)

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
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    # baseline=100; three consecutive breaches, all well above the threshold.
    fake = _fake_vmmap_sequence([_vmmap_ok(100), _vmmap_ok(700), _vmmap_ok(710), _vmmap_ok(720)])
    monkeypatch.setattr(bd, "_vmmap_parsed", fake)

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
    returns quietly instead of looping or crashing."""
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    fake = _fake_vmmap_sequence([_vmmap_fail("vmmap not found")])
    monkeypatch.setattr(bd, "_vmmap_parsed", fake)

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
    import campy.brain_daemon as bd

    daemon = _make_daemon()
    shutdown_calls = []
    monkeypatch.setattr(daemon, "shutdown", lambda: shutdown_calls.append(True))

    # baseline=100; breach, a transient vmmap failure in between, then two
    # more breaches -> 3 real breaches recorded, restart fires despite the
    # failure sitting in the middle of the streak.
    fake = _fake_vmmap_sequence([
        _vmmap_ok(100), _vmmap_ok(700), _vmmap_fail("transient"), _vmmap_ok(710), _vmmap_ok(720),
    ])
    monkeypatch.setattr(bd, "_vmmap_parsed", fake)

    await asyncio.wait_for(
        daemon._periodic_footprint_watchdog(
            check_interval_seconds=0.01, growth_threshold_mb=500, consecutive_breaches_required=3
        ),
        timeout=2.0,
    )

    assert shutdown_calls == [True]


# ---------------------------------------------------------------------------
# Real-Kùzu integration: upsert_lesson attributes source to a non-local
# principal. Same pattern as tests/test_idempotent_writes.py.
# ---------------------------------------------------------------------------

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CONFIG = {"embeddings": {"model": EMBEDDING_MODEL}}
_FAKE_VEC = [0.02] * 384


@pytest.fixture(scope="module", autouse=True)
def _patch_embed_for_module():
    from campy.brain.hippocampus import schema as _schema_mod
    from campy.brain.thalamus.tools import lessons as _lessons_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    originals = {
        "schema_embed": _schema_mod.emb.embed,
        "schema_embed_batch": _schema_mod.emb.embed_batch,
        "lessons_embed": _lessons_mod.emb.embed,
    }
    _schema_mod.emb.embed = _fake_embed
    _schema_mod.emb.embed_batch = _fake_embed_batch
    _lessons_mod.emb.embed = _fake_embed
    try:
        yield
    finally:
        _schema_mod.emb.embed = originals["schema_embed"]
        _schema_mod.emb.embed_batch = originals["schema_embed_batch"]
        _lessons_mod.emb.embed = originals["lessons_embed"]


@pytest.fixture(scope="module")
def db(tmp_path_factory, _patch_embed_for_module):
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.hippocampus.schema import init_schema

    path = tmp_path_factory.mktemp("b315_auth") / "b315.db"
    client = KuzuClient(str(path))
    init_schema(client, SEED_PATH, EMBEDDING_MODEL)
    return client


def _lesson_source(db, lesson_id: str) -> str | None:
    r = db.execute(
        "MATCH (l:Lesson {lesson_id: $id}) RETURN l.source", {"id": lesson_id}
    )
    assert r.has_next()
    return r.get_next()[0]


@pytest.mark.asyncio
async def test_upsert_lesson_attributes_source_to_non_local_principal(db):
    from campy.brain.thalamus.tools.lessons import upsert_lesson

    principal = await _FakeCloudResolver().resolve(TransportContext(transport="http"))

    result = await upsert_lesson(
        {"text": "B315 attributes this lesson to a real principal, not a guess.",
         "domain": "generic", "lesson_type": "optimization"},
        db, CONFIG, principal=principal,
    )
    lesson_id = result["lesson_id"] if "lesson_id" in result else result.get("id")
    assert lesson_id, f"upsert_lesson did not return a lesson id: {result}"

    source = _lesson_source(db, lesson_id)
    assert source == f"{principal.client}:{principal.subject_id}"
    assert source == "agentcore:svc-account-123"


@pytest.mark.asyncio
async def test_upsert_lesson_without_principal_falls_back_to_agent_source(db):
    from campy.brain.thalamus.tools.lessons import upsert_lesson

    result = await upsert_lesson(
        {"text": "B315 without a principal keeps the pre-existing default.",
         "domain": "generic", "lesson_type": "optimization",
         "agent_source": "unit-test"},
        db, CONFIG,
    )
    lesson_id = result["lesson_id"] if "lesson_id" in result else result.get("id")
    assert lesson_id

    source = _lesson_source(db, lesson_id)
    assert source == "agent:unit-test"


# ---------------------------------------------------------------------------
# scripts/check_principal_ratchet.py — exits 0 on the current tree, and
# non-zero when a converted handler loses its `principal` parameter.
# ---------------------------------------------------------------------------


@pytest.fixture
def ratchet_module():
    import importlib
    return importlib.import_module("scripts.check_principal_ratchet")


def test_ratchet_main_exits_zero_on_current_tree(ratchet_module):
    assert ratchet_module.main([]) == 0


def test_ratchet_detects_a_handler_that_adopted_principal(ratchet_module, monkeypatch):
    import campy.brain.thalamus.tools as tools_mod

    async def with_principal(params, db, config, *, principal=None):
        return {}

    async def without_principal(params, db, config):
        return {}

    monkeypatch.setattr(
        tools_mod, "TOOL_HANDLERS",
        {"fake_a": with_principal, "fake_b": without_principal},
    )
    non_adopting = ratchet_module._non_adopting_handlers()
    assert non_adopting == ["fake_b"]


def test_ratchet_fails_when_a_converted_handler_reverts(ratchet_module, monkeypatch):
    """The regression this ratchet exists to catch: a handler that used to
    declare `principal` loses it again (someone reverts/simplifies a
    signature). The script must exit non-zero, not silently accept it."""
    monkeypatch.setattr(ratchet_module, "_load_baseline", lambda: 0)
    monkeypatch.setattr(
        ratchet_module, "_non_adopting_handlers", lambda: ["notify_turn"]
    )
    assert ratchet_module.main([]) == 1
