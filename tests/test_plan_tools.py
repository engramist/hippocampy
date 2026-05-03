from __future__ import annotations

import pytest

from mcp_engine.tool_schemas import TOOLS
from mcp_engine.tools import TOOL_HANDLERS, register_plan, report_outcome, recall_plans


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


class MockDB:
    def __init__(self):
        self.writes = []
        self.step_rows_by_plan = {}

    async def execute_write(self, query, params=None):
        self.writes.append((query, params or {}))
        return _Result([])

    def execute(self, query, params=None):
        params = params or {}
        if "RETURN q.quest_id, labels(q)" in query:
            return _Result([])
        if "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})" in query:
            return _Result(self.step_rows_by_plan.get(params.get("pid", ""), []))
        if "RETURN avg(o.valence), count(o)" in query:
            return _Result([])
        return _Result([])

    def vector_search(self, table, index, _embedding, _limit):
        if table == "Concept":
            return []
        if table == "Plan":
            return []
        return []


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    monkeypatch.setattr(
        "mcp_engine.tools.emb.embed",
        lambda _text, model_name=None: [0.01] * 384,
    )


def test_tool_registry_includes_plan_tools():
    names = {t["name"] for t in TOOLS}
    assert "register_plan" in names
    assert "report_outcome" in names
    assert "recall_plans" in names

    assert "register_plan" in TOOL_HANDLERS
    assert "report_outcome" in TOOL_HANDLERS
    assert "recall_plans" in TOOL_HANDLERS


@pytest.mark.asyncio
async def test_register_plan_creates_chain():
    db = MockDB()
    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}

    out = await register_plan(
        {
            "goal": "Ship migration",
            "steps": ["Write migration", "Run tests", "Deploy"],
            "session_id": "s1",
        },
        db,
        config,
    )

    assert out["plan_id"]
    assert out["id"] == out["plan_id"]
    assert out["write_ok"] is True
    assert out["status"] == "registered"
    assert out["result_summary"].startswith("plan_id=")
    assert len(out["step_ids"]) == 3
    assert out["warnings"] == []
    assert out["suggestions"] == []


@pytest.mark.asyncio
async def test_report_outcome_plan_level_creates_lesson_when_strong_valence():
    db = MockDB()
    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}

    out = await report_outcome(
        {
            "plan_id": "p1",
            "outcome": "All tests pass and deployed cleanly",
            "valence": 0.9,
            "session_id": "s1",
            "valence_source": "test_result",
        },
        db,
        config,
    )

    assert out["updated"] is True
    assert out["plan_status"] == "completed"
    assert out["lesson_id"] is not None


@pytest.mark.asyncio
async def test_recall_plans_returns_ranked_steps():
    class RecallDB(MockDB):
        def vector_search(self, table, index, _embedding, _limit):
            if table == "Plan":
                return [
                    {
                        "node": {
                            "plan_id": "p-good",
                            "goal": "Ship migration safely",
                            "valence": 0.8,
                            "pathway_strength": 1.2,
                        },
                        "score": 0.92,
                    },
                    {
                        "node": {
                            "plan_id": "p-bad",
                            "goal": "Risky migration",
                            "valence": 0.2,
                            "pathway_strength": 0.8,
                        },
                        "score": 0.85,
                    },
                ]
            return []

    db = RecallDB()
    db.step_rows_by_plan = {
        "p-good": [(1, "Write migration", 0.5, "succeeded"), (2, "Run tests", 0.9, "succeeded")],
        "p-bad": [(1, "Skip tests", -0.6, "failed")],
    }

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    out = await recall_plans(
        {"goal_query": "safe migration", "session_id": "s1", "min_valence": 0.0, "limit": 2},
        db,
        config,
    )

    assert len(out["plans"]) == 2
    assert out["plans"][0]["plan_id"] == "p-good"
    assert out["plans"][0]["steps"][0]["description"] == "Write migration"
