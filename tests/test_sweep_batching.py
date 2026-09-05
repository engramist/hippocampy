"""
B282 — Batched sweep writes.

Verifies that decay/archive and resurrection use chunked UNWIND writes
instead of one execute_write per node, and that sweep stats keep shape.

Run with: python3 -m pytest tests/test_sweep_batching.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from campy.brain.brainstem.sweep import (
    _BATCH_SIZE,
    _batch_write,
    _decay_and_archive,
    SWEEP_TABLES,
)


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


class _RecordingDB:
    """Mock DB: every active node is below the archive threshold."""

    def __init__(self, active_ids_per_table):
        self.active_ids = active_ids_per_table
        self.write_calls = []

    def execute(self, query, params=None):
        # The single post-decay read returns (pk, pathway_strength) rows.
        if "RETURN n." in query and "pathway_strength" in query:
            for table in self.active_ids:
                if f":{table})" in query or f":{table} " in query:
                    return _Result([(nid, 0.01) for nid in self.active_ids[table]])
        return _Result([])

    async def execute_write(self, query, params=None):
        self.write_calls.append((query, params))


@pytest.mark.asyncio
async def test_batch_write_chunks_at_500():
    db = _RecordingDB({})
    ids = [f"c{i}" for i in range(1200)]
    ok, bad = await _batch_write(db, "sweep.unwind_archive_concept", ids)
    assert ok == 1200
    assert bad == 0
    assert len(db.write_calls) == 3  # ceil(1200/500)
    sizes = [len(p["ids"]) for _, p in db.write_calls]
    assert sizes == [500, 500, 200]


@pytest.mark.asyncio
async def test_batch_write_counts_failed_chunks():
    class FailingDB:
        def __init__(self):
            self.calls = 0

        async def execute_write(self, query, params=None):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("boom")

    db = FailingDB()
    ids = [f"c{i}" for i in range(1100)]
    ok, bad = await _batch_write(db, "sweep.unwind_archive_concept", ids)
    assert ok == 600   # chunks 1 (500) + 3 (100)
    assert bad == 500  # chunk 2 failed wholesale


@pytest.mark.asyncio
async def test_decay_archive_uses_unwind_batches():
    concept_table = SWEEP_TABLES[0][0]
    ids = [f"c{i}" for i in range(1200)]
    db = _RecordingDB({concept_table: ids})

    decayed, archived, errors = await _decay_and_archive(
        db, decay_rates={}, interval_days=1.0, archive_threshold=0.2
    )

    assert decayed >= 1200
    assert archived == 1200
    assert errors == 0

    unwind_calls = [
        (q, p) for q, p in db.write_calls
        if "UNWIND" in q and f":{concept_table})" in q and "archived = true" in q
    ]
    assert len(unwind_calls) == 3
    assert sum(len(p["ids"]) for _, p in unwind_calls) == 1200


@pytest.mark.asyncio
async def test_decay_archive_no_per_row_writes():
    """No archive write may target a single literal node id."""
    concept_table = SWEEP_TABLES[0][0]
    db = _RecordingDB({concept_table: [f"c{i}" for i in range(50)]})

    await _decay_and_archive(db, {}, 1.0, 0.2)

    for query, params in db.write_calls:
        if "archived = true" in query:
            assert "UNWIND" in query, f"per-row archive write found: {query}"


@pytest.mark.asyncio
async def test_decay_single_read_per_table():
    """The post-decay scan and the decayed-count scan are now one query."""
    concept_table = SWEEP_TABLES[0][0]

    class CountingDB(_RecordingDB):
        def __init__(self, *a):
            super().__init__(*a)
            self.read_queries = []

        def execute(self, query, params=None):
            self.read_queries.append(query)
            return super().execute(query, params)

    db = CountingDB({concept_table: ["c1", "c2"]})
    await _decay_and_archive(db, {}, 1.0, 0.2)

    concept_reads = [q for q in db.read_queries if f":{concept_table})" in q]
    assert len(concept_reads) == 1, f"expected 1 read for {concept_table}, got {concept_reads}"
    assert not any("count(n)" in q for q in db.read_queries)
