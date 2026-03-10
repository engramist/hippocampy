"""
mcp_engine/llm/provider.py — LLM Provider Factory

All LLM calls use OpenAI-SDK-compatible interface.
Only base_url and api_key differ between providers.
"""

import os


def get_client(config: dict):
    """Return the configured LLM client."""
    provider = config["llm"]["provider"]

    if provider == "ollama":
        from mcp_engine.llm.providers.ollama import OllamaClient
        return OllamaClient(config)

    elif provider == "openai":
        from openai import OpenAI
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    elif provider == "anthropic":
        from openai import OpenAI
        return OpenAI(
            base_url="https://api.anthropic.com/v1",
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )

    elif provider == "google":
        from openai import OpenAI
        return OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=os.environ["GOOGLE_API_KEY"],
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. "
                         f"Expected: ollama | openai | anthropic | google")
