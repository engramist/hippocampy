import json
from pathlib import Path

import pytest

from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.schema import NODE_TABLES, REL_TABLES
from mcp_engine.tools.arc_artifacts import ingest_arc_artifacts
from mcp_engine.wiki_projection import export_wiki_projection


def _init_arc_schema(db: KuzuClient) -> None:
    for table in ("ArcRun", "ArcTaskResult", "ArcArtifact", "ArcEvent", "ArcWorldModelStep", "ArcWorldModelSummary", "ArcMechanic"):
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table} ({NODE_TABLES[table]})")
    for ddl in REL_TABLES:
        if any(rel in ddl for rel in (
            "ARC_RUN_HAS_TASK", "ARC_RUN_HAS_ARTIFACT", "ARC_TASK_HAS_EVENT", "ARC_EVENT_FROM_ARTIFACT",
            "ARC_RUN_HAS_WORLD_MODEL_STEP", "ARC_RUN_HAS_WORLD_MODEL_SUMMARY",
            "ARC_WORLD_MODEL_FROM_ARTIFACT", "ARC_WORLD_MODEL_SUMMARY_FROM_ARTIFACT"
        )):
            db.execute(ddl)


def _write_fixture_artifacts(root: Path) -> None:
    root.mkdir()
    (root / "master_timeline.json").write_text(json.dumps([
        {"source": "sidequests", "event": "call", "name": "branch_quest", "task_id": "arc_eval_001", "timestamp_iso": "2026-04-17T15:32:45Z", "data": {"step": 0}}
    ]))
    (root / "agent_execution_trace.json").write_text(json.dumps([
        {"event_type": "phase", "task_id": "arc_eval_001", "phase": "model", "phase_answer": "building model"}
    ]))
    (root / "submission_results_single.json").write_text(json.dumps([
        {"game_id": "ft09-0d8bbf25", "task_id": "arc_eval_001", "correct": True, "steps": 3}
    ]))
    (root / "submission_results_arcServer.json").write_text(json.dumps([]))
    (root / "submission_results_single.live.jsonl").write_text(
        json.dumps({"snapshot_type": "step", "task_id": "arc_eval_001", "step": 2, "action_id": "ACTION1"}) + "\n"
    )
    (root / "submission_results_single.world_model.live.jsonl").write_text(
        json.dumps({"kind": "world_model_summary", "task_id": "arc_eval_001", "data": {"graph_bounded": True, "compiler_active": True}}) + "\n"
    )


@pytest.mark.asyncio
async def test_wiki_projection_for_ingested_arc_run(tmp_path):
    root = tmp_path / "ARC_AGI"
    _write_fixture_artifacts(root)
    db = KuzuClient(str(tmp_path / "brain.db"))
    _init_arc_schema(db)
    await ingest_arc_artifacts({"artifact_root": str(root)}, db, {})
    
    # Manually add a mechanic
    from mcp_engine.tools.arc_mechanics import publish_mechanic_summary
    await publish_mechanic_summary({"summary": {"name": "Test Mech", "task_id": "arc_eval_001"}}, db, {})

    vault = tmp_path / "wiki"
    persona_dir = vault / "personas" / "arc_agi"
    config = {
        "wiki_projection": {
            "enabled": True,
            "vault_dir": str(vault),
            "personas": [
                {
                    "name": "arc_agi",
                    "output_dir": str(persona_dir),
                    "include_node_types": ["ArcRun", "ArcTaskResult", "ArcArtifact", "ArcEvent", "ArcMechanic", "ArcWorldModelSummary"],
                    "max_pages_per_sweep": 20,
                    "home_title": "ARC-AGI Memory",
                }
            ],
        }
    }

    summary = await export_wiki_projection(db, config)

    assert summary["status"] == "success"
    assert summary["pages_written"] >= 1
    assert (persona_dir / "Home.md").exists()
    files = list((persona_dir / "pages").glob("*.md"))
    assert files

    contents = "\n".join(path.read_text() for path in files)
    assert "ARC run from" in contents
    assert "World Model Health" in contents
    assert "compiler=True" in contents
    assert "ARC Mechanic: Test Mech" in contents
    assert "ARC WM Summary:" in contents
