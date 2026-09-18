from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.brainstem.sweep import _index_hygiene
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.temporal_lobe.loop.step5_retrieval import _headroom


def test_adaptive_headroom_bounds() -> None:
    # limit+5 floor preserves room for the self/exclude postfilter at ratio 0.
    assert _headroom(1, 0.0) == 6
    assert _headroom(5, 0.0) == 10
    assert _headroom(10, 0.0) == 15
    assert _headroom(10, 0.9) == 28
    assert _headroom(30, 0.9) == 50


class _Rows:
    def __init__(self, rows: list[list]):
        self._rows = rows
        self._i = 0

    def has_next(self) -> bool:
        return self._i < len(self._rows)

    def get_next(self):
        row = self._rows[self._i]
        self._i += 1
        return row


class _MockDB:
    def __init__(self, rows_by_table: dict[str, list[list]]):
        self._rows_by_table = rows_by_table
        self.rebuild_calls = []

    def execute(self, query: str, params: dict | None = None):
        _ = params
        for table, rows in self._rows_by_table.items():
            if f"MATCH (n:{table})" in query:
                return _Rows(rows)
        return _Rows([])

    async def rebuild_vector_index(self, table: str, prop: str, index_name: str) -> None:
        self.rebuild_calls.append((table, prop, index_name))


@pytest.mark.asyncio
async def test_ratio_metric_in_sweep_stats() -> None:
    db = _MockDB(
        {
            "Concept": [[False, 4], [True, 6]],
        }
    )
    report = await _index_hygiene(db, {"sweep": {"index_rebuild_archived_ratio": 0.5}})
    assert "Concept" in report
    assert report["Concept"]["total"] == 10
    assert report["Concept"]["archived_ratio"] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_rebuild_skipped_below_threshold() -> None:
    db = _MockDB({"Concept": [[False, 9], [True, 1]]})
    report = await _index_hygiene(
        db,
        {"sweep": {"index_rebuild_archived_ratio": 0.5, "index_rebuild_enabled": True}},
    )
    assert report["Concept"]["rebuilt"] is False
    assert db.rebuild_calls == []


@pytest.mark.asyncio
async def test_rebuild_respects_disable_flag() -> None:
    db = _MockDB({"Concept": [[False, 1], [True, 9]]})
    report = await _index_hygiene(
        db,
        {"sweep": {"index_rebuild_archived_ratio": 0.5, "index_rebuild_enabled": False}},
    )
    assert report["Concept"]["rebuilt"] is False
    assert db.rebuild_calls == []


@pytest.mark.asyncio
async def test_threshold_crossing_logs_warning_even_though_rebuild_stays_disabled(caplog) -> None:
    """B285: rebuild is intentionally disabled (Path B - physically moving
    archived rows to a non-indexed table - was ruled out of scope by the
    plan without a dedicated architecture decision). But a table crossing
    the threshold should not accumulate staleness *silently* - the sweep
    must at least log it so an operator can see it."""
    import logging
    db = _MockDB({"Concept": [[False, 1], [True, 9]]})

    with caplog.at_level(logging.WARNING, logger="campy.brain.brainstem.sweep"):
        report = await _index_hygiene(
            db,
            {"sweep": {"index_rebuild_archived_ratio": 0.5, "index_rebuild_enabled": True}},
        )

    assert report["Concept"]["rebuilt"] is False
    assert db.rebuild_calls == []
    warnings = [r.getMessage() for r in caplog.records]
    assert any("Concept" in w and "0.9" in w for w in warnings)


@pytest.mark.asyncio
async def test_below_threshold_does_not_log_warning(caplog) -> None:
    import logging
    db = _MockDB({"Concept": [[False, 9], [True, 1]]})

    with caplog.at_level(logging.WARNING, logger="campy.brain.brainstem.sweep"):
        await _index_hygiene(
            db,
            {"sweep": {"index_rebuild_archived_ratio": 0.5, "index_rebuild_enabled": True}},
        )

    assert caplog.records == []


def test_temp_db_search_returns_active_top4() -> None:
    # B427: migrated off KuzuClient. Real 384-dim Concept table instead of
    # a synthetic ad-hoc 4-dim one -- OxigraphClient.write_node() is
    # schema-driven off the real global NODE_COLUMNS and can't accommodate
    # a custom per-test dimension. Only the first 2 of 384 dims vary
    # (rest zero-padded) so the near/far cosine-similarity structure the
    # test actually cares about is preserved exactly.
    tmp = tempfile.mkdtemp(prefix="hnsw_hygiene_")
    try:
        db = OxigraphClient(f"{tmp}/db")

        for i in range(4):
            db.write_node("Concept", {
                "concept_id": f"a{i}", "embedding": [1.0, i * 0.01] + [0.0] * 382,
                "archived": False,
            })
        for i in range(6):
            db.write_node("Concept", {
                "concept_id": f"x{i}", "embedding": [0.0, 1.0 - i * 0.01] + [0.0] * 382,
                "archived": True,
            })

        rows = db.vector_search("Concept", "concept_emb_idx", [1.0, 0.0] + [0.0] * 382, 4)

        assert len(rows) == 4
        ids = [row["node"]["concept_id"] for row in rows]
        assert all(node_id.startswith("a") for node_id in ids)
        assert all(bool(row["node"].get("archived", False)) is False for row in rows)
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
