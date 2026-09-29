"""B385: cloud deployment readiness.

Covers the code side of running Campy as a container:
  * 12-factor env overrides (campy/brain/brainstem/config.py::ENV_OVERRIDES)
    reach the pieces that consume them: the IAM principal resolver and the
    bind guard;
  * `dashboard_enabled = false` is a minimal surface: /health, /mcp, /sse and
    the per-workspace REST API (/api/v1/*), no dashboard;
  * GET /health reports version/uptime/RSS and a storage probe, and answers
    503 when the store can't be queried (so a load balancer drains the task).

The container assets themselves (deploy/) are covered separately.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from campy.brain.brainstem.config import ENV_OVERRIDES, apply_env_overrides, load_config


def _base() -> dict:
    return {"server": {"auth": "none", "bind_host": "127.0.0.1", "dashboard_enabled": True},
            "web": {"port": 7799}}


# ---------------------------------------------------------------------------
# Env overrides
# ---------------------------------------------------------------------------

def test_every_documented_override_applies():
    env = {
        "CAMPY_SERVER_AUTH": "iam",
        "CAMPY_SERVER_BIND_HOST": "0.0.0.0",
        "CAMPY_SERVER_DASHBOARD_ENABLED": "false",
        "CAMPY_WEB_PORT": "8080",
        "CAMPY_IAM_TENANT_ID": "acme",
        "CAMPY_IAM_WORKSPACE_ID": "acme-default",
        "CAMPY_IAM_WORKSPACE_MAP_JSON": '{"arn:aws:iam::1:role/a": "ws-a"}',
        "CAMPY_IAM_TENANT_MAP_JSON": '{"arn:aws:iam::1:role/a": "tenant-a"}',
        "CAMPY_IAM_PRINCIPAL_SCOPE_MAP_JSON": '{"arn:aws:iam::1:role/a": ["memory.read"]}',
        "CAMPY_IAM_DEFAULT_SCOPES_JSON": '["memory.read", "memory.write"]',
    }
    assert set(env) == set(ENV_OVERRIDES), "test must cover every override"
    cfg = apply_env_overrides(_base(), env)
    s = cfg["server"]
    assert s["auth"] == "iam" and s["bind_host"] == "0.0.0.0"
    assert s["dashboard_enabled"] is False
    assert cfg["web"]["port"] == 8080
    assert s["iam_tenant_id"] == "acme" and s["iam_workspace_id"] == "acme-default"
    assert s["iam_workspace_map"] == {"arn:aws:iam::1:role/a": "ws-a"}
    assert s["iam_tenant_map"] == {"arn:aws:iam::1:role/a": "tenant-a"}
    assert s["iam_principal_scope_map"] == {"arn:aws:iam::1:role/a": ["memory.read"]}
    assert s["iam_default_scopes"] == ["memory.read", "memory.write"]
    assert sorted(cfg["_env_overrides"]) == sorted(env)


def test_unset_and_empty_vars_leave_config_alone():
    cfg = apply_env_overrides(_base(), {"CAMPY_SERVER_AUTH": ""})
    assert cfg["server"] == _base()["server"] and cfg["_env_overrides"] == []


@pytest.mark.parametrize("var,raw", [
    ("CAMPY_SERVER_DASHBOARD_ENABLED", "maybe"),
    ("CAMPY_WEB_PORT", "70000"),
    ("CAMPY_WEB_PORT", "http"),
    ("CAMPY_IAM_WORKSPACE_MAP_JSON", "{not json"),
    ("CAMPY_IAM_WORKSPACE_MAP_JSON", '["a", "b"]'),
    ("CAMPY_IAM_PRINCIPAL_SCOPE_MAP_JSON", '{"arn": "memory.read"}'),
    ("CAMPY_IAM_DEFAULT_SCOPES_JSON", '"memory.read"'),
])
def test_malformed_override_fails_loudly_naming_the_variable(var, raw):
    with pytest.raises(ValueError, match=var):
        apply_env_overrides(_base(), {var: raw})


def test_error_does_not_echo_the_value():
    secret_ish = '{"arn:aws:iam::123456789012:role/prod": 5}'
    with pytest.raises(ValueError) as exc:
        apply_env_overrides(_base(), {"CAMPY_IAM_WORKSPACE_MAP_JSON": secret_ish})
    assert "123456789012" not in str(exc.value)


def test_load_config_applies_overrides_over_the_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('[server]\nauth = "none"\ndashboard_enabled = true\n')
    monkeypatch.setenv("CAMPY_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CAMPY_SERVER_DASHBOARD_ENABLED", "0")
    cfg = load_config()
    assert cfg["server"]["dashboard_enabled"] is False
    assert cfg["_env_overrides"] == ["CAMPY_SERVER_DASHBOARD_ENABLED"]


def test_env_iam_maps_reach_the_principal_resolver():
    from campy.brain_daemon import _build_http_principal_resolver
    cfg = apply_env_overrides(_base(), {
        "CAMPY_IAM_WORKSPACE_MAP_JSON": '{"arn:aws:iam::1:role/a": "ws-a"}',
        "CAMPY_IAM_TENANT_MAP_JSON": '{"arn:aws:iam::1:role/a": "tenant-a"}',
    })
    resolver = _build_http_principal_resolver("iam", cfg["server"])
    assert resolver._workspace_map == {"arn:aws:iam::1:role/a": "ws-a"}
    assert resolver._tenant_map == {"arn:aws:iam::1:role/a": "tenant-a"}


def test_env_bind_host_is_still_guarded():
    """Setting 0.0.0.0 via env must not bypass the bind guard."""
    from campy.brain_daemon import BindGuardError, _enforce_bind_guard
    cfg = apply_env_overrides(_base(), {"CAMPY_SERVER_BIND_HOST": "0.0.0.0"})
    with pytest.raises(BindGuardError):
        _enforce_bind_guard(cfg["server"]["bind_host"], cfg["server"]["auth"])
    cfg = apply_env_overrides(cfg, {"CAMPY_SERVER_AUTH": "iam"})
    _enforce_bind_guard(cfg["server"]["bind_host"], cfg["server"]["auth"])  # allowed


# ---------------------------------------------------------------------------
# Minimal surface with the dashboard off
# ---------------------------------------------------------------------------

def _paths(app) -> set:
    return {getattr(r, "path", None) for r in app.router.routes}


def test_dashboard_off_keeps_health_mcp_and_rest_api_only():
    from unittest.mock import MagicMock
    from web.server import create_app
    on = _paths(create_app(MagicMock(), {"server": {"dashboard_enabled": True}}))
    off = _paths(create_app(MagicMock(), {"server": {"dashboard_enabled": False}}))
    rest = {p for p in on if p and p.startswith("/api/v1/")}
    assert len(rest) == 10
    assert off == {"/health", "/mcp", "/sse"} | rest
    assert "/api/stats" in on and "/" in on  # the dashboard exists when enabled...
    assert "/api/stats" not in off and "/" not in off  # ...and is gone when not


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

async def _get_health(db):
    from web.server import create_app
    app = create_app(db, {"server": {"auth": "none"}})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get("/health")


async def test_health_probes_a_real_store(tmp_path):
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    r = await _get_health(OxigraphClient(str(tmp_path / "store")))
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "ok" and body["storage"] == "ok"
    assert body["version"] and body["uptime_s"] >= 0
    assert body["rss_mb"] is None or body["rss_mb"] > 0


class _BrokenStore:
    async def ping(self):
        raise RuntimeError("store is gone")


class _HungStore:
    async def ping(self):
        await asyncio.sleep(30)


@pytest.mark.parametrize("store", [_BrokenStore(), _HungStore()])
async def test_health_is_503_when_storage_cannot_be_queried(store):
    r = await _get_health(store)
    assert r.status_code == 503
    assert r.json()["status"] == "unhealthy" and r.json()["storage"] == "unreachable"
    assert "store is gone" not in r.text  # no exception text on a public endpoint


async def test_health_without_a_probe_stays_ok():
    from unittest.mock import MagicMock
    r = await _get_health(MagicMock())
    assert r.status_code == 200 and r.json()["storage"] == "unknown"
