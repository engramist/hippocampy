"""B305 — bundle relevance floor: off-topic queries must not manufacture content.

`_stage_plans` (and other similarity-ranked bundle stages) previously returned
whatever ranked highest with no minimum-similarity floor, so a bundle was
never truly empty even for a query with zero matching content in the graph.
These tests pin the 0.70 similarity floor (mirroring the convention already
used in `_stage_exact_facts`) and confirm B303's lexical identifier bypass
still survives it.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph import embeddings as emb_mod
from campy.brain.thalamus.bundle_compiler import _stage_plans, compile_bundle
from campy.brain.thalamus.tools import compile_context


class FakeResult:
    def __init__(self, rows):
        self.rows = rows
        self.idx = 0

    def has_next(self):
        return self.idx < len(self.rows)

    def get_next(self):
        row = self.rows[self.idx]
        self.idx += 1
        return row


class PlanFloorDB:
    """Minimal fake DB: plan vector_search + lexical scan + plan-step lookup."""

    def __init__(self):
        self.plans: dict[str, dict] = {}

    def vector_search(self, table_name, index_name, embedding, limit):
        if index_name != "plan_emb_idx":
            return []
        rows = []
        for plan in self.plans.values():
            rows.append({
                "node": {
                    "plan_id": plan["plan_id"],
                    "goal": plan.get("goal", ""),
                    "status": plan.get("status", "completed"),
                    "valence": plan.get("valence", 0.8),
                    "pathway_strength": plan.get("pathway_strength", 0.9),
                    "confidence": plan.get("confidence", 0.9),
                    "archived": False,
                },
                "score": plan.get("score", 0.95),
            })
        return rows[:limit]

    def execute(self, query: str, params: dict | None = None):
        params = params or {}
        q = " ".join(query.split())

        if "MATCH (p:Plan) WHERE p.archived = false" in q and "RETURN p.plan_id" in q:
            rows = []
            for plan in self.plans.values():
                rows.append([
                    plan["plan_id"],
                    plan.get("goal", ""),
                    plan.get("status", "completed"),
                    plan.get("valence", 0.8),
                    plan.get("pathway_strength", 0.9),
                    plan.get("confidence", 0.9),
                ])
            return FakeResult(rows)

        if "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})" in q:
            return FakeResult([])

        # _stage_exact_facts / _stage_semantic_context issue raw vector_distance
        # Cypher this fake doesn't model — always "no match" for those, which
        # is the realistic outcome for an off-topic query anyway.
        return FakeResult([])

    async def execute_write(self, query: str, params: dict | None = None):
        return None


@pytest.fixture(autouse=True)
def _offline_embeddings(monkeypatch):
    monkeypatch.setattr(emb_mod, "embed", lambda text, model_name=None: [0.1] * 384)


@pytest.fixture
def config():
    return {"embeddings": {"model": "mock"}}


@pytest.mark.asyncio
async def test_stage_plans_returns_none_when_all_candidates_below_floor(config):
    """Plans whose vector similarity never clears 0.70 must not surface at all."""
    db = PlanFloorDB()
    db.plans["off-topic"] = {
        "plan_id": "off-topic",
        "goal": "Implement B292 by splitting tools/__init__.py into focused modules",
        "score": 0.20,
    }

    section = await _stage_plans(db, "What did we decide about Kubernetes deployment?", config, {"max_semantic": 10})

    assert section is None


@pytest.mark.asyncio
async def test_stage_plans_keeps_candidates_at_or_above_floor(config):
    db = PlanFloorDB()
    db.plans["on-topic"] = {
        "plan_id": "on-topic",
        "goal": "Implement B299 plan-lane retrieval visibility",
        "score": 0.85,
    }

    section = await _stage_plans(db, "What work did we do for B299?", config, {"max_semantic": 10})

    assert section is not None
    plan_ids = [item["plan_id"] for item in section.content]
    assert plan_ids == ["on-topic"]


@pytest.mark.asyncio
async def test_stage_plans_lexical_identifier_match_survives_floor(config):
    """B303's exact \\bB\\d+\\b bypass must surface a plan even far below 0.70
    cosine similarity — an identifier match is strong evidence on its own."""
    db = PlanFloorDB()
    db.plans["b292"] = {
        "plan_id": "b292",
        "goal": "Implement B292 by splitting tools/__init__.py into focused modules",
        "score": 0.05,
    }

    section = await _stage_plans(db, "What work was done on B292?", config, {"max_semantic": 10})

    assert section is not None
    plan_ids = [item["plan_id"] for item in section.content]
    assert "b292" in plan_ids


@pytest.mark.asyncio
async def test_compile_bundle_off_topic_query_has_no_non_lexical_sections(config):
    """Mirrors B304's negative-control setup: a realistic fixture graph with
    on-topic plans, queried about something the graph has zero information
    on. The bundle must come back with no plans section at all (not just an
    empty one)."""
    db = PlanFloorDB()
    db.plans["b292"] = {
        "plan_id": "b292",
        "goal": "Implement B292 by splitting tools/__init__.py into focused modules",
        "score": 0.15,
    }
    db.plans["b299"] = {
        "plan_id": "b299",
        "goal": "Implement B299 plan-lane retrieval visibility",
        "score": 0.10,
    }

    bundle = await compile_bundle(
        query="What did we decide about the Kubernetes deployment?",
        db=db,
        config=config,
    )

    section_types = [s.section_type for s in bundle.sections]
    assert "plans" not in section_types


@pytest.mark.asyncio
async def test_compile_bundle_off_topic_query_still_surfaces_lexical_identifier_match(config):
    """Same off-topic-graph setup, but the query names an identifier that
    exists in the fixture — the lexical bypass must still surface that plan."""
    db = PlanFloorDB()
    db.plans["b292"] = {
        "plan_id": "b292",
        "goal": "Implement B292 by splitting tools/__init__.py into focused modules",
        "score": 0.05,
    }

    bundle = await compile_bundle(
        query="What did we decide about B292?",
        db=db,
        config=config,
    )

    plans_sections = [s for s in bundle.sections if s.section_type == "plans"]
    assert plans_sections
    plan_ids = [item["plan_id"] for item in plans_sections[0].content]
    assert "b292" in plan_ids


@pytest.mark.asyncio
async def test_compile_context_off_topic_query_returns_empty_bundle(config):
    """End-to-end via the compile_context MCP tool entry point."""
    db = PlanFloorDB()
    db.plans["b292"] = {
        "plan_id": "b292",
        "goal": "Implement B292 by splitting tools/__init__.py into focused modules",
        "score": 0.15,
    }

    result = await compile_context(
        {"query": "What did we decide about the Kubernetes deployment?", "token_budget": 32000},
        db,
        config,
    )

    sections = result["bundle"]["sections"]
    assert all(s["type"] != "plans" for s in sections)
