"""
campy/brain/llm/bedrock.py — AWS Bedrock LLM Provider (B324)

Implements the same interface as LLMClient (campy/brain/llm/provider.py) —
chat() / chat_with_usage() / achat() / achat_with_usage() / last_usage — but
speaks Bedrock's Converse API instead of the OpenAI chat-completions wire
format that every other provider in this module rides on.

Why Converse and not InvokeModel:
    InvokeModel requires a different request/response body per model family
    (Anthropic, Llama, Mistral, Titan, Nova all differ). Converse normalizes
    all of them behind one request shape, which is what's needed since the
    customer picks the model, Campy doesn't.

Auth:
    No API key. Uses boto3's default credential chain (ECS task role in
    deployment, developer's local profile/SSO otherwise). Composes with
    B315/B316 — the same IAM identity that scopes the workspace authorizes
    the model call.

Config keys (config["llm"]):
    provider = "bedrock"
    model    = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # or any Bedrock model id
    region   = "us-east-1"   # optional; falls back to AWS_REGION / boto3 default
    profile  = "..."         # optional, local dev only

boto3 is an OPTIONAL dependency (see pyproject.toml `[bedrock]` extra /
requirements.txt). It is imported lazily inside this module so that
`import campy.brain.llm.provider` — and every other provider — keeps working
on a machine that never installed boto3.
"""

from __future__ import annotations

import asyncio
import os


class BedrockConfigError(RuntimeError):
    """Raised for a Bedrock configuration/auth problem with an actionable message."""


class BedrockInferenceProfileError(RuntimeError):
    """
    Raised when Bedrock rejects a bare model id that requires a cross-region
    inference profile. Bedrock's own validation error does not explain this,
    so we translate it into one that does.
    """


_BOTO3_INSTALL_HINT = (
    "AWS Bedrock provider requires boto3, which is not installed. "
    "Install it with: pip install 'hippocampy[bedrock]'  (or: pip install boto3)"
)

# Substrings observed in Bedrock's ValidationException when a bare model id
# is passed for a model that is only invocable via a cross-region inference
# profile. Matched case-insensitively against the raw boto error text.
_INFERENCE_PROFILE_ERROR_MARKERS = (
    "on-demand throughput isn't supported",
    "on-demand throughput isn",  # tolerate curly/straight apostrophe variants
    "with on-demand throughput",
    "inference profile that contains this model",
)


def _import_boto3():
    """
    Import boto3/botocore lazily. Raises BedrockConfigError with an install
    hint if boto3 is not present — never let this bubble up as a bare
    ModuleNotFoundError from deep inside the factory.
    """
    try:
        import boto3
        from botocore.config import Config as BotocoreConfig
        from botocore.exceptions import ClientError
    except ImportError as e:
        raise BedrockConfigError(_BOTO3_INSTALL_HINT) from e
    return boto3, BotocoreConfig, ClientError


def _to_converse_messages(messages: list[dict]) -> tuple[list[dict] | None, list[dict]]:
    """
    Translate OpenAI-style `messages` into Converse's (system, messages) shape.

    - `system`-role messages are lifted out into a separate top-level `system`
      list (Converse has no "system" message role).
    - Every remaining message's `content` string is wrapped as [{"text": ...}].
    - Consecutive same-role messages are merged into one message with multiple
      content blocks — Converse requires strict user/assistant alternation and
      rejects back-to-back same-role messages.
    """
    system_blocks: list[dict] = []
    converse_messages: list[dict] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content") or ""

        if role == "system":
            system_blocks.append({"text": content})
            continue

        # Bedrock Converse only knows "user" and "assistant" roles.
        role = "assistant" if role == "assistant" else "user"
        block = {"text": content}

        if converse_messages and converse_messages[-1]["role"] == role:
            converse_messages[-1]["content"].append(block)
        else:
            converse_messages.append({"role": role, "content": [block]})

    return (system_blocks or None), converse_messages


def _extract_text(response: dict) -> str:
    """
    Pull assistant text out of a Converse response.
    Text lives at response["output"]["message"]["content"][0]["text"].
    An empty (or missing) content list returns "" rather than raising IndexError.
    """
    try:
        content = response["output"]["message"]["content"]
    except (KeyError, TypeError):
        return ""
    if not content:
        return ""
    return content[0].get("text", "") or ""


def _map_usage(response: dict) -> dict:
    """Map Converse's inputTokens/outputTokens/totalTokens to B180's usage keys."""
    usage = response.get("usage") or {}
    return {
        "prompt_tokens": usage.get("inputTokens", 0) or 0,
        "completion_tokens": usage.get("outputTokens", 0) or 0,
        "total_tokens": usage.get("totalTokens", 0) or 0,
    }


