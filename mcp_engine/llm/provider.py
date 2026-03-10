"""
mcp_engine/llm/provider.py — LLM Provider Abstraction

All LLM calls use the OpenAI SDK wire format so Ollama and cloud providers
share the same code path (only base_url and api_key differ).

Interface:
    client = create_llm_client(config)
    response_text = client.chat([{"role": "user", "content": "..."}])

Supported providers (configured in sidequests.toml [llm] section):
    ollama      → local Ollama server (OpenAI-compatible API)
    openai      → OpenAI cloud API
    anthropic   → Anthropic cloud API (via openai-compatible shim)
    google      → Google Gemini (via openai-compatible endpoint)

Returns None from create_llm_client() if provider is unavailable —
callers must handle None gracefully (graceful degradation to System 1 only).
"""

import os


class LLMClient:
    """
    Thin synchronous wrapper around an OpenAI-SDK-compatible chat endpoint.
    Synchronous because Loop steps run in the asyncio event loop thread
    (Ollama latency is acceptable for the expected message rate).
    """

    def __init__(self, client, model: str):
        self._client = client
        self._model  = model

    def chat(self, messages: list[dict]) -> str:
        """
        Send a chat request. Returns the response content as a string.
        Raises on connection/timeout errors — callers should catch Exception.
        """
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.0,
        )
        return response.choices[0].message.content or ""


def create_llm_client(config: dict):
    """
    Factory. Returns an LLMClient instance or None if unavailable.

    Config keys read from config["llm"]:
        provider  — "ollama" | "openai" | "anthropic" | "google"
        model     — model identifier string
        base_url  — required for ollama; optional override for others
        api_key   — cloud providers: read from env var if not set
    """
    llm_cfg  = config.get("llm", {})
    provider = llm_cfg.get("provider", "ollama").lower()
    model    = llm_cfg.get("model", "llama3.1:8b")

    try:
        from openai import OpenAI

        if provider == "ollama":
            base_url = llm_cfg.get("base_url", "http://localhost:11434/v1")
            # Ollama does not require a real API key
            client = OpenAI(base_url=base_url, api_key="ollama")
            return LLMClient(client, model)

        if provider == "openai":
            api_key = llm_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
            client = OpenAI(api_key=api_key)
            return LLMClient(client, model)

        if provider == "anthropic":
            # Anthropic has an OpenAI-compatible endpoint via the API gateway
            base_url = llm_cfg.get("base_url", "https://api.anthropic.com/v1")
            api_key  = llm_cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
            client = OpenAI(base_url=base_url, api_key=api_key)
            return LLMClient(client, model)

        if provider == "google":
            base_url = llm_cfg.get(
                "base_url",
                "https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            api_key = llm_cfg.get("api_key") or os.environ.get("GOOGLE_API_KEY", "")
            client = OpenAI(base_url=base_url, api_key=api_key)
            return LLMClient(client, model)

        print(f"[LLM] Unknown provider '{provider}'. Loop will run in degraded mode.")
        return None

    except Exception as e:
        print(f"[LLM] Could not initialize provider '{provider}': {e}. "
              f"Loop will run in degraded mode (System 1 only).")
        return None
