"""
tests/test_bedrock_provider.py — B324: AWS Bedrock LLM Provider

Covers:
- create_llm_client(provider="bedrock") returns a client satisfying
  LLMClientProtocol (not the concrete OpenAI-wire LLMClient class)
- message translation to Converse's request shape (system lifted out,
  consecutive same-role messages merged, content wrapped as [{"text": ...}],
  temperature routed into inferenceConfig) — all via a stubbed boto3 client,
  no network
- usage mapping (inputTokens/outputTokens/totalTokens -> prompt/completion/total)
- empty content list -> "" instead of IndexError
- a bare model id that needs a cross-region inference profile produces an
  error naming the fix, rather than the raw boto error
- timeout_seconds / max_retries reach botocore's Config
- missing boto3 raises a clear install-hint error, and importing
  campy.brain.llm.provider without boto3 installed still works for every
  other provider (the regression this card must not introduce)
- existing providers (ollama/openai/anthropic/google) are unchanged

No live AWS calls are made anywhere in this file.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError

from campy.brain.llm.provider import (
    LLMClient,
    LLMClientProtocol,
    create_llm_client,
)
from campy.brain.llm import bedrock
from campy.brain.llm.bedrock import (
    BedrockConfigError,
    BedrockInferenceProfileError,
    BedrockLLMClient,
    create_bedrock_client,
    _to_converse_messages,
    _extract_text,
    _map_usage,
)


# ---------------------------------------------------------------------------
# Fixtures / stubs
# ---------------------------------------------------------------------------

_DEFAULT_RESPONSE = {
    "output": {"message": {"role": "assistant", "content": [{"text": "hello there"}]}},
    "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
}


class _StubConverseClient:
    """Records converse() calls and returns a canned response — no network."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else _DEFAULT_RESPONSE
        self.error = error
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeSession:
    """Stand-in for boto3.Session — records constructor/client() kwargs."""

    instances: list["_FakeSession"] = []

    def __init__(self, **kwargs):
        self.session_kwargs = kwargs
        self.client_calls: list[tuple[str, dict]] = []
        self.fake_client = _StubConverseClient()
        _FakeSession.instances.append(self)

    def client(self, service_name, **kwargs):
        self.client_calls.append((service_name, kwargs))
        return self.fake_client


@pytest.fixture(autouse=True)
def _reset_fake_session():
    _FakeSession.instances.clear()
    yield
    _FakeSession.instances.clear()


def _inference_profile_client_error() -> ClientError:
    """A ClientError shaped like Bedrock's real 'needs an inference profile' failure."""
    return ClientError(
        error_response={
            "Error": {
                "Code": "ValidationException",
                "Message": (
                    "Invocation of model ID anthropic.claude-3-5-sonnet-20240620-v1:0 "
                    "with on-demand throughput isn't supported. Retry your request "
                    "with the ID or ARN of an inference profile that contains this model."
                ),
            }
        },
        operation_name="Converse",
    )


# ---------------------------------------------------------------------------
# Message translation (no network — direct BedrockLLMClient over a stub client)
# ---------------------------------------------------------------------------

class TestMessageTranslation:
    def test_system_message_lifted_to_top_level(self):
        system, messages = _to_converse_messages(
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "hi"},
            ]
        )
        assert system == [{"text": "You are a helpful assistant."}]
        assert all(m["role"] != "system" for m in messages)
        assert messages == [{"role": "user", "content": [{"text": "hi"}]}]

    def test_content_wrapped_as_text_blocks(self):
        _, messages = _to_converse_messages([{"role": "user", "content": "plain string"}])
        assert messages[0]["content"] == [{"text": "plain string"}]

    def test_consecutive_same_role_messages_are_merged(self):
        _, messages = _to_converse_messages(
            [
                {"role": "user", "content": "first"},
                {"role": "user", "content": "second"},
                {"role": "assistant", "content": "reply one"},
                {"role": "assistant", "content": "reply two"},
            ]
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == [{"text": "first"}, {"text": "second"}]
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == [{"text": "reply one"}, {"text": "reply two"}]

    def test_multiple_system_messages_all_lifted(self):
        system, messages = _to_converse_messages(
            [
                {"role": "system", "content": "rule one"},
                {"role": "system", "content": "rule two"},
                {"role": "user", "content": "go"},
            ]
        )
        assert system == [{"text": "rule one"}, {"text": "rule two"}]
        assert messages == [{"role": "user", "content": [{"text": "go"}]}]

    def test_no_system_messages_returns_none(self):
        system, _ = _to_converse_messages([{"role": "user", "content": "hi"}])
        assert system is None

    def test_temperature_lands_in_inference_config(self):
        stub = _StubConverseClient()
        client = BedrockLLMClient(stub, "some-model")
        client.chat([{"role": "user", "content": "hi"}], temperature=0.7)
        request = stub.calls[0]
        assert request["inferenceConfig"] == {"temperature": 0.7}
        assert "temperature" not in request

    def test_default_temperature_is_zero(self):
        stub = _StubConverseClient()
        client = BedrockLLMClient(stub, "some-model")
        client.chat([{"role": "user", "content": "hi"}])
        assert stub.calls[0]["inferenceConfig"] == {"temperature": 0.0}

    def test_system_param_only_present_when_system_messages_exist(self):
        stub = _StubConverseClient()
        client = BedrockLLMClient(stub, "some-model")
        client.chat([{"role": "user", "content": "hi"}])
        assert "system" not in stub.calls[0]

        client.chat(
            [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}]
        )
        assert stub.calls[1]["system"] == [{"text": "be nice"}]


