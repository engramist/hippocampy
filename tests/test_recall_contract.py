from __future__ import annotations

import pytest

from campy.brain.thalamus.tools import (
    compile_context,
    current_truth,
    notify_turn,
    register_plan,
    report_outcome,
)


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


class RecallContractDB:
    """Small in-memory stand-in for the recall contract.

    It models the pieces current_truth/notify_turn need without requiring a
    real Kuzu lock: Message writes, vector candidates, exact Message lookup,
    LOADED writes, and token accounting.
    """

    def __init__(self):
        self.messages: dict[str, dict] = {}
        self.decisions: dict[str, dict] = {}
        self.plans: dict[str, dict] = {}
        self.plan_steps: dict[str, dict] = {}
        self.step_plan: dict[str, str] = {}
        self.loaded_edges: list[dict] = []
        self.writes: list[dict] = []
        self.token_estimate = 0
        self.token_limit = 128000

    def add_decision(
        self,
        *,
        decision_id: str,
        text_raw: str,
        pathway_strength: float,
        confidence: float,
        score: float = 0.7,
    ) -> None:
        self.decisions[decision_id] = {
            "node": {
                "decision_id": decision_id,
                "text_raw": text_raw,
                "pathway_strength": pathway_strength,
                "confidence": confidence,
                "confidence_low": False,
                "archived": False,
            },
            "score": score,
        }

    def vector_search(self, table_name, index_name, embedding, limit):
        if index_name == "message_emb_idx":
            rows = []
            for message in self.messages.values():
                rows.append({
                    "node": {
                        "message_id": message["message_id"],
                        "text_raw": message["text_raw"],
                        "role": message["role"],
                        "pathway_strength": message.get("pathway_strength", 0.0),
                        "confidence": message.get("confidence", 0.0),
                        "confidence_low": message.get("confidence_low", True),
                        "archived": False,
                    },
                    "score": message.get("score", 0.95),
                })
            return rows[:limit]
        if index_name == "decision_emb_idx":
            return list(self.decisions.values())[:limit]
        if index_name == "plan_emb_idx":
            rows = []
            for plan in self.plans.values():
                rows.append({
                    "node": {
                        "plan_id": plan["plan_id"],
                        "goal": plan.get("goal", ""),
                        "status": plan.get("status", "active"),
                        "valence": plan.get("valence"),
                        "pathway_strength": plan.get("pathway_strength", 0.9),
                        "confidence": plan.get("confidence", 0.9),
                        "confidence_low": False,
                        "archived": False,
                    },
                    "score": plan.get("score", 0.95),
                })
            return rows[:limit]
        return []

    def execute(self, query: str, params: dict | None = None):
        params = params or {}
        q = " ".join(query.split())

        if "WORKING_ON" in q:
            return FakeResult([])

        if "UNWIND $ids AS nid" in q:
            return FakeResult([])

        if "RETURN s.token_estimate, s.token_limit, s.loaded_node_count" in q:
            return FakeResult([[self.token_estimate, self.token_limit, len(self.loaded_edges), 0, 0]])

        if "RETURN s.token_estimate" in q:
            return FakeResult([[self.token_estimate]])

        if "RETURN count(m)" in q:
            return FakeResult([[len(self.messages)]])

        if "RETURN count(*)" in q and "LOADED" in q:
            return FakeResult([[len(self.loaded_edges)]])

        if "[:LOADED]->" in q and "RETURN n." in q:
            return FakeResult([[edge["node_id"]] for edge in self.loaded_edges])

        if "-[l:LOADED]->" in q and "RETURN l.load_hits" in q:
            nid = params.get("nid")
            hits = [edge["load_hits"] for edge in self.loaded_edges if edge["node_id"] == nid]
            return FakeResult([[hits[0]]] if hits else [])

        if "MATCH (m:Message) WHERE lower(m.text_raw) CONTAINS lower($query)" in q:
            needle = (params.get("query") or "").lower()
            rows = []
            for message in self.messages.values():
                if needle in message["text_raw"].lower():
                    rows.append([
                        message["message_id"],
                        message["text_raw"],
                        message["role"],
                        message.get("confidence", 0.0),
                        message.get("confidence_low", True),
                        message.get("pathway_strength", 0.0),
                        message.get("created_at"),
                    ])
            return FakeResult(rows)

        if "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})" in q:
            pid = params.get("pid")
            rows = []
            for step_id, plan_id in self.step_plan.items():
                if plan_id != pid:
                    continue
                step = self.plan_steps.get(step_id, {})
                rows.append([
                    step.get("step_number", 0),
                    step.get("description", ""),
                    step.get("valence"),
                    step.get("status", "pending"),
                ])
            rows.sort(key=lambda r: r[0])
            return FakeResult(rows)

        if "WHERE m.message_id <> $mid" in q:
            return FakeResult([])

        if "MATCH (p:Plan) WHERE p.archived = false" in q and "RETURN p.plan_id" in q:
            rows = []
            for plan in self.plans.values():
                rows.append([
                    plan["plan_id"],
                    plan.get("goal", ""),
                    plan.get("status", "active"),
                    plan.get("valence"),
                    plan.get("pathway_strength", 0.9),
                    plan.get("confidence", 0.9),
                ])
            return FakeResult(rows)

        return FakeResult([])

    async def execute_write(self, query: str, params: dict | None = None):
        params = params or {}
        q = " ".join(query.split())
        self.writes.append({"query": q, "params": params})

        if "CREATE (m:Message" in q:
            self.messages[params["message_id"]] = {
                "message_id": params["message_id"],
                "text_raw": params["text_raw"],
                "role": params["role"],
                "created_at": params["created_at"],
                "pathway_strength": 0.0,
                "confidence": 0.0,
                "confidence_low": True,
                "score": 0.95,
            }
            return

        if "CREATE (p:Plan" in q:
            self.plans[params["plan_id"]] = {
                "plan_id": params["plan_id"],
                "goal": params.get("goal", ""),
                "status": "active",
                "valence": None,
                "pathway_strength": params.get("pathway_strength", 0.9),
                "confidence": params.get("confidence", 0.9),
                "score": 0.98,
            }
            return

        if "CREATE (ps:PlanStep" in q:
            self.plan_steps[params["step_id"]] = {
                "step_id": params["step_id"],
                "step_number": params.get("step_number", 0),
                "description": params.get("description", ""),
                "valence": None,
                "status": "pending",
            }
            return

        if "MERGE (ps)-[:STEP_OF]->(p)" in q:
            self.step_plan[params["step_id"]] = params["plan_id"]
            return

        if "SET ps.actual_outcome = $outcome" in q and "ps.status = $status" in q:
            pid = params.get("pid")
            step_number = params.get("step_number")
            for sid, linked_pid in self.step_plan.items():
                if linked_pid != pid:
                    continue
                step = self.plan_steps.get(sid)
                if step and step.get("step_number") == step_number:
                    step["valence"] = params.get("valence")
                    step["status"] = params.get("status", "pending")
            return

        if "MATCH (p:Plan {plan_id: $pid})" in q and "SET p.valence = $valence" in q:
            plan = self.plans.get(params.get("pid"))
            if plan is not None:
                plan["valence"] = params.get("valence")
                plan["status"] = "completed"
            return

        if "CREATE (s)-[:LOADED" in q:
            self.loaded_edges.append({
                "node_id": params["nid"],
                "source": params.get("source"),
                "load_hits": 1,
            })
            return

        if "SET s.token_estimate = $est" in q:
            self.token_estimate = params["est"]


