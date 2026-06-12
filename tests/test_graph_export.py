from __future__ import annotations

import asyncio
import json
import math
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from campy.brain.hippocampus.graph.export import export_graph_dump, import_graph_dump
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import NODE_TABLES, REL_TABLES
from campy.cli.main import cli


def _create_schema(db: KuzuClient) -> None:
    for table, ddl in NODE_TABLES.items():
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table} ({ddl})")
    for ddl in REL_TABLES:
        db.execute(ddl)


def _seed_graph(db: KuzuClient) -> dict[str, list[dict[str, object]]]:
    _create_schema(db)

    def _embed(head: list[float]) -> list[float]:
        return (head + [0.0] * 384)[:384]

    concept_rows = [
        {
            "concept_id": "c-1",
            "text_raw": "alpha",
            "embedding": _embed([1.0, 0.0, 0.0, 0.0]),
            "embedding_model": "mini",
            "embedding_dim": 384,
            "confidence": 0.95,
            "confidence_low": False,
            "pathway_strength": 0.9,
            "archived": False,
            "created_at": datetime(2026, 1, 1, 12, 0, 0),
            "last_accessed_at": datetime(2026, 1, 2, 12, 0, 0),
        },
        {
            "concept_id": "c-2",
            "text_raw": "beta",
            "embedding": _embed([0.0, 1.0, 0.0, 0.0]),
            "embedding_model": "mini",
            "embedding_dim": 384,
            "confidence": 0.7,
            "confidence_low": True,
            "pathway_strength": 0.2,
            "archived": True,
            "created_at": datetime(2026, 1, 3, 12, 0, 0),
            "last_accessed_at": datetime(2026, 1, 4, 12, 0, 0),
        },
        {
            "concept_id": "c-3",
            "text_raw": "gamma",
            "embedding": _embed([0.70710678, 0.70710678, 0.0, 0.0]),
            "embedding_model": "mini",
            "embedding_dim": 384,
            "confidence": 0.88,
            "confidence_low": False,
            "pathway_strength": 0.5,
            "archived": False,
            "created_at": datetime(2026, 1, 5, 12, 0, 0),
            "last_accessed_at": datetime(2026, 1, 6, 12, 0, 0),
        },
    ]
    for row in concept_rows:
        db.execute(
            "CREATE (n:Concept {concept_id: $concept_id, text_raw: $text_raw, embedding: $embedding, "
            "embedding_model: $embedding_model, embedding_dim: $embedding_dim, confidence: $confidence, "
            "confidence_low: $confidence_low, pathway_strength: $pathway_strength, archived: $archived, "
            "created_at: $created_at, last_accessed_at: $last_accessed_at})",
            row,
        )

    decision_rows = [
        {
            "decision_id": "d-1",
            "text_raw": "choose alpha",
            "embedding": _embed([0.2, 0.8, 0.0, 0.0]),
            "embedding_model": "mini",
            "embedding_dim": 384,
            "confidence": 0.9,
            "confidence_low": False,
            "pathway_strength": 0.4,
            "archived": False,
            "created_at": datetime(2026, 1, 7, 12, 0, 0),
        },
        {
            "decision_id": "d-2",
            "text_raw": "choose gamma",
            "embedding": _embed([0.6, 0.6, 0.0, 0.0]),
            "embedding_model": "mini",
            "embedding_dim": 384,
            "confidence": 0.8,
            "confidence_low": True,
            "pathway_strength": 0.3,
            "archived": False,
            "created_at": datetime(2026, 1, 8, 12, 0, 0),
        },
    ]
    for row in decision_rows:
        db.execute(
            "CREATE (n:Decision {decision_id: $decision_id, text_raw: $text_raw, embedding: $embedding, "
            "embedding_model: $embedding_model, embedding_dim: $embedding_dim, confidence: $confidence, "
            "confidence_low: $confidence_low, pathway_strength: $pathway_strength, archived: $archived, "
            "created_at: $created_at})",
            row,
        )

    quest_embedding = _embed([0.1, 0.2, 0.3, 0.4])
    purpose_embedding = _embed([0.4, 0.3, 0.2, 0.1])
    db.execute(
        "CREATE (q:MainQuest {quest_id: 'q-1', name: 'quest', status: 'active', purpose: 'demo', "
        "text_raw: 'quest', embedding: "
        + str(quest_embedding)
        + ", embedding_model: 'mini', embedding_dim: 384, confidence: 0.5, confidence_low: false, "
        "pathway_strength: 0.6, archived: false, created_at: timestamp('2026-01-09T12:00:00'), "
        "last_active_at: timestamp('2026-01-10T12:00:00'), git_repo_root: '/tmp/repo', purpose_embedding: "
        + str(purpose_embedding)
        + ", routing_method: 'git'})"
    )
    db.execute(
        "CREATE (s:Session {session_id: 's-1', started_at: timestamp('2026-01-11T12:00:00'), "
        "last_active_at: timestamp('2026-01-11T12:01:00'), onboarded: true, purpose: 'demo', "
        "routing_state: 'ok', routing_confidence: 0.9, routing_method: 'manual', token_estimate: 123, "
        "token_limit: 2048, loaded_node_count: 2, injection_count: 1, dedup_tokens_saved: 3, "
        "last_injection_at: timestamp('2026-01-11T12:02:00'), last_loop_summary: 'summary', "
        "last_warm_frontier_at: timestamp('2026-01-11T12:03:00')})"
    )
    plan_embedding = _embed([0.9, 0.1, 0.0, 0.0])
    db.execute(
        "CREATE (p:Plan {plan_id: 'p-1', goal: 'demo', strategy: 'trace', source: 'test', embedding: "
        + str(plan_embedding)
        + ", embedding_model: 'mini', embedding_dim: 384, step_count: 1, valence: 0.1, "
        "valence_source: 'test', status: 'active', confidence: 0.7, confidence_low: false, "
        "pathway_strength: 0.8, archived: false, created_at: timestamp('2026-01-12T12:00:00'), "
        "completed_at: timestamp('2026-01-13T12:00:00')})"
    )
    db.execute("MATCH (a:Concept {concept_id: 'c-1'}), (b:Concept {concept_id: 'c-2'}) CREATE (a)-[:CO_OCCURS_WITH {count: 3, strength: 0.75}]->(b)")
    db.execute("MATCH (a:Decision {decision_id: 'd-1'}), (b:Session {session_id: 's-1'}) CREATE (a)-[:ESTABLISHED_IN]->(b)")
    db.execute("MATCH (a:Plan {plan_id: 'p-1'}), (b:Session {session_id: 's-1'}) CREATE (a)-[:PLANNED_IN]->(b)")
    db.execute("MATCH (a:Plan {plan_id: 'p-1'}), (b:MainQuest {quest_id: 'q-1'}) CREATE (a)-[:TARGETS]->(b)")

    return {"concepts": concept_rows, "decisions": decision_rows}


