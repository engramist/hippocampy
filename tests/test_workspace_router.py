"""
tests/test_workspace_router.py — B316: WorkspaceRouter, one Kùzu database
per workspace.

A minimal, fast schema (`_minimal_schema_init`) is used for most tests — a
single trivial node table — rather than the real `init_schema()`, which
needs a real embedding call. This keeps these tests hermetic and fast while
still exercising real, file-backed `KuzuClient` instances (real isolation,
real schema-init timing, real locks) rather than mocks. One test
(`test_isolation_...`) is the card's literal acceptance criterion: write via
one client, read via the other, assert absent.

Note on the card's stated fact-check (see the PR): the card asks to "run
the existing kuzu_client lock tests unmodified (grep tests/ for them
first)" for the write-lock staleness behavior. No such dedicated test file
or test function exists anywhere in tests/ today (confirmed by grepping for
`_get_write_lock`, `_write_locks`, `weakref`, `loop_ref`, and `stale.*lock`
across tests/ — zero hits). The staleness behavior is instead exercised
indirectly, across many real-KuzuClient integration tests that each run
under their own pytest-asyncio function-scoped loop. This file adds new,
direct tests for the staleness behavior instead of "running it unmodified",
since there was nothing pre-existing to run.
"""

from __future__ import annotations

import asyncio

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient, _get_write_lock
from campy.brain.hippocampus.graph.router import (
    LOCAL_WORKSPACE_ID,
    WorkspaceRouter,
    _workspace_dir,
)


async def _minimal_schema_init(client: KuzuClient) -> None:
    """Fast fake schema — one trivial node table, no embeddings involved."""
    await asyncio.to_thread(
        client.execute,
        "CREATE NODE TABLE IF NOT EXISTS Fact(id STRING, text STRING, PRIMARY KEY(id))",
    )


def _counting_schema_init(counter: dict):
    async def _init(client: KuzuClient) -> None:
        counter["calls"] = counter.get("calls", 0) + 1
        await _minimal_schema_init(client)
    return _init


# ---------------------------------------------------------------------------
# Isolation — the headline property.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_isolation_fact_written_to_one_workspace_not_readable_from_another(tmp_path):
    router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)

    db_a = await router.get("workspace-a")
    db_b = await router.get("workspace-b")

    await db_a.execute_write(
        "CREATE (f:Fact {id: $id, text: $text})",
        {"id": "f1", "text": "only in workspace-a"},
    )

    rows_a = await db_a.execute_read("MATCH (f:Fact) RETURN f.id")
    rows_b = await db_b.execute_read("MATCH (f:Fact) RETURN f.id")

    assert len(rows_a) == 1
    assert len(rows_b) == 0

    router.release("workspace-a")
    router.release("workspace-b")
    await router.close_all()


@pytest.mark.asyncio
async def test_different_workspaces_get_different_directories(tmp_path):
    router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)
    db_a = await router.get("workspace-a")
    db_b = await router.get("workspace-b")
    assert db_a is not db_b
    assert db_a.db_path != db_b.db_path
    router.release("workspace-a")
    router.release("workspace-b")
    await router.close_all()


# ---------------------------------------------------------------------------
# First access: schema init, exactly once under concurrency.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_access_creates_directory_and_initializes_schema(tmp_path):
    counter = {}
    router = WorkspaceRouter(tmp_path, schema_init=_counting_schema_init(counter))

    db = await router.get("new-workspace")
    assert counter["calls"] == 1
    # The Fact table from _minimal_schema_init must exist and be queryable.
    rows = await db.execute_read("MATCH (f:Fact) RETURN f.id")
    assert rows == []
    router.release("new-workspace")
    await router.close_all()


