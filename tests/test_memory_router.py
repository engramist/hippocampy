"""
tests/test_memory_router.py — Tests for Memory Router Classification
"""

from __future__ import annotations

import json

import pytest

from mcp_engine.memory_router import (
    DOCUMENT_EXTENSIONS,
    TABULAR_EXTENSIONS,
    MemoryRoute,
    _looks_tabular,
    classify_input,
)


class TestMemoryRoute:
    """Test MemoryRoute dataclass."""

    def test_memory_route_creation(self):
        """Test MemoryRoute instantiation."""
        route = MemoryRoute(
            storage_type="tabular",
            reason="CSV file",
            confidence=0.95,
            suggested_tool="ingest_tabular"
        )
        assert route.storage_type == "tabular"
        assert route.confidence == 0.95


class TestExtensionConstants:
    """Test extension constants."""

    def test_tabular_extensions(self):
        """Test TABULAR_EXTENSIONS set."""
        assert ".csv" in TABULAR_EXTENSIONS
        assert ".xlsx" in TABULAR_EXTENSIONS
        assert ".tsv" in TABULAR_EXTENSIONS

    def test_document_extensions(self):
        """Test DOCUMENT_EXTENSIONS set."""
        assert ".md" in DOCUMENT_EXTENSIONS
        assert ".txt" in DOCUMENT_EXTENSIONS
        assert ".py" in DOCUMENT_EXTENSIONS


class TestLooksTabular:
    """Test _looks_tabular heuristic."""

    def test_csv_like_content(self):
        """Test CSV-like content detection."""
        csv_content = "name,age,department\nAlice,30,Eng\nBob,25,Sales"
        assert _looks_tabular(csv_content) is True

    def test_tsv_like_content(self):
        """Test TSV-like content detection."""
        tsv_content = "name\tage\tdepartment\nAlice\t30\tEng\nBob\t25\tSales"
        assert _looks_tabular(tsv_content) is True

    def test_json_array_content(self):
        """Test JSON array detection."""
        json_content = json.dumps([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25}
        ])
        assert _looks_tabular(json_content) is True

    def test_conversational_content(self):
        """Test that normal text is not detected as tabular."""
        text = "This is a normal conversational message about meetings and plans."
        assert _looks_tabular(text) is False

    def test_short_content(self):
        """Test that short content is not detected as tabular."""
        short = "a,b\n1,2"  # Only 2 lines
        assert _looks_tabular(short) is False


class TestFileExtensionRouting:
    """Test routing based on file extensions."""

    def test_csv_extension_routes_to_tabular(self):
        """Test CSV file → tabular route."""
        route = classify_input(file_path="/path/to/file.csv")
        assert route.storage_type == "tabular"
        assert route.suggested_tool == "ingest_tabular"
        assert route.confidence == 0.95

    def test_xlsx_extension_routes_to_tabular(self):
        """Test XLSX file → tabular route."""
        route = classify_input(file_path="/path/to/file.xlsx")
        assert route.storage_type == "tabular"
        assert route.confidence == 0.95

    def test_tsv_extension_routes_to_tabular(self):
        """Test TSV file → tabular route."""
        route = classify_input(file_path="/path/to/file.tsv")
        assert route.storage_type == "tabular"

    def test_markdown_extension_routes_to_document(self):
        """Test MD file → document route."""
        route = classify_input(file_path="/path/to/file.md")
        assert route.storage_type == "document"
        assert route.suggested_tool == "ingest_document"
        assert route.confidence == 0.95

    def test_python_extension_routes_to_document(self):
        """Test PY file → document route."""
        route = classify_input(file_path="/path/to/file.py")
        assert route.storage_type == "document"

    def test_json_extension_routes_to_document(self):
        """Test JSON file → document route."""
        route = classify_input(file_path="/path/to/file.json")
        assert route.storage_type == "document"

    def test_unknown_extension_uses_other_rules(self):
        """Test that unknown extension falls through to other rules."""
        route = classify_input(file_path="/path/to/file.unknown", content="short text")
        assert route.storage_type == "graph"
        assert route.suggested_tool == "notify_turn"


