# tests/adapters/test_hermes_adapter.py
"""Test Hermes agent adapter."""
import asyncio
import pytest
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that records calls and returns canned responses."""

    def __init__(self, get_response=None, post_response=None):
        self._get_response = get_response
        self._post_response = post_response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None):
        self.calls.append(("GET", url, params))
        return self._get_response

    async def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        return self._post_response


def test_hermes_adapter_importable():
    """HermesAdapter should be importable."""
    from adapters.hermes.adapter import HermesAdapter
    assert HermesAdapter is not None


def test_hermes_get_adapter_factory():
    """get_adapter factory should work."""
    from adapters.hermes.adapter import get_adapter
    
    adapter = get_adapter({
        "session_id": "test-session",
        "memory_url": "http://127.0.0.1:7799"
    })
    assert adapter is not None
    assert adapter._session_id == "test-session"


def test_hermes_adapter_initialization():
    """HermesAdapter should initialize properly."""
    from adapters.hermes.adapter import HermesAdapter
    
    adapter = HermesAdapter(memory_url="http://localhost:9999")
    assert adapter.memory_url == "http://localhost:9999"
    assert adapter.name == "hermes-campy"
    assert adapter.version == "0.1.0"


def test_hermes_adapter_configure():
    """Adapter.configure should accept config."""
    from adapters.hermes.adapter import HermesAdapter
    
    adapter = HermesAdapter()
    config = {"session_id": "custom-session"}
    success = adapter.configure(config)
    
    assert success is True
    assert adapter._session_id == "custom-session"


def test_hermes_adapter_health_check():
    """Adapter.health_check should return bool."""
    from adapters.hermes.adapter import HermesAdapter
    
    adapter = HermesAdapter()
    result = adapter.health_check()
    assert isinstance(result, bool)
    # If daemon not running, result will be False, which is OK for this test


def test_hermes_detect_function():
    """detect_hermes should be available."""
    from campy.cli.detect import detect_hermes
    assert callable(detect_hermes)


def test_hermes_register_function():
    """register_hermes should be available."""
    from campy.cli.register import register_hermes
    assert callable(register_hermes)


def test_hermes_in_setup_targets():
    """Hermes should be available as a setup target."""
    try:
        from campy.cli.main import setup
    except ModuleNotFoundError as exc:
        if "kuzu" in str(exc):
            pytest.skip("kuzu optional dependency not installed in this test environment")
        raise
    import inspect
    
    source = inspect.getsource(setup)
    assert "hermes" in source.lower()


def test_hermes_readme_exists():
    """Hermes README should exist."""
    from pathlib import Path

    readme = Path(__file__).parent.parent.parent / "adapters" / "hermes" / "README.md"
    assert readme.exists()
    content = readme.read_text()
    assert "HermesAdapter" in content or "Hermes" in content


async def test_hermes_notify_actually_succeeds_against_mocked_transport():
    """B264: notify() imported `aiohttp`, which is not a declared dependency
    anywhere in pyproject.toml and is not installed in this environment -
    every call silently failed with ModuleNotFoundError, swallowed by the
    broad except clause, always returning False. The adapter must use
    httpx (an already-declared, installed dependency) instead."""
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter(memory_url="http://127.0.0.1:7799")
    adapter.configure({"session_id": "sess-1"})

    fake_client = _FakeAsyncClient(post_response=_FakeResponse(status_code=200))
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await adapter.notify("user", "hello world")

    assert result is True
    assert fake_client.calls == [
        ("POST", "http://127.0.0.1:7799/api/v1/notify",
         {"role": "user", "content": "hello world", "session_id": "sess-1"})
    ]


async def test_hermes_recall_actually_succeeds_against_mocked_transport():
    """Same aiohttp-missing bug as notify() - recall() must also work."""
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter()
    adapter.configure({"session_id": "sess-2"})

    fake_client = _FakeAsyncClient(get_response=_FakeResponse(
        status_code=200, json_data={"ok": True, "data": {"facts": ["x"]}}
    ))
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await adapter.recall("what did we decide")

    assert result == {"facts": ["x"]}
    assert fake_client.calls[0][0] == "GET"
    assert fake_client.calls[0][1].endswith("/api/v1/recall")


async def test_hermes_session_recall_calls_bundle_endpoint_with_defaults():
    """session_recall() must hit /api/v1/bundle (compile_context), not
    /api/v1/recall (current_truth) - these are semantically different."""
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter(memory_url="http://127.0.0.1:7799")
    adapter.configure({"session_id": "sess-3"})

    fake_client = _FakeAsyncClient(post_response=_FakeResponse(
        status_code=200, json_data={"ok": True, "data": {"bundle": {"decisions": []}}}
    ))
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await adapter.session_recall("brief me on the auth refactor")

    assert result == {"bundle": {"decisions": []}}
    method, url, payload = fake_client.calls[0]
    assert method == "POST"
    assert url == "http://127.0.0.1:7799/api/v1/bundle"
    assert payload == {
        "query": "brief me on the auth refactor",
        "token_budget": 32000,
        "agent_type": "generic",
    }


async def test_hermes_session_recall_custom_budget_and_agent_type():
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter()
    adapter.configure({"session_id": "sess-4"})

    fake_client = _FakeAsyncClient(post_response=_FakeResponse(status_code=200, json_data={"data": {}}))
    with patch("httpx.AsyncClient", return_value=fake_client):
        await adapter.session_recall("task", token_budget=4096, agent_type="claude_code")

    _, _, payload = fake_client.calls[0]
    assert payload["token_budget"] == 4096
    assert payload["agent_type"] == "claude_code"


async def test_hermes_session_recall_returns_none_on_failure_status():
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter()
    fake_client = _FakeAsyncClient(post_response=_FakeResponse(status_code=500))
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await adapter.session_recall("task")

    assert result is None


async def test_hermes_spawn_context_calls_bundle_endpoint_with_smaller_default_budget():
    """spawn_context() is the card's stated core motivation: task-scoped context
    for Hermes-spawned background agents, using a smaller default token budget
    than a full session_recall since spawned agents get a narrower slice."""
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter(memory_url="http://127.0.0.1:7799")
    adapter.configure({"session_id": "parent-sess"})

    fake_client = _FakeAsyncClient(post_response=_FakeResponse(
        status_code=200, json_data={"data": {"bundle": {"decisions": []}}}
    ))
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await adapter.spawn_context("parent-sess", "investigate the failing test")

    assert result == {"bundle": {"decisions": []}}
    method, url, payload = fake_client.calls[0]
    assert method == "POST"
    assert url == "http://127.0.0.1:7799/api/v1/bundle"
    assert payload["query"] == "investigate the failing test"
    assert payload["token_budget"] == 8000
    assert payload["agent_type"] == "spawned"


async def test_hermes_spawn_context_returns_none_on_failure_status():
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter()
    fake_client = _FakeAsyncClient(post_response=_FakeResponse(status_code=500))
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await adapter.spawn_context("parent-sess", "task")

    assert result is None


async def test_hermes_capture_turn_delegates_to_notify_endpoint():
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter()
    adapter.configure({"session_id": "sess-5"})

    fake_client = _FakeAsyncClient(post_response=_FakeResponse(status_code=200))
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await adapter.capture_turn("assistant", "done")

    assert result is True
    method, url, payload = fake_client.calls[0]
    assert url.endswith("/api/v1/notify")
    assert payload == {"role": "assistant", "content": "done", "session_id": "sess-5"}


async def test_hermes_capture_turn_overrides_session_id_without_leaking():
    """capture_turn's session_id override must be scoped to that one call -
    it must not permanently overwrite the adapter's configured session."""
    from adapters.hermes.adapter import HermesAdapter

    adapter = HermesAdapter()
    adapter.configure({"session_id": "configured-session"})

    fake_client = _FakeAsyncClient(post_response=_FakeResponse(status_code=200))
    with patch("httpx.AsyncClient", return_value=fake_client):
        await adapter.capture_turn("user", "hi", session_id="one-off-session")

    _, _, payload = fake_client.calls[0]
    assert payload["session_id"] == "one-off-session"
    assert adapter._session_id == "configured-session"


