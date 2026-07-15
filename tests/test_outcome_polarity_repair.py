"""B302 — outcome-polarity graph repair sweep tests.

Fake-db coverage: agree leaves a Lesson untouched, disagree flips it (prefix +
valence + [valence_relabel: marker), ambiguous archives it, linked
system-valence Plans are corrected/nulled to match, explicit-valence Plans are
never touched, and post-B301 lessons (carrying [valence_trigger:) are never
candidates.
"""

from __future__ import annotations

import pytest

from campy.cli.graph_repair import find_candidates, repair_outcome_polarity

# Real B290 Lesson bodies (per B301's Problem section, filled out from the
# graph-confirmed fact that B290 shipped and merged — see docs/backlog/B301.md)
# so the current infer_outcome_valence reads them as unambiguous successes.
B290_LESSON_A = (
    "Plan outcome (failure): ✅ B290 Continuous Work State — COMPLETE & CERTIFIED "
    "… 192 passed, daemon healthy, merged to main via PR #2…"
)
B290_LESSON_B = (
    "Plan outcome (failure): ✅ B290 Continuous Work State — COMPLETE & CERTIFIED "
    "… 192 passed, daemon healthy, all 9 B290 commits in place, PR approved and merged…"
)


class FakeDB:
    def __init__(self, lessons: list[dict], plans: list[dict] | None = None):
        self.lessons = {l["lesson_id"]: dict(l) for l in lessons}
        self.plans = {p["plan_id"]: dict(p) for p in (plans or [])}
        # lesson_id -> plan_id, mirrors (Plan)-[:PRODUCED_PLAN_LESSON]->(Lesson)
        self.links = {
            p["plan_id"]: p["produced_lesson_id"]
            for p in (plans or [])
            if p.get("produced_lesson_id")
        }
        self.writes: list[tuple[str, dict]] = []

    async def execute_read(self, query: str, params: dict | None = None):
        assert "MATCH (l:Lesson)" in query
        rows = []
        for lesson in self.lessons.values():
            text = lesson["text_raw"]
            if not text.startswith("Plan outcome ("):
                continue
            if "[valence_trigger:" in text:
                continue
            if "[valence_relabel:" in text:
                continue
            if lesson.get("archived"):
                continue
            rows.append({"lesson_id": lesson["lesson_id"], "text_raw": text})
        return rows

    async def execute_write(self, query: str, params: dict | None = None):
        params = params or {}
        self.writes.append((query, params))
        if "MATCH (l:Lesson {lesson_id: $lid}) SET l.text_raw" in query:
            lesson = self.lessons[params["lid"]]
            lesson["text_raw"] = params["text"]
            lesson["valence"] = params["valence"]
        elif "MATCH (l:Lesson {lesson_id: $lid}) SET l.archived" in query:
            self.lessons[params["lid"]]["archived"] = True
        elif "PRODUCED_PLAN_LESSON" in query:
            lid = params["lid"]
            for plan_id, produced_lid in self.links.items():
                if produced_lid != lid:
                    continue
                plan = self.plans[plan_id]
                if plan.get("valence_source") != "system":
                    continue
                old_valence = plan.get("valence") or 0.0
                wants_negative = "p.valence < 0" in query
                if wants_negative and not (old_valence < 0):
                    continue
                if not wants_negative and not (old_valence > 0):
                    continue
                plan["valence"] = params["valence"]


@pytest.mark.asyncio
async def test_agreeing_polarity_is_left_untouched():
    db = FakeDB([
        {"lesson_id": "l1", "text_raw": "Plan outcome (failure): that broke the build, revert it"},
    ])
    candidates = await find_candidates(db)
    assert candidates == []


@pytest.mark.asyncio
async def test_wrong_polarity_flips_prefix_valence_and_marker():
    db = FakeDB([
        {"lesson_id": "l1", "text_raw": B290_LESSON_A},
        {"lesson_id": "l2", "text_raw": B290_LESSON_B},
    ])
    candidates = await find_candidates(db)
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.old_polarity == "failure"
        assert candidate.new_polarity == "success"
        assert candidate.action == "flip"
        assert candidate.new_text.startswith("Plan outcome (success):")
        assert "[valence_relabel: B302, was failure]" in candidate.new_text
        assert candidate.new_valence == 0.8


@pytest.mark.asyncio
async def test_ambiguous_verdict_is_archived():
    db = FakeDB([
        {"lesson_id": "l1", "text_raw": "Plan outcome (failure): 17 failed"},
    ])
    candidates = await find_candidates(db)
    assert len(candidates) == 1
    assert candidates[0].action == "archive"
    assert candidates[0].new_polarity is None

    await repair_outcome_polarity(db, apply=True)
    assert db.lessons["l1"]["archived"] is True


@pytest.mark.asyncio
async def test_lessons_with_valence_trigger_are_never_candidates():
    db = FakeDB([
        {
            "lesson_id": "l1",
            "text_raw": "Plan outcome (failure): that broke it\n[valence_trigger: that broke]",
        },
    ])
    candidates = await find_candidates(db)
    assert candidates == []


@pytest.mark.asyncio
async def test_linked_system_valence_plan_is_corrected():
    db = FakeDB(
        [{"lesson_id": "l1", "text_raw": B290_LESSON_A}],
        [{"plan_id": "p1", "valence": -0.8, "valence_source": "system", "produced_lesson_id": "l1"}],
    )
    await repair_outcome_polarity(db, apply=True)
    assert db.lessons["l1"]["text_raw"].startswith("Plan outcome (success):")
    assert db.plans["p1"]["valence"] == 0.8


@pytest.mark.asyncio
async def test_explicit_valence_plan_is_never_touched():
    db = FakeDB(
        [{"lesson_id": "l1", "text_raw": B290_LESSON_A}],
        [{"plan_id": "p1", "valence": -0.8, "valence_source": "user", "produced_lesson_id": "l1"}],
    )
    await repair_outcome_polarity(db, apply=True)
    assert db.plans["p1"]["valence"] == -0.8


@pytest.mark.asyncio
async def test_apply_is_idempotent():
    db = FakeDB([
        {"lesson_id": "l1", "text_raw": B290_LESSON_A},
        {"lesson_id": "l2", "text_raw": "Plan outcome (failure): 17 failed"},
    ])
    first = await repair_outcome_polarity(db, apply=True)
    assert len(first) == 2

    second = await repair_outcome_polarity(db, apply=True)
    assert second == []
