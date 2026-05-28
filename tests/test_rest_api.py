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
