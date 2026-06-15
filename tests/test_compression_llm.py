# tests/test_compression_llm.py
import pytest
from unittest.mock import MagicMock
from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression.llm_prose import LLMCompressor


def _prose_section(text: str) -> BundleSection:
    return BundleSection(
        section_type="summary",
        content=[{"text": text}],
        token_estimate=len(text) // 4,
        source_node_ids=[],
    )


def _make_compressor(response: str) -> tuple[LLMCompressor, MagicMock]:
    mock_llm = MagicMock()
    mock_llm.chat.return_value = response
    compressor = LLMCompressor({}, llm_override=mock_llm)
    return compressor, mock_llm


def test_prose_section_is_compressed():
    long_prose = "We decided that all authentication calls should use JWT tokens. " * 20
    section = _prose_section(long_prose)
    compressed_text = "JWT tokens for auth."
    compressor, mock_llm = _make_compressor(compressed_text)

    result = compressor.compress(section, "auth decision", {})

    mock_llm.chat.assert_called_once()
    assert result.content[0]["text"] == compressed_text
    assert result.token_estimate < section.token_estimate


def test_empty_section_skips_llm_call():
    section = BundleSection(
        section_type="summary", content=[], token_estimate=0, source_node_ids=[]
    )
    compressor, mock_llm = _make_compressor("")
    result = compressor.compress(section, "", {})
    mock_llm.chat.assert_not_called()
    assert result.content == []


def test_compression_prompt_preserves_entities():
    compressor, mock_llm = _make_compressor("JWT auth decision.")
    section = _prose_section("we use JWT tokens")
    compressor.compress(section, "auth", {})
    call_args = mock_llm.chat.call_args[0][0]  # messages list
    user_content = next(m["content"] for m in call_args if m["role"] == "user")
    assert "entity names" in user_content.lower() or "verbatim" in user_content.lower()