def _looks_like_inference_profile_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _INFERENCE_PROFILE_ERROR_MARKERS)


class BedrockLLMClient:
    """
    Wraps a boto3 bedrock-runtime client's converse() call behind the same
    interface as LLMClient, so callers holding an LLMClientProtocol don't need
    to know or care which provider they actually have.
    """

    def __init__(self, client, model: str):
        self._client = client
        self._model = model
        self.last_usage: dict | None = None

    # -- request building -----------------------------------------------

    def _build_request(self, messages: list[dict], temperature: float) -> dict:
        system, converse_messages = _to_converse_messages(messages)

        request: dict = {
            "modelId": self._model,
            "messages": converse_messages,
            "inferenceConfig": {"temperature": temperature},
        }
        if system:
            request["system"] = system
        return request

    def _converse(self, messages: list[dict], temperature: float = 0.0) -> dict:
        request = self._build_request(messages, temperature)
        try:
            return self._client.converse(**request)
        except Exception as e:  # noqa: BLE001 — translate, then re-raise
            raise self._translate_error(e) from e

    def _translate_error(self, e: Exception) -> Exception:
        """
        Detect the "bare model id needs an inference profile" validation
        error and raise a message naming the likely fix instead of surfacing
        the raw boto error, which does not explain the problem.
        """
        message = str(e)
        if _looks_like_inference_profile_error(message):
            return BedrockInferenceProfileError(
                f"Bedrock rejected model id '{self._model}'. Many current models "
                "(e.g. Claude, Llama) are only invocable through a cross-region "
                "inference profile, not the bare model id. Try prefixing the model "
                f"id with a geography, e.g. 'us.{self._model}', 'eu.{self._model}', "
                f"or 'apac.{self._model}' — see the 'Cross-region inference' section "
                "of the Bedrock model catalog for the exact inference-profile id. "
                f"(original error: {message})"
            )
        return e

    # -- protocol surface --------------------------------------------------

    def chat(self, messages: list[dict], **kwargs) -> str:
        """
        Synchronous chat — blocks the calling thread.
        Use achat() from async code to avoid blocking the event loop.
        """
        temperature = kwargs.pop("temperature", 0.0)
        response = self._converse(messages, temperature=temperature)
        self.last_usage = _map_usage(response)
        return _extract_text(response)

    def chat_with_usage(self, messages: list[dict]) -> tuple[str, dict]:
        """B180: Synchronous chat that also returns token usage."""
        response = self._converse(messages)
        usage = _map_usage(response)
        self.last_usage = usage
        return _extract_text(response), usage

    async def achat(self, messages: list[dict]) -> str:
        """Async chat — offloads the blocking network call to a thread pool."""
        return await asyncio.to_thread(self.chat, messages)

    async def achat_with_usage(self, messages: list[dict]) -> tuple[str, dict]:
        """B180: Async chat that also returns token usage."""
        return await asyncio.to_thread(self.chat_with_usage, messages)


def create_bedrock_client(
    llm_cfg: dict,
    model: str,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
):
    """
    Build a BedrockLLMClient over boto3's bedrock-runtime client.

    Auth uses boto3's default credential chain (no api_key config key exists
    for this provider): the ECS task role in deployment, or the developer's
    local profile/SSO/env credentials otherwise.

    llm_cfg keys read:
        region   — optional; falls back to AWS_REGION / AWS_DEFAULT_REGION / boto3 default
        profile  — optional, local dev only; selects a named AWS CLI profile

    timeout_seconds / max_retries honor the same config keys every other
    provider reads, mapped onto botocore's Config(read_timeout=..., retries=...).
    """
    boto3, BotocoreConfig, _ClientError = _import_boto3()

    region = (
        llm_cfg.get("region")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )
    profile = llm_cfg.get("profile")

    config_kwargs: dict = {}
    if timeout_seconds is not None:
        config_kwargs["read_timeout"] = timeout_seconds
    if max_retries is not None:
        config_kwargs["retries"] = {"max_attempts": max_retries}
    botocore_config = BotocoreConfig(**config_kwargs) if config_kwargs else None

    session_kwargs: dict = {}
    if profile:
        session_kwargs["profile_name"] = profile
    session = boto3.Session(**session_kwargs)

    client_kwargs: dict = {}
    if region:
        client_kwargs["region_name"] = region
    if botocore_config is not None:
        client_kwargs["config"] = botocore_config

    try:
        bedrock_client = session.client("bedrock-runtime", **client_kwargs)
    except Exception as e:
        raise BedrockConfigError(f"Could not create Bedrock client: {e}") from e

    return BedrockLLMClient(bedrock_client, model)