class TestMimeTypeRouting:
    """Test routing based on MIME type."""

    def test_csv_mime_routes_to_tabular(self):
        """Test CSV MIME type → tabular route."""
        route = classify_input(mime_type="text/csv")
        assert route.storage_type == "tabular"
        assert route.confidence == 0.90

    def test_spreadsheet_mime_routes_to_tabular(self):
        """Test spreadsheet MIME type → tabular route."""
        route = classify_input(mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        assert route.storage_type == "tabular"

    def test_text_mime_routes_to_document(self):
        """Test text MIME type → document route."""
        route = classify_input(mime_type="text/plain")
        assert route.storage_type == "document"
        assert route.confidence >= 0.80


class TestContentStructureRouting:
    """Test routing based on content structure."""

    def test_tabular_content_routes_to_tabular(self):
        """Test CSV-like content → tabular route."""
        csv_content = "col1,col2,col3\n1,2,3\n4,5,6\n7,8,9"
        route = classify_input(content=csv_content)
        assert route.storage_type == "graph+tabular"
        assert route.confidence == 0.75

    def test_long_content_routes_to_document(self):
        """Test long content (>2000 chars) → document route."""
        long_content = "a" * 2500
        route = classify_input(content=long_content)
        assert route.storage_type == "document"
        assert route.confidence == 0.70

    def test_short_conversational_content_routes_to_graph(self):
        """Test short conversational text → graph route."""
        short = "This is a brief note about today's meeting."
        route = classify_input(content=short)
        assert route.storage_type == "graph"
        assert route.suggested_tool == "notify_turn"


class TestPriorityOrder:
    """Test that rules are applied in priority order."""

    def test_file_extension_overrides_content(self):
        """Test that file extension takes precedence over content."""
        # CSV file with conversational content
        route = classify_input(
            file_path="/path/to/file.csv",
            content="This is just a message, not really tabular data"
        )
        assert route.storage_type == "tabular"
        assert route.confidence == 0.95  # Extension wins

    def test_mime_type_overrides_content(self):
        """Test that MIME type takes precedence over content inference."""
        route = classify_input(
            mime_type="text/csv",
            content="just some text"
        )
        assert route.storage_type == "tabular"
        assert route.confidence == 0.90

    def test_extension_overrides_mime_type(self):
        """Test that extension takes precedence over MIME type."""
        route = classify_input(
            file_path="/path/to/file.csv",
            mime_type="text/plain"
        )
        assert route.storage_type == "tabular"
        assert route.confidence == 0.95  # Extension (0.95) > MIME (0.90)


class TestDefaultBehavior:
    """Test default behavior when no rules match."""

    def test_no_context_defaults_to_graph(self):
        """Test that empty input defaults to graph storage."""
        route = classify_input()
        assert route.storage_type == "graph"
        assert route.suggested_tool == "notify_turn"
        assert route.confidence == 0.60

    def test_unknown_file_without_content_defaults_to_graph(self):
        """Test unknown file with no content → graph."""
        route = classify_input(file_path="/path/to/unknown")
        assert route.storage_type == "graph"

    def test_short_text_defaults_to_graph(self):
        """Test short text defaults to graph."""
        route = classify_input(content="brief message")
        assert route.storage_type == "graph"


class TestConfidenceLevels:
    """Test confidence scores."""

    def test_extension_has_high_confidence(self):
        """Test that extension-based routing has high confidence."""
        route = classify_input(file_path="/path/to/file.csv")
        assert route.confidence == 0.95

    def test_mime_type_has_medium_high_confidence(self):
        """Test that MIME type routing has medium-high confidence."""
        route = classify_input(mime_type="text/csv")
        assert route.confidence == 0.90

    def test_content_detection_has_medium_confidence(self):
        """Test that content detection has medium confidence."""
        route = classify_input(content="a,b,c\n1,2,3\n4,5,6")
        assert route.confidence == 0.75

    def test_default_has_low_confidence(self):
        """Test that default routing has low confidence."""
        route = classify_input()
        assert route.confidence == 0.60


class TestReasonMessages:
    """Test that reason messages are informative."""

    def test_reason_includes_extension(self):
        """Test that reason mentions the detected extension."""
        route = classify_input(file_path="/path/to/file.csv")
        assert ".csv" in route.reason

    def test_reason_includes_mime_type(self):
        """Test that reason mentions the MIME type."""
        route = classify_input(mime_type="text/csv")
        assert "text/csv" in route.reason or "tabular" in route.reason

    def test_reason_describes_content_detection(self):
        """Test that reason explains content detection."""
        route = classify_input(content="a,b\n1,2\n3,4")
        assert "structure" in route.reason.lower()


class TestEdgeCases:
    """Test edge cases and corner cases."""

    def test_mixed_case_extension(self):
        """Test that extensions are case-insensitive."""
        route1 = classify_input(file_path="/path/to/file.CSV")
        route2 = classify_input(file_path="/path/to/file.csv")
        assert route1.storage_type == route2.storage_type
        assert route1.suggested_tool == route2.suggested_tool

    def test_empty_string_content(self):
        """Test handling of empty string content."""
        route = classify_input(content="")
        assert route.storage_type == "graph"

    def test_whitespace_only_content(self):
        """Test handling of whitespace-only content."""
        route = classify_input(content="   \n  \n  ")
        assert route.storage_type == "graph"

    def test_very_long_path(self):
        """Test handling of very long file paths."""
        long_path = "/very/long/path/" * 10 + "file.csv"
        route = classify_input(file_path=long_path)
        assert route.storage_type == "tabular"

    def test_special_characters_in_mime_type(self):
        """Test handling of MIME types with special characters."""
        route = classify_input(mime_type="application/vnd.ms-excel")
        assert route.storage_type == "tabular"


class TestIntegration:
    """Integration tests for classify_input."""

    def test_typical_csv_file_workflow(self):
        """Test typical CSV file ingestion scenario."""
        route = classify_input(
            file_path="budget_2024_Q1.csv",
            mime_type="text/csv"
        )
        assert route.storage_type == "tabular"
        assert route.suggested_tool == "ingest_tabular"
        assert route.confidence == 0.95

    def test_typical_python_file_workflow(self):
        """Test typical Python file ingestion scenario."""
        route = classify_input(
            file_path="src/utils/helpers.py",
            mime_type="text/x-python"
        )
        assert route.storage_type == "document"
        assert route.suggested_tool == "ingest_document"

    def test_typical_conversational_workflow(self):
        """Test typical conversational text scenario."""
        route = classify_input(
            content="I think we should use Kuzu for the graph database."
        )
        assert route.storage_type == "graph"
        assert route.suggested_tool == "notify_turn"

    def test_ambiguous_json_data_workflow(self):
        """Test JSON-like structured data."""
        json_str = json.dumps([
            {"id": 1, "name": "Item1"},
            {"id": 2, "name": "Item2"}
        ])
        route = classify_input(content=json_str)
        assert route.storage_type == "graph+tabular"
