"""
mcp_engine/tabular_store.py — Tabular Data Storage Layer

Stores tabular data (DataFrames) in per-dataset SQLite files.
Provides read-only query interface and schema introspection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from campy.paths import tables_dir


def _db_path(dataset_id: str) -> Path:
    """Return the SQLite database path for a dataset."""
    return tables_dir() / f"{dataset_id}.sqlite"


def create_table_from_dataframe(dataset_id: str, df, schema_json: str) -> Path:
    """Write a pandas DataFrame to a per-dataset SQLite file. Returns path."""
    path = _db_path(dataset_id)
    conn = sqlite3.connect(str(path))
    try:
        df.to_sql("data", conn, if_exists="replace", index=False)
    finally:
        conn.close()
    return path


def query_table(dataset_id: str, sql: str) -> list[dict]:
    """Execute read-only SQL against a dataset. Returns list of row dicts."""
    path = _db_path(dataset_id)
    if not path.exists():
        raise FileNotFoundError(f"No table for dataset {dataset_id}")
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA query_only = ON")
    try:
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_table_summary(dataset_id: str, sample_rows: int = 5) -> dict:
    """Return schema, row count, and sample rows without loading full table."""
    path = _db_path(dataset_id)
    if not path.exists():
        raise FileNotFoundError(f"No table for dataset {dataset_id}")
    conn = sqlite3.connect(str(path))
    try:
        # Get schema
        cursor = conn.execute("PRAGMA table_info(data)")
        columns = [{"name": row[1], "type": row[2]} for row in cursor.fetchall()]
        # Get row count
        row_count = conn.execute("SELECT COUNT(*) FROM data").fetchone()[0]
        # Get sample rows
        cursor = conn.execute(f"SELECT * FROM data LIMIT {sample_rows}")
        col_names = [desc[0] for desc in cursor.description]
        samples = [dict(zip(col_names, row)) for row in cursor.fetchall()]
        return {
            "columns": columns,
            "row_count": row_count,
            "sample_rows": samples,
        }
    finally:
        conn.close()


def delete_table(dataset_id: str) -> bool:
    """Remove SQLite file for a dataset. Returns True if file existed."""
    path = _db_path(dataset_id)
    if path.exists():
        path.unlink()
        return True
    return False
