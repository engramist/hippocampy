"""
tests/test_model_router.py — B382 Dynamic Phase-Aware Model Router.

Drives a real OxigraphClient (not a mock) per this session's established
practice: NamedQuery Cypher text passing a syntax check proves nothing
about the actual Oxigraph SPARQL dispatch path (see B432/B437's history
of "tests only ever exercised Kùzu, never the real production engine").
"""

from __future__ import annotations

import shutil
import tempfile
import time

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient, mint_uri
from campy.brain.thalamus.model_router import (
    DEFAULT_ROUTING_CONFIG,
    _is_reflex_task,
    _resolve_routing_config,
    detect_phase,
    route_task,
)

CONFIG = {"embeddings": {"model": "fake-test-model"}}


@pytest.fixture()
def real_db():
    tmp = tempfile.mkdtemp(prefix="model_router_")
    db = OxigraphClient(f"{tmp}/db")
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _seed_session_and_quest(db, session_id: str, quest_id: str) -> None:
    db.write_node("MainQuest", {
        "quest_id": quest_id, "name": "test quest", "status": "active",
    })
    db.write_node("Session", {"session_id": session_id})
    db.write_edge("WORKING_ON", mint_uri("Session", session_id), mint_uri("MainQuest", quest_id))


def _seed_active_plan(db, plan_id: str, quest_id: str, goal: str) -> None:
    db.write_node("Plan", {
        "plan_id": plan_id, "goal": goal, "status": "active", "confidence": 0.8,
    })
    db.write_edge("TARGETS", mint_uri("Plan", plan_id), mint_uri("MainQuest", quest_id))


def _seed_completed_plan(db, plan_id: str, quest_id: str, goal: str) -> None:
    db.write_node("Plan", {
        "plan_id": plan_id, "goal": goal, "status": "completed", "confidence": 0.9,
    })
    db.write_edge("TARGETS", mint_uri("Plan", plan_id), mint_uri("MainQuest", quest_id))


def _seed_task_graph(db, graph_id: str, session_id: str, task_statuses: list[str]) -> None:
    db.write_node("TaskGraph", {
        "graph_id": graph_id, "session_id": session_id, "status": "active",
    })
    for i, status in enumerate(task_statuses):
        task_id = f"{graph_id}-t{i}"
        db.write_node("TaskNode", {
            "task_id": task_id, "graph_id": graph_id, "label": f"task {i}", "status": status,
        })
        db.write_edge("TASK_OF", mint_uri("TaskNode", task_id), mint_uri("TaskGraph", graph_id))


class TestReflexFastPath:
    def test_reflex_keywords_detected(self):
        assert _is_reflex_task("run prettier formatting on this file")
        assert _is_reflex_task("just a lint pass please")
        assert _is_reflex_task("syntax check the module")
        assert not _is_reflex_task("design the new auth architecture")

    async def test_reflex_task_never_touches_graph(self):
        """A reflex task must short-circuit before any db call -- pass a
        db object that raises on any attribute access to prove it."""
        class ExplodingDB:
            def __getattr__(self, name):
                raise AssertionError(f"reflex path touched db.{name}")

        result = await route_task(
            ExplodingDB(), CONFIG, "please run prettier formatting", session_id="s1",
        )
        assert result["tier"] == "local_reflex"
        assert result["phase"] == "reflex"
        assert result["context_bundle"] is None


