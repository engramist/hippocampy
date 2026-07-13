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