@pytest.fixture(autouse=True)
def _offline_embeddings(monkeypatch):
    monkeypatch.setattr("campy.brain.thalamus.tools.emb.embed", lambda text, model_name=None: [0.1] * 384)


@pytest.fixture
def _no_git_quest_work(monkeypatch):
    async def _quest(*args, **kwargs):
        return "quest-recall-contract"

    async def _session(*args, **kwargs):
        return None

    monkeypatch.setattr("campy.brain.thalamus.tools.get_or_create_main_quest", _quest)
    monkeypatch.setattr("campy.brain.thalamus.tools.get_or_create_session", _session)


@pytest.mark.asyncio
async def test_recall_contract_captures_and_finds_raw_message_without_loaded_edge(_no_git_quest_work):
    db = RecallContractDB()
    phrase = "recall_contract_probe_sidequests_no_context_bloat_001"

    stored = await notify_turn(
        {
            "role": "user",
            "content": f"Please remember this test phrase: {phrase}",
            "session_id": "recall-contract",
            "repo_root": "/repo",
            "git_branch": "main",
        },
        db,
        {"embeddings": {"model": "mock"}, "ingestion": {"max_ingest_chars": 4000}},
    )
    assert stored["status"] == "ingested"
    assert db.messages

    recalled = await current_truth(
        {
            "query": phrase,
            "session_id": "recall-contract",
            "scope": "both",
            "limit": 5,
        },
        db,
        {"embeddings": {"model": "mock"}},
    )

    assert any(r["node_type"] == "Message" and phrase in r["text_raw"] for r in recalled["results"])
    assert db.loaded_edges == []
    assert db.token_estimate > 0


