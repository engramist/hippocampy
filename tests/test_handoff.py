"""
tests/test_handoff.py — B383 Automated Model Handoff Generator.

Drives a real OxigraphClient (not a mock), per this session's
established practice.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient, mint_uri
from campy.brain.thalamus.handoff import MAX_HANDOFF_NODES, generate_handoff


@pytest.fixture()
def real_db():
    tmp = tempfile.mkdtemp(prefix="handoff_")
    db = OxigraphClient(f"{tmp}/db")
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _seed_session_and_quest(db, session_id: str, quest_id: str) -> None:
    db.write_node("MainQuest", {"quest_id": quest_id, "name": "test quest", "status": "active"})
    db.write_node("Session", {"session_id": session_id})
    db.write_edge("WORKING_ON", mint_uri("Session", session_id), mint_uri("MainQuest", quest_id))


def _seed_active_plan(db, plan_id: str, quest_id: str, goal: str) -> None:
    db.write_node("Plan", {"plan_id": plan_id, "goal": goal, "status": "active", "confidence": 0.8})
    db.write_edge("TARGETS", mint_uri("Plan", plan_id), mint_uri("MainQuest", quest_id))


def _seed_decision(db, decision_id: str, session_id: str, text: str, archived: bool = False) -> None:
    db.write_node("Decision", {
        "decision_id": decision_id, "text_raw": text, "archived": archived, "confidence": 0.9,
    })
    db.write_edge("ESTABLISHED_IN", mint_uri("Decision", decision_id), mint_uri("Session", session_id))


def _seed_constraint(db, constraint_id: str, session_id: str, text: str, archived: bool = False) -> None:
    db.write_node("Constraint", {
        "constraint_id": constraint_id, "text_raw": text, "archived": archived, "confidence": 0.9,
    })
    db.write_edge("ESTABLISHED_IN", mint_uri("Constraint", constraint_id), mint_uri("Session", session_id))


def _seed_work_artifact(db, artifact_id: str, session_id: str, file_path: str, title: str = "") -> None:
    db.write_node("WorkArtifact", {
        "artifact_id": artifact_id, "file_path": file_path, "title": title,
    })
    db.write_edge("CREATED_IN", mint_uri("WorkArtifact", artifact_id), mint_uri("Session", session_id))


def _seed_task_graph(db, graph_id: str, session_id: str, task_statuses: list[str]) -> None:
    db.write_node("TaskGraph", {"graph_id": graph_id, "session_id": session_id, "status": "active"})
    for i, status in enumerate(task_statuses):
        task_id = f"{graph_id}-t{i}"
        db.write_node("TaskNode", {
            "task_id": task_id, "graph_id": graph_id, "label": f"task {i}", "status": status,
        })
        db.write_edge("TASK_OF", mint_uri("TaskNode", task_id), mint_uri("TaskGraph", graph_id))


class TestColdStart:
    async def test_no_quest_returns_usable_empty_artifact(self, real_db):
        result = await generate_handoff(real_db, session_id="unknown")
        assert result["quest_id"] == ""
        assert result["goal"] is None
        assert result["decisions"] == []
        assert "cold start" in result["markdown"].lower()

    async def test_quest_with_nothing_yet(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        result = await generate_handoff(db, session_id="s1")
        assert result["quest_id"] == "q1"
        assert result["goal"] is None
        assert result["decisions"] == []
        assert result["constraints"] == []
        assert result["files"] == []


class TestGoalAndDecisions:
    async def test_active_plan_provides_goal(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_active_plan(db, "p1", "q1", "migrate the auth system")
        result = await generate_handoff(db, session_id="s1")
        assert result["goal"] == "migrate the auth system"

    async def test_decisions_scoped_to_whole_quest_not_just_current_session(self, real_db):
        """The real gap this card fills over B290's WorkSummary: a
        decision made in an EARLIER session on the same quest must still
        show up in a handoff generated from a NEW session."""
        db = real_db
        _seed_session_and_quest(db, "s-old", "q1")
        _seed_decision(db, "d1", "s-old", "use PostgreSQL for the new service")
        db.write_node("Session", {"session_id": "s-new"})
        db.write_edge("WORKING_ON", mint_uri("Session", "s-new"), mint_uri("MainQuest", "q1"))

        result = await generate_handoff(db, session_id="s-new")

        texts = {d["text"] for d in result["decisions"]}
        assert "use PostgreSQL for the new service" in texts

    async def test_archived_decision_excluded(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_decision(db, "d1", "s1", "an old archived decision", archived=True)
        result = await generate_handoff(db, session_id="s1")
        assert result["decisions"] == []

    async def test_deprecated_decision_excluded(self, real_db):
        """A decision with an outgoing DEPRECATED_BY edge is stale --
        must not appear in the handoff even though it's not archived."""
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_decision(db, "d-old", "s1", "use MySQL")
        _seed_decision(db, "d-new", "s1", "use PostgreSQL instead of MySQL")
        db.write_edge("DEPRECATED_BY", mint_uri("Decision", "d-old"), mint_uri("Decision", "d-new"))

        result = await generate_handoff(db, session_id="s1")

        texts = {d["text"] for d in result["decisions"]}
        assert "use MySQL" not in texts
        assert "use PostgreSQL instead of MySQL" in texts


