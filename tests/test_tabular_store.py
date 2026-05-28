"""
tests/test_tabular_store.py — Tests for Tabular Data Storage Layer
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from campy.paths import tables_dir
from campy.brain.sensory_cortex.tabular_store import (
    create_table_from_dataframe,
    delete_table,
    get_table_summary,
    query_table,
)


@pytest.fixture
def pandas():
    """Import pandas or skip test if not available."""
    pytest.importorskip("pandas")
    import pandas as pd
    return pd


@pytest.fixture
def sample_df(pandas):
    """Create a small sample DataFrame."""
    pd = pandas
    return pd.DataFrame({
        "name": ["Alice", "Bob", "Charlie"],
        "age": [30, 25, 35],
        "department": ["Engineering", "Sales", "Engineering"],
    })


@pytest.fixture
def dataset_id():
    """Generate a unique dataset ID."""
    return f"dataset_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup_tables():
    """Clean up any test tables after each test."""
    yield
    # Clean up all test tables
    tables_path = tables_dir()
    if tables_path.exists():
        for db_file in tables_path.glob("dataset_*.sqlite"):
            db_file.unlink(missing_ok=True)


class TestCreateTableFromDataFrame:
    """Test create_table_from_dataframe function."""

    def test_create_table_returns_path(self, sample_df, dataset_id):
        """Test that create_table_from_dataframe returns the correct path."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        path = create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        assert path.exists()
        assert path.name == f"{dataset_id}.sqlite"
        assert path.parent == tables_dir()

    def test_table_created_with_data(self, sample_df, dataset_id):
        """Test that the table is created with the correct data."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        # Query the table directly
        results = query_table(dataset_id, "SELECT COUNT(*) as cnt FROM data")
        assert results[0]["cnt"] == 3

    def test_dataframe_replaced_on_recreate(self, sample_df, dataset_id):
        """Test that recreating a table replaces the old data."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        # Create a smaller DataFrame and recreate
        small_df = sample_df.head(1)
        create_table_from_dataframe(dataset_id, small_df, schema_json)
        
        results = query_table(dataset_id, "SELECT COUNT(*) as cnt FROM data")
        assert results[0]["cnt"] == 1


class TestQueryTable:
    """Test query_table function."""

    def test_query_table_select_all(self, sample_df, dataset_id):
        """Test SELECT * query."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        results = query_table(dataset_id, "SELECT * FROM data")
        assert len(results) == 3
        assert all("name" in r and "age" in r for r in results)

    def test_query_table_with_where(self, sample_df, dataset_id):
        """Test SELECT with WHERE clause."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        results = query_table(dataset_id, "SELECT * FROM data WHERE department = 'Engineering'")
        assert len(results) == 2
        assert all(r["department"] == "Engineering" for r in results)

    def test_query_table_with_order_by(self, sample_df, dataset_id):
        """Test SELECT with ORDER BY clause."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        results = query_table(dataset_id, "SELECT * FROM data ORDER BY age DESC")
        assert len(results) == 3
        assert results[0]["age"] == 35  # Charlie
        assert results[2]["age"] == 25  # Bob

    def test_query_table_nonexistent_dataset(self):
        """Test query on nonexistent dataset raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="No table for dataset"):
            query_table("nonexistent_dataset", "SELECT * FROM data")

    def test_query_table_read_only(self, sample_df, dataset_id):
        """Test that write operations are rejected with PRAGMA query_only."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        # Attempting to write should raise an error
        with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
            query_table(dataset_id, "INSERT INTO data VALUES ('Dave', 40, 'Marketing')")


class TestGetTableSummary:
    """Test get_table_summary function."""

    def test_get_table_summary_schema(self, sample_df, dataset_id):
        """Test that schema is returned correctly."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        summary = get_table_summary(dataset_id)
        
        assert "columns" in summary
        assert len(summary["columns"]) == 3
        assert summary["columns"][0]["name"] == "name"
        assert summary["columns"][1]["name"] == "age"

    def test_get_table_summary_row_count(self, sample_df, dataset_id):
        """Test that row count is correct."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        summary = get_table_summary(dataset_id)
        assert summary["row_count"] == 3

    def test_get_table_summary_sample_rows(self, sample_df, dataset_id):
        """Test that sample rows are returned."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        
        summary = get_table_summary(dataset_id, sample_rows=2)
        
        assert "sample_rows" in summary
        assert len(summary["sample_rows"]) == 2
        assert all("name" in r for r in summary["sample_rows"])

    def test_get_table_summary_nonexistent_dataset(self):
        """Test summary on nonexistent dataset raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="No table for dataset"):
            get_table_summary("nonexistent_dataset")


class TestDeleteTable:
    """Test delete_table function."""

    def test_delete_table_removes_file(self, sample_df, dataset_id):
        """Test that delete_table removes the SQLite file."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        path = create_table_from_dataframe(dataset_id, sample_df, schema_json)
        assert path.exists()
        
        result = delete_table(dataset_id)
        assert result is True
        assert not path.exists()

    def test_delete_table_nonexistent_returns_false(self):
        """Test that delete_table returns False for nonexistent dataset."""
        result = delete_table("nonexistent_dataset")
        assert result is False

    def test_delete_table_then_recreate(self, sample_df, dataset_id):
        """Test that a dataset can be recreated after deletion."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        create_table_from_dataframe(dataset_id, sample_df, schema_json)
        delete_table(dataset_id)
        
        # Recreate the table
        path = create_table_from_dataframe(dataset_id, sample_df, schema_json)
        assert path.exists()


class TestTabularStoreIntegration:
    """Integration tests for the tabular store."""

    def test_full_workflow(self, sample_df, dataset_id):
        """Test complete workflow: create → query → summarize → delete."""
        schema_json = '{"columns": ["name", "age", "department"]}'
        
        # Create
        path = create_table_from_dataframe(dataset_id, sample_df, schema_json)
        assert path.exists()
        
        # Query
        results = query_table(dataset_id, "SELECT * FROM data WHERE age > 25")
        assert len(results) >= 2
        
        # Summarize
        summary = get_table_summary(dataset_id)
        assert summary["row_count"] == 3
        assert len(summary["sample_rows"]) == 3
        
        # Delete
        deleted = delete_table(dataset_id)
        assert deleted is True
        assert not path.exists()

    def test_multiple_datasets(self, sample_df, pandas):
        """Test multiple datasets can coexist."""
        pd = pandas
        schema_json = '{"columns": ["col1", "col2"]}'
        
        id1 = f"dataset_{uuid.uuid4().hex[:8]}"
        id2 = f"dataset_{uuid.uuid4().hex[:8]}"
        
        # Create two different datasets
        df1 = pd.DataFrame({"col1": [1, 2], "col2": [10, 20]})
        df2 = pd.DataFrame({"col1": [3, 4, 5], "col2": [30, 40, 50]})
        
        path1 = create_table_from_dataframe(id1, df1, schema_json)
        path2 = create_table_from_dataframe(id2, df2, schema_json)
        
        # Query each independently
        results1 = query_table(id1, "SELECT COUNT(*) as cnt FROM data")
        results2 = query_table(id2, "SELECT COUNT(*) as cnt FROM data")
        
        assert results1[0]["cnt"] == 2
        assert results2[0]["cnt"] == 3
        
        # Cleanup
        delete_table(id1)
        delete_table(id2)
