# tests/test_rest_api.py
"""Test REST API router module."""
import json


def test_rest_router_importable():
    """REST API router should be importable."""
    from campy.brain.brainstem.rest_api import create_router
    router = create_router()
    assert router is not None


def test_rest_router_has_routes():
    """Router should have the expected API routes."""
    from campy.brain.brainstem.rest_api import create_router
    router = create_router()
    route_paths = [r.path for r in router if hasattr(r, 'path')]
    assert "/api/v1/recall" in route_paths
    assert "/api/v1/status" in route_paths
    assert "/api/v1/bundle" in route_paths
    assert "/api/v1/tools" in route_paths


def test_ok_envelope():
    """_ok should format responses correctly."""
    from campy.brain.brainstem.rest_api import _ok
    resp = _ok({"foo": "bar"})
    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["data"]["foo"] == "bar"


def test_err_envelope():
    """_err should format error responses correctly."""
    from campy.brain.brainstem.rest_api import _err
    resp = _err("something broke", 500)
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert body["error"] == "something broke"
    assert resp.status_code == 500


def test_err_default_status():
    """_err should default to 400 status."""
    from campy.brain.brainstem.rest_api import _err
    resp = _err("bad input")
    assert resp.status_code == 400


class _EmptyResult:
    def has_next(self):
        return False


class _StubDB:
    """Minimal stand-in DB that accepts writes and returns no rows.

    Regression coverage for a real bug found 2026-08-03: `_call_tool()` in
    rest_api.py was invoking tool handlers with `handler(arguments=..., ...)`,
    but every handler in TOOL_HANDLERS is wrapped by `_with_phase()`, whose
    signature is `wrapper(params=None, db=None, config=None, **kw)` and which
    forwards to the real tool function as `fn(params=params, ...)`. Because
    `arguments` doesn't match `params`, every real tool call landed in `**kw`
    and the underlying function raised `TypeError: <tool>() got an unexpected
    keyword argument 'arguments'` — silently turned into a 500 JSON envelope
    by `_call_tool`'s except clause, so no endpoint could ever succeed. Only
    caught by actually invoking the endpoints end-to-end (TestClient + a real
    FastAPI app), not by testing `_ok`/`_err`/route-shape in isolation.
    """

    def execute(self, q, p=None):
        return _EmptyResult()

    async def execute_write(self, q, p=None):
        return None


def test_notify_endpoint_calls_real_handler_without_typeerror():
    """POST /api/v1/notify must reach notify_turn's real params= signature."""
    from fastapi.testclient import TestClient
    from web.server import create_app

    app = create_app(_StubDB())
    client = TestClient(app)
    resp = client.post(
        "/api/v1/notify",
        json={"role": "user", "content": "hello world", "session_id": "test-session"},
    )
    body = resp.json()
    assert resp.status_code == 200, body
    assert body["ok"] is True
    assert "unexpected keyword argument" not in json.dumps(body)


def test_status_endpoint_passes_session_id():
    """GET /api/v1/status must supply a session_id — context_status requires one."""
    from fastapi.testclient import TestClient
    from web.server import create_app

    app = create_app(_StubDB())
    client = TestClient(app)
    resp = client.get("/api/v1/status")
    body = resp.json()
    assert resp.status_code == 200, body
    assert body["ok"] is True
