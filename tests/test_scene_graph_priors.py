from __future__ import annotations

import pytest

from campy.brain.thalamus.tools import recall_scene_graph_priors

# B314: recall_scene_graph_priors' Cypher moved into the named query
# `lessons.list_scene_graph_priors`, run through GraphGateway — which
# routes non-mutating queries through `KuzuClient.execute_read()`
# (materialized dict rows, aliased to clean column names) rather than the
# raw synchronous cursor this fake previously exposed via `execute()`.
# `_DB` now implements `execute_read` directly, zipping each row's raw
# tuple against the same aliases the named query's RETURN clause declares
# (lesson_id, progress_score, valence, archetype, text) — the fixture data
# below is unchanged, only how it's delivered to the tool.
_COLUMNS = ("lesson_id", "progress_score", "valence", "archetype", "text")


class _DB:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def execute_read(self, query, params=None):
        return [dict(zip(_COLUMNS, row)) for row in self._rows]


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
