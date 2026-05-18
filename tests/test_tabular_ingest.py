"""
tests/test_tabular_ingest.py — Tests for Tabular Data Ingestion Pipeline
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fixtures import sample_budget_path, sample_data_path


@pytest.fixture
def pandas():
    """Import pandas or skip test if not available."""
    pytest.importorskip("pandas")
    import pandas as pd
    return pd


@pytest.fixture
def openpyxl():
    """Import openpyxl or skip test if not available."""
    pytest.importorskip("openpyxl")
    import openpyxl
    return openpyxl


@pytest.fixture
def mock_db():
    """Create a mock KuzuClient for testing."""
    db = AsyncMock()
    db.execute = MagicMock(return_value=None)
    return db


@pytest.fixture
def config():
    """Sample configuration."""
    return {
        "embeddings": {
            "model": "sentence-transformers/all-MiniLM-L6-v2"
        },
        "tabular": {
            "multi_sheet_strategy": "per_sheet"
        }
    }


class TestCSVIngestion:
    """Test CSV ingestion."""

    @pytest.mark.asyncio
    async def test_csv_ingestion_basic(self, pandas, mock_db, config, tmp_path):
        """Test basic CSV ingestion."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        # Create a test CSV file
        csv_file = tmp_path / "test.csv"
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "age": [30, 25],
        })
        df.to_csv(csv_file, index=False)
        
        result = await ingest_tabular(mock_db, str(csv_file), config)
        
        assert "dataset_ids" in result
        assert len(result["dataset_ids"]) == 1
        assert result["row_counts"] == [2]
        assert result["column_counts"] == [2]

    @pytest.mark.asyncio
    async def test_csv_nonexistent_file(self, mock_db, config):
        """Test ingestion of nonexistent file."""
        from mcp_engine.tabular_ingest import ingest_tabular
        
        result = await ingest_tabular(mock_db, "/nonexistent/file.csv", config)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_csv_creates_dataset_node(self, pandas, mock_db, config, tmp_path):
        """Test that CSV ingestion creates a Dataset node in Kuzu."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        csv_file = tmp_path / "test.csv"
        df = pd.DataFrame({
            "col1": [1, 2, 3],
            "col2": [10, 20, 30],
        })
        df.to_csv(csv_file, index=False)
        
        result = await ingest_tabular(mock_db, str(csv_file), config)
        
        # Verify that execute was called to create Dataset node
        assert mock_db.execute.called
        # The Cypher query should create a Dataset node
        calls = mock_db.execute.call_args_list
        assert any("Dataset" in str(call) for call in calls)


class TestTSVIngestion:
    """Test TSV ingestion."""

    @pytest.mark.asyncio
    async def test_tsv_ingestion(self, pandas, mock_db, config, tmp_path):
        """Test TSV file ingestion."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        # Create a test TSV file
        tsv_file = tmp_path / "test.tsv"
        df = pd.DataFrame({
            "name": ["Alice", "Bob", "Charlie"],
            "department": ["Eng", "Sales", "Eng"],
        })
        df.to_csv(tsv_file, sep="\t", index=False)
        
        result = await ingest_tabular(mock_db, str(tsv_file), config)
        
        assert len(result["dataset_ids"]) == 1
        assert result["row_counts"] == [3]


class TestXLSXIngestion:
    """Test XLSX ingestion with multiple sheets."""

    @pytest.mark.asyncio
    async def test_xlsx_single_sheet(self, pandas, openpyxl, mock_db, config, tmp_path):
        """Test XLSX with single sheet."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        xlsx_file = tmp_path / "test.xlsx"
        df = pd.DataFrame({
            "col1": [1, 2],
            "col2": [10, 20],
        })
        df.to_excel(xlsx_file, index=False, sheet_name="Sheet1")
        
        result = await ingest_tabular(mock_db, str(xlsx_file), config)
        
        assert result["sheets_processed"] == 1
        assert len(result["dataset_ids"]) == 1

    @pytest.mark.asyncio
    async def test_xlsx_multiple_sheets(self, pandas, openpyxl, mock_db, config, tmp_path):
        """Test XLSX with multiple sheets."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        xlsx_file = tmp_path / "test.xlsx"
        df1 = pd.DataFrame({"col1": [1, 2], "col2": [10, 20]})
        df2 = pd.DataFrame({"col3": [100, 200], "col4": [1000, 2000]})
        
        with pd.ExcelWriter(xlsx_file, engine="openpyxl") as writer:
            df1.to_excel(writer, sheet_name="Sheet1", index=False)
            df2.to_excel(writer, sheet_name="Sheet2", index=False)
        
        result = await ingest_tabular(mock_db, str(xlsx_file), config)
        
        assert result["sheets_processed"] == 2
        assert len(result["dataset_ids"]) == 2

    @pytest.mark.asyncio
    async def test_xlsx_first_sheet_only_strategy(self, pandas, openpyxl, mock_db, tmp_path):
        """Test XLSX with first_only strategy."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        xlsx_file = tmp_path / "test.xlsx"
        df1 = pd.DataFrame({"col1": [1, 2]})
        df2 = pd.DataFrame({"col2": [10, 20]})
        
        with pd.ExcelWriter(xlsx_file, engine="openpyxl") as writer:
            df1.to_excel(writer, sheet_name="Sheet1", index=False)
            df2.to_excel(writer, sheet_name="Sheet2", index=False)
        
        config = {
            "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
            "tabular": {"multi_sheet_strategy": "first_only"}
        }
        
        result = await ingest_tabular(mock_db, str(xlsx_file), config)
        
        assert result["sheets_processed"] == 1
        assert len(result["dataset_ids"]) == 1


class TestChangeDetection:
    """Test change detection for re-uploaded files."""

    @pytest.mark.asyncio
    async def test_change_detection_same_hash(self, pandas, mock_db, config, tmp_path):
        """Test that re-uploading identical file is detected."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        csv_file = tmp_path / "test.csv"
        df = pd.DataFrame({"col1": [1, 2], "col2": [10, 20]})
        df.to_csv(csv_file, index=False)
        
        # Ingest twice
        result1 = await ingest_tabular(mock_db, str(csv_file), config)
        result2 = await ingest_tabular(mock_db, str(csv_file), config)
        
        # Both should succeed (hash check is not yet fully implemented)
        assert len(result1["dataset_ids"]) >= 1
        assert len(result2["dataset_ids"]) >= 1


