"""
tests/test_lexical_fallback_fts_real_kuzu.py — Real-Kuzu regression tests for B284.

The 2026-08-03 audit found that current_truth's FTS branch (used whenever
the pinned kuzu==0.11.3 build has the FTS extension loaded - true in this
environment) has NO recency window at all: only the CONTAINS fallback
branch filters on created_at, and it never runs when FTS is available.
tests/test_lexical_fallback.py's LexicalCaptureDB mock has no has_fts
attribute, so it structurally can never exercise the FTS branch - these
tests run against a real Kuzu DB with a real FTS index instead.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

import campy.brain.thalamus.tools as tools_mod
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_MESSAGE_DDL = """
    message_id STRING,
    text_raw STRING,
    role STRING,
    confidence DOUBLE,
    confidence_low BOOLEAN,
    pathway_strength DOUBLE,
    archived BOOLEAN,
    created_at TIMESTAMP,
    PRIMARY KEY (message_id)
"""


@pytest.fixture()
def real_db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="lexical_fts_real_")
    db = KuzuClient(f"{tmp}/db")
    db.execute(f"CREATE NODE TABLE Message({_MESSAGE_DDL})")
    monkeypatch.setattr(
        "campy.brain.hippocampus.graph.embeddings.embed",
        lambda text, model_name=None: [0.1] * 384,
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _create_message(db: KuzuClient, message_id: str, text: str, age_days: float) -> None:
    created_at = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    db.execute(
        "CREATE (m:Message {message_id: $id, text_raw: $t, role: 'user', "
        "confidence: 0.5, confidence_low: true, pathway_strength: 0.5, "
        "archived: false, created_at: timestamp($c)})",
        {"id": message_id, "t": text, "c": created_at},
    )


class TestFtsSearchCutoff:
    """Unit-level: KuzuClient.fts_search() itself, isolated from current_truth."""

    def test_fts_search_without_cutoff_returns_everything(self, real_db):
        db = real_db
        if not db.has_fts():
            pytest.skip("FTS extension not available in this environment")
        _create_message(db, "m-recent", "zephyr_token recent", age_days=1)
        _create_message(db, "m-old", "zephyr_token old", age_days=30)
        db.create_fts_index("Message", "message_fts_idx", ["text_raw"])

        rows = db.fts_search("Message", "message_fts_idx", "zephyr_token", limit=10)

        ids = {r["node"]["message_id"] for r in rows}
        assert ids == {"m-recent", "m-old"}

    def test_fts_search_with_cutoff_excludes_old_rows(self, real_db):
        db = real_db
        if not db.has_fts():
            pytest.skip("FTS extension not available in this environment")
        _create_message(db, "m-recent", "zephyr_token recent", age_days=1)
        _create_message(db, "m-old", "zephyr_token old", age_days=30)
        db.create_fts_index("Message", "message_fts_idx", ["text_raw"])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

        rows = db.fts_search("Message", "message_fts_idx", "zephyr_token", limit=10, cutoff=cutoff)

        ids = {r["node"]["message_id"] for r in rows}
        assert ids == {"m-recent"}

    def test_fts_search_with_cutoff_excludes_archived_rows(self, real_db):
        db = real_db
        if not db.has_fts():
            pytest.skip("FTS extension not available in this environment")
        _create_message(db, "m-active", "zephyr_token active", age_days=1)
        db.execute(
            "CREATE (m:Message {message_id: 'm-archived', text_raw: 'zephyr_token archived', "
            "role: 'user', confidence: 0.5, confidence_low: true, pathway_strength: 0.5, "
            "archived: true, created_at: timestamp($c)})",
            {"c": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
        )
        db.create_fts_index("Message", "message_fts_idx", ["text_raw"])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

        rows = db.fts_search("Message", "message_fts_idx", "zephyr_token", limit=10, cutoff=cutoff)

        ids = {r["node"]["message_id"] for r in rows}
        assert ids == {"m-active"}

    def test_fts_search_cutoff_does_not_truncate_before_filtering(self, real_db):
        """Regression guard: the window predicate must be applied before
        LIMIT, not after - otherwise a limit of 1 could return only an old
        row and silently hide a matching recent one."""
        db = real_db
        if not db.has_fts():
            pytest.skip("FTS extension not available in this environment")
        _create_message(db, "m-old-1", "zephyr_token old one", age_days=40)
        _create_message(db, "m-old-2", "zephyr_token old two", age_days=35)
        _create_message(db, "m-recent", "zephyr_token recent", age_days=1)
        db.create_fts_index("Message", "message_fts_idx", ["text_raw"])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

        rows = db.fts_search("Message", "message_fts_idx", "zephyr_token", limit=1, cutoff=cutoff)

        assert len(rows) == 1
        assert rows[0]["node"]["message_id"] == "m-recent"


class TestCurrentTruthLexicalWindowViaFts:
    """End-to-end: the exact scenario from the B284 audit reproduction,
    through the real current_truth() tool with a real FTS-backed DB."""

    async def test_old_message_does_not_surface_lexically_via_fts(self, real_db):
        db = real_db
        if not db.has_fts():
            pytest.skip("FTS extension not available in this environment")
        _create_message(db, "msg-recent", "unique_zephyr_marker recent message", age_days=1)
        _create_message(db, "msg-old", "unique_zephyr_marker old message", age_days=30)
        db.create_fts_index("Message", "message_fts_idx", ["text_raw"])

        result = await tools_mod.current_truth(
            {"query": "unique_zephyr_marker", "session_id": "unknown"},
            db,
            {
                "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
                "retrieval": {"lexical_window_days": 14, "lexical_limit": 10},
            },
        )

        lexical_ids = {r["node_id"] for r in result["results"] if r.get("lexical_exact")}
        assert "msg-recent" in lexical_ids
        assert "msg-old" not in lexical_ids

    async def test_recent_message_still_surfaces_lexically_via_fts(self, real_db):
        db = real_db
        if not db.has_fts():
            pytest.skip("FTS extension not available in this environment")
        _create_message(db, "msg-recent", "another_unique_marker recent", age_days=1)
        db.create_fts_index("Message", "message_fts_idx", ["text_raw"])

        result = await tools_mod.current_truth(
            {"query": "another_unique_marker", "session_id": "unknown"},
            db,
            {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
        )

        lexical_ids = {r["node_id"] for r in result["results"] if r.get("lexical_exact")}
        assert "msg-recent" in lexical_ids