# ---------------------------------------------------------------------------
# Usage mapping
# ---------------------------------------------------------------------------

class TestUsageMapping:
    def test_usage_keys_mapped(self):
        assert _map_usage(_DEFAULT_RESPONSE) == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_missing_usage_defaults_to_zero(self):
        assert _map_usage({"output": {}}) == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def test_chat_populates_last_usage(self):
        stub = _StubConverseClient()
        client = BedrockLLMClient(stub, "some-model")
        assert client.last_usage is None
        client.chat([{"role": "user", "content": "hi"}])
        assert client.last_usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_chat_with_usage_returns_tuple(self):
        stub = _StubConverseClient()
        client = BedrockLLMClient(stub, "some-model")
        text, usage = client.chat_with_usage([{"role": "user", "content": "hi"}])
        assert text == "hello there"
        assert usage == client.last_usage
        assert usage["total_tokens"] == 15


# ---------------------------------------------------------------------------
# Text extraction / empty content
# ---------------------------------------------------------------------------

class TestTextExtraction:
    def test_extracts_text(self):
        assert _extract_text(_DEFAULT_RESPONSE) == "hello there"

    def test_empty_content_list_returns_empty_string(self):
        response = {"output": {"message": {"role": "assistant", "content": []}}}
        assert _extract_text(response) == ""

    def test_missing_output_returns_empty_string(self):
        assert _extract_text({}) == ""

    def test_chat_with_empty_content_does_not_raise(self):
        stub = _StubConverseClient(
            response={
                "output": {"message": {"role": "assistant", "content": []}},
                "usage": {"inputTokens": 1, "outputTokens": 0, "totalTokens": 1},
            }
        )
        client = BedrockLLMClient(stub, "some-model")
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == ""


# ---------------------------------------------------------------------------
# Inference-profile error translation
# ---------------------------------------------------------------------------