class TestPhaseDetection:
    async def test_cold_start_defaults_to_planning(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")

        result = await detect_phase(db, "s1")

        assert result["phase"] == "planning"
        assert result["active_plans"] == []
        assert result["task_graph_status"] is None

    async def test_active_plan_means_planning_phase(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_active_plan(db, "p1", "q1", "decide on the auth architecture")

        result = await detect_phase(db, "s1")

        assert result["phase"] == "planning"
        assert len(result["active_plans"]) == 1
        assert result["active_plans"][0]["goal"] == "decide on the auth architecture"

    async def test_completed_plan_does_not_trigger_planning(self, real_db):
        """A completed Plan must not count as an open planning signal --
        only status='active' Plans should."""
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_completed_plan(db, "p1", "q1", "already decided this")
        _seed_task_graph(db, "g1", "s1", ["pending", "pending"])

        result = await detect_phase(db, "s1")

        assert result["phase"] == "implementation"
        assert result["active_plans"] == []

    async def test_active_task_graph_means_implementation_phase(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_task_graph(db, "g1", "s1", ["pending", "active", "complete"])

        result = await detect_phase(db, "s1")

        assert result["phase"] == "implementation"
        assert result["task_graph_status"]["graph_id"] == "g1"
        assert result["task_graph_status"]["pending_or_active"] == 2
        assert result["task_graph_status"]["complete"] == 1
        assert result["task_graph_status"]["total"] == 3

    async def test_task_graph_all_complete_falls_back_to_planning(self, real_db):
        """A TaskGraph with every TaskNode complete has no pending
        execution work -- with no active Plan either, this is cold-start
        Planning, not a false Implementation signal."""
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_task_graph(db, "g1", "s1", ["complete", "complete"])

        result = await detect_phase(db, "s1")

        assert result["phase"] == "planning"

    async def test_active_plan_overrides_active_task_graph(self, real_db):
        """A new open Plan on a quest that also has in-progress execution
        should still route to Planning -- a fresh unresolved decision
        takes priority over ongoing mechanical execution."""
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_active_plan(db, "p1", "q1", "reconsider the approach")
        _seed_task_graph(db, "g1", "s1", ["pending"])

        result = await detect_phase(db, "s1")

        assert result["phase"] == "planning"

    async def test_unknown_session_resolves_no_quest(self, real_db):
        db = real_db
        result = await detect_phase(db, "unknown")
        assert result["phase"] == "planning"
        assert result["quest_id"] == ""

    async def test_explicit_quest_id_bypasses_session_resolution(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_active_plan(db, "p1", "q1", "explicit quest goal")

        result = await detect_phase(db, "s-does-not-matter", quest_id="q1")

        assert result["quest_id"] == "q1"
        assert result["phase"] == "planning"
        assert len(result["active_plans"]) == 1


class TestRouteTaskRecommendation:
    async def test_planning_phase_routes_to_frontier_tier(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_active_plan(db, "p1", "q1", "pick the right caching strategy")

        result = await route_task(db, CONFIG, "help me decide on caching", session_id="s1")

        assert result["tier"] == "frontier"
        assert result["provider"] == "anthropic"
        assert result["recommended_model"] == "claude-opus-5"
        assert result["phase"] == "planning"
        assert result["context_bundle"] is not None
        assert result["context_bundle"]["sections"][0]["type"] == "plans"

    async def test_implementation_phase_routes_to_economy_tier(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_task_graph(db, "g1", "s1", ["pending", "active"])

        result = await route_task(db, CONFIG, "implement the next task", session_id="s1")

        assert result["tier"] == "economy"
        assert result["provider"] == "ollama"
        assert result["recommended_model"] == "llama3.1:8b"
        assert result["phase"] == "implementation"

    async def test_reflex_task_routes_to_local_reflex_tier(self, real_db):
        db = real_db
        result = await route_task(db, CONFIG, "run black formatting", session_id="s1")
        assert result["tier"] == "local_reflex"
        assert result["recommended_model"] == "qwen2.5-coder:7b"

    async def test_routing_disabled_returns_no_recommendation(self, real_db):
        db = real_db
        config = {**CONFIG, "routing": {"enabled": False}}
        result = await route_task(db, config, "anything", session_id="s1")
        assert result["tier"] == "disabled"
        assert result["recommended_model"] is None

    async def test_result_always_includes_rationale_and_latency(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        result = await route_task(db, CONFIG, "some task", session_id="s1")
        assert result["rationale"]
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0.0


class TestRoutingConfigResolution:
    def test_absent_routing_section_uses_full_defaults(self):
        resolved = _resolve_routing_config({})
        assert resolved == DEFAULT_ROUTING_CONFIG

    def test_partial_tier_override_merges_not_replaces(self):
        config = {
            "routing": {
                "tiers": {
                    "frontier": {"model": "claude-sonnet-5"},
                }
            }
        }
        resolved = _resolve_routing_config(config)
        assert resolved["tiers"]["frontier"]["model"] == "claude-sonnet-5"
        assert resolved["tiers"]["frontier"]["provider"] == "anthropic"  # inherited default
        assert resolved["tiers"]["economy"] == DEFAULT_ROUTING_CONFIG["tiers"]["economy"]

    def test_custom_tier_not_in_defaults_is_preserved(self):
        config = {
            "routing": {
                "tiers": {
                    "custom_tier": {"provider": "openai", "model": "gpt-4o", "trigger_phases": []},
                }
            }
        }
        resolved = _resolve_routing_config(config)
        assert resolved["tiers"]["custom_tier"]["model"] == "gpt-4o"
        assert "frontier" in resolved["tiers"]  # defaults still present


class TestLatencyBound:
    async def test_phase_detection_latency_on_moderate_graph(self, real_db):
        """Not a hard CI assertion (shared-runner timing is unreliable --
        see B439's lesson on this exact class of flake) -- seeds a
        moderately-sized graph and reports the actual latency."""
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        for i in range(20):
            _seed_active_plan(db, f"p{i}", "q1", f"goal {i}")
        _seed_task_graph(db, "g1", "s1", ["pending"] * 50 + ["complete"] * 50)

        iterations = 10
        t0 = time.perf_counter()
        for _ in range(iterations):
            await detect_phase(db, "s1")
        elapsed_ms = (time.perf_counter() - t0) / iterations * 1000.0

        print(f"\nmodel_router.detect_phase latency (20 plans, 100 tasks): {elapsed_ms:.2f}ms")
        # Generous ceiling -- this reports the real number above; this
        # assertion just catches a genuine regression (e.g. an
        # accidental full-graph scan), not a tight timing gate.
        assert elapsed_ms < 200.0
