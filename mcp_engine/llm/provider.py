"""
mcp_engine/llm/provider.py — LLM Provider Abstraction

All LLM calls use an OpenAI-SDK-compatible interface.
Ollama and cloud providers share the same code path — only base_url and api_key differ.

Config loaded from sidequests.toml [llm] section:
  provider = "ollama" | "openai" | "anthropic" | "google"
  model    = "llama3.1:8b" (or any model supported by the provider)
  base_url = "http://localhost:11434"  (Ollama only)
  api_key  = loaded from env var (cloud providers only)

Env vars: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY

Ollama recommended for real-time Loop steps (Steps 2 + 6) due to latency.
Cloud providers acceptable for document ingestion (Open Brain, M6).

M1 scope: implement get_client() factory + smoke test connection.
"""


def get_client(config: dict):
    """
    Return an OpenAI-SDK-compatible client for the configured provider.
    All providers expose the same .chat.completions.create() interface.
    """
    provider = config["llm"]["provider"]
    if provider == "ollama":
        from mcp_engine.llm.providers.ollama import OllamaClient
        return OllamaClient(config)
    elif provider == "openai":
        from mcp_engine.llm.providers.openai import OpenAIClient
        return OpenAIClient(config)
    elif provider == "anthropic":
        from mcp_engine.llm.providers.anthropic import AnthropicClient
        return AnthropicClient(config)
    elif provider == "google":
        from mcp_engine.llm.providers.google import GoogleClient
        return GoogleClient(config)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
