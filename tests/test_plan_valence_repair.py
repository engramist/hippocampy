"""B303 — plan-valence graph repair sweep tests.

Extends B302's outcome-polarity sweep from Lessons to Plans directly: plans
whose Lessons were archived, or whose valence came straight from the old
buggy auto-report_outcome, keep their wrong valence even after B302 runs.
This sweep re-judges Plan.goal + PlanStep.actual_outcome text with the fixed
infer_outcome_valence and flips/nulls plans whose stored valence disagrees.
"""

from __future__ import annotations

import pytest

from campy.cli.graph_repair import find_plan_valence_candidates, repair_plan_valence

B290_GOAL = (
    "✅ B290 Continuous Work State — COMPLETE & CERTIFIED "
    "… 192 passed, daemon healthy, merged to main via PR #2…"
)


class FakeDB:
    def __init__(self, plans: list[dict], steps: list[dict] | None = None):
        self.plans = {p["plan_id"]: dict(p) for p in plans}
        self.steps: dict[str, list[dict]] = {}
        for step in steps or []:
            self.steps.setdefault(step["plan_id"], []).append(step)
        self.writes: list[tuple[str, dict]] = []

    async def execute_read(self, query: str, params: dict | None = None):
        params = params or {}
        if "MATCH (p:Plan)" in query and "RETURN p.plan_id" in query:
            rows = []
            for plan in self.plans.values():
                if plan.get("valence_source") not in (None, "system"):
                    continue
                if plan.get("valence") is None:
                    continue
                if plan.get("archived"):
                    continue
                rows.append({
                    "plan_id": plan["plan_id"],
                    "goal": plan.get("goal", ""),
                    "valence": plan.get("valence"),
                })
            return rows

        if "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})" in query:
            pid = params["pid"]
            steps = sorted(self.steps.get(pid, []), key=lambda s: s.get("step_number", 0))
            return [{"actual_outcome": s.get("actual_outcome")} for s in steps]

        return []

    async def execute_write(self, query: str, params: dict | None = None):
        params = params or {}
        self.writes.append((query, params))
        if "MATCH (p:Plan {plan_id: $pid}) SET p.valence" in query:
            plan = self.plans[params["pid"]]
            plan["valence"] = params["valence"]
            plan["valence_source"] = params["source"]


@pytest.mark.asyncio
async def test_agreeing_valence_is_left_untouched():
    db = FakeDB([
        {"plan_id": "p1", "goal": "that broke the build, revert it", "valence": -0.8, "valence_source": "system"},
    ])
    candidates = await find_plan_valence_candidates(db)
    assert candidates == []


@pytest.mark.asyncio
async def test_wrong_polarity_plan_flips():
    db = FakeDB([
        {"plan_id": "p1", "goal": B290_GOAL, "valence": -0.8, "valence_source": "system"},
    ])
    candidates = await find_plan_valence_candidates(db)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.plan_id == "p1"
    assert candidate.old_valence == -0.8
    assert candidate.new_valence == 0.8
    assert candidate.action == "flip"

    await repair_plan_valence(db, apply=True)
    assert db.plans["p1"]["valence"] == 0.8
    assert db.plans["p1"]["valence_source"] != "system"


@pytest.mark.asyncio
async def test_ambiguous_verdict_is_left_untouched():
    """Flip-only: pre-fix report_outcome stamped explicit MCP calls as
    'system' too, so an ambiguous re-judgment of the text can't distinguish
    "auto-inferred badly" from "the judgment was the explicit number". Nulling
    would erase legitimate valences (recall_plans skips valence-None plans)."""
    db = FakeDB([
        {"plan_id": "p1", "goal": "17 failed", "valence": -0.8, "valence_source": "system"},
    ])
    candidates = await find_plan_valence_candidates(db)
    assert candidates == []

    await repair_plan_valence(db, apply=True)
    assert db.plans["p1"]["valence"] == -0.8
    assert db.plans["p1"]["valence_source"] == "system"


@pytest.mark.asyncio
async def test_explicit_valence_source_plan_is_never_a_candidate():
    db = FakeDB([
        {"plan_id": "p1", "goal": B290_GOAL, "valence": -0.8, "valence_source": "user"},
    ])
    candidates = await find_plan_valence_candidates(db)
    assert candidates == []


@pytest.mark.asyncio
async def test_null_valence_source_plan_is_a_candidate():
    db = FakeDB([
        {"plan_id": "p1", "goal": B290_GOAL, "valence": -0.8, "valence_source": None},
    ])
    candidates = await find_plan_valence_candidates(db)
    assert len(candidates) == 1
    assert candidates[0].action == "flip"


@pytest.mark.asyncio
async def test_archived_plan_is_never_a_candidate():
    db = FakeDB([
        {"plan_id": "p1", "goal": B290_GOAL, "valence": -0.8, "valence_source": "system", "archived": True},
    ])
    candidates = await find_plan_valence_candidates(db)
    assert candidates == []


@pytest.mark.asyncio
async def test_step_outcomes_are_folded_into_the_verdict():
    """A neutral goal with a decisive step outcome should still be re-judged
    correctly — the sweep re-judges goal+step outcomes together, per B303."""
    db = FakeDB(
        [{"plan_id": "p1", "goal": "Ship the thing", "valence": -0.8, "valence_source": "system"}],
        [{"plan_id": "p1", "step_number": 1, "actual_outcome": "that broke the build, revert it"}],
    )
    candidates = await find_plan_valence_candidates(db)
    assert candidates == []  # step outcome agrees with stored -0.8 (failure)


@pytest.mark.asyncio
async def test_apply_is_idempotent():
    db = FakeDB([
        {"plan_id": "p1", "goal": B290_GOAL, "valence": -0.8, "valence_source": "system"},
        {"plan_id": "p2", "goal": "17 failed", "valence": -0.8, "valence_source": "system"},
    ])
    first = await repair_plan_valence(db, apply=True)
    assert len(first) == 1  # p2 is ambiguous — skipped, not nulled

    second = await repair_plan_valence(db, apply=True)
    assert second == []
