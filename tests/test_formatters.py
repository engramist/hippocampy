"""
tests/test_formatters.py — Tests for Agent Output Formatters
"""

from __future__ import annotations

import json

import pytest

from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle
from campy.brain.thalamus.formatters import (
    format_bundle,
    get_formatter,
    ArcFormatter,
    ChatGPTDesktopFormatter,
    ClaudeCodeFormatter,
    ClaudeDesktopFormatter,
    CodexFormatter,
    GenericFormatter,
)


@pytest.fixture
def sample_bundle() -> ContextBundle:
    """Create a sample ContextBundle for testing."""
    section1 = BundleSection(
        section_type="exact_fact",
        content=[
            {"text": "Decision: Use Kuzu for graph storage", "type": "Decision", "confidence": 0.95}
        ],
        token_estimate=50,
        source_node_ids=["node1"],
    )
    section2 = BundleSection(
        section_type="semantic",
        content=[
            {"text": "Similar project used embedded database", "type": "Concept", "pathway_strength": 0.8, "confidence": 0.85}
        ],
        token_estimate=100,
        source_node_ids=["node2"],
    )
    
    return ContextBundle(
        query="Should we use Kuzu?",
        sections=[section1, section2],
        total_token_estimate=150,
        token_budget=1000,
        truncated=False,
        sources=["source1", "source2"],
        compilation_ms=42.5,
    )


class TestGenericFormatter:
    """Test generic JSON formatter."""

    def test_generic_formatter_name(self):
        """Test formatter name."""
        formatter = GenericFormatter()
        assert formatter.name == "generic"

    def test_generic_formatter_returns_json(self, sample_bundle):
        """Test that generic formatter returns valid JSON."""
        formatter = GenericFormatter()
        result = formatter.format(sample_bundle)
        
        parsed = json.loads(result)
        assert parsed["query"] == "Should we use Kuzu?"
        assert len(parsed["sections"]) == 2

    def test_generic_formatter_includes_all_fields(self, sample_bundle):
        """Test that all fields are included in JSON."""
        formatter = GenericFormatter()
        result = formatter.format(sample_bundle)
        
        parsed = json.loads(result)
        assert "query" in parsed
        assert "total_token_estimate" in parsed
        assert "token_budget" in parsed
        assert "truncated" in parsed
        assert "sources" in parsed


class TestClaudeCodeFormatter:
    """Test Claude Code markdown formatter."""

    def test_claude_code_formatter_name(self):
        """Test formatter name."""
        formatter = ClaudeCodeFormatter()
        assert formatter.name == "claude_code"

    def test_claude_code_formatter_returns_string(self, sample_bundle):
        """Test that formatter returns a string."""
        formatter = ClaudeCodeFormatter()
        result = formatter.format(sample_bundle)
        assert isinstance(result, str)

    def test_claude_code_formatter_includes_headers(self, sample_bundle):
        """Test that markdown includes section headers."""
        formatter = ClaudeCodeFormatter()
        result = formatter.format(sample_bundle)
        
        assert "# Context:" in result
        assert "## Exact Facts" in result
        assert "## Relevant Memory" in result

    def test_claude_code_formatter_includes_content(self, sample_bundle):
        """Test that content is included."""
        formatter = ClaudeCodeFormatter()
        result = formatter.format(sample_bundle)
        
        assert "Kuzu" in result
        assert "confidence" in result.lower()

    def test_claude_code_formatter_is_markdown(self, sample_bundle):
        """Test that output looks like markdown."""
        formatter = ClaudeCodeFormatter()
        result = formatter.format(sample_bundle)
        
        assert "#" in result  # Headers
        assert "-" in result  # Bullet points
