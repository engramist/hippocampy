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
        "CAMPY_LLM_PROVIDER": "bedrock",
        "CAMPY_LLM_MODEL": "us.example.model-v1:0",
        "CAMPY_LLM_REGION": "us-east-1",
        "CAMPY_LLM_BASE_URL": "https://llm.internal/v1",
        "CAMPY_IAM_TENANT_ID": "acme",
        "CAMPY_IAM_WORKSPACE_ID": "acme-default",
        "CAMPY_IAM_WORKSPACE_MAP_JSON": '{"arn:aws:iam::1:role/a": "ws-a"}',
        "CAMPY_IAM_TENANT_MAP_JSON": '{"arn:aws:iam::1:role/a": "tenant-a"}',
        "CAMPY_IAM_PRINCIPAL_SCOPE_MAP_JSON": '{"arn:aws:iam::1:role/a": ["memory.read"]}',
        "CAMPY_IAM_DEFAULT_SCOPES_JSON": '["memory.read", "memory.write"]',
        "CAMPY_OBSERVATIONS_ENABLED": "1",
        "CAMPY_OBSERVATIONS_RETRIEVAL": "1",
    }
    assert set(env) == set(ENV_OVERRIDES), "test must cover every override"
    cfg = apply_env_overrides(_base(), env)
    s = cfg["server"]
    assert s["auth"] == "iam" and s["bind_host"] == "0.0.0.0"
    assert s["dashboard_enabled"] is False
    assert cfg["web"]["port"] == 8080
    assert cfg["observations"]["enabled"] is True
    assert cfg["observations"]["retrieval"] is True
    assert cfg["llm"] == {"provider": "bedrock", "model": "us.example.model-v1:0",
                          "region": "us-east-1", "base_url": "https://llm.internal/v1"}
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


# ---------------------------------------------------------------------------
# deploy/ assets. The image itself is built in CI/by the operator (the build
# needs registry + model downloads); these checks catch drift between the
# assets and the code without a Docker daemon.
# ---------------------------------------------------------------------------

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy"

# Non-override env vars the assets may legitimately set.
_KNOWN_RUNTIME_VARS = {"CAMPY_HOME", "CAMPY_SOCKET_PATH", "CAMPY_DEFAULT_CONFIG"}


def _campy_vars_in(text: str) -> set:
    # Full names only: prose wildcards like "CAMPY_IAM_*" end in "_".
    return set(re.findall(r"\bCAMPY_[A-Z0-9_]*[A-Z0-9]\b", text))


def test_assets_only_set_env_vars_the_daemon_reads():
    """A typo'd CAMPY_* name in an asset would be silently ignored at runtime."""
    known = set(ENV_OVERRIDES) | _KNOWN_RUNTIME_VARS
    for name in ("Dockerfile", "ecs-task-definition.json", "docker-compose.yml", "entrypoint.sh"):
        unknown = _campy_vars_in((DEPLOY / name).read_text()) - known
        assert not unknown, f"{name} sets unknown vars {sorted(unknown)}"


def test_dockerfile_runs_non_root_offline_with_iam():
    text = (DEPLOY / "Dockerfile").read_text()
    assert re.search(r"useradd --uid 1000\b", text)
    assert re.search(r"^USER 1000:1000$", text, re.M)
    for env in ("HF_HUB_OFFLINE=1", "CAMPY_SERVER_AUTH=iam", "CAMPY_SERVER_BIND_HOST=0.0.0.0",
                "CAMPY_SERVER_DASHBOARD_ENABLED=false", "CAMPY_HOME=/data/campy",
                "FASTEMBED_CACHE_PATH=/opt/campy-models/fastembed"):
        assert env in text, env
    assert "spacy download en_core_web_md" in text   # step1_ner loads it at runtime
    assert "HEALTHCHECK" in text and "/health" in text


def test_ecs_task_definition_shape():
    td = json.loads((DEPLOY / "ecs-task-definition.json").read_text())
    assert td["requiresCompatibilities"] == ["FARGATE"] and td["networkMode"] == "awsvpc"
    (c,) = td["containerDefinitions"]
    assert c["user"] == "1000:1000"
    assert c["mountPoints"][0]["containerPath"] == "/data/campy"
    assert td["volumes"][0]["efsVolumeConfiguration"]["transitEncryption"] == "ENABLED"
    env = {e["name"]: e["value"] for e in c["environment"]}
    assert env["CAMPY_SERVER_AUTH"] == "iam" and env["CAMPY_SERVER_DASHBOARD_ENABLED"] == "false"
    assert "/health" in " ".join(c["healthCheck"]["command"])
    # IAM maps come from SSM, not plain-text environment
    assert {s["name"] for s in c["secrets"]} >= {"CAMPY_IAM_WORKSPACE_MAP_JSON"}


def test_container_config_passes_the_bind_guard_and_builds_iam_resolver(tmp_path, monkeypatch):
    from campy.brain_daemon import _build_http_principal_resolver, _enforce_bind_guard
    from campy.brain.auth import IAMPrincipalResolver
    home = tmp_path / "home"
    home.mkdir()
    shutil.copy(DEPLOY / "campy.container.toml", home / "config.toml")
    monkeypatch.setenv("CAMPY_HOME", str(home))
    monkeypatch.chdir(home)
    for var in ENV_OVERRIDES:
        monkeypatch.delenv(var, raising=False)
    cfg = load_config()
    s = cfg["server"]
    _enforce_bind_guard(s["bind_host"], s["auth"])  # 0.0.0.0 + iam: allowed
    assert isinstance(_build_http_principal_resolver(s["auth"], s), IAMPrincipalResolver)
    assert cfg["watchdog"]["enabled"] is False and cfg["observability"]["enabled"] is False
    assert cfg["daemon"]["restart_interval_hours"] == 0
    assert cfg["embeddings"]["offline"] is True


def _run_entrypoint(tmp_path, env_extra):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "python"
    fake.write_text('#!/bin/sh\necho "fake-python $*"\n')
    fake.chmod(0o755)
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "CAMPY_HOME": str(tmp_path / "home"),
           "CAMPY_SOCKET_PATH": str(tmp_path / "sock" / "brain.sock"),
           "CAMPY_DEFAULT_CONFIG": str(DEPLOY / "campy.container.toml"), **env_extra}
    return subprocess.run(["sh", str(DEPLOY / "entrypoint.sh")], env=env,
                          capture_output=True, text=True, timeout=30)


def test_entrypoint_seeds_config_then_runs_the_daemon(tmp_path):
    r = _run_entrypoint(tmp_path, {"CAMPY_LLM_MODEL": "m"})
    assert r.returncode == 0, r.stderr
    assert "fake-python -m campy.brain_daemon" in r.stdout
    seeded = tmp_path / "home" / "config.toml"
    assert seeded.read_text() == (DEPLOY / "campy.container.toml").read_text()
    assert (tmp_path / "sock").is_dir()


def test_entrypoint_never_overwrites_an_existing_config(tmp_path):
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "config.toml").write_text('[llm]\nmodel = "mine"\n')
    r = _run_entrypoint(tmp_path, {})
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "home" / "config.toml").read_text() == '[llm]\nmodel = "mine"\n'


def test_entrypoint_refuses_to_start_without_a_model(tmp_path):
    r = _run_entrypoint(tmp_path, {})
    assert r.returncode == 64
    assert "CAMPY_LLM_MODEL" in r.stderr and "fake-python" not in r.stdout