@pytest.mark.xfail(
    reason="B287 (Principled Score Fusion): current_truth's ranking is ad-hoc — "
    "a lexical/vector 'score' field is mixed with pathway_strength and confidence "
    "with no normalization, so a high-score-but-low-confidence raw Message can "
    "outrank a lower-score-but-high-confidence consolidated Decision. B287 replaces "
    "this with Reciprocal Rank Fusion + bounded pathway_strength/confidence "
    "adjustments; see backlog/B287.md for the fix design.",
    strict=False,
)
@pytest.mark.asyncio
async def test_recall_contract_consolidated_memory_outranks_raw_message(_no_git_quest_work):
    db = RecallContractDB()
    phrase = "recall_contract_installer_capture_policy"
    db.messages["m-low"] = {
        "message_id": "m-low",
        "text_raw": f"Raw transcript mention: {phrase}",
        "role": "user",
        "created_at": "2026-05-10T00:00:00Z",
        "pathway_strength": 0.1,
        "confidence": 0.2,
        "confidence_low": True,
        "score": 0.99,
    }
    db.add_decision(
        decision_id="d-high",
        text_raw=f"Decision: keep {phrase} as durable capture fallback, not context cargo.",
        pathway_strength=0.9,
        confidence=0.9,
        score=0.65,
    )

    recalled = await current_truth(
        {
            "query": phrase,
            "session_id": "recall-contract",
            "scope": "both",
            "limit": 5,
        },
        db,
        {"embeddings": {"model": "mock"}},
    )

    assert recalled["results"][0]["node_type"] == "Decision"
    assert recalled["results"][0]["node_id"] == "d-high"
    assert any(edge["node_id"] == "d-high" for edge in db.loaded_edges)
    assert not any(edge["node_id"] == "m-low" for edge in db.loaded_edges)


@pytest.mark.asyncio
async def test_recall_contract_respects_limit(_no_git_quest_work):
    db = RecallContractDB()
    for idx in range(10):
        db.add_decision(
            decision_id=f"d-{idx}",
            text_raw=f"Recall limit candidate {idx}",
            pathway_strength=1.0 - (idx * 0.01),
            confidence=0.9,
            score=0.8,
        )

    recalled = await current_truth(
        {
            "query": "Recall limit candidate",
            "session_id": "recall-contract",
            "scope": "both",
            "limit": 3,
        },
        db,
        {"embeddings": {"model": "mock"}},
    )

    assert len(recalled["results"]) == 3