def _db_rows(db: KuzuClient, query: str) -> list[dict[str, object]]:
    rows = asyncio.run(db.execute_read(query))
    assert isinstance(rows, list)
    return rows


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)


class TestFacadeConformance:
    def test_execute_create_and_match(self, tmp_path: Path) -> None:
        db = KuzuClient(str(tmp_path / "db"))
        try:
            db.execute("CREATE NODE TABLE T(id STRING, PRIMARY KEY (id))")
            db.execute("CREATE (n:T {id: 'x'})")
            result = db.execute("MATCH (n:T) RETURN count(n)")
            assert result.get_next()[0] == 1
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_execute_read_returns_dict_rows(self, tmp_path: Path) -> None:
        db = KuzuClient(str(tmp_path / "db"))
        try:
            db.execute("CREATE NODE TABLE T(id STRING, label STRING, PRIMARY KEY (id))")
            db.execute("CREATE (n:T {id: 'x', label: 'alpha'})")
            rows = await db.execute_read("MATCH (n:T) RETURN n.id AS id, n.label AS label")
            assert rows == [{"id": "x", "label": "alpha"}]
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_execute_write_serializes_under_lock(self, tmp_path: Path) -> None:
        db = KuzuClient(str(tmp_path / "db"))
        try:
            db.execute("CREATE NODE TABLE T(id STRING, PRIMARY KEY (id))")
            await asyncio.gather(
                db.execute_write("CREATE (n:T {id: 'a'})"),
                db.execute_write("CREATE (n:T {id: 'b'})"),
            )
            result = db.execute("MATCH (n:T) RETURN count(n)")
            assert result.get_next()[0] == 2
        finally:
            db.close()

    def test_create_vector_index_and_search(self, tmp_path: Path) -> None:
        db = KuzuClient(str(tmp_path / "db"))
        try:
            db.execute("CREATE NODE TABLE Calib(id STRING, embedding FLOAT[4], PRIMARY KEY (id))")
            db.execute("CREATE (n:Calib {id: 'identical', embedding: [1.0, 0.0, 0.0, 0.0]})")
            db.execute("CREATE (n:Calib {id: 'diag', embedding: [0.70710678, 0.70710678, 0.0, 0.0]})")
            db.create_vector_index("Calib", "embedding", "calib_idx")
            rows = db.vector_search("Calib", "calib_idx", [1.0, 0.0, 0.0, 0.0], 2)
            assert rows[0]["node"]["id"] == "identical"
            assert rows[0]["score"] >= rows[1]["score"]
            assert rows[0]["score"] == pytest.approx(1.0, abs=1e-6)
        finally:
            db.close()

    def test_close_releases(self, tmp_path: Path) -> None:
        db = KuzuClient(str(tmp_path / "db"))
        db.close()
        assert not hasattr(db, "conn")
        assert not hasattr(db, "db")


