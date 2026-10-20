"""
Tests for campy/brain/llm/provider.py — T7 coverage.
"""

import sys
import os
from unittest.mock import patch

import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# create_llm_client — factory behavior
# ---------------------------------------------------------------------------

def test_create_llm_client_ollama_returns_client():
    """Ollama provider config returns an LLMClient (no real connection required)."""
    from campy.brain.llm.provider import create_llm_client, LLMClient
    config = {
        "llm": {
            "provider": "ollama",
            "model": "llama3.1:8b",
            "base_url": "http://localhost:11434/v1",
        }
    }
    client = create_llm_client(config)
    # openai package present in test env — should return LLMClient
    assert client is None or isinstance(client, LLMClient)


def test_create_llm_client_unknown_provider_returns_none():
    """Unknown provider returns None (graceful degradation)."""
    from campy.brain.llm.provider import create_llm_client
    config = {"llm": {"provider": "totally_unknown_provider_xyz", "model": "m"}}
    client = create_llm_client(config)
    assert client is None


def test_create_llm_client_default_config():
    """Empty config falls back to ollama defaults without crashing."""
    from campy.brain.llm.provider import create_llm_client
    # Should not raise even with empty config
    client = create_llm_client({})
    # Either returns LLMClient (openai importable) or None (not importable)
    assert client is None or hasattr(client, "chat")


def test_create_llm_client_ollama_uses_slow_model_friendly_timeout():
    """Local Ollama defaults should tolerate slower reasoning models."""
    from campy.brain.llm.provider import create_llm_client, LLMClient

    config = {
        "llm": {
            "provider": "ollama",
            "model": "gemma4:e4b",
            "base_url": "http://localhost:11434/v1",
        }
    }

    with patch("openai.OpenAI") as mock_openai:
        mock_openai.return_value = object()
        client = create_llm_client(config)

    assert isinstance(client, LLMClient)
    mock_openai.assert_called_once_with(
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        timeout=180.0,
        max_retries=3,
    )


def test_create_llm_client_ollama_respects_timeout_override():
    """Explicit timeout/retry config should flow into the OpenAI-compatible client."""
    from campy.brain.llm.provider import create_llm_client, LLMClient

    config = {
        "llm": {
            "provider": "ollama",
            "model": "gemma4:26b",
            "base_url": "http://localhost:11434/v1",
            "timeout_seconds": 600,
            "max_retries": 5,
        }
    }

    with patch("openai.OpenAI") as mock_openai:
        mock_openai.return_value = object()
        client = create_llm_client(config)

    assert isinstance(client, LLMClient)
    mock_openai.assert_called_once_with(
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        timeout=600.0,
        max_retries=5,
    )


# ---------------------------------------------------------------------------
# LLMClient — interface
# ---------------------------------------------------------------------------

def test_llm_client_has_chat_method():
    """LLMClient exposes .chat() method."""
    from campy.brain.llm.provider import LLMClient

    class FakeOpenAI:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    class Choice:
                        class message:
                            content = "test response"
                    class R:
                        choices = [Choice()]
                    return R()

    client = LLMClient(FakeOpenAI(), "test-model")
    result = client.chat([{"role": "user", "content": "hello"}])
    assert result == "test response"


def test_llm_client_chat_returns_empty_string_on_none_content():
    """chat() returns '' when message.content is None (not NoneType error)."""
    from campy.brain.llm.provider import LLMClient

    class FakeOpenAI:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    class Choice:
                        class message:
                            content = None
                    class R:
                        choices = [Choice()]
                    return R()

    client = LLMClient(FakeOpenAI(), "test-model")
    result = client.chat([{"role": "user", "content": "hello"}])
    assert result == ""


@pytest.mark.asyncio
async def test_llm_client_achat_returns_string():
    """achat() returns the same string as chat() via thread pool."""
    from campy.brain.llm.provider import LLMClient

    class FakeOpenAI:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    class Choice:
                        class message:
                            content = "async response"
                    class R:
                        choices = [Choice()]
                    return R()

    client = LLMClient(FakeOpenAI(), "test-model")
    result = await client.achat([{"role": "user", "content": "hello"}])
    assert result == "async response"