@pytest.mark.asyncio
async def test_plan_lane_surfaces_in_current_truth_and_compile_context(_no_git_quest_work, monkeypatch):
    import campy.brain.thalamus.tools.quests as quests_mod

    db = RecallContractDB()
    config = {"embeddings": {"model": "mock"}}

    async def _stub_store_plan_outcome_lesson(*args, **kwargs):
        return "lesson-plan-lane"

    monkeypatch.setattr(quests_mod, "_store_plan_outcome_lesson", _stub_store_plan_outcome_lesson)

    registered = await register_plan(
        {
            "goal": "Implement B299 plan-lane retrieval visibility",
            "steps": [
                "Add Plan and Procedure retrievable tags",
                "Wire plan lane into compile_context",
            ],
            "session_id": "recall-contract",
        },
        db,
        config,
    )
    assert registered["status"] == "registered"

    completed = await report_outcome(
        {
            "plan_id": registered["plan_id"],
            "outcome": "Implemented and verified with regression tests",
            "valence": 0.9,
            "session_id": "recall-contract",
            "valence_source": "test_result",
        },
        db,
        config,
    )
    assert completed["plan_status"] == "completed"

    truth = await current_truth(
        {
            "query": "What work did we do for B299 plan lane retrieval?",
            "session_id": "recall-contract",
            "scope": "both",
            "limit": 5,
        },
        db,
        config,
    )

    plan_rows = [r for r in truth["results"] if r.get("node_type") == "Plan"]
    assert plan_rows
    assert plan_rows[0]["text_raw"]
    assert plan_rows[0].get("status") == "completed"
    assert plan_rows[0].get("valence") == pytest.approx(0.9)

    compiled = await compile_context(
        {
            "query": "Summarize B299 plan lane work",
            "token_budget": 32000,
            "session_id": "recall-contract",
        },
        db,
        config,
    )
    sections = compiled["bundle"]["sections"]
    plan_sections = [s for s in sections if s.get("type") == "plans"]
    assert plan_sections
    top_plan = plan_sections[0]["content"][0]
    assert "B299" in top_plan.get("goal", "")
    assert top_plan.get("steps")


@pytest.mark.asyncio
async def test_recall_plans_lexical_assist_surfaces_identifier_match_over_embedding_noise():
    """B303: a question mentioning a card identifier ("B292") must always
    surface plans whose goal mentions that identifier, even when unrelated
    plans score higher on embedding similarity (the question-vs-goal
    mismatch B303 documents)."""
    from campy.brain.thalamus.tools.quests import recall_plans_for_query

    db = RecallContractDB()
    config = {"embeddings": {"model": "mock"}}

    for i in range(3):
        db.plans[f"noise-{i}"] = {
            "plan_id": f"noise-{i}",
            "goal": f"Unrelated verbose plan {i} about something else entirely",
            "status": "completed",
            "valence": 0.8,
            "pathway_strength": 0.9,
            "confidence": 0.9,
            "score": 0.85,
        }

    db.plans["b292"] = {
        "plan_id": "b292",
        "goal": "Implement B292 by splitting tools/__init__.py into focused modules",
        "status": "completed",
        "valence": 0.7,
        "pathway_strength": 0.9,
        "confidence": 0.9,
        "score": 0.10,
    }

    plans = await recall_plans_for_query(
        goal_query="What work did the agent do on B292?",
        db=db,
        config=config,
        limit=3,
        min_valence=-1.0,
    )

    plan_ids = [p["plan_id"] for p in plans]
    assert "b292" in plan_ids
    assert plans[0]["plan_id"] == "b292"


@pytest.mark.asyncio
async def test_recall_plans_lexical_assist_noop_without_identifier_or_quoted_phrase():
    """No lexical terms in the query means no extra candidates are pulled in
    beyond whatever vector_search already returned."""
    from campy.brain.thalamus.tools.quests import recall_plans_for_query

    db = RecallContractDB()
    config = {"embeddings": {"model": "mock"}}
    db.plans["p1"] = {
        "plan_id": "p1",
        "goal": "Some plan with no identifiers",
        "status": "completed",
        "valence": 0.5,
        "pathway_strength": 0.9,
        "confidence": 0.9,
        "score": 0.5,
    }

    plans = await recall_plans_for_query(
        goal_query="generic question with no identifiers",
        db=db,
        config=config,
        limit=5,
        min_valence=-1.0,
    )
    assert [p["plan_id"] for p in plans] == ["p1"]