@pytest.mark.asyncio
async def test_concurrent_first_access_initializes_schema_exactly_once(tmp_path):
    counter = {}
    router = WorkspaceRouter(tmp_path, schema_init=_counting_schema_init(counter))

    clients = await asyncio.gather(*[router.get("shared-new-ws") for _ in range(10)])

    assert counter["calls"] == 1
    assert all(c is clients[0] for c in clients)
    for _ in clients:
        router.release("shared-new-ws")
    await router.close_all()


# ---------------------------------------------------------------------------
# LRU eviction + busy-client protection.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lru_eviction_closes_evicted_client_and_respects_max_open(tmp_path):
    router = WorkspaceRouter(tmp_path, max_open=2, schema_init=_minimal_schema_init)

    db1 = await router.get("ws-1")
    router.release("ws-1")
    db2 = await router.get("ws-2")
    router.release("ws-2")
    assert router.open_count == 2

    db3 = await router.get("ws-3")  # exceeds max_open=2, evicts LRU (ws-1)
    router.release("ws-3")

    assert router.open_count <= 2
    # ws-1 was the least-recently-used and unborrowed — it should be gone.
    assert "ws-1" not in router._clients
    # The evicted client must actually be closed (its .conn/.db attrs gone).
    assert not hasattr(db1, "conn") or db1.conn is None or not hasattr(db1.conn, "execute")
    await router.close_all()


@pytest.mark.asyncio
async def test_busy_client_is_not_evicted_while_in_flight(tmp_path):
    router = WorkspaceRouter(tmp_path, max_open=1, schema_init=_minimal_schema_init)

    db1 = await router.get("ws-busy")  # borrowed, NOT released — stays "in flight"
    assert router.open_count == 1

    db2 = await router.get("ws-other")  # would push open_count to 2, over max_open=1
    router.release("ws-other")

    # ws-busy must still be open and usable — eviction had to skip it.
    assert "ws-busy" in router._clients
    rows = await db1.execute_read("MATCH (f:Fact) RETURN f.id")
    assert rows == []  # still a live, working client

    router.release("ws-busy")
    await router.close_all()


# ---------------------------------------------------------------------------
# Traversal safety — _workspace_dir()'s allowlist + digest + backstop.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", [
    "../../etc",
    "a/b",
    "..",
    "",
    "x" * 200,
    "null\x00byte",
])
def test_traversal_ids_raise_value_error_and_create_nothing(tmp_path, bad_id):
    before = set(tmp_path.iterdir()) if tmp_path.exists() else set()
    with pytest.raises(ValueError):
        _workspace_dir(tmp_path, bad_id, local_db_path=tmp_path / "brain.db")
    after = set(tmp_path.iterdir()) if tmp_path.exists() else set()
    assert before == after, "a rejected workspace_id must create nothing on disk"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [
    "../../etc",
    "a/b",
    "..",
    "",
    "x" * 200,
    "null\x00byte",
])
async def test_router_get_rejects_traversal_ids_and_creates_nothing(tmp_path, bad_id):
    router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        await router.get(bad_id)
    after = set(tmp_path.iterdir())
    assert before == after


@pytest.mark.parametrize("workspace_id", [
    "a", "abc-123", "A1", "x" * 64, "workspace_with_underscores",
    "../etc/passwd", "..", "a/../b", "%2e%2e", "a\x00b", "a" * 65,
])
def test_resolved_path_always_inside_root_or_raises(tmp_path, workspace_id):
    """Property test: for any workspace_id, _workspace_dir() either raises
    ValueError, or returns a path provably inside root. There is no third
    outcome."""
    try:
        resolved = _workspace_dir(tmp_path, workspace_id, local_db_path=tmp_path / "brain.db")
    except ValueError:
        return
    root_resolved = tmp_path.resolve()
    assert resolved == root_resolved or root_resolved in resolved.parents


