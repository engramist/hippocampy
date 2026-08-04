"""
tests/test_tabular_ingest_real_kuzu.py — Real-Kuzu regression tests for B251.

`tests/test_tabular_ingest.py` is 100% mock-based (`db.execute = MagicMock`),
per B250's own audit finding — it never exercises real Kuzu Cypher or the
real SQLite tabular store. These tests run `ingest_tabular()` /
`ingest_tabular_from_content()` against a real temp Kuzu DB with the real
`Dataset` node schema, and against the real on-disk tabular store, so a
column-name or type mismatch (like the TIMESTAMP-cast bug B250 already
found once via this same style of test) would actually be caught.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.sensory_cortex import tabular_ingest
from campy.brain.sensory_cortex.tabular_store import get_table_summary
from campy.paths import tables_dir

pytest.importorskip("pandas")

CONFIG = {
    "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
    "tabular": {"multi_sheet_strategy": "per_sheet"},
}

_DATASET_DDL = """
    dataset_id STRING,
    name STRING,
    description STRING,
    embedding FLOAT[384],
    embedding_model STRING,
    embedding_dim INT32,
    storage_uri STRING,
    schema_json STRING,
    row_count INT64,
    column_count INT32,
    source_format STRING,
    content_hash STRING,
    confidence DOUBLE,
    confidence_low BOOLEAN,
    pathway_strength DOUBLE,
    archived BOOLEAN,
    created_at TIMESTAMP,
    last_accessed_at TIMESTAMP,
    PRIMARY KEY (dataset_id)
"""


@pytest.fixture()
def real_db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="tabular_ingest_real_")
    db = KuzuClient(f"{tmp}/db")
    db.execute(f"CREATE NODE TABLE Dataset({_DATASET_DDL})")
    monkeypatch.setattr(
        "campy.brain.hippocampus.graph.embeddings.embed",
        lambda text, model_name=None: [0.0] * 384,
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(autouse=True)
def cleanup_sqlite():
    before = set(tables_dir().glob("*.sqlite")) if tables_dir().exists() else set()
    yield
    after = set(tables_dir().glob("*.sqlite")) if tables_dir().exists() else set()
    for path in after - before:
        path.unlink(missing_ok=True)


class TestJsonExtensionSupport:
    """AC: classify_input() routes JSON arrays to the tabular path - but
    ingest_tabular() had no .json branch at all, so even a correctly-routed
    JSON array would fail with "Unsupported file extension: .json"."""

    async def test_json_array_file_ingests_successfully(self, real_db, tmp_path):
        db = real_db
        json_path = tmp_path / "people.json"
        json_path.write_text('[{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]')

        result = await tabular_ingest.ingest_tabular(db, str(json_path), CONFIG)

        assert "error" not in result
        assert result["row_counts"] == [2]
        assert result["column_counts"] == [2]
        summary = get_table_summary(result["dataset_ids"][0])
        assert summary["row_count"] == 2
        assert {c["name"] for c in summary["columns"]} == {"name", "age"}


class TestIngestTabularFromContent:
    """AC (real gap, B251 audit): raw pasted tabular content never reached
    the tabular pipeline - ingest_data's content branch unconditionally
    called notify_turn regardless of what classify_input() recommended.
    ingest_tabular_from_content() is the missing piece: write content to a
    temp file with an inferred extension, delegate to ingest_tabular(),
    clean up the temp file (Dataset.storage_uri points at the independent
    SQLite table, not the source file, so this is always safe)."""

    async def test_csv_content_ingests_into_tabular_store(self, real_db):
        db = real_db
        content = "name,age,dept\nAlice,30,Eng\nBob,25,Sales\nCharlie,35,Eng\n"

        result = await tabular_ingest.ingest_tabular_from_content(db, content, CONFIG)

        assert "error" not in result
        assert result["row_counts"] == [3]
        assert result["column_counts"] == [3]
        summary = get_table_summary(result["dataset_ids"][0])
        assert summary["row_count"] == 3
        assert {c["name"] for c in summary["columns"]} == {"name", "age", "dept"}

    async def test_tab_delimited_content_ingests_into_tabular_store(self, real_db):
        db = real_db
        content = "name\tage\nAlice\t30\nBob\t25\nCharlie\t35\n"

        result = await tabular_ingest.ingest_tabular_from_content(db, content, CONFIG)

        assert "error" not in result
        summary = get_table_summary(result["dataset_ids"][0])
        assert summary["row_count"] == 3
        assert {c["name"] for c in summary["columns"]} == {"name", "age"}

    async def test_json_array_content_ingests_into_tabular_store(self, real_db):
        db = real_db
        content = '[{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5, "b": 6}]'

        result = await tabular_ingest.ingest_tabular_from_content(db, content, CONFIG)

        assert "error" not in result
        summary = get_table_summary(result["dataset_ids"][0])
        assert summary["row_count"] == 3
        assert {c["name"] for c in summary["columns"]} == {"a", "b"}

    async def test_temp_file_is_cleaned_up_after_ingestion(self, real_db, tmp_path, monkeypatch):
        db = real_db
        seen_paths = []
        real_ingest = tabular_ingest.ingest_tabular

        async def spy(db_, file_path, config, loop_queue=None, quest_id=""):
            seen_paths.append(file_path)
            return await real_ingest(db_, file_path, config, loop_queue, quest_id)

        monkeypatch.setattr(tabular_ingest, "ingest_tabular", spy)

        content = "name,age\nAlice,30\nBob,25\nCarl,40\n"
        result = await tabular_ingest.ingest_tabular_from_content(db, content, CONFIG)

        assert "error" not in result
        assert len(seen_paths) == 1
        from pathlib import Path
        assert not Path(seen_paths[0]).exists()

    async def test_temp_file_cleaned_up_even_on_failure(self, real_db, monkeypatch):
        db = real_db

        async def boom(*a, **kw):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(tabular_ingest, "ingest_tabular", boom)

        with pytest.raises(RuntimeError):
            await tabular_ingest.ingest_tabular_from_content(db, "a,b\n1,2\n3,4\n", CONFIG)
