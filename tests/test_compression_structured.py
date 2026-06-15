# tests/test_compression_structured.py
import json
import pytest
from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression.structured_data import StructuredDataCompressor


def _section(content: list[dict]) -> BundleSection:
    return BundleSection(
        section_type="exact_fact",
        content=content,
        token_estimate=len(json.dumps(content)),
        source_node_ids=[],
    )


def test_toon_reduces_tokens():
    content = [
        {"key": "auth_provider", "value": "JWT", "node_type": "GlobalConstraint"},
        {"key": "session_timeout", "value": "3600", "node_type": "GlobalPreference"},
        {"key": "db_host", "value": "localhost", "node_type": "GlobalConstraint"},
    ]
    section = _section(content)
    original_tokens = section.token_estimate

    compressor = StructuredDataCompressor({})
    result = compressor.compress(section, "auth config", {})

    assert result.token_estimate < original_tokens
    assert result.section_type == "exact_fact"
    assert result.content  # not empty


def test_toon_output_contains_field_names_once():
    content = [
        {"key": "x", "value": "1", "node_type": "GlobalConstraint"},
        {"key": "y", "value": "2", "node_type": "GlobalConstraint"},
    ]
    section = _section(content)
    compressor = StructuredDataCompressor({})
    result = compressor.compress(section, "", {})
    # TOON format: field names in header, not repeated per row
    text = result.content[0]["toon"] if result.content else ""
    assert text.count("key") <= 1  # appears in header only, not per row


def test_empty_content_returns_section_unchanged():
    section = _section([])
    compressor = StructuredDataCompressor({})
    result = compressor.compress(section, "", {})
    assert result.content == []