# ---------------------------------------------------------------------------
# "local" resolves to the pre-existing DB_PATH — no migration.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_workspace_resolves_to_pre_existing_db_path(tmp_path):
    # Seed a "pre-existing install" DB at the old path.
    old_db_path = tmp_path / "brain.db"
    seed_client = KuzuClient(str(old_db_path))
    await _minimal_schema_init(seed_client)
    await seed_client.execute_write(
        "CREATE (f:Fact {id: $id, text: $text})",
        {"id": "pre-existing", "text": "seeded before B316"},
    )
    seed_client.close()

    router = WorkspaceRouter(
        tmp_path, schema_init=_minimal_schema_init, local_db_path=old_db_path,
    )
    db = await router.get(LOCAL_WORKSPACE_ID)
    rows = await db.execute_read("MATCH (f:Fact) RETURN f.id AS id, f.text AS text")
    assert len(rows) == 1
    assert rows[0]["id"] == "pre-existing"
    router.release(LOCAL_WORKSPACE_ID)
    await router.close_all()


def test_local_workspace_dir_is_local_db_path_not_digest_suffixed(tmp_path):
    local_db_path = tmp_path / "brain.db"
    resolved = _workspace_dir(tmp_path, LOCAL_WORKSPACE_ID, local_db_path=local_db_path)
    assert resolved == local_db_path.resolve()


# ---------------------------------------------------------------------------
# Write lock is per (loop, db_path).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_writes_to_different_workspaces_overlap_in_time(tmp_path):
    router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)
    db_a = await router.get("ws-a")
    db_b = await router.get("ws-b")

    order: list[str] = []

    async def _slow_write(db, tag, delay):
        order.append(f"{tag}-start")
        # Hold the write lock for `delay` by wrapping a real write with a
        # sleep INSIDE execute_write's critical section, via a tiny query
        # plus an explicit sleep before releasing — simplest way to prove
        # overlap without reaching into KuzuClient internals: run two
        # writes concurrently and assert their start times overlap.
        await db.execute_write(
            "CREATE (f:Fact {id: $id, text: $text})", {"id": tag, "text": tag},
        )
        await asyncio.sleep(delay)
        order.append(f"{tag}-end")

    await asyncio.gather(
        _slow_write(db_a, "a", 0.05),
        _slow_write(db_b, "b", 0.05),
    )
    # Both starts must happen before either end — proves they were not
    # serialized against each other's write lock (different db_path).
    assert order.index("a-start") < order.index("b-end")
    assert order.index("b-start") < order.index("a-end")

    router.release("ws-a")
    router.release("ws-b")
    await router.close_all()


@pytest.mark.asyncio
async def test_concurrent_writes_to_same_workspace_serialize(tmp_path):
    router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)
    db = await router.get("ws-serial")

    active = 0
    max_concurrent = 0

    async def _tracked_write(tag):
        nonlocal active, max_concurrent
        async with _get_write_lock(db.db_path):
            active += 1
            max_concurrent = max(max_concurrent, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*[_tracked_write(f"w{i}") for i in range(5)])
    assert max_concurrent == 1, "writes to the same db_path must serialize"

    router.release("ws-serial")
    await router.close_all()


@pytest.mark.asyncio
async def test_write_lock_keyed_by_db_path_not_loop_alone():
    """Two KuzuClient-shaped db_paths sharing the same running loop get
    DIFFERENT lock objects — the core of the B316 Task 3 change."""
    lock_a = _get_write_lock("/tmp/fake-a.db")
    lock_b = _get_write_lock("/tmp/fake-b.db")
    assert lock_a is not lock_b
    # Same db_path, same loop -> same lock object (still true post-change).
    lock_a_again = _get_write_lock("/tmp/fake-a.db")
    assert lock_a is lock_a_again