async def test_hermes_adapter_calls_real_app_routes_via_asgi_transport():
    """Integration guard: exercise adapter calls against create_app() routes,
    not a fully mocked transport, so route drift is caught by tests."""
    import httpx
    import sys
    import types

    from adapters.hermes.adapter import HermesAdapter
    from web.server import create_app

    class _EmptyResult:
        def has_next(self):
            return False

    class _EmptyDB:
        def execute(self, q, p=None):
            return _EmptyResult()

        async def execute_write(self, q, p=None):
            pass

    app = create_app(_EmptyDB(), config={"server": {"auth": "none"}})

    async def _current_truth(*, params, db, config):
        return {"results": [{"fact": params["query"]}], "session_id": params.get("session_id")}

    async def _memory_decision(*, params, db, config):
        return {"recommended_tool": "compile_context", "query": params["query"]}

    async def _notify_turn(*, params, db, config):
        return {"status": "queued", "session_id": params.get("session_id")}

    async def _compile_context(*, params, db, config):
        return {"bundle": {"query": params["query"], "agent_type": params.get("agent_type", "generic")}}

    fake_tools_module = types.SimpleNamespace(
        TOOL_HANDLERS={
            "current_truth": _current_truth,
            "memory_decision": _memory_decision,
            "notify_turn": _notify_turn,
            "compile_context": _compile_context,
        }
    )

    with patch.dict(sys.modules, {"campy.brain.thalamus.tools": fake_tools_module}):
        def _client_factory():
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            )

        adapter = HermesAdapter(
            memory_url="http://testserver",
            async_client_factory=_client_factory,
        )
        adapter.configure({"session_id": "sess-int"})

        recall = await adapter.recall("what changed?")
        decide = await adapter.decide("which tool")
        notified = await adapter.notify("assistant", "done")
        bundle = await adapter.session_recall("auth rollout", agent_type="spawned")

    assert recall == {"results": [{"fact": "what changed?"}], "session_id": "sess-int"}
    assert decide == {"recommended_tool": "compile_context", "query": "which tool"}
    assert notified is True
    assert bundle == {"bundle": {"query": "auth rollout", "agent_type": "spawned"}}