class TestConstraintsAndNegativeControls:
    async def test_constraints_included(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_constraint(db, "c1", "s1", "all API responses must be JSON")
        result = await generate_handoff(db, session_id="s1")
        texts = {c["text"] for c in result["constraints"]}
        assert "all API responses must be JSON" in texts

    async def test_negative_control_heuristic_extraction(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_constraint(db, "c1", "s1", "Do not delete production data under any circumstances")
        _seed_constraint(db, "c2", "s1", "Use snake_case for all Python identifiers")

        result = await generate_handoff(db, session_id="s1")

        assert "Do not delete production data under any circumstances" in result["negative_controls"]
        assert "Use snake_case for all Python identifiers" not in result["negative_controls"]
        assert "Do Not" in result["markdown"]

    async def test_deprecated_constraint_excluded_from_negative_controls_too(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_constraint(db, "c-old", "s1", "never use tabs for indentation")
        _seed_constraint(db, "c-new", "s1", "use tabs for indentation (policy changed)")
        db.write_edge("DEPRECATED_BY", mint_uri("Constraint", "c-old"), mint_uri("Constraint", "c-new"))

        result = await generate_handoff(db, session_id="s1")

        assert "never use tabs for indentation" not in result["negative_controls"]


class TestExecutionStatusAndFiles:
    async def test_task_graph_status_included(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_task_graph(db, "g1", "s1", ["pending", "active", "complete"])
        result = await generate_handoff(db, session_id="s1")
        assert result["task_graph_status"]["graph_id"] == "g1"
        assert result["task_graph_status"]["pending_or_active"] == 2
        assert "TaskGraph" in result["markdown"]

    async def test_files_scoped_to_whole_quest(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s-old", "q1")
        _seed_work_artifact(db, "a1", "s-old", "campy/brain/thalamus/handoff.py", "handoff module")
        db.write_node("Session", {"session_id": "s-new"})
        db.write_edge("WORKING_ON", mint_uri("Session", "s-new"), mint_uri("MainQuest", "q1"))

        result = await generate_handoff(db, session_id="s-new")

        file_paths = {f["file_path"] for f in result["files"]}
        assert "campy/brain/thalamus/handoff.py" in file_paths
        assert "handoff module" in result["markdown"]


class TestNodeCap:
    async def test_total_nodes_capped_at_max(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        for i in range(20):
            _seed_decision(db, f"d{i}", "s1", f"decision {i}")
        for i in range(20):
            _seed_constraint(db, f"c{i}", "s1", f"constraint {i}")
        for i in range(20):
            _seed_work_artifact(db, f"a{i}", "s1", f"file_{i}.py")

        result = await generate_handoff(db, session_id="s1")

        total = len(result["decisions"]) + len(result["constraints"]) + len(result["files"])
        assert total <= MAX_HANDOFF_NODES


class TestLoadedDedup:
    async def test_second_call_marks_previously_seen_decisions(self, real_db):
        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_decision(db, "d1", "s1", "adopt trunk-based development")

        first = await generate_handoff(db, session_id="s1")
        assert "(already seen)" not in first["markdown"]

        second = await generate_handoff(db, session_id="s1")
        assert "(already seen)" in second["markdown"]


class TestLatency:
    async def test_generate_handoff_latency_under_500ms(self, real_db):
        """The card's actual acceptance criterion (<500ms), reported
        honestly rather than tuned to hit it."""
        import time

        db = real_db
        _seed_session_and_quest(db, "s1", "q1")
        _seed_active_plan(db, "p1", "q1", "ship the feature")
        for i in range(10):
            _seed_decision(db, f"d{i}", "s1", f"decision {i}")
        for i in range(10):
            _seed_constraint(db, f"c{i}", "s1", f"constraint {i}")
        _seed_task_graph(db, "g1", "s1", ["pending"] * 10)
        for i in range(10):
            _seed_work_artifact(db, f"a{i}", "s1", f"file_{i}.py")

        t0 = time.perf_counter()
        result = await generate_handoff(db, session_id="s1")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        print(f"\nhandoff.generate_handoff latency: {elapsed_ms:.2f}ms (reported: {result['latency_ms']}ms)")
        assert elapsed_ms < 500.0
