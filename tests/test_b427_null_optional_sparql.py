"""tests/test_b427_null_optional_sparql.py — regression tests for the
"required-vs-optional property divergence" bug class found while sweeping
arc.py/thalamus.py for more instances of the class thalamus.wiki_arc_run_wm_summary
and thalamus.wiki_arc_wm_summaries already had (see B427's card, batch 3c).

Root cause, same in every case here: a write query skips asserting an RDF
triple entirely for any param that's `None` (matching Cypher's `SET x = NULL`
no-op), but the read query chained that property as a REQUIRED (non-OPTIONAL)
triple. In RDF a required triple pattern with no matching triple drops the
WHOLE row, unlike Kùzu/LPG where `RETURN s.prop` on a NULL property still
returns the row. Each test below reproduces the exact real-world condition
(traced to the actual call site that can produce a None for that field) that
used to make the row vanish, and asserts the row comes back non-empty and
correct -- not just "the query runs".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus.tools.arc_artifacts import ingest_arc_artifacts
from campy.brain.thalamus.tools.arc_mechanics import publish_mechanic_summary
from campy.brain.thalamus.tools.arc_queries import (
    arc_get_goal_evidence,
    arc_perceive_state,
    arc_update_goal_confidence,
)


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b427.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


# ---------------------------------------------------------------------------
# arc.get_entity_centroid: arc_perceive_state (arc_queries.py) writes
# centroid_row/centroid_col straight from the caller's
# ent.get("centroid_row")/ent.get("centroid_col") -- None whenever the
# caller's entity dict doesn't report a centroid this frame.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_entity_centroid_returns_row_when_centroid_unset(gw, ox_client):
    result = await arc_perceive_state(
        {
            "task_id": "b427-test",
            "step": 0,
            "entities": [{"color_id": 3, "region_index": 0, "pixel_count": 5}],
        },
        ox_client,
        {},
    )
    assert result.get("status") != "error", result

    entity_id = "b427-test_e3_0"
    rows = await gw.run("arc.get_entity_centroid", eid=entity_id)
    assert len(rows) == 1, "GridEntity with unset centroid vanished from the read"
    assert rows[0]["centroid_row"] is None
    assert rows[0]["centroid_col"] is None


@pytest.mark.asyncio
async def test_perceive_state_detects_existing_entity_with_unset_centroid(gw, ox_client):
    """Regression for the real consequence: arc_perceive_state's own
    `existing_row is not None` check used to silently misread "entity has an
    unset centroid" as "entity doesn't exist yet" -- because the required
    triple pattern made the lookup return zero rows even though the entity
    node itself existed. A second perceive_state call for the same entity
    (now reporting a real centroid) must not error and must record the move
    once a prior centroid is on file.
    """
    await arc_perceive_state(
        {"task_id": "b427-test2", "step": 0, "entities": [{"color_id": 1, "region_index": 0}]},
        ox_client, {},
    )
    result2 = await arc_perceive_state(
        {
            "task_id": "b427-test2", "step": 1,
            "entities": [{"color_id": 1, "region_index": 0, "centroid_row": 4.0, "centroid_col": 2.0}],
        },
        ox_client, {},
    )
    assert result2.get("status") != "error", result2

    rows = await gw.run("arc.get_entity_centroid", eid="b427-test2_e1_0")
    assert len(rows) == 1
    assert rows[0]["centroid_row"] == 4.0
    assert rows[0]["centroid_col"] == 2.0


# ---------------------------------------------------------------------------
# thalamus.wiki_arc_task_results / wiki_arc_events / wiki_arc_wm_steps:
# arc_artifacts.py's _extract_task_results/_extract_events/
# _extract_world_model_steps compute steps/step_index/node_count/edge_count/
# compiled_claim_count via _safe_int(...), which is None whenever the source
# artifact doesn't carry that field.
# ---------------------------------------------------------------------------
def _write_partial_fixture_artifacts(root: Path) -> None:
    root.mkdir()
    # Task result with no steps/step_count/num_steps field at all.
    (root / "submission_results_single.json").write_text(json.dumps([
        {"task_id": "b427-wiki", "puzzle_id": "puzzle-1", "correct": True}
    ]))
    # Event with no step/step_index/step_num field (run-level, not tied to a step).
    (root / "submission_results_single.live.jsonl").write_text(
        json.dumps({"event_type": "run_started", "task_id": "b427-wiki", "timestamp_iso": "2026-09-18T00:00:00Z"}) + "\n"
    )
    # World-model step with no step/node_count/edge_count/compiled_claim_count.
    (root / "submission_results_single.world_model.live.jsonl").write_text(
        json.dumps({"kind": "world_model_step", "task_id": "b427-wiki", "data": {}}) + "\n"
    )


@pytest.mark.asyncio
async def test_wiki_arc_task_results_includes_result_with_unset_steps(gw, ox_client, tmp_path):
    root = tmp_path / "ARC_AGI"
    _write_partial_fixture_artifacts(root)
    summary = await ingest_arc_artifacts({"artifact_root": str(root)}, ox_client, {})
    assert summary["ok"] is True
    assert summary["task_results_upserted"] == 1

    rows = await gw.run("thalamus.wiki_arc_task_results", lim=10)
    assert len(rows) == 1, "ArcTaskResult with unset steps vanished from the wiki projection"
    assert rows[0]["task_id"] == "b427-wiki"
    assert rows[0]["steps"] is None


@pytest.mark.asyncio
async def test_wiki_arc_events_includes_event_with_unset_step_index(gw, ox_client, tmp_path):
    root = tmp_path / "ARC_AGI"
    _write_partial_fixture_artifacts(root)
    summary = await ingest_arc_artifacts({"artifact_root": str(root)}, ox_client, {})
    assert summary["ok"] is True
    assert summary["events_upserted"] == 1

    rows = await gw.run("thalamus.wiki_arc_events", lim=10)
    assert len(rows) == 1, "ArcEvent with unset step_index vanished from the wiki projection"
    assert rows[0]["event_type"] == "run_started"
    assert rows[0]["step_index"] is None


@pytest.mark.asyncio
async def test_wiki_arc_wm_steps_includes_step_with_unset_counts(gw, ox_client, tmp_path):
    root = tmp_path / "ARC_AGI"
    _write_partial_fixture_artifacts(root)
    summary = await ingest_arc_artifacts({"artifact_root": str(root)}, ox_client, {})
    assert summary["ok"] is True
    assert summary["wm_steps_upserted"] == 1

    rows = await gw.run("thalamus.wiki_arc_wm_steps", lim=10)
    assert len(rows) == 1, "ArcWorldModelStep with unset counts vanished from the wiki projection"
    assert rows[0]["task_id"] == "b427-wiki"
    assert rows[0]["step_index"] is None
    assert rows[0]["node_count"] is None
    assert rows[0]["edge_count"] is None
    assert rows[0]["compiled_claim_count"] is None


# ---------------------------------------------------------------------------
# thalamus.wiki_arc_mechanics: arc.merge_mechanic's own SPARQL (queries/arc.py)
# writes terminal_relevance/coordinate_relevance straight from the ?terminal_relevance/
# ?coordinate_relevance params via the same UNDEF-on-None VALUES injection as
# every other query in this file -- None is a value the query is structurally
# built to accept. The one current call site (arc_mechanics.py's
# publish_mechanic_summary) happens to floor both through its own
# _safe_float(..., default=0.0) and so never actually passes None today, but
# that is a property of that one caller, not of the query -- and nothing
# stops a future/second caller (or a change to that default) from passing
# None, at which point the same live-tool-breaking bug as
# thalamus.wiki_arc_wm_summaries would reappear. Exercise the query directly
# (as arc.merge_mechanic's own contract, not through that one caller) to
# pin down the query's behavior independent of today's caller default.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wiki_arc_mechanics_includes_mechanic_with_unset_relevance(gw, ox_client):
    await gw.run(
        "arc.merge_mechanic",
        mechanic_id="mech-b427-wiki",
        now="2026-09-18T00:00:00Z",
        name="Unset Relevance Mech",
        signature="unknown",
        confidence=0.5,
        terminal_relevance=None,
        coordinate_relevance=None,
        task_id="b427-wiki",
        domain="arc,arc_agi",
        summary="test",
    )

    rows = await gw.run("thalamus.wiki_arc_mechanics", lim=10)
    assert len(rows) == 1, "ArcMechanic with unset terminal/coordinate_relevance vanished from the wiki projection"
    assert rows[0]["name"] == "Unset Relevance Mech"
    assert rows[0]["terminal_relevance"] is None
    assert rows[0]["coordinate_relevance"] is None


# ---------------------------------------------------------------------------
# arc.get_goal_evidence: no writer anywhere in the repo ever asserts
# campy:condition_type on a VictoryCondition (arc.merge_victory_condition_confidence,
# the only writer, never sets it) -- a required triple pattern for it meant
# this query, and the live arc_get_goal_evidence MCP tool built on it,
# returned zero goals for EVERY task, unconditionally, since it was written.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_goal_evidence_returns_victory_condition_with_no_condition_type(ox_client):
    result = await arc_update_goal_confidence(
        {"goal_id": "vc-b427", "task_id": "b427-goal", "new_confidence": 0.7,
         "has_meaningful_progress": True},
        ox_client, {},
    )
    assert result["status"] == "ok"

    evidence = await arc_get_goal_evidence({"task_id": "b427-goal"}, ox_client, {})
    assert len(evidence["goals"]) == 1, "VictoryCondition with unset condition_type vanished from goal evidence"
    assert evidence["goals"][0]["id"] == "vc-b427"
    assert evidence["goals"][0]["type"] is None
    assert evidence["goals"][0]["confidence"] == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_publish_mechanic_summary_currently_always_floors_relevance_to_zero(gw, ox_client):
    """Documents the current real-caller behavior (not a bug on its own):
    publish_mechanic_summary's own _safe_float(..., 0.0) means
    terminal_relevance/coordinate_relevance are never actually None through
    this call site today -- the None case above is a query-contract/
    future-caller concern, not a currently-reachable one via this tool."""
    res = await publish_mechanic_summary(
        {"summary": {"name": "Defaulted Mech", "task_id": "b427-wiki"}}, ox_client, {}
    )
    assert res["ok"] is True

    rows = await gw.run("thalamus.wiki_arc_mechanics", lim=10)
    assert len(rows) == 1
    assert rows[0]["terminal_relevance"] == 0.0
    assert rows[0]["coordinate_relevance"] == 0.0
