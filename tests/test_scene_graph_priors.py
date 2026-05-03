from __future__ import annotations

import pytest

from mcp_engine.tools import recall_scene_graph_priors


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._idx = 0

    def has_next(self):
        return self._idx < len(self._rows)

    def get_next(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row


class _DB:
    def __init__(self, rows=None):
        self._rows = rows or []

    def execute(self, query, params=None):
        return _Result(self._rows)


@pytest.mark.asyncio
async def test_recall_scene_graph_priors_returns_aggregates():
    db = _DB(
        [
            ["l1", 0.2, 0.9, "race", "first"],
            ["l2", 0.8, 0.7, "race", "second"],
            ["l3", 0.5, None, "race", "third"],
        ]
    )
    result = await recall_scene_graph_priors(
        {"wl_hash": "wl:abc", "archetype": "race", "min_valence": 0.5},
        db,
        {},
    )

    assert result["evidence_count"] == 3
    assert result["expected_progress"] == 0.5
    assert result["median_progress"] == 0.5
    assert result["priors"][0]["lesson_id"] == "l1"


@pytest.mark.asyncio
async def test_recall_scene_graph_priors_empty_without_hash():
    db = _DB([["l1", 0.8, 0.9, "race", "x"]])
    result = await recall_scene_graph_priors({}, db, {})
    assert result["evidence_count"] == 0
    assert result["expected_progress"] == 0.0
    assert result["median_progress"] == 0.0
    assert result["priors"] == []
