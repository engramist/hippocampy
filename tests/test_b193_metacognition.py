"""
Tests for B193 Metacognition — Knowledge Gap Detection and retrieval.

Run with: python -m pytest tests/test_b193_metacognition.py -q
"""
from __future__ import annotations
import pytest
import json


def _make_db(rows_by_query=None):
    rows_by_query = rows_by_query or {}

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

    return MockDB()


@pytest.mark.asyncio
async def test_detects_missing_lessons_creates_gap():
    from mcp_engine.sweep import _detect_knowledge_gaps

    rows_by_query = {
        # No lessons returned
        "MATCH (l:Lesson) WHERE l.archived = false": [],
        # Messages referencing gist_class 'spatial' -> 6 messages
        "MATCH (m:Message)-[:ESTABLISHED]->(c:Concept)": [["spatial", 6]],
        # No completed plans
        "MATCH (p:Plan) WHERE p.status = 'completed'": [],
        # No existing KnowledgeGap
        "MATCH (g:KnowledgeGap {domain: $d, resolved: false})": [],
    }

    db = _make_db(rows_by_query=rows_by_query)
    synthesized, errors = await _detect_knowledge_gaps(db, {})
    assert synthesized >= 1
    assert errors == 0
    assert any("CREATE (g:KnowledgeGap" in w["q"] for w in db.written)


@pytest.mark.asyncio
async def test_get_knowledge_gaps_returns_rows():
    from mcp_engine.tools import get_knowledge_gaps

    rows_by_query = {
        "MATCH (g:KnowledgeGap) WHERE g.resolved = false": [["gap-1", "spatial", "missing_lessons", "desc", 0.8, 6, 0, "2026-04-10T00:00:00Z"]]
    }
    db = _make_db(rows_by_query=rows_by_query)
    res = await get_knowledge_gaps({}, db, {})
    assert "gaps" in res
    assert len(res["gaps"]) == 1
    assert res["gaps"][0]["domain"] == "spatial"
