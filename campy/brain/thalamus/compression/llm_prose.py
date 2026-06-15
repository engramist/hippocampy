"""
campy/brain/thalamus/compression/llm_prose.py

LLMCompressor — compresses prose sections using Campy's existing LLMClient.

Fires only when the section contains prose (summary, semantic text). Uses
the configured compression_model (defaults to the main LLM to avoid loading
a second model). Set compression_model = "claude-3-5-haiku" or an Ollama
model in [compression] to run compression cheaply.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection

_COMPRESSION_PROMPT = (
    "Compress the following text. Rules:\n"
    "1. Preserve every entity name, decision, file path, number, and negation verbatim.\n"
    "2. Eliminate filler phrases, connective tissue, and redundant transitions.\n"
    "3. Do not alter semantic intent. Do not invent new facts.\n"
    "4. Return only the compressed text, no preamble.\n\n"
    "Text:\n{text}"
)


class LLMCompressor(Compressor):
    """Compresses prose via LLMClient. Skips if content is empty."""

    def __init__(self, config: dict, llm_override=None) -> None:
        self._config = config
        self._llm_override = llm_override  # injected in tests

    def _get_llm(self):
        if self._llm_override is not None:
            return self._llm_override
        from mcp_engine.llm.provider import create_llm_client
        compression_model = self._config.get("compression", {}).get("compression_model", "")
        cfg = dict(self._config)
        if compression_model:
            cfg = dict(cfg)
            cfg.setdefault("llm", {})
            cfg["llm"] = dict(cfg.get("llm", {}))
            cfg["llm"]["model"] = compression_model
        return create_llm_client(cfg)

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        from campy.brain.thalamus.bundle_compiler import BundleSection as BS

        if not section.content:
            return section

        prose = " ".join(
            item.get("text", "") for item in section.content if isinstance(item, dict)
        ).strip()
        if not prose:
            return section

        try:
            llm = self._get_llm()
            if llm is None:
                return section
            messages = [
                {"role": "user", "content": _COMPRESSION_PROMPT.format(text=prose)}
            ]
            compressed = llm.chat(messages)
            token_estimate = len(compressed) // 4
            return BS(
                section_type=section.section_type,
                content=[{"text": compressed}],
                token_estimate=token_estimate,
                source_node_ids=section.source_node_ids,
            )
        except Exception:
            return section  # fail-safe