class TestInferenceProfileError:
    def test_bare_model_id_error_names_the_fix(self):
        stub = _StubConverseClient(error=_inference_profile_client_error())
        client = BedrockLLMClient(stub, "anthropic.claude-3-5-sonnet-20240620-v1:0")

        with pytest.raises(BedrockInferenceProfileError) as excinfo:
            client.chat([{"role": "user", "content": "hi"}])

        message = str(excinfo.value)
        assert "inference profile" in message.lower()
        assert "anthropic.claude-3-5-sonnet-20240620-v1:0" in message
        # Names the likely fix (geography-prefixed cross-region inference profile id)
        assert "us.anthropic.claude-3-5-sonnet-20240620-v1:0" in message

    def test_unrelated_error_passes_through_unmodified(self):
        stub = _StubConverseClient(error=ValueError("some other network problem"))
        client = BedrockLLMClient(stub, "some-model")

        with pytest.raises(ValueError, match="some other network problem"):
            client.chat([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Auth / config plumbing (timeout, retries, region, profile) via a stubbed
# boto3.Session — no network
# ---------------------------------------------------------------------------

class TestClientConstruction:
    def test_timeout_and_retries_reach_botocore_config(self, monkeypatch):
        monkeypatch.setattr(boto3, "Session", _FakeSession)

        create_bedrock_client(
            {"region": "us-east-1"}, "some-model",
            timeout_seconds=42.0, max_retries=5,
        )

        session = _FakeSession.instances[-1]
        service_name, kwargs = session.client_calls[-1]
        assert service_name == "bedrock-runtime"
        cfg = kwargs["config"]
        assert cfg.read_timeout == 42.0
        assert cfg.retries["max_attempts"] == 5

    def test_region_and_profile_passed_through(self, monkeypatch):
        monkeypatch.setattr(boto3, "Session", _FakeSession)

        create_bedrock_client(
            {"region": "eu-west-1", "profile": "my-profile"}, "some-model",
        )

        session = _FakeSession.instances[-1]
        assert session.session_kwargs == {"profile_name": "my-profile"}
        _, kwargs = session.client_calls[-1]
        assert kwargs["region_name"] == "eu-west-1"

    def test_no_config_kwargs_when_timeout_and_retries_unset(self, monkeypatch):
        monkeypatch.setattr(boto3, "Session", _FakeSession)

        create_bedrock_client({"region": "us-east-1"}, "some-model")

        session = _FakeSession.instances[-1]
        _, kwargs = session.client_calls[-1]
        assert "config" not in kwargs

    def test_returns_bedrock_llm_client(self, monkeypatch):
        monkeypatch.setattr(boto3, "Session", _FakeSession)
        client = create_bedrock_client({"region": "us-east-1"}, "some-model")
        assert isinstance(client, BedrockLLMClient)


# ---------------------------------------------------------------------------
# Factory integration — create_llm_client(provider="bedrock")
# ---------------------------------------------------------------------------

class TestFactoryIntegration:
    def test_create_llm_client_returns_protocol_conforming_client(self, monkeypatch):
        monkeypatch.setattr(boto3, "Session", _FakeSession)

        client = create_llm_client(
            {
                "llm": {
                    "provider": "bedrock",
                    "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                    "region": "us-east-1",
                }
            }
        )

        # Assert against the protocol, not the concrete class.
        assert isinstance(client, LLMClientProtocol)
        assert not isinstance(client, LLMClient)

        # And it actually works end-to-end through the factory-built client.
        text = client.chat([{"role": "user", "content": "hi"}])
        assert text == "hello there"
        assert client.last_usage["total_tokens"] == 15

    def test_create_llm_client_for_step_inherits_bedrock(self, monkeypatch):
        """create_llm_client_for_step delegates to create_llm_client, so it
        must not need its own bedrock branch."""
        from campy.brain.llm.provider import create_llm_client_for_step

        monkeypatch.setattr(boto3, "Session", _FakeSession)

        config = {
            "llm": {
                "provider": "bedrock",
                "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "region": "us-east-1",
            }
        }
        client = create_llm_client_for_step(config, "step6_arbitration")
        assert isinstance(client, LLMClientProtocol)


# ---------------------------------------------------------------------------
# Missing boto3 — the regression this card must not introduce
# ---------------------------------------------------------------------------

class TestMissingBoto3:
    def test_create_bedrock_client_raises_clear_message(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "boto3", None)

        with pytest.raises(BedrockConfigError) as excinfo:
            create_bedrock_client({"region": "us-east-1"}, "some-model")

        message = str(excinfo.value)
        assert "boto3" in message.lower()
        assert "pip install" in message.lower()

    def test_create_llm_client_bedrock_degrades_gracefully_without_boto3(self, monkeypatch, capsys):
        """Matches the existing contract: create_llm_client() returns None
        (not an exception) when a provider is unavailable, with a clear
        message printed for the operator."""
        monkeypatch.setitem(sys.modules, "boto3", None)

        result = create_llm_client(
            {"llm": {"provider": "bedrock", "model": "some-model", "region": "us-east-1"}}
        )
        assert result is None
        captured = capsys.readouterr()
        assert "boto3" in captured.out.lower()

    def test_provider_module_importable_without_boto3(self):
        """The critical regression check: importing provider.py, and using
        every non-Bedrock provider, must work with boto3 entirely absent
        from the interpreter — not just hidden after the fact."""
        script = (
            "import sys\n"
            "sys.modules['boto3'] = None\n"
            "import campy.brain.llm.provider as provider\n"
            "from unittest.mock import patch, MagicMock\n"
            "mock_client = MagicMock()\n"
            "with patch('openai.OpenAI', return_value=mock_client):\n"
            "    c = provider.create_llm_client({'llm': {'provider': 'ollama', "
            "'model': 'llama3.1:8b', 'base_url': 'http://localhost:11434/v1'}})\n"
            "    assert c is not None, 'ollama client should not be None'\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Existing providers unchanged
# ---------------------------------------------------------------------------

class TestExistingProvidersUnchanged:
    @pytest.mark.parametrize("provider", ["ollama", "openai", "anthropic", "google"])
    def test_existing_providers_still_return_concrete_llm_client(self, provider):
        with patch("openai.OpenAI") as mock_openai_cls:
            mock_openai_cls.return_value = MagicMock()
            config = {
                "llm": {
                    "provider": provider,
                    "model": "some-model",
                    "api_key": "test-key",
                    "base_url": "http://localhost:11434/v1" if provider == "ollama" else None,
                }
            }
            client = create_llm_client(config)
            assert isinstance(client, LLMClient)
            assert isinstance(client, LLMClientProtocol)

    def test_unknown_provider_still_returns_none(self):
        client = create_llm_client({"llm": {"provider": "not-a-real-provider"}})
        assert client is None
