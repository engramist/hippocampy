"""
campy/brain/llm/provider.py — LLM Provider Abstraction

All LLM calls use the OpenAI SDK wire format so Ollama and cloud providers
share the same code path (only base_url and api_key differ).

Interface:
    client = create_llm_client(config)
    response_text = client.chat([{"role": "user", "content": "..."}])

    # B16: Per-step routing
    client = create_llm_client_for_step(config, step_name)

Supported providers (configured in campy.toml [llm] section):
    ollama      → local Ollama server (OpenAI-compatible API)
    openai      → OpenAI cloud API
    anthropic   → Anthropic cloud API (via openai-compatible shim)
    google      → Google Gemini (via openai-compatible endpoint)
    bedrock     → AWS Bedrock (via boto3 Converse API — B324; see campy/brain/llm/bedrock.py)

Returns None from create_llm_client() if provider is unavailable —
callers must handle None gracefully (graceful degradation to System 1 only).

B324 — Provider Protocol:
    create_llm_client()/create_llm_client_for_step() are typed to return
    LLMClientProtocol rather than the concrete LLMClient class. Bedrock does
    not speak the OpenAI chat-completions wire format (SigV4 auth, Converse
    request/response shapes), so it is implemented as a sibling class
    (BedrockLLMClient in campy/brain/llm/bedrock.py) satisfying the same
    protocol rather than as another OpenAI(base_url=...) branch. Callers that
    only use chat()/chat_with_usage()/achat()/achat_with_usage()/last_usage
    work unmodified against either implementation.

B16 — Task-Based Model Routing:
    Per-step LLM overrides use a merged config strategy.
    Presence of [llm.step_name] in campy.toml overrides provider/model/base_url/api_key
    for that step while inheriting any keys not explicitly set in the override block.

    Step name keys (matching campy.toml override block names):
        step2_gist          — System 1/2 classification (tractable for small models)
        step3b_relations    — Relation extraction with type context (tractable for small models)
        step6_arbitration   — Contradiction arbitration (benefits most from frontier models)
        quest_purpose       — Quest purpose synthesis
        tabular_ingest      — Dataset summary + key-fact extraction (B250)
"""

import hashlib
import logging
import os
from typing import Protocol, runtime_checkable

_logger = logging.getLogger(__name__)


@runtime_checkable
class LLMClientProtocol(Protocol):
    """
    B324 — Interface every LLM client implementation must satisfy.

    Captures exactly what callers touch across the codebase (verified by
    grepping for `create_llm_client`, `create_llm_client_for_step`, and
    `last_usage` under campy/): chat(), chat_with_usage(), achat(),
    achat_with_usage(), and the last_usage attribute used by B180's token
    tracking. create_llm_client()/create_llm_client_for_step() are typed to
    return this protocol rather than the concrete LLMClient class so that a
    non-OpenAI-wire-format implementation (e.g. BedrockLLMClient) can stand
    in without callers needing to know which concrete class they hold.
    """

    last_usage: dict | None

    def chat(self, messages: list[dict], **kwargs) -> str: ...

    def chat_with_usage(self, messages: list[dict], **kwargs) -> tuple[str, dict]: ...

    async def achat(self, messages: list[dict], **kwargs) -> str: ...

    async def achat_with_usage(self, messages: list[dict], **kwargs) -> tuple[str, dict]: ...


def _resolve_timeout_seconds(provider: str, llm_cfg: dict) -> float | None:
    """Return the configured request timeout, with safer defaults for local Ollama."""
    raw_timeout = llm_cfg.get("timeout_seconds")
    if raw_timeout in (None, ""):
        return 180.0 if provider == "ollama" else None
    try:
        return float(raw_timeout)
    except (TypeError, ValueError):
        return 180.0 if provider == "ollama" else None


def _resolve_max_retries(provider: str, llm_cfg: dict) -> int | None:
    """Return the configured retry count, with a slightly more forgiving Ollama default."""
    raw_retries = llm_cfg.get("max_retries")
    if raw_retries in (None, ""):
        return 3 if provider == "ollama" else None
    try:
        return int(raw_retries)
    except (TypeError, ValueError):
        return 3 if provider == "ollama" else None


DEFAULT_MAX_TOKENS = 2048


