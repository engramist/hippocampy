"""
Tests for B196 Consistency Audit (contradiction detection, stale & orphan flagging).
Run with: pytest tests/test_b196_consistency_audit.py -q
"""
from __future__ import annotations
import json
import uuid
import pytest
from datetime import datetime, timezone, timedelta


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
            self._rows = rows_by_query
        def execute(self, q, p=None):
            for pattern, rows in self._rows.items():
                if pattern in q:
                    return MockResult(rows)
            return MockResult([])
        async def execute_write(self, q, p=None):
            self.written.append({"q": q, "p": p})

    return MockDB()


class _LLM:
    def __init__(self, obj):
        self._obj = obj
    async def chat(self, messages):
        return json.dumps(self._obj)


@pytest.mark.asyncio
async def test_audit_detects_contradiction_creates_disambiguation():
    from mcp_engine.sweep import _audit_consistency

    # Two lessons in same domain with very similar embeddings
    emb = [0.05] * 384
    now = datetime.now(timezone.utc).isoformat()

    rows_by_query = {
        "RETURN DISTINCT l.domain": [["infra"]],
        "WHERE l.domain = $domain": [["l1", emb, "Do X always", 0.9, 0.9, now, None], ["l2", emb, "Never do X", 0.85, 0.88, now, None]],
    }

    db = _make_db(rows_by_query=rows_by_query)

    llm = _LLM({"action": "contradict", "confidence": 0.95, "explanation": "direct conflict"})

    config = {"sweep": {"consistency": {"top_lessons": 20, "sim_threshold": 0.7, "max_llm_calls": 5}}}

    audited, errors = await _audit_consistency(db, config, llm)
    assert errors == 0
    assert audited >= 1
    # Verify that a DisambiguationEvent CREATE was written
    assert any("DisambiguationEvent" in (w["q"] or "") for w in db.written)


@pytest.mark.asyncio
async def test_stale_and_orphan_flagging():
    from mcp_engine.sweep import _audit_consistency

    thirty_one_days_ago = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()

    rows_by_query = {
        # no domains — skip pairwise LLM work
        "RETURN DISTINCT l.domain": [],
        # stale detection query
        "NOT EXISTS { MATCH (l)-[:APPLIES_TO|RELATED_TO|GENERALIZES_LESSON]->() } RETURN l.lesson_id": [["stale1", "old lesson"]],
        # orphan detection query
        "NOT EXISTS { MATCH ()-[:CONTAINS_LESSON|PRODUCED_LESSON|PRODUCED_PLAN_LESSON|LEARNED]->(l) } RETURN l.lesson_id": [["orphan1", "orphaned lesson"]],
    }

    db = _make_db(rows_by_query=rows_by_query)
    # llm_client None — audit should still flag stale/orphan
    audited, errors = await _audit_consistency(db, {}, None)
    assert errors == 0
    # Check that stale and orphan flags were set via execute_write calls
    assert any("stale_flagged" in (w["q"] or "") for w in db.written)
    assert any("orphan_flagged" in (w["q"] or "") for w in db.written)