"""
tests/test_ingest_data_routing.py — B251 regression: ingest_data() must
actually route raw content according to classify_input()'s recommendation.

The 2026-08-03 audit found that `ingest_data()`'s content branch called
`notify_turn(...)` unconditionally, ignoring `classify_input()`'s route -
so pasting a CSV or JSON array directly (no file_path) silently went
through the conversational graph path and never reached the tabular
store, starving B249/B250's tabular pipeline of real input. These tests
exercise the real dispatch against a real Kuzu DB + real on-disk tabular
store; `notify_turn` is mocked since its own behavior is covered
elsewhere and is orthogonal to the routing decision under test here.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.sensory_cortex.tabular_store import get_table_summary
from campy.brain.thalamus.tools import context_tools
from campy.paths import tables_dir

pytest.importorskip("pandas")

CONFIG = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}

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
    tmp = tempfile.mkdtemp(prefix="ingest_data_routing_")
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


@pytest.fixture()
def mock_notify_turn(monkeypatch):
    calls = []

    async def fake_notify_turn(params, db, config):
        calls.append(params)
        return {"status": "ok", "message_id": "fake-msg-id"}

    monkeypatch.setattr(context_tools, "notify_turn", fake_notify_turn)
    return calls


class TestTabularContentRouting:
    async def test_pasted_csv_content_reaches_tabular_store(self, real_db, mock_notify_turn):
        content = "name,age,dept\nAlice,30,Eng\nBob,25,Sales\nCharlie,35,Eng\n"

        result = await context_tools.ingest_data(
            {"content": content, "session_id": "s1"}, real_db, CONFIG
        )

        assert result["route"]["storage_type"] == "graph+tabular"
        assert "error" not in result["result"]["tabular"]
        dataset_id = result["result"]["tabular"]["dataset_ids"][0]
        summary = get_table_summary(dataset_id)
        assert summary["row_count"] == 3

    async def test_pasted_json_array_reaches_tabular_store(self, real_db, mock_notify_turn):
        content = '[{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5, "b": 6}]'

        result = await context_tools.ingest_data(
            {"content": content, "session_id": "s1"}, real_db, CONFIG
        )

        assert result["route"]["storage_type"] == "graph+tabular"
        dataset_id = result["result"]["tabular"]["dataset_ids"][0]
        summary = get_table_summary(dataset_id)
        assert summary["row_count"] == 3

    async def test_graph_plus_tabular_route_also_calls_notify_turn(self, real_db, mock_notify_turn):
        """"graph+tabular" means dual-write: the conversational turn is
        still recorded, not just the tabular data."""
        content = "name,age\nAlice,30\nBob,25\nCarl,40\n"

        result = await context_tools.ingest_data(
            {"content": content, "session_id": "s1"}, real_db, CONFIG
        )

        assert len(mock_notify_turn) == 1
        assert mock_notify_turn[0]["content"] == content
        assert result["result"]["graph"]["status"] == "ok"


class TestConversationalContentRouting:
    """Regression guard: plain conversational text must keep going through
    notify_turn exactly as before - this card must not touch that path."""

    async def test_short_conversational_text_still_uses_notify_turn(self, real_db, mock_notify_turn):
        result = await context_tools.ingest_data(
            {"content": "remember that I prefer dark mode", "session_id": "s1"}, real_db, CONFIG
        )

        assert result["route"]["storage_type"] == "graph"
        assert len(mock_notify_turn) == 1
        assert result["result"]["status"] == "ok"

    async def test_long_prose_content_still_uses_notify_turn(self, real_db, mock_notify_turn):
        """"document" classification for raw content (no file_path) has no
        file-based document pipeline to route into, so it still falls back
        to notify_turn - unchanged, out of scope for this card."""
        content = "This is a long piece of prose. " * 100

        result = await context_tools.ingest_data(
            {"content": content, "session_id": "s1"}, real_db, CONFIG
        )

        assert result["route"]["storage_type"] == "document"
        assert len(mock_notify_turn) == 1


class TestClassificationObservability:
    """AC: classification confidence is logged for observability."""

    async def test_classification_decision_is_logged(self, real_db, mock_notify_turn, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="campy.brain.thalamus.tools.context_tools"):
            await context_tools.ingest_data(
                {"content": "remember that I prefer dark mode", "session_id": "s1"}, real_db, CONFIG
            )

        assert any(
            "storage_type=graph" in record.getMessage() and "confidence=" in record.getMessage()
            for record in caplog.records
        )


class TestFilePathRoutingUnaffected:
    async def test_file_path_routing_still_calls_ingest_document(self, real_db, mock_notify_turn, tmp_path, monkeypatch):
        calls = []

        async def fake_ingest_document(params, db, config):
            calls.append(params)
            return {"document_id": "fake-doc-id"}

        monkeypatch.setattr(context_tools, "ingest_document", fake_ingest_document)

        md_path = tmp_path / "notes.md"
        md_path.write_text("# Notes\nSome text.")

        result = await context_tools.ingest_data(
            {"file_path": str(md_path), "session_id": "s1"}, real_db, CONFIG
        )

        assert len(calls) == 1
        assert len(mock_notify_turn) == 0
        assert result["result"]["document_id"] == "fake-doc-id"
