"""
Tests for B194 Procedural Memory synthesis and recall.

Run with: python -m pytest tests/test_b194_procedural_memory.py -q
"""
from __future__ import annotations
import json
import uuid
import pytest


def _make_db(rows_by_query=None, vector_results=None):
    rows_by_query = rows_by_query or {}
    vector_results = vector_results or {}

    class MockResult:
        def __init__(self, rows):
            self._rows = list(rows)
            self._idx = 0

        def has_next(self):
            return self._idx < len(self._rows)

        def get_next(self):
            row = self._rows[self._idx]
            self._idx += 1
            return row

    class MockDB:
        def __init__(self):
            self.written = []

        def execute(self, q, p=None):
            for pattern, rows in rows_by_query.items():
                if pattern in q:
                    return MockResult(rows)
            return MockResult([])

        async def execute_write(self, q, p=None):
            self.written.append({"q": q, "p": p})

        def vector_search(self, table_name, index_name, vec, limit):
            return vector_results.get(index_name, [])

    return MockDB()


class _LLM:
    def __init__(self, obj):
        self._obj = obj

    async def chat(self, messages):
        return json.dumps(self._obj)


@pytest.mark.asyncio
async def test_synthesize_procedures_creates_procedure(monkeypatch):
    from campy.brain.brainstem.sweep import _synthesize_procedures
    from campy.brain.hippocampus.graph import embeddings as emb

    # Mock embeddings to avoid remote model
    monkeypatch.setattr(emb, "embed", lambda text, model_name=None: [0.01] * 384)

    rows_by_query = {
        "RETURN DISTINCT p.strategy": [["spatial-nav"]],
        "MATCH (p:Plan) WHERE p.strategy": [
            ["plan-1", "Find player quickly", [0.1] * 384, 0.9, 0.9],
            ["plan-2", "Explore maze", [0.1] * 384, 0.8, 0.85],
            ["plan-3", "Probe objects", [0.1] * 384, 0.75, 0.88],
        ],
    }
    db = _make_db(rows_by_query=rows_by_query)

    llm = _LLM({
        "name": "Spatial Navigation Procedure",
        "description": "A concise procedure for spatial puzzles",
        "steps": [{"step": "explore", "precondition": "unknown", "action": "move", "expected_outcome": "see player"}],
    })

    config = {"sweep": {"procedural": {"min_cluster_size": 3}}, "embeddings": {"model": "mock-model"}}

    synthesized, errors = await _synthesize_procedures(db, config, llm)
    assert synthesized >= 1
    assert errors == 0
    # Verify that a Procedure CREATE was attempted
    assert any("CREATE (pr:Procedure" in w["q"] or "CREATE (pr:Procedure" in (w["q"] or "") for w in db.written)


@pytest.mark.asyncio
async def test_recall_procedures_by_archetype():
    from campy.brain.thalamus.tools import recall_procedures

    rows_by_query = {
        "MATCH (p:Procedure) WHERE p.archived = false AND p.archetype": [
            ["proc-1", "Spatial Navigation Procedure", "desc", "[]", 3, 0.9]
        ]
    }
    db = _make_db(rows_by_query=rows_by_query)
    res = await recall_procedures({"archetype": "spatial-nav", "limit": 3}, db, {})
    assert "procedures" in res
    assert len(res["procedures"]) == 1
    assert res["procedures"][0]["name"] == "Spatial Navigation Procedure"