def resolve_max_tokens(llm_cfg: dict) -> int | None:
    """
    B494: output-token cap for every completion. ``[llm] max_tokens`` (default
    2048); 0 or negative disables the cap (returns None). A malformed value
    falls back to the default rather than raising.
    """
    raw = llm_cfg.get("max_tokens")
    if raw in (None, ""):
        return DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_TOKENS
    return value if value > 0 else None


def log_truncated(provider_label: str, model: str, cap, messages: list[dict]) -> None:
    """B494: warn that a completion hit the output cap, identifying the question without its text."""
    last_user = ""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content")
            last_user = content if isinstance(content, str) else str(content)
            break
    # B519: no raw user text in daemon.log; length and a short hash identify the question.
    digest = hashlib.sha256(last_user.encode("utf-8", "replace")).hexdigest()[:12]
    _logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
        "[LLM] %s/%s hit the output cap (max_tokens=%s); response truncated. "
        "Last user message: %d chars, sha256 %s",
        provider_label, model, cap, len(last_user), digest,
    )


class LLMClient:
    """
    Wrapper around an OpenAI-SDK-compatible chat endpoint.
    Provides both sync chat() for backward compat and async achat()
    that offloads the blocking network call to a thread pool.

    B494: every request carries max_tokens (``[llm] max_tokens``, default 2048)
    so a degenerate repetition cannot run until the request timeout. A call can
    override the cap with ``max_tokens=`` in kwargs.
    """

    def __init__(self, client, model: str, max_tokens: int | None = DEFAULT_MAX_TOKENS,
                 provider: str = "openai"):
        self._client = client
        self._model  = model
        self._max_tokens = max_tokens
        self._provider = provider
        self.last_usage: dict | None = None

    def _create(self, messages: list[dict], **kwargs):
        kwargs = dict(kwargs)
        override = kwargs.pop("max_tokens", None)
        cap = override if override is not None else self._max_tokens
        if cap is not None and cap > 0:
            kwargs["max_tokens"] = cap
        kwargs.setdefault("temperature", 0.0)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            **kwargs
        )
        try:
            if response.choices[0].finish_reason == "length":
                log_truncated(self._provider, self._model, cap, messages)
        except (AttributeError, IndexError, TypeError):
            pass
        return response

    def chat(self, messages: list[dict], **kwargs) -> str:
        """
        Synchronous chat — blocks the calling thread.
        Use achat() from async code to avoid blocking the event loop.
        """
        response = self._create(messages, **kwargs)

        # B180: Track token usage if available
        if hasattr(response, 'usage') and response.usage:
            self.last_usage = {
                "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(response.usage, 'completion_tokens', 0),
                "total_tokens": getattr(response.usage, 'total_tokens', 0),
            }

        return response.choices[0].message.content or ""

    def chat_with_usage(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        """
        B180: Synchronous chat that also returns token usage.
        Returns (content, usage_dict).
        """
        response = self._create(messages, **kwargs)
        content = response.choices[0].message.content or ""
        usage = {
            "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0) if response.usage else 0,
            "completion_tokens": getattr(response.usage, 'completion_tokens', 0) if response.usage else 0,
            "total_tokens": getattr(response.usage, 'total_tokens', 0) if response.usage else 0,
        }
        return content, usage

    async def achat(self, messages: list[dict], **kwargs) -> str:
        """
        Async chat — offloads blocking LLM call to a thread pool.
        Use this from async code (loop steps, sweep, quest synthesis).
        Fixes S1: sync LLM calls were blocking the asyncio event loop.
        """
        import asyncio
        return await asyncio.to_thread(self.chat, messages, **kwargs)

    async def achat_with_usage(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        """
        B180: Async chat that also returns token usage.
        """
        import asyncio
        return await asyncio.to_thread(self.chat_with_usage, messages, **kwargs)


def create_llm_client(config: dict) -> LLMClientProtocol | None:
    """
    Factory. Returns a client satisfying LLMClientProtocol, or None if unavailable.

    Config keys read from config["llm"]:
        provider          — "ollama" | "openai" | "anthropic" | "google" | "bedrock"
        model             — model identifier string
        base_url          — required for ollama; optional override for others
        api_key           — cloud providers: read from env var if not set
        timeout_seconds   — optional request timeout for slow models / long reasoning
        max_retries       — optional retry count for transient provider errors
        max_tokens        — B494: output-token cap per call (default 2048; 0 = no cap)

    Bedrock-only keys (see campy/brain/llm/bedrock.py):
        region            — optional; falls back to AWS_REGION / boto3 default
        profile           — optional, local dev only; no api_key — auth uses
                             boto3's default credential chain (ECS task role
                             in deployment, developer's local profile otherwise)
    """
    llm_cfg  = config.get("llm", {})
    provider = llm_cfg.get("provider", "ollama").lower()
    model    = llm_cfg.get("model", "llama3.1:8b")

    client_options = {}
    timeout_seconds = _resolve_timeout_seconds(provider, llm_cfg)
    max_retries = _resolve_max_retries(provider, llm_cfg)
    max_tokens = resolve_max_tokens(llm_cfg)
    if timeout_seconds is not None:
        client_options["timeout"] = timeout_seconds
    if max_retries is not None:
        client_options["max_retries"] = max_retries

    try:
        from openai import OpenAI

        if provider == "ollama":
            base_url = llm_cfg.get("base_url", "http://localhost:11434/v1")
            # Ollama does not require a real API key
            client = OpenAI(base_url=base_url, api_key="ollama", **client_options)
            return LLMClient(client, model, max_tokens, provider)

        if provider == "openai":
            api_key = llm_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
            client = OpenAI(api_key=api_key, **client_options)
            return LLMClient(client, model, max_tokens, provider)

        if provider == "anthropic":
            # Anthropic has an OpenAI-compatible endpoint via the API gateway
            base_url = llm_cfg.get("base_url", "https://api.anthropic.com/v1")
            api_key  = llm_cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
            client = OpenAI(base_url=base_url, api_key=api_key, **client_options)
            return LLMClient(client, model, max_tokens, provider)

        if provider == "google":
            base_url = llm_cfg.get(
                "base_url",
                "https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            api_key = llm_cfg.get("api_key") or os.environ.get("GOOGLE_API_KEY", "")
            client = OpenAI(base_url=base_url, api_key=api_key, **client_options)
            return LLMClient(client, model, max_tokens, provider)

        if provider == "bedrock":
            # Bedrock does not speak the OpenAI chat-completions wire format
            # (SigV4 auth, Converse request/response shapes) — it is a sibling
            # class over boto3, not another OpenAI(base_url=...) branch.
            # Imported here (not at module top) so boto3 stays an optional
            # dependency: importing this module never requires boto3 unless
            # a caller actually asks for provider="bedrock".
            from campy.brain.llm.bedrock import create_bedrock_client
            return create_bedrock_client(llm_cfg, model, timeout_seconds, max_retries, max_tokens)

        print(f"[LLM] Unknown provider '{provider}'. Loop will run in degraded mode.")
        return None

    except Exception as e:
        print(f"[LLM] Could not initialize provider '{provider}': {e}. "
              f"Loop will run in degraded mode (System 1 only).")
        return None


# ---------------------------------------------------------------------------
# B16 — Task-Based Model Routing
# ---------------------------------------------------------------------------

def create_llm_client_for_step(config: dict, step_name: str) -> LLMClientProtocol | None:
    """
    Return a client (satisfying LLMClientProtocol) for the given loop step,
    honouring per-step overrides.

    Resolution order (first match wins):
      1. config["llm"][step_name] — per-step override block
      2. config["llm"]           — global default

    The per-step block is merged with the global block: only the keys present
    in the override (provider, model, base_url, api_key) are replaced; any
    key absent from the override inherits its value from the global block.

    This lets a minimal override like::

        [llm.step6_arbitration]
        provider = "anthropic"
        model    = "claude-sonnet-4-6"

    inherit base_url / api_key (loaded from env) from the global block without
    repeating them in every override section.

    Returns None if the resolved provider is unavailable.
    """
    base_cfg  = dict(config.get("llm", {}))
    step_cfg  = base_cfg.pop(step_name, None)   # pop to avoid nested dicts confusing create_llm_client

    if step_cfg:
        # Merge: start from global defaults, overlay step-specific keys
        merged_llm = {k: v for k, v in base_cfg.items() if not isinstance(v, dict)}
        merged_llm.update(step_cfg)
        merged_config = dict(config)
        merged_config["llm"] = merged_llm
    else:
        # No override — strip any nested step dicts and use globals
        clean_llm = {k: v for k, v in base_cfg.items() if not isinstance(v, dict)}
        merged_config = dict(config)
        merged_config["llm"] = clean_llm

    return create_llm_client(merged_config)
