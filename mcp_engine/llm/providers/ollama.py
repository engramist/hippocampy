"""Ollama provider — OpenAI-SDK-compatible, points to localhost."""

from openai import OpenAI


class OllamaClient:
    def __init__(self, config: dict):
        llm = config["llm"]
        self.model = llm["model"]
        self.client = OpenAI(
            base_url=llm.get("base_url", "http://localhost:11434/v1"),
            api_key="ollama",  # Ollama ignores this but OpenAI SDK requires it
        )

    def chat(self, messages: list[dict], **kwargs) -> str:
        """Send messages, return assistant response text."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs
        )
        return response.choices[0].message.content

    def smoke_test(self) -> bool:
        """Verify Ollama is reachable and the configured model is available."""
        try:
            result = self.chat([{"role": "user", "content": "ping"}], max_tokens=5)
            return bool(result)
        except Exception as e:
            print(f"Ollama smoke test failed: {e}")
            return False
