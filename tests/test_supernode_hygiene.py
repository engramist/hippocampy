"""
B283 — Supernode monitoring and session edge pruning.

Run with: python3 -m pytest tests/test_supernode_hygiene.py -v
"""

from __future__ import annotations

import pytest

from campy.brain.brainstem.sweep import (
    _report_degree_hotspots,
    _prune_session_edges,
)
from campy.brain.temporal_lobe.loop.step7_pathway import write_co_occurs_with


class _Result:
    def __init__(self, rows=None):
        self._rows = list(rows or [])
        self._idx = 0

    def has_next(self):
        return self._idx < len(self._rows)

    def get_next(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row


class _MockDB:
    def __init__(self, read_rows=None):
        # read_rows: {substring_of_query: [rows]}
        self.read_rows = read_rows or {}
        self.read_queries = []
        self.write_calls = []

    def execute(self, query, params=None):
        self.read_queries.append((query, params))
        for needle, rows in self.read_rows.items():
            if needle in query:
                return _Result(rows)
        return _Result([])

    async def execute_write(self, query, params=None):
        self.write_calls.append((query, params))


# ---------------------------------------------------------------------------
# Degree hotspot report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_degree_report_shape():
    node = {"_label": "Session", "session_id": "s1"}
    db = _MockDB({"r:LOADED": [(node, 250)]})
    hotspots = await _report_degree_hotspots(db, {})
    loaded = [h for h in hotspots if h["rel_table"] == "LOADED"]
    assert loaded, "LOADED hotspot missing"
    entry = loaded[0]
    assert set(entry) == {"node_id", "table", "rel_table", "degree", "direction"}
    assert entry["table"] == "Session"
    assert entry["node_id"] == "s1"
    assert entry["degree"] == 250


@pytest.mark.asyncio
async def test_degree_report_survives_query_failure():
    class FailingDB(_MockDB):
        def execute(self, query, params=None):
            raise RuntimeError("no such table")

    hotspots = await _report_degree_hotspots(FailingDB(), {})
    assert hotspots == []


@pytest.mark.asyncio
async def test_degree_report_respects_top_k():
    db = _MockDB()
    await _report_degree_hotspots(db, {"sweep": {"degree_report_top_k": 3}})
    assert any("LIMIT 3" in q for q, _ in db.read_queries)


# ---------------------------------------------------------------------------
# Session edge pruning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_session_edges_pruned():
    db = _MockDB({"MATCH (s:Session)": [("old1",), ("old2",)]})
    pruned, errors = await _prune_session_edges(db, {})
    assert pruned == 2
    assert errors == 0
    # One UNWIND DELETE per cache rel table (LOADED, WARM_NODE)
    deletes = [(q, p) for q, p in db.write_calls if "DELETE r" in q]
    assert len(deletes) == 2
    for query, params in deletes:
        assert "UNWIND" in query
        assert params["ids"] == ["old1", "old2"]
    rels = {("LOADED" in q, "WARM_NODE" in q) for q, _ in deletes}
    assert (True, False) in rels and (False, True) in rels


@pytest.mark.asyncio
async def test_prune_noop_when_no_stale_sessions():
    db = _MockDB({"MATCH (s:Session)": []})
    pruned, errors = await _prune_session_edges(db, {})
    assert pruned == 0
    assert db.write_calls == []


@pytest.mark.asyncio
async def test_prune_respects_disable_flag():
    db = _MockDB({"MATCH (s:Session)": [("old1",)]})
    pruned, _ = await _prune_session_edges(
        db, {"sweep": {"prune_session_edges": False}})
    assert pruned == 0
    assert db.read_queries == []
    assert db.write_calls == []


@pytest.mark.asyncio
async def test_prune_never_deletes_nodes():
    db = _MockDB({"MATCH (s:Session)": [("old1",)]})
    await _prune_session_edges(db, {})
    for query, _ in db.write_calls:
        assert "DETACH" not in query.upper()
        assert "DELETE r" in query  # edge variable only


# ---------------------------------------------------------------------------
# CO_OCCURS_WITH pair cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_co_occurrence_pair_cap():
    db = _MockDB()
    concept_ids = [f"c{i:02d}" for i in range(15)]  # 105 raw pairs
    written = await write_co_occurs_with(
        concept_ids, 0.7, db, "2026-06-11T00:00:00Z", max_pairs=45)
    assert written == 45
    assert len(db.write_calls) == 1
    _, params = db.write_calls[0]
    assert len(params["pairs"]) == 45


@pytest.mark.asyncio
async def test_co_occurrence_cap_deterministic():
    db1, db2 = _MockDB(), _MockDB()
    ids = [f"c{i:02d}" for i in range(15)]
    await write_co_occurs_with(ids, 0.7, db1, "2026-06-11T00:00:00Z", max_pairs=45)
    await write_co_occurs_with(list(reversed(ids)), 0.7, db2, "2026-06-11T00:00:00Z", max_pairs=45)
    assert db1.write_calls[0][1]["pairs"] == db2.write_calls[0][1]["pairs"]


@pytest.mark.asyncio
async def test_co_occurrence_cap_disabled_with_zero():
    db = _MockDB()
    ids = [f"c{i:02d}" for i in range(15)]
    written = await write_co_occurs_with(
        ids, 0.7, db, "2026-06-11T00:00:00Z", max_pairs=0)
    assert written == 105


@pytest.mark.asyncio
async def test_co_occurrence_under_cap_unchanged():
    db = _MockDB()
    ids = ["a", "b", "c"]  # 3 pairs, under any cap
    written = await write_co_occurs_with(
        ids, 0.7, db, "2026-06-11T00:00:00Z", max_pairs=45)
    assert written == 3