@pytest.mark.asyncio
async def test_llm_client_achat_offloads_to_thread(monkeypatch):
    """achat() calls asyncio.to_thread, not chat() directly in the event loop."""
    import asyncio
    from campy.brain.llm.provider import LLMClient

    thread_calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        thread_calls.append(fn.__name__)
        return fn(*args, **kwargs)

    class FakeOpenAI:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    class Choice:
                        class message:
                            content = "ok"
                    class R:
                        choices = [Choice()]
                    return R()

    client = LLMClient(FakeOpenAI(), "m")
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    result = await client.achat([{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert "chat" in thread_calls   # was offloaded to thread


# ---------------------------------------------------------------------------
# B494 — output-token cap
# ---------------------------------------------------------------------------

def _fake_openai(finish_reason="stop", text="hello"):
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.choices[0].finish_reason = finish_reason
    resp.choices[0].message.content = text
    resp.usage = None
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    return client


def _kwargs(client):
    return client.chat.completions.create.call_args.kwargs


def _make(cfg_llm, fake):
    from campy.brain.llm.provider import LLMClient, resolve_max_tokens
    return LLMClient(fake, "m", resolve_max_tokens(cfg_llm), "ollama")


def test_b494_default_cap_passed_on_every_method():
    fake = _fake_openai()
    c = _make({}, fake)
    c.chat([{"role": "user", "content": "q"}])
    assert _kwargs(fake)["max_tokens"] == 2048
    c.chat_with_usage([{"role": "user", "content": "q"}])
    assert _kwargs(fake)["max_tokens"] == 2048
    import asyncio
    asyncio.run(c.achat([{"role": "user", "content": "q"}]))
    assert _kwargs(fake)["max_tokens"] == 2048
    asyncio.run(c.achat_with_usage([{"role": "user", "content": "q"}]))
    assert _kwargs(fake)["max_tokens"] == 2048


def test_b494_zero_disables_cap():
    fake = _fake_openai()
    _make({"max_tokens": 0}, fake).chat([{"role": "user", "content": "q"}])
    assert "max_tokens" not in _kwargs(fake)


def test_b494_configured_cap_and_per_call_override():
    fake = _fake_openai()
    c = _make({"max_tokens": 100}, fake)
    c.chat([{"role": "user", "content": "q"}])
    assert _kwargs(fake)["max_tokens"] == 100
    c.chat([{"role": "user", "content": "q"}], max_tokens=7)
    assert _kwargs(fake)["max_tokens"] == 7


def test_b494_factory_reads_config():
    from campy.brain.llm.provider import create_llm_client
    c = create_llm_client({"llm": {"provider": "ollama", "max_tokens": 64}})
    assert c._max_tokens == 64
    c = create_llm_client({"llm": {"provider": "ollama"}})
    assert c._max_tokens == 2048
    c = create_llm_client({"llm": {"provider": "ollama", "max_tokens": 0}})
    assert c._max_tokens is None


def test_b494_env_override_parses():
    from campy.brain.brainstem.config import apply_env_overrides
    cfg = apply_env_overrides({"llm": {}}, {"CAMPY_LLM_MAX_TOKENS": "512"})
    assert cfg["llm"]["max_tokens"] == 512


def test_b494_length_finish_warns_and_returns_text(caplog):
    import logging
    fake = _fake_openai(finish_reason="length", text="partial")
    c = _make({}, fake)
    with caplog.at_level(logging.WARNING, logger="campy.brain.llm.provider"):
        out = c.chat([{"role": "user", "content": "Q" * 300}])
    assert out == "partial"
    rec = [r for r in caplog.records if "output cap" in r.getMessage()]
    assert rec and "ollama/m" in rec[0].getMessage()
    assert "2048" in rec[0].getMessage()
    assert "Q" * 120 in rec[0].getMessage() and "Q" * 121 not in rec[0].getMessage()


def test_b494_normal_finish_does_not_warn(caplog):
    import logging
    c = _make({}, _fake_openai())
    with caplog.at_level(logging.WARNING, logger="campy.brain.llm.provider"):
        c.chat([{"role": "user", "content": "q"}])
    assert not caplog.records


def test_b494_bedrock_cap_in_request():
    from campy.brain.llm.bedrock import BedrockLLMClient
    from unittest.mock import MagicMock
    stub = MagicMock()
    stub.converse.return_value = {"output": {"message": {"content": [{"text": "x"}]}}}
    BedrockLLMClient(stub, "m", 2048).chat([{"role": "user", "content": "q"}])
    assert stub.converse.call_args.kwargs["inferenceConfig"]["maxTokens"] == 2048
    BedrockLLMClient(stub, "m", None).chat([{"role": "user", "content": "q"}])
    assert "maxTokens" not in stub.converse.call_args.kwargs["inferenceConfig"]
