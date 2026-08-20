from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from campy.brain.auth import KNOWN_SCOPES, Principal, TransportContext


class EmptyResult:
    def has_next(self):
        return False


class EmptyDB:
    def execute(self, q, p=None):
        return EmptyResult()

    async def execute_write(self, q, p=None):
        pass


class HeaderGateResolver:
    async def resolve(self, transport_ctx: TransportContext) -> Principal:
        headers = transport_ctx.headers or {}
        if headers.get("x-test-auth") != "ok":
            raise RuntimeError("missing test auth header")
        return Principal(
            subject_id="tester",
            tenant_id="tenant",
            workspace_id="workspace",
            scopes=frozenset(KNOWN_SCOPES),
            client="test",
            session_id=None,
            derived_from="test",
        )


def _route_path_with_placeholders_resolved(path: str) -> str:
    return (
        path.replace("{node_id}", "node-1")
        .replace("{merge_event_id}", "merge-1")
        .replace("{id}", "id-1")
    )


def test_non_health_routes_require_auth_when_auth_enabled():
    from web.server import create_app

    app = create_app(
        EmptyDB(),
        config={"server": {"auth": "iam"}},
        principal_resolver=HeaderGateResolver(),
    )
    client = TestClient(app)

    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or path == "/health":
            continue

        request_path = _route_path_with_placeholders_resolved(path)
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            response = client.request(method, request_path)
            assert response.status_code == 401, f"{method} {path} should be auth-protected"


def test_auth_none_mode_keeps_local_routes_open():
    from web.server import create_app

    app = create_app(EmptyDB(), config={"server": {"auth": "none"}})
    client = TestClient(app)

    assert client.get("/api/stats").status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/confirm/node-1"),
        ("POST", "/api/reject/node-1"),
        ("DELETE", "/api/merge-events/merge-1"),
    ],
)
def test_destructive_routes_reject_unauthenticated_requests(method: str, path: str):
    from web.server import create_app

    app = create_app(
        EmptyDB(),
        config={"server": {"auth": "iam"}},
        principal_resolver=HeaderGateResolver(),
    )
    client = TestClient(app)

    response = client.request(method, path)
    assert response.status_code == 401


def test_dashboard_disable_flag_mounts_only_health_mcp_and_sse():
    from web.server import create_app

    app = create_app(
        EmptyDB(),
        config={"server": {"dashboard_enabled": False}},
    )

    paths = {getattr(route, "path", None) for route in app.router.routes}
    assert "/health" in paths
    assert "/mcp" in paths
    assert "/sse" in paths

    assert "/" not in paths
    assert "/api/stats" not in paths
    assert "/static" not in paths
