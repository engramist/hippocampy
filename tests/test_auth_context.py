"""
Tests for B315 — AuthContext: Principal Derivation and Threading.

Covers, in order:
  Task 1 — Principal type + require()
  Task 2 — TransportContext / PrincipalResolver seam (local + a fake
           non-local resolver, proving the seam without a real cloud
           resolver)
  Task 3 — signature-inspection threading in brain_daemon._dispatch
           (_WANTS_PRINCIPAL), both directions (a handler that wants
           `principal` and one that doesn't)
  Task 4 — capture.py / lessons.py attribute B312 `source` to the
           principal; scripts/check_principal_ratchet.py's counting logic
  Task 5 — the forbidden-key guard (every key in _FORBIDDEN_PARAM_KEYS,
           individually) + its WARNING-level log
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import json
import logging
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Stub kuzu — brain_daemon.py imports KuzuClient, which imports the kuzu
# native module. Mirrors tests/test_daemon.py's `_setup_stubs()` exactly so
# this file behaves the same whether run alone or alongside the rest of the
# suite (a real `kuzu` package may already be installed and importable —
# stubbing only kicks in if nothing has claimed `sys.modules["kuzu"]` yet).
# ---------------------------------------------------------------------------


def _setup_stubs():
    if "kuzu" in sys.modules:
        return
    # Only stub if the real package genuinely can't be imported. This repo's
    # test environment normally has the real `kuzu` installed (it's a hard
    # requirement — see requirements.txt), so this branch is the exception,
    # not the rule. Guessing wrong here (stubbing when real kuzu is actually
    # available) is the more dangerous failure mode: it silently swaps every
    # KuzuClient in the process — including this file's own real-DB test —
    # onto a fake connection whose `execute()` always returns None, and that
    # binding sticks (module-level `import kuzu` in kuzu_client.py binds a
    # name once; reassigning sys.modules afterward doesn't retroactively fix
    # it), so prefer a real import whenever one is possible.
    try:
        importlib.import_module("kuzu")
        return
    except ImportError:
        pass

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

from campy.brain.auth import (
    LOCAL_TENANT_ID,
    LOCAL_WORKSPACE_ID,
    SCOPES,
    LocalSingleUserResolver,
    Principal,
    PrincipalResolver,
    TransportContext,
)


# ---------------------------------------------------------------------------
# Task 1 — Principal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_resolver_yields_real_principal_not_none():
    """AC: local mode yields a real Principal — never None."""
    resolver = LocalSingleUserResolver()
    principal = await resolver.resolve(TransportContext())

    assert principal is not None
    assert isinstance(principal, Principal)
    assert principal.tenant_id == LOCAL_TENANT_ID == "local"
    assert principal.workspace_id == LOCAL_WORKSPACE_ID == "local"
    assert principal.scopes == frozenset(SCOPES)
    assert principal.derived_from == "local-single-user"


def test_principal_require_raises_permissionerror_for_missing_scope():
    principal = Principal(
        subject_id="u1", tenant_id="t1", workspace_id="w1",
        scopes=frozenset({"memory.read"}), client="test", session_id=None,
        derived_from="local-single-user",
    )
    with pytest.raises(PermissionError):
        principal.require("memory.write")


def test_principal_require_returns_none_when_scope_held():
    principal = Principal(
        subject_id="u1", tenant_id="t1", workspace_id="w1",
        scopes=frozenset({"memory.write", "memory.read"}), client="test",
        session_id=None, derived_from="local-single-user",
    )
    assert principal.require("memory.write") is None


# ---------------------------------------------------------------------------
# Task 2 — TransportContext / PrincipalResolver seam
# ---------------------------------------------------------------------------


def test_transport_context_has_no_param_carrying_field():
    """AC: TransportContext has no field carrying request params — assert by
    constructing one and checking its declared fields."""
    field_names = {f.name for f in dataclasses.fields(TransportContext)}
    forbidden_shapes = {"params", "request", "body", "raw_request", "raw_params", "jsonrpc"}
    assert not (field_names & forbidden_shapes), field_names

    ctx = TransportContext()
    for name in forbidden_shapes:
        assert not hasattr(ctx, name)


class _FakeCloudResolver:
    """Stub non-local resolver. Proves the PrincipalResolver seam works for
    a non-local principal without building a real OIDC/IAM resolver (which
    is explicitly out of scope for B315)."""

    async def resolve(self, transport_ctx: TransportContext) -> Principal:
        return Principal(
            subject_id="svc-42",
            tenant_id="acme-corp",
            workspace_id="acme-prod",
            scopes=frozenset({"memory.read", "memory.write"}),
            client="fake-cloud",
            session_id=None,
            derived_from="oidc",
        )


def test_resolvers_satisfy_principal_resolver_protocol():
    assert isinstance(LocalSingleUserResolver(), PrincipalResolver)
    assert isinstance(_FakeCloudResolver(), PrincipalResolver)


@pytest.mark.asyncio
async def test_fake_cloud_resolver_yields_different_tenant():
    """AC: a fake non-local resolver in tests produces a Principal with a
    different tenant."""
    principal = await _FakeCloudResolver().resolve(TransportContext())
    assert principal.tenant_id == "acme-corp"
    assert principal.tenant_id != LOCAL_TENANT_ID
    assert principal.derived_from == "oidc"


# ---------------------------------------------------------------------------
# Task 4 — capture.py / lessons.py source attribution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_lesson_attributes_source_to_fake_cloud_principal(monkeypatch):
    """AC: capture attributes the fact to a non-local principal (proves the
    seam works for cloud); AC: facts written via capture carry `source`
    derived from the principal (composes with B312)."""
    from campy.brain.hippocampus.graph import embeddings as emb
    from campy.brain.thalamus.tools.lessons import upsert_lesson

    monkeypatch.setattr(emb, "embed", MagicMock(return_value=[0.1] * 384))

    db = MagicMock()
    db.execute_write = AsyncMock()
    db.execute_read = AsyncMock(return_value=[])
    config = {"embeddings": {"model": "mock-model"}}

    principal = await _FakeCloudResolver().resolve(TransportContext())

    result = await upsert_lesson(
        {"text": "b315 cloud principal attribution", "domain": "b315-test"},
        db, config, principal=principal,
    )
    assert result["status"] == "upserted"

    create_calls = [
        c.args for c in db.execute_write.await_args_list
        if c.args and isinstance(c.args[1], dict) and "prov_source" in c.args[1]
        and c.args[1].get("text") == "b315 cloud principal attribution"
    ]
    assert create_calls, f"no Lesson CREATE call found; calls were {db.execute_write.await_args_list}"
    _, write_params = create_calls[0]
    assert write_params["prov_source"] == "fake-cloud:svc-42"


@pytest.mark.asyncio
async def test_upsert_lesson_without_principal_keeps_legacy_source(monkeypatch):
    """Regression guard: omitting `principal` (the vast majority of this
    module's existing callers) keeps the pre-B315 agent_source-derived
    convention exactly as before."""
    from campy.brain.hippocampus.graph import embeddings as emb
    from campy.brain.thalamus.tools.lessons import upsert_lesson

    monkeypatch.setattr(emb, "embed", MagicMock(return_value=[0.1] * 384))

    db = MagicMock()
    db.execute_write = AsyncMock()
    db.execute_read = AsyncMock(return_value=[])
    config = {"embeddings": {"model": "mock-model"}}

    result = await upsert_lesson(
        {"text": "b315 legacy source path", "domain": "b315-test", "agent_source": "claude-code"},
        db, config,
    )
    assert result["status"] == "upserted"

    create_calls = [
        c.args for c in db.execute_write.await_args_list
        if c.args and isinstance(c.args[1], dict) and c.args[1].get("text") == "b315 legacy source path"
    ]
    assert create_calls
    _, write_params = create_calls[0]
    assert write_params["prov_source"] == "agent:claude-code"


@pytest.mark.asyncio
async def test_notify_turn_passive_plan_attributes_source_to_principal(monkeypatch, tmp_path):
    """`notify_turn` (capture.py) is the other converted primary-capture
    path; exercise it against a real KuzuClient (matches
    tests/test_provenance.py's pattern) so the Plan/PlanStep provenance
    columns this composes with (B312) are checked end to end."""
    from campy.brain.hippocampus import schema as _schema_mod
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.hippocampus.schema import init_schema
    from campy.brain.thalamus.tools import capture as _capture_mod
    from campy.brain.thalamus.tools.capture import notify_turn

    # Matches tests/test_provenance.py's `_patch_embed` fixture: patch the
    # `emb` attribute on each *consuming* module's already-bound module
    # object (schema.py's init_schema()->_bootstrap_centroids() needs
    # embed_batch(); capture.py's notify_turn needs embed()) rather than
    # patching the shared campy.brain.hippocampus.graph.embeddings module
    # by dotted path, which this test suite's import ordering can leave
    # pointing at a different module object than the one each consumer
    # actually calls through.
    _fake_vec = [0.1] * 384

    def _fake_embed(text, model_name=None):
        return list(_fake_vec)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_fake_vec) for _ in texts]

    for mod in (_schema_mod, _capture_mod):
        monkeypatch.setattr(mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)

    seed_path = REPO_ROOT / "campy" / "data" / "GistSeedExamples.md"
    db = KuzuClient(str(tmp_path / "b315_capture.db"))
    init_schema(db, str(seed_path), "mock-model")

    config = {"embeddings": {"model": "mock-model"}}
    principal = await _FakeCloudResolver().resolve(TransportContext())

    content = (
        "Plan:\n"
        "1. First we will set up the environment.\n"
        "2. Then we will write the code.\n"
        "3. Finally we will run the tests.\n"
    )
    result = await notify_turn(
        {"role": "user", "content": content, "session_id": "b315-sess"},
        db, config, principal=principal,
    )
    assert result.get("passive_plan"), result
    plan_id = result["passive_plan"]["plan_id"]

    r = db.execute(
        "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $id}) "
        "RETURN ps.source LIMIT 1",
        {"id": plan_id},
    )
    assert r.has_next()
    assert r.get_next()[0] == "fake-cloud:svc-42"


# ---------------------------------------------------------------------------
# Ratchet script (Task 4)
# ---------------------------------------------------------------------------


@pytest.fixture
def ratchet_module():
    return importlib.import_module("scripts.check_principal_ratchet")


def test_ratchet_counting_matches_wants_principal_set(ratchet_module):
    """The ratchet's count and brain_daemon's dispatch-time _WANTS_PRINCIPAL
    set must never silently drift apart — both walk TOOL_HANDLERS with the
    identical `inspect.signature(fn).parameters` check."""
    import campy.brain_daemon as bd

    without, total, missing = ratchet_module.count_handlers_without_principal(REPO_ROOT)
    assert total == len(bd.TOOL_HANDLERS)
    assert without == total - len(bd._WANTS_PRINCIPAL)
    assert set(missing) == (set(bd.TOOL_HANDLERS) - bd._WANTS_PRINCIPAL)
    # The two handlers this card converts must be counted as adopted.
    assert "notify_turn" not in missing
    assert "upsert_lesson" not in missing


def test_ratchet_script_exits_zero_on_current_tree(ratchet_module):
    """AC: ratchet script exits 0 on the current tree."""
    assert ratchet_module.main([]) == 0


def test_ratchet_script_fails_when_a_converted_handler_regresses(ratchet_module, tmp_path, monkeypatch):
    """AC: ratchet script exits non-zero when a converted handler loses its
    `principal` parameter. Simulated by pointing the script at a baseline
    lower than the real current count — exactly what would happen if a
    handler currently counted as "wants principal" stopped declaring it
    (the missing-count would rise relative to the last checked-in
    baseline) — without touching the real checked-in baseline file."""
    without, _total, _missing = ratchet_module.count_handlers_without_principal(REPO_ROOT)

    fake_baseline = tmp_path / "principal_baseline.json"
    fake_baseline.write_text(json.dumps({"handlers_without_principal": max(without - 1, 0)}))
    monkeypatch.setattr(ratchet_module, "BASELINE_PATH", fake_baseline)

    assert ratchet_module.main([]) == 1


def test_ratchet_baseline_file_matches_current_tree(ratchet_module):
    """The checked-in scripts/principal_baseline.json must not be stale —
    this is what `make check-principal` / CI actually enforces."""
    without, total, _missing = ratchet_module.count_handlers_without_principal(REPO_ROOT)
    baseline = json.loads((REPO_ROOT / "scripts" / "principal_baseline.json").read_text())
    assert baseline["handlers_without_principal"] == without
    assert baseline.get("total_handlers", total) == total


# ---------------------------------------------------------------------------
# Task 3 / Task 5 — brain_daemon._dispatch threading + forbidden-key guard
# ---------------------------------------------------------------------------


def _make_daemon():
    """Construct a `campy.brain_daemon.BrainDaemon` with a minimal mock
    config and DB — same `__new__`-bypassing-`__init__` pattern as
    tests/test_daemon.py's `_make_daemon()` helper, kept independent here
    (own import, own helper) so this file has no import-order dependency
    on that one.

    NOTE: this repo has two `brain_daemon.py` modules — the repo-root
    `./brain_daemon.py` (which `tests/test_daemon.py` imports, and which
    B315 does not touch) and `campy/brain_daemon.py` (the one wired to the
    real `campy-daemon` entry point via `campy/daemon.py`, and the one the
    B315 backlog card names explicitly — `campy/brain_daemon.py:_dispatch`
    etc). This helper deliberately imports the latter.
    """
    import campy.brain_daemon as brain_daemon

    class MockDB:
        def close(self): pass

    config = {
        "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
        "llm":        {"provider": "ollama", "model": "llama3.1:8b"},
        "pruning":    {"sweep_interval_seconds": 300},
        "web":        {"port": 7799},
    }

    daemon = brain_daemon.BrainDaemon.__new__(brain_daemon.BrainDaemon)
    daemon.config      = config
    daemon.db          = MockDB()
    daemon.running     = False
    daemon._llm_client = None
    daemon._centroids  = {}
    daemon._loop_queue = asyncio.Queue()
    return daemon


@pytest.mark.asyncio
async def test_dispatch_without_explicit_principal_still_resolves_one():
    """AC: local mode never hands a handler `None` — even `_dispatch`
    callers (tests, chiefly) that don't pass `principal` explicitly still
    get a real one via the lazy fallback."""
    daemon = _make_daemon()
    principal = await daemon._get_default_principal()
    assert principal is not None
    assert principal.derived_from == "local-single-user"
    assert principal.tenant_id == "local"


@pytest.mark.asyncio
async def test_wants_principal_includes_both_converted_handlers():
    import campy.brain_daemon as bd
    assert "notify_turn" in bd._WANTS_PRINCIPAL
    assert "upsert_lesson" in bd._WANTS_PRINCIPAL


@pytest.mark.asyncio
async def test_handler_declaring_principal_receives_it():
    """AC: a handler declaring `principal` receives it."""
    import campy.brain_daemon as bd
    daemon = _make_daemon()
    received = {}

    async def fake_handler(params, db, config, *, principal=None):
        received["principal"] = principal
        received["params"] = params
        return {"ok": True}

    bd.TOOL_HANDLERS["_b315_test_wants_principal"] = fake_handler
    bd._WANTS_PRINCIPAL.add("_b315_test_wants_principal")
    try:
        response = await daemon._dispatch({
            "jsonrpc": "2.0", "id": 10, "method": "_b315_test_wants_principal",
            "params": {"x": 1},
        })
    finally:
        bd.TOOL_HANDLERS.pop("_b315_test_wants_principal", None)
        bd._WANTS_PRINCIPAL.discard("_b315_test_wants_principal")

    assert response["result"] == {"ok": True}
    assert received["params"] == {"x": 1}
    assert received["principal"] is not None
    assert received["principal"].derived_from == "local-single-user"


@pytest.mark.asyncio
async def test_handler_not_declaring_principal_still_works_unchanged():
    """AC: a handler that does NOT declare `principal` still works unchanged
    — the regression guard for the other ~57 handlers that haven't opted
    in yet. Calling this handler with a `principal=` kwarg would raise
    TypeError, so the assertion that matters is simply that dispatch
    succeeds and the handler's own two-positional-plus-config call shape
    is untouched."""
    import campy.brain_daemon as bd
    daemon = _make_daemon()

    async def legacy_handler(params, db, config):
        return {"legacy": True, "params": params}

    bd.TOOL_HANDLERS["_b315_test_no_principal"] = legacy_handler
    assert "_b315_test_no_principal" not in bd._WANTS_PRINCIPAL
    try:
        response = await daemon._dispatch({
            "jsonrpc": "2.0", "id": 11, "method": "_b315_test_no_principal",
            "params": {"y": 2},
        })
    finally:
        bd.TOOL_HANDLERS.pop("_b315_test_no_principal", None)

    assert response["result"] == {"legacy": True, "params": {"y": 2}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden_key",
    ["tenant_id", "workspace_id", "subject_id", "principal", "scopes"],
)
async def test_forbidden_param_key_rejected_individually(forbidden_key):
    """AC: a request whose params contain a forbidden key is rejected with
    JSON-RPC -32602 and the key named in the message. Repeated for every
    key in _FORBIDDEN_PARAM_KEYS individually, not one representative
    case."""
    import campy.brain_daemon as bd
    assert forbidden_key in bd._FORBIDDEN_PARAM_KEYS  # keep this list and the guard in lockstep

    daemon = _make_daemon()
    response = await daemon._dispatch({
        "jsonrpc": "2.0", "id": 20, "method": "recall_relevant_lessons",
        "params": {forbidden_key: "evil-value", "query": "hello"},
    })
    assert "error" in response, response
    assert response["error"]["code"] == -32602
    assert forbidden_key in response["error"]["message"]


def test_forbidden_param_keys_set_matches_card_spec():
    import campy.brain_daemon as bd
    assert bd._FORBIDDEN_PARAM_KEYS == frozenset(
        {"tenant_id", "workspace_id", "subject_id", "principal", "scopes"}
    )


@pytest.mark.asyncio
async def test_forbidden_param_key_logs_warning_with_subject_id(caplog):
    """AC: the rejection is logged at WARNING with the subject_id."""
    daemon = _make_daemon()
    with caplog.at_level(logging.WARNING):
        response = await daemon._dispatch({
            "jsonrpc": "2.0", "id": 21, "method": "recall_relevant_lessons",
            "params": {"workspace_id": "some-other-tenant"},
        })
    assert response["error"]["code"] == -32602
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("local-user" in r.getMessage() for r in warnings), [r.getMessage() for r in warnings]
    assert any("workspace_id" in r.getMessage() for r in warnings)


@pytest.mark.asyncio
async def test_non_forbidden_params_pass_through_unaffected():
    """Regression guard: ordinary params (including the renamed
    `dedupe_workspace_id` / pre-existing `agent_source`) are untouched by
    the guard."""
    import campy.brain_daemon as bd
    daemon = _make_daemon()

    async def echo_handler(params, db, config):
        return {"echo": params}

    bd.TOOL_HANDLERS["_b315_test_echo"] = echo_handler
    try:
        response = await daemon._dispatch({
            "jsonrpc": "2.0", "id": 22, "method": "_b315_test_echo",
            "params": {"agent_source": "claude-code", "dedupe_workspace_id": "ws-1", "text": "hi"},
        })
    finally:
        bd.TOOL_HANDLERS.pop("_b315_test_echo", None)

    assert "error" not in response
    assert response["result"]["echo"] == {
        "agent_source": "claude-code", "dedupe_workspace_id": "ws-1", "text": "hi",
    }


@pytest.mark.asyncio
async def test_dispatch_unknown_method_still_returns_minus_32601():
    """Regression guard: unrelated to this card, but a cheap check that the
    forbidden-key guard (which now runs before method dispatch) didn't
    change the unknown-method error path."""
    daemon = _make_daemon()
    response = await daemon._dispatch({
        "jsonrpc": "2.0", "id": 23, "method": "nonexistent_method", "params": {},
    })
    assert response["error"]["code"] == -32601