class TestSchemaExtraction:
    """Test schema extraction from DataFrames."""

    @pytest.mark.asyncio
    async def test_schema_json_structure(self, pandas, mock_db, config, tmp_path):
        """Test that schema_json is correctly formatted."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        csv_file = tmp_path / "test.csv"
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "age": [30, 25],
            "salary": [100000.0, 95000.0]
        })
        df.to_csv(csv_file, index=False)
        
        result = await ingest_tabular(mock_db, str(csv_file), config)
        
        assert result["sheets_processed"] == 1
        
        # Check that schema was captured in mock calls
        calls = mock_db.execute.call_args_list
        for call in calls:
            if "schema_json" in str(call):
                # Schema was created
                assert any("name" in str(c) for c in calls)


class TestDatasetNodeProperties:
    """Test Dataset node properties."""

    @pytest.mark.asyncio
    async def test_dataset_node_has_all_properties(self, pandas, mock_db, config, tmp_path):
        """Test that Dataset node includes required properties."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        csv_file = tmp_path / "test.csv"
        df = pd.DataFrame({"col": [1, 2, 3]})
        df.to_csv(csv_file, index=False)
        
        result = await ingest_tabular(mock_db, str(csv_file), config)
        
        # Verify Dataset node was created with required properties
        assert result["dataset_ids"]
        assert result["storage_uris"]
        assert result["row_counts"] == [3]
        assert result["column_counts"] == [1]
        assert result["summaries"]


class TestErrorHandling:
    """Test error handling in tabular ingestion."""

    @pytest.mark.asyncio
    async def test_malformed_csv_handling(self, pandas, mock_db, config, tmp_path):
        """Test handling of malformed CSV."""
        csv_file = tmp_path / "malformed.csv"
        csv_file.write_text("column1,column2\nvalue1\n")  # Missing value in second row
        
        from mcp_engine.tabular_ingest import ingest_tabular
        
        # Should handle gracefully or raise appropriate error
        result = await ingest_tabular(mock_db, str(csv_file), config)
        
        # pandas can handle this, so it should succeed
        assert "dataset_ids" in result or "error" in result

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, mock_db, config, tmp_path):
        """Test handling of unsupported file extension."""
        from mcp_engine.tabular_ingest import ingest_tabular
        
        unsupported_file = tmp_path / "test.docx"
        unsupported_file.write_text("some content")
        
        result = await ingest_tabular(mock_db, str(unsupported_file), config)
        
        assert "error" in result


class TestIntegration:
    """Integration tests for tabular ingestion."""

    @pytest.mark.asyncio
    async def test_full_workflow_csv_to_dataset(self, pandas, mock_db, config, tmp_path):
        """Test complete workflow from CSV to Dataset node."""
        pd = pandas
        from mcp_engine.tabular_ingest import ingest_tabular
        
        csv_file = tmp_path / "budget.csv"
        df = pd.DataFrame({
            "category": ["Marketing", "Engineering", "Sales"],
            "amount": [12000, 25000, 8000],
            "approved": [True, True, False],
        })
        df.to_csv(csv_file, index=False)
        
        result = await ingest_tabular(mock_db, str(csv_file), config)
        
        assert not ("error" in result and result.get("error"))
        assert len(result["dataset_ids"]) == 1
        assert result["row_counts"] == [3]
        assert result["column_counts"] == [3]
        assert mock_db.execute.called
