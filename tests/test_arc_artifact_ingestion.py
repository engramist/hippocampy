import json
from pathlib import Path

import pytest

from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.schema import NODE_TABLES, REL_TABLES
from mcp_engine.tools.arc_artifacts import ingest_arc_artifacts


def _init_arc_schema(db: KuzuClient) -> None:
    for table in ("ArcRun", "ArcTaskResult", "ArcArtifact", "ArcEvent", "ArcWorldModelStep", "ArcWorldModelSummary"):
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table} ({NODE_TABLES[table]})")
    for ddl in REL_TABLES:
        if any(rel in ddl for rel in (
            "ARC_RUN_HAS_TASK", "ARC_RUN_HAS_ARTIFACT", "ARC_TASK_HAS_EVENT", "ARC_EVENT_FROM_ARTIFACT",
            "ARC_RUN_HAS_WORLD_MODEL_STEP", "ARC_RUN_HAS_WORLD_MODEL_SUMMARY",
            "ARC_WORLD_MODEL_FROM_ARTIFACT", "ARC_WORLD_MODEL_SUMMARY_FROM_ARTIFACT"
        )):
            db.execute(ddl)


def _make_db(tmp_path: Path) -> KuzuClient:
    db = KuzuClient(str(tmp_path / "brain.db"))
    _init_arc_schema(db)
    return db


def _write_fixture_artifacts(root: Path) -> None:
    root.mkdir()
    (root / "master_timeline.json").write_text(json.dumps([
        {"source": "sidequests", "event": "call", "name": "branch_quest", "task_id": "arc_eval_001", "timestamp_iso": "2026-04-17T15:32:45Z", "data": {"step": 0}},
        {"source": "arc", "snapshot_type": "step", "task_id": "arc_eval_001", "step": 1, "action_id": "ACTION6", "state_after": "NOT_FINISHED"},
    ]))
    (root / "agent_execution_trace.json").write_text(json.dumps([
        {"event_type": "phase", "task_id": "arc_eval_001", "phase": "model", "phase_answer": "building model"}
    ]))
    (root / "submission_results_single.json").write_text(json.dumps([
        {"game_id": "ft09-0d8bbf25", "task_id": "arc_eval_001", "correct": True, "steps": 3, "tokens_input": 10, "tokens_output": 2}
    ]))
    (root / "submission_results_arcServer.json").write_text(json.dumps([]))
    (root / "submission_results_single.live.jsonl").write_text(
        json.dumps({"snapshot_type": "step", "task_id": "arc_eval_001", "step": 2, "action_id": "ACTION1"})
        + "\n{malformed-json}\n"
    )
    (root / "submission_results_single.world_model.live.jsonl").write_text(
        json.dumps({"kind": "world_model_step", "task_id": "arc_eval_001", "step": 1, "data": {"node_count": 10, "edge_count": 20}})
        + "\n" + json.dumps({"kind": "world_model_summary", "task_id": "arc_eval_001", "data": {"graph_bounded": True, "compiler_active": True}})
    )


@pytest.mark.asyncio
async def test_missing_artifact_root():
    res = await ingest_arc_artifacts({"artifact_root": "/non/existent/path"}, None, {})
    assert res.get("ok") is False
    assert "artifact_root" in res.get("error", "")


@pytest.mark.asyncio
async def test_dry_run_and_missing_files(tmp_path):
    root = tmp_path / "ARC_AGI"
    root.mkdir()
    (root / "submission_results_single.json").write_text(json.dumps([
        {"task_id": "t1", "correct": True, "steps": 3}
    ]))

    db = _make_db(tmp_path)
    res = await ingest_arc_artifacts({"artifact_root": str(root), "dry_run": True}, db, {})

    assert res["dry_run"] is True
    assert res["runs_upserted"] == 1
    assert isinstance(res["missing_files"], list)

    rows = db.execute("MATCH (r:ArcRun) RETURN count(r)")
    assert rows.get_next()[0] == 0


@pytest.mark.asyncio
async def test_ingestion_creates_graph_records_and_is_idempotent(tmp_path):
    root = tmp_path / "ARC_AGI"
    _write_fixture_artifacts(root)
    db = _make_db(tmp_path)

    first = await ingest_arc_artifacts({"artifact_root": str(root), "include_live_jsonl": True, "dry_run": False}, db, {})
    second = await ingest_arc_artifacts({"artifact_root": str(root), "include_live_jsonl": True, "dry_run": False}, db, {})

    assert first["ok"] is True
    assert first["artifacts_ingested"] == 6
    assert first["runs_upserted"] == 1
    assert first["task_results_upserted"] >= 1
    assert first["events_upserted"] >= 1
    assert first["wm_steps_upserted"] == 1
    assert first["wm_summaries_upserted"] == 1
    assert first["malformed_records_skipped"] == 1
    assert second["runs_upserted"] == 1

    run_count = db.execute("MATCH (r:ArcRun) RETURN count(r)").get_next()[0]
    task_count = db.execute("MATCH (t:ArcTaskResult) RETURN count(t)").get_next()[0]
    event_count = db.execute("MATCH (e:ArcEvent) RETURN count(e)").get_next()[0]
    artifact_count = db.execute("MATCH (a:ArcArtifact) RETURN count(a)").get_next()[0]
    wm_step_count = db.execute("MATCH (s:ArcWorldModelStep) RETURN count(s)").get_next()[0]

    assert run_count == 1
    assert task_count == 1
    assert event_count >= 1
    assert artifact_count == 6
    assert wm_step_count == 1

    domain = db.execute("MATCH (r:ArcRun) RETURN r.domain LIMIT 1").get_next()[0]
    source_files = db.execute("MATCH (r:ArcRun) RETURN r.source_files LIMIT 1").get_next()[0]
    assert "arc_agi" in domain
    assert "submission_results_single.live.jsonl" in source_files
