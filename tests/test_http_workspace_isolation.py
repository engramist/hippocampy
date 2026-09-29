"""B457: workspace isolation holds on every HTTP route, not just /mcp.

Before B457 the REST API (/api/v1/*) and the dashboard (/api/*, /, ...) ran
against the daemon's fixed database whatever the authenticated caller's
workspace, so with auth on, any tenant could read and write the shared
"local" workspace through them. These tests drive the real app
(`web.server.create_app`) over ASGI with auth on, a real `WorkspaceRouter`
with the daemon's local database registered as "local" (as brain_daemon
does), and a resolver that maps a test header to a `Principal`.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from campy.brain.auth import SCOPE_MEMORY_READ, SCOPE_MEMORY_WRITE, Principal
from campy.brain.hippocampus.graph.router import WorkspaceRouter
from tests.kuzu_test_client import KuzuClient

_RW = frozenset({SCOPE_MEMORY_READ, SCOPE_MEMORY_WRITE})
_RO = frozenset({SCOPE_MEMORY_READ})


def _principal(workspace_id: str, scopes=_RW) -> Principal:
    return Principal(subject_id=f"user-{workspace_id}", tenant_id=workspace_id,
                     workspace_id=workspace_id, scopes=scopes, client="test",
                     session_id=None, derived_from="test")


PRINCIPALS = {
    "tenant-a": _principal("tenant-a"),
    "tenant-b": _principal("tenant-b"),
    "local-admin": _principal("local"),
    "local-readonly": _principal("local", _RO),
    "tenant-a-readonly": _principal("tenant-a", _RO),
}


class _HeaderResolver:
    """Stands in for IAMPrincipalResolver: the caller's identity comes from a
    transport header, never from the request body."""

    async def resolve(self, ctx):
        key = (ctx.headers or {}).get("x-test-principal")
        if key not in PRINCIPALS:
            raise PermissionError("no valid credential")
        return PRINCIPALS[key]


async def _fact_schema(client: KuzuClient) -> None:
    await asyncio.to_thread(
        client.execute,
        "CREATE NODE TABLE IF NOT EXISTS Fact(id STRING, text STRING, PRIMARY KEY(id))",
    )


async def _facts(db) -> list:
    rows = await db.execute_read("MATCH (f:Fact) RETURN f.text")
    return sorted(r[0] if isinstance(r, (list, tuple)) else next(iter(r.values())) for r in rows)


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """App with auth on, a router whose "local" workspace is the fixed db, and
    notify_turn/current_truth stubbed to write/read Fact nodes in whichever
    db they are handed -- so the test sees exactly which store a call hit."""
    import campy.brain_daemon as bd
    from web.server import create_app

    local_db = KuzuClient(str(tmp_path / "local.db"))
    await _fact_schema(local_db)
    router = WorkspaceRouter(tmp_path / "workspaces", schema_init=_fact_schema)
    router.register("local", local_db)

    async def notify_turn(params, db, config, **kw):
        await db.execute_write("CREATE (f:Fact {id: $id, text: $t})",
                               {"id": params["content"], "t": params["content"]})
        return {"status": "queued"}

    async def current_truth(params, db, config, **kw):
        return {"results": await _facts(db)}

    monkeypatch.setitem(bd.TOOL_HANDLERS, "notify_turn", notify_turn)
    monkeypatch.setitem(bd.TOOL_HANDLERS, "current_truth", current_truth)

    config = {"server": {"auth": "iam"}, "activity": {"log_path": str(tmp_path / "activity.log")}}
    app = create_app(local_db, config, principal_resolver=_HeaderResolver(), router=router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, router, local_db
    await router.close_all()


def _as(who: str) -> dict:
    return {"x-test-principal": who}


# ---------------------------------------------------------------------------
# REST (/api/v1/*): routed per workspace, through the shared chokepoint.
# ---------------------------------------------------------------------------

async def test_rest_write_lands_in_callers_workspace_not_the_shared_db(env):
    client, router, local_db = env
    r = await client.post("/api/v1/notify", headers=_as("tenant-a"),
                          json={"role": "user", "content": "secret-of-a"})
    assert r.status_code == 200, r.text

    db_a = await router.get("tenant-a")
    assert await _facts(db_a) == ["secret-of-a"]
    router.release("tenant-a")
    # Pre-B457 this write went to the fixed (local) database.
    assert await _facts(local_db) == []


async def test_rest_read_does_not_see_another_tenants_writes(env):
    client, _, _ = env
    await client.post("/api/v1/notify", headers=_as("tenant-a"),
                      json={"role": "user", "content": "secret-of-a"})

    as_b = await client.get("/api/v1/recall", params={"q": "secret"}, headers=_as("tenant-b"))
    as_a = await client.get("/api/v1/recall", params={"q": "secret"}, headers=_as("tenant-a"))

    assert as_b.status_code == 200 and as_b.json()["data"]["results"] == []
    assert as_a.json()["data"]["results"] == ["secret-of-a"]


async def test_rest_enforces_scopes(env):
    client, _, _ = env
    r = await client.post("/api/v1/notify", headers=_as("tenant-a-readonly"),
                          json={"role": "user", "content": "x"})
    assert r.status_code == 403
    assert "memory.write" in r.json()["error"]
    r = await client.get("/api/v1/recall", params={"q": "x"}, headers=_as("tenant-a-readonly"))
    assert r.status_code == 200


async def test_rest_rejects_unauthenticated(env):
    client, _, _ = env
    r = await client.get("/api/v1/recall", params={"q": "x"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Dashboard: local workspace only, with scopes.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/stats"),
    ("GET", "/api/graph"),
    ("GET", "/"),
    ("POST", "/api/confirm/some-node"),
    ("DELETE", "/api/merge-events/some-event"),
])
async def test_dashboard_refuses_other_workspaces(env, method, path):
    client, _, _ = env
    r = await client.request(method, path, headers=_as("tenant-b"))
    assert r.status_code == 403
    assert "local workspace only" in r.json()["detail"]


async def test_dashboard_serves_local_workspace(env):
    client, _, _ = env
    r = await client.get("/api/stats", headers=_as("local-admin"))
    assert r.status_code != 403


async def test_dashboard_write_needs_write_scope(env):
    client, _, _ = env
    r = await client.post("/api/confirm/some-node", headers=_as("local-readonly"))
    assert r.status_code == 403
    assert "memory.write" in r.json()["detail"]
    r = await client.get("/api/stats", headers=_as("local-readonly"))
    assert r.status_code != 403


async def test_health_stays_public(env):
    client, _, _ = env
    r = await client.get("/health")
    assert r.status_code == 200