class TestRoundTrip:
    def test_export_import_equality(self, tmp_path: Path) -> None:
        src_db = KuzuClient(str(tmp_path / "src.db"))
        try:
            seeded = _seed_graph(src_db)
            dump_dir = tmp_path / "dump"
            manifest = export_graph_dump(src_db, dump_dir)

            assert manifest["node_tables"]["Concept"]["rows"] == 3
            assert manifest["rel_tables"]["CO_OCCURS_WITH"]["rows"] == 1

            fresh_db_path = tmp_path / "fresh.db"
            fresh_db = KuzuClient(str(fresh_db_path))
            try:
                restored = import_graph_dump(fresh_db, dump_dir)
                assert restored["ok"] is True

                assert fresh_db.execute("MATCH (n:Concept) RETURN count(n)").get_next()[0] == 3
                assert fresh_db.execute("MATCH (n:Decision) RETURN count(n)").get_next()[0] == 2
                assert fresh_db.execute("MATCH (n:MainQuest) RETURN count(n)").get_next()[0] == 1
                assert fresh_db.execute("MATCH (n:Session) RETURN count(n)").get_next()[0] == 1
                assert fresh_db.execute("MATCH ()-[r:CO_OCCURS_WITH]->() RETURN count(r)").get_next()[0] == 1
                assert fresh_db.execute("MATCH ()-[r:ESTABLISHED_IN]->() RETURN count(r)").get_next()[0] == 1

                imported_concepts = _db_rows(
                    fresh_db,
                    "MATCH (n:Concept) RETURN n.concept_id AS concept_id, n.text_raw AS text_raw, "
                    "n.embedding AS embedding, n.created_at AS created_at, n.last_accessed_at AS last_accessed_at "
                    "ORDER BY n.concept_id",
                )
                assert imported_concepts[0]["text_raw"] == "alpha"
                assert isinstance(imported_concepts[0]["created_at"], datetime)
                assert isinstance(imported_concepts[0]["last_accessed_at"], datetime)
                assert len(imported_concepts[0]["embedding"]) == 384
                assert imported_concepts[0]["embedding"] == seeded["concepts"][0]["embedding"]

                imported_session = _db_rows(
                    fresh_db,
                    "MATCH (n:Session) RETURN n.started_at AS started_at, n.last_injection_at AS last_injection_at",
                )[0]
                assert isinstance(imported_session["started_at"], datetime)
                assert isinstance(imported_session["last_injection_at"], datetime)

                original = seeded["concepts"][2]["embedding"]
                imported = _db_rows(
                    fresh_db,
                    "MATCH (n:Concept {concept_id: 'c-3'}) RETURN n.embedding AS embedding",
                )[0]["embedding"]
                assert _cosine(original, imported) >= 0.9999
            finally:
                fresh_db.close()
        finally:
            src_db.close()

    def test_embedding_precision(self, tmp_path: Path) -> None:
        db = KuzuClient(str(tmp_path / "src.db"))
        try:
            _seed_graph(db)
            dump_dir = tmp_path / "dump"
            export_graph_dump(db, dump_dir)
            fresh_db = KuzuClient(str(tmp_path / "fresh.db"))
            try:
                import_graph_dump(fresh_db, dump_dir)
                original = [0.70710678, 0.70710678, 0.0, 0.0] + [0.0] * 380
                imported = fresh_db.execute(
                    "MATCH (n:Concept {concept_id: 'c-3'}) RETURN n.embedding"
                ).get_next()[0]
                assert _cosine(original, imported) >= 0.9999
            finally:
                fresh_db.close()
        finally:
            db.close()


def test_cli_export_and_import_roundtrip(tmp_path: Path) -> None:
    db = KuzuClient(str(tmp_path / "cli-src.db"))
    try:
        _seed_graph(db)
        db.close()

        dump_dir = tmp_path / "dump"
        import_dir = tmp_path / "cli-fresh.db"

        runner = CliRunner()
        export_result = runner.invoke(cli, ["export-graph", "--db-path", str(tmp_path / "cli-src.db"), "--out", str(dump_dir)])
        assert export_result.exit_code == 0, export_result.output

        import_result = runner.invoke(cli, ["import-graph", "--in", str(dump_dir), "--db", str(import_dir)])
        assert import_result.exit_code == 0, import_result.output

        restored = KuzuClient(str(import_dir))
        try:
            assert restored.execute("MATCH (n:Concept) RETURN count(n)").get_next()[0] == 3
        finally:
            restored.close()
    finally:
        if hasattr(db, "conn") or hasattr(db, "db"):
            db.close()
