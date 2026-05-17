# Plan for 249 - Dataset Node + Tabular Data Store

## Metadata

- **Card ID**: 249
- **Priority**: P1
- **Dependencies**: None
- **Risk**: Low - additive schema change, new module, no existing code modified

## Goal

Add a `Dataset` node type to Kuzu and a local SQLite-per-dataset storage layer so Campy can store and query tabular data while keeping the graph as the metadata index.

## Step 1: Add Dataset Node to Schema

In `mcp_engine/schema.py`, add to `NODE_TABLES`:

```python
"Dataset": {
    "columns": [
        ("dataset_id", "STRING"),
        ("name", "STRING"),
        ("description", "STRING"),
        ("embedding", "FLOAT[384]"),
        ("embedding_model", "STRING"),
        ("embedding_dim", "INT32"),
        ("storage_uri", "STRING"),
        ("schema_json", "STRING"),
        ("row_count", "INT64"),
        ("column_count", "INT32"),
        ("source_format", "STRING"),
        ("content_hash", "STRING"),
        ("confidence", "FLOAT"),
        ("confidence_low", "BOOLEAN"),
        ("pathway_strength", "FLOAT"),
        ("archived", "BOOLEAN"),
        ("created_at", "TIMESTAMP"),
        ("last_accessed_at", "TIMESTAMP"),
    ],
    "primary_key": "dataset_id",
}
```

Add relationships to `EDGE_TABLES`:

```python
# Dataset provenance
("DATASET_DERIVED_FROM", "Dataset", "Document", []),
# Dataset quest linkage
("DATASET_BELONGS_TO_QUEST", "Dataset", ["MainQuest", "SideQuest"], []),
# Entity-to-dataset linkage
("DESCRIBED_BY_DATASET", "Concept", "Dataset", [
    ("extraction_method", "STRING"),
    ("created_at", "TIMESTAMP"),
]),
```

Add HNSW vector index for Dataset embeddings (same pattern as other node tables).

## Step 2: Add tables_dir() to paths.py

In `sidequests/paths.py`, add:

```python
def tables_dir() -> Path:
    """Return path to tabular data storage directory, creating if needed."""
    d = runtime_dir() / "tables"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

## Step 3: Create tabular_store.py

New module `mcp_engine/tabular_store.py`:

```python
import sqlite3
import json
from pathlib import Path
from typing import Optional
from sidequests.paths import tables_dir

def _db_path(dataset_id: str) -> Path:
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
```

## Step 4: Tests

Create `tests/test_tabular_store.py`:

- Test `create_table_from_dataframe` with a small DataFrame
- Test `query_table` with SELECT, WHERE, ORDER BY
- Test `query_table` rejects writes (PRAGMA query_only)
- Test `get_table_summary` returns correct schema and sample
- Test `delete_table` removes file
- Test `delete_table` on nonexistent dataset returns False
- Test Dataset node created in Kuzu with correct properties
- Test HNSW vector index exists on Dataset table

## Completion Criteria

Run:

```bash
.venv/bin/pytest -q tests/test_tabular_store.py tests/test_schema.py
.venv/bin/pytest -q
```