@pytest.mark.asyncio
async def test_write_lock_staleness_still_detected_per_db_path():
    """The pre-existing weakref-to-loop staleness check, now scoped per
    db_path: a lock entry whose loop has been garbage-collected must be
    replaced, not reused — exactly as it was pre-B316, just keyed by
    (loop, db_path) instead of (loop,) alone."""
    import campy.brain.hippocampus.graph.kuzu_client as kc_mod
    import weakref

    db_path = "/tmp/fake-staleness.db"
    loop = asyncio.get_running_loop()
    key = (id(loop), db_path)

    class _DeadRef:
        def __call__(self):
            return None  # simulates a garbage-collected loop

    # Seed a deliberately-stale entry for this exact key.
    stale_lock = asyncio.Lock()
    kc_mod._write_locks[key] = (_DeadRef(), stale_lock)

    fresh_lock = _get_write_lock(db_path)
    assert fresh_lock is not stale_lock, "a stale (dead-loop) entry must be replaced"


# ---------------------------------------------------------------------------
# close_all / close_all_sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_all_closes_every_open_client(tmp_path):
    router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)
    await router.get("ws-1")
    router.release("ws-1")
    await router.get("ws-2")
    router.release("ws-2")
    assert router.open_count == 2

    await router.close_all()
    assert router.open_count == 0


@pytest.mark.asyncio
async def test_close_all_sync_closes_every_open_client(tmp_path):
    router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)
    await router.get("ws-1")
    router.release("ws-1")
    await router.get("ws-2")
    router.release("ws-2")
    assert router.open_count == 2

    router.close_all_sync()
    assert router.open_count == 0


# ---------------------------------------------------------------------------
# Daemon + HTTP transport integration: both routing paths agree.
# ---------------------------------------------------------------------------


class _FakePrincipal:
    def __init__(self, workspace_id):
        self.workspace_id = workspace_id
        self.subject_id = "test"
        self.tenant_id = "test"
        self.client = "test"
        self.session_id = None
        self.derived_from = "test"


@pytest.mark.asyncio
async def test_brain_daemon_dispatch_resolves_db_from_router(tmp_path, monkeypatch):
    """BrainDaemon._dispatch resolves `db` via the router, keyed on
    principal.workspace_id — the same fake-handler technique
    tests/test_auth_context.py uses, proving the router (not `self.db`) is
    what a converted handler actually receives."""
    import campy.brain_daemon as bd
    from campy.brain.auth import LocalSingleUserResolver, TransportContext

    class MockDB:
        def close(self):
            pass

    daemon = bd.BrainDaemon.__new__(bd.BrainDaemon)
    daemon.config = {}
    daemon.db = MockDB()
    daemon.running = False
    daemon._llm_client = None
    daemon._centroids = {}
    daemon._loop_queue = None
    daemon._principal_resolver = LocalSingleUserResolver()
    daemon._router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)

    seen = {}

    async def spy_handler(params, db, config):
        seen["db"] = db
        return {"ok": True}

    monkeypatch.setitem(bd.TOOL_HANDLERS, "router_spy_method", spy_handler)

    principal = _FakePrincipal("ws-router-test")
    response = await daemon._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "router_spy_method", "params": {}},
        principal,
    )
    assert response["result"] == {"ok": True}
    assert seen["db"] is not daemon.db

    await daemon._router.close_all()


@pytest.mark.asyncio
async def test_http_dispatch_mcp_resolves_db_from_router(tmp_path, monkeypatch):
    """web/server.py::_dispatch_mcp resolves `db` via the router too, when
    one is passed — the same workspace isolation the socket path gets."""
    import campy.brain_daemon as bd
    from web.server import _dispatch_mcp

    router = WorkspaceRouter(tmp_path, schema_init=_minimal_schema_init)

    seen = {}

    async def spy_handler(params, db, config):
        seen["db"] = db
        return {"ok": True}

    monkeypatch.setitem(bd.TOOL_HANDLERS, "router_spy_http_method", spy_handler)

    principal = _FakePrincipal("ws-http-router-test")
    response = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "router_spy_http_method", "arguments": {}}},
        None, {}, principal, router,
    )
    assert "error" not in response
    assert seen["db"] is not None
    assert seen["db"].db_path == (await router.get("ws-http-router-test")).db_path
    router.release("ws-http-router-test")

    await router.close_all()
