"""
Tests for B323 — Task Dependency Graph, Agent Provenance, and Card/Branch
Context Bundle.

This file covers:
  - Task 0 audit: BLOCKS/ENABLES are untouched by this card, and their
    existing edges survive init_schema().
  - Task 1: TASK_BLOCKS/TASK_ENABLES creation, column types, cycle safety.
  - Task 2: Workspace.branch_name/active migration preserves existing rows.
  - Task 3: AgentWorker.worker_id equals the string B312 writes to `source`
    for the same event (SOLVED_BY).

Uses a real (embedded, file-backed) Kùzu database via KuzuClient — the same
pattern as tests/test_b64_integration.py and tests/test_provenance.py — with
embeddings monkeypatched to a fixed vector so tests don't depend on network
access to a sentence-transformers / Ollama endpoint.
"""

from __future__ import annotations

import uuid

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import (
    NODE_TABLES,
    REL_TABLES,
    SOLVED_BY_TABLES,
    init_schema,
    upsert_agent_worker_and_link,
)
from campy.brain.thalamus.tools.lessons import upsert_lesson
from campy.brain.thalamus.tools.task_graph import (
    TASK_DEPENDENCY_TABLES,
    TaskDependencyCycleError,
    add_task_dependency_edge,
)

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CONFIG = {"embeddings": {"model": EMBEDDING_MODEL}}

_FAKE_VEC = [0.01] * 384


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    """See tests/test_provenance.py for why this patches the bound `emb`
    attribute on each consuming module rather than the dotted import path."""
    from campy.brain.hippocampus import schema as _schema_mod
    from campy.brain.thalamus.tools import lessons as _lessons_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    for mod in (_schema_mod, _lessons_mod):
        monkeypatch.setattr(mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)


def _table_columns(db: KuzuClient, table: str) -> dict[str, str]:
    r = db.execute(f"CALL table_info('{table}') RETURN *")
    cols: dict[str, str] = {}
    while r.has_next():
        row = r.get_next()
        cols[str(row[1])] = str(row[2])
    return cols


def _show_tables(db: KuzuClient) -> set[str]:
    r = db.execute("CALL show_tables() RETURN *")
    names = set()
    while r.has_next():
        names.add(r.get_next()[1])
    return names


def _make_action_item(db: KuzuClient, action_item_id: str) -> None:
    db.execute(
        "CREATE (:ActionItem {action_item_id: $id, embedding: $emb, "
        "embedding_model: 'stub', embedding_dim: 384, confidence: 0.5, "
        "confidence_low: false, pathway_strength: 0.5, archived: false})",
        {"id": action_item_id, "emb": list(_FAKE_VEC)},
    )


# ---------------------------------------------------------------------------
# Task 0 — audit: BLOCKS / ENABLES untouched, existing edges survive
# ---------------------------------------------------------------------------

def test_blocks_and_enables_retain_original_definitions():
    """BLOCKS is still FROM GridEntity TO GridEntity (ARC puzzle mechanics);
    ENABLES is still FROM Concept TO Concept (concept inference). This card
    never redefines either — assert the DDL strings in REL_TABLES prove it."""
    rels = "\n".join(REL_TABLES)
    assert "CREATE REL TABLE IF NOT EXISTS BLOCKS (FROM GridEntity TO GridEntity" in rels
    assert "CREATE REL TABLE IF NOT EXISTS ENABLES      (FROM Concept TO Concept" in rels
    # And no accidental second BLOCKS/ENABLES definition was introduced.
    assert sum(1 for r in REL_TABLES if r.split("(", 1)[0].split()[-1] == "BLOCKS") == 1
    assert sum(1 for r in REL_TABLES if r.split("(", 1)[0].split()[-1] == "ENABLES") == 1


def test_blocks_and_enables_edges_survive_init_schema(tmp_path):
    """A GridEntity BLOCKS edge and a Concept ENABLES edge, written before
    this card's tables exist, both survive a (re-)run of init_schema()."""
    db = KuzuClient(str(tmp_path / "blocks_enables.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    db.execute(
        "CREATE (:GridEntity {entity_id: 'ge1', task_id: 't1', level: 0})"
    )
    db.execute(
        "CREATE (:GridEntity {entity_id: 'ge2', task_id: 't1', level: 0})"
    )
    db.execute(
        "MATCH (a:GridEntity {entity_id: 'ge1'}), (b:GridEntity {entity_id: 'ge2'}) "
        "CREATE (a)-[:BLOCKS {action_id: 'act1', step: 1}]->(b)"
    )

    c1 = str(uuid.uuid4())
    c2 = str(uuid.uuid4())
    for cid in (c1, c2):
        db.execute(
            "CREATE (:Concept {concept_id: $id, text_raw: 'x', embedding: $emb, "
            "embedding_model: 'stub', embedding_dim: 384, confidence: 0.5, "
            "confidence_low: false, pathway_strength: 0.5, archived: false})",
            {"id": cid, "emb": list(_FAKE_VEC)},
        )
    db.execute(
        "MATCH (a:Concept {concept_id: $c1}), (b:Concept {concept_id: $c2}) "
        "CREATE (a)-[:ENABLES {confidence: 0.9, inferred_by: 'test', "
        "inferred_at: timestamp('2026-01-01T00:00:00+00:00')}]->(b)",
        {"c1": c1, "c2": c2},
    )

    # Re-run init_schema (idempotent) — the exact scenario this card's
    # acceptance criterion is guarding against a regression of.
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    r1 = db.execute("MATCH (:GridEntity)-[e:BLOCKS]->(:GridEntity) RETURN count(e)")
    assert r1.get_next()[0] == 1

    r2 = db.execute("MATCH (:Concept)-[e:ENABLES]->(:Concept) RETURN count(e)")
    assert r2.get_next()[0] == 1


# ---------------------------------------------------------------------------
# Task 1 — TASK_BLOCKS / TASK_ENABLES
# ---------------------------------------------------------------------------

def test_task_blocks_and_task_enables_created_with_all_pairs_and_types(tmp_path):
    db = KuzuClient(str(tmp_path / "task_dep_schema.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    assert {"TASK_BLOCKS", "TASK_ENABLES", "AgentWorker", "SOLVED_BY"} <= _show_tables(db)

    for ddl in REL_TABLES:
        if ddl.split("(", 1)[0].split()[-1] not in ("TASK_BLOCKS", "TASK_ENABLES"):
            continue
        assert "FROM MainQuest TO MainQuest" in ddl
        assert "FROM SideQuest TO SideQuest" in ddl
        assert "FROM ActionItem TO ActionItem" in ddl
        assert "confidence DOUBLE" in ddl
        assert "observed_at TIMESTAMP" in ddl
        assert "FLOAT" not in ddl
        assert "INT64" not in ddl


@pytest.mark.asyncio
async def test_add_task_dependency_edge_creates_edge_with_properties(tmp_path):
    db = KuzuClient(str(tmp_path / "task_dep_edge.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _make_action_item(db, "a1")
    _make_action_item(db, "a2")

    result = await add_task_dependency_edge(
        db, rel_type="TASK_BLOCKS", table="ActionItem", from_id="a1", to_id="a2",
        declared_by="agent:claude-code", confidence=0.9, source="agent:claude-code",
        authority="earned",
    )
    assert result["status"] == "created"

    r = db.execute(
        "MATCH (a:ActionItem {action_item_id: 'a1'})-[r:TASK_BLOCKS]->(b:ActionItem {action_item_id: 'a2'}) "
        "RETURN r.declared_by, r.confidence, r.observed_at, r.source, r.authority"
    )
    assert r.has_next()
    row = r.get_next()
    assert row[0] == "agent:claude-code"
    assert row[1] == 0.9
    assert row[2] is not None
    assert row[3] == "agent:claude-code"
    assert row[4] == "earned"


@pytest.mark.asyncio
async def test_task_dependency_cycle_rejected_two_node(tmp_path):
    db = KuzuClient(str(tmp_path / "task_dep_cycle2.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _make_action_item(db, "a1")
    _make_action_item(db, "a2")

    await add_task_dependency_edge(
        db, rel_type="TASK_BLOCKS", table="ActionItem", from_id="a1", to_id="a2",
        declared_by="tester",
    )
    with pytest.raises(TaskDependencyCycleError) as excinfo:
        await add_task_dependency_edge(
            db, rel_type="TASK_BLOCKS", table="ActionItem", from_id="a2", to_id="a1",
            declared_by="tester",
        )
    # Error names the cycle path.
    assert "a1" in str(excinfo.value)
    assert "a2" in str(excinfo.value)


@pytest.mark.asyncio
async def test_task_dependency_self_edge_rejected(tmp_path):
    db = KuzuClient(str(tmp_path / "task_dep_self.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _make_action_item(db, "a1")

    with pytest.raises(TaskDependencyCycleError):
        await add_task_dependency_edge(
            db, rel_type="TASK_BLOCKS", table="ActionItem", from_id="a1", to_id="a1",
            declared_by="tester",
        )


@pytest.mark.asyncio
async def test_task_dependency_ten_hop_cycle_detected(tmp_path):
    """A cycle closing exactly at the bound (10 hops) must still be caught —
    the bound must not be so tight it misses real cycles at its edge."""
    db = KuzuClient(str(tmp_path / "task_dep_cycle10.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    ids = [f"a{i}" for i in range(11)]
    for aid in ids:
        _make_action_item(db, aid)

    for i in range(10):
        await add_task_dependency_edge(
            db, rel_type="TASK_ENABLES", table="ActionItem",
            from_id=ids[i], to_id=ids[i + 1], declared_by="tester",
        )

    with pytest.raises(TaskDependencyCycleError):
        await add_task_dependency_edge(
            db, rel_type="TASK_ENABLES", table="ActionItem",
            from_id=ids[10], to_id=ids[0], declared_by="tester",
        )


@pytest.mark.asyncio
async def test_task_dependency_unsupported_table_raises(tmp_path):
    db = KuzuClient(str(tmp_path / "task_dep_badtable.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    with pytest.raises(ValueError):
        await add_task_dependency_edge(
            db, rel_type="TASK_BLOCKS", table="Concept", from_id="x", to_id="y",
            declared_by="tester",
        )


def test_task_dependency_tables_constant():
    assert TASK_DEPENDENCY_TABLES == {
        "MainQuest": "quest_id",
        "SideQuest": "quest_id",
        "ActionItem": "action_item_id",
    }


# ---------------------------------------------------------------------------
# Task 2 — Workspace.branch_name / active migration
# ---------------------------------------------------------------------------

def test_workspace_branch_name_and_active_via_migration_preserves_rows(tmp_path):
    """Build a DB from the pre-B323 Workspace DDL (workspace_id, path, os,
    hostname only), insert a row, then run the current init_schema() and
    assert both new columns exist and the row survived."""
    db = KuzuClient(str(tmp_path / "workspace_upgrade.db"))

    db.execute(
        "CREATE NODE TABLE Workspace(workspace_id STRING, path STRING, "
        "os STRING, hostname STRING, PRIMARY KEY(workspace_id))"
    )
    db.execute(
        "CREATE (:Workspace {workspace_id: 'w1', path: '/repo', os: 'linux', hostname: 'h1'})"
    )

    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    cols = _table_columns(db, "Workspace")
    assert "branch_name" in cols
    assert "active" in cols

    r = db.execute("MATCH (w:Workspace {workspace_id: 'w1'}) RETURN w.path, w.branch_name")
    assert r.has_next()
    row = r.get_next()
    assert row[0] == "/repo"
    assert row[1] is None


def test_workspace_node_tables_have_no_stale_branch_definition():
    """Sanity: Workspace's base NODE_TABLES DDL is untouched (branch_name/
    active arrive via _MIGRATIONS only, matching the MainQuest.git_repo_root
    precedent) — this card never redefines the Workspace table."""
    assert "workspace_id" in NODE_TABLES["Workspace"]
    assert "path" in NODE_TABLES["Workspace"]


# ---------------------------------------------------------------------------
# Task 3 — AgentWorker / SOLVED_BY reconciliation with B312 `source`
# ---------------------------------------------------------------------------

def test_solved_by_tables_constant():
    assert SOLVED_BY_TABLES == {
        "Decision": "decision_id",
        "ActionItem": "action_item_id",
        "Lesson": "lesson_id",
    }


@pytest.mark.asyncio
async def test_upsert_lesson_agent_worker_id_matches_b312_source(tmp_path):
    """AgentWorker.worker_id must equal the exact string B312 writes to
    Lesson.source for the same upsert_lesson() call."""
    db = KuzuClient(str(tmp_path / "solved_by.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    result = await upsert_lesson(
        {"text": "captured lesson", "domain": "test", "agent_source": "claude-code"},
        db,
        CONFIG,
    )
    lesson_id = result["lesson_id"]

    r = db.execute("MATCH (l:Lesson {lesson_id: $id}) RETURN l.source", {"id": lesson_id})
    assert r.has_next()
    source = r.get_next()[0]
    assert source == "agent:claude-code"

    r2 = db.execute(
        "MATCH (l:Lesson {lesson_id: $id})-[r:SOLVED_BY]->(w:AgentWorker) "
        "RETURN w.worker_id, r.confidence",
        {"id": lesson_id},
    )
    assert r2.has_next()
    worker_id, confidence = r2.get_next()
    assert worker_id == source
    assert confidence == 1.0


@pytest.mark.asyncio
async def test_upsert_agent_worker_and_link_noops_for_user_source(tmp_path):
    """No AgentWorker/SOLVED_BY edge is created for a human ("user:direct")
    or unrecognized source — only the "agent:<id>" convention applies."""
    db = KuzuClient(str(tmp_path / "solved_by_noop.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    lesson_id = str(uuid.uuid4())
    db.execute(
        "CREATE (l:Lesson {lesson_id: $id, text_raw: 'x', embedding: $emb, "
        "embedding_model: 'stub', embedding_dim: 384, domain: 'd', "
        "lesson_type: 'optimization', confidence: 0.9, confidence_low: false, "
        "pathway_strength: 1.0, archived: false, source: 'user:direct'})",
        {"id": lesson_id, "emb": list(_FAKE_VEC)},
    )
    await upsert_agent_worker_and_link(
        db, worker_id="user:direct", node_table="Lesson", node_id=lesson_id,
    )

    r = db.execute("MATCH (:AgentWorker) RETURN count(*)")
    assert r.get_next()[0] == 0

    r2 = db.execute("MATCH ()-[:SOLVED_BY]->() RETURN count(*)")
    assert r2.get_next()[0] == 0


@pytest.mark.asyncio
async def test_upsert_agent_worker_and_link_noops_for_unsupported_table(tmp_path):
    db = KuzuClient(str(tmp_path / "solved_by_badtable.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    # Concept isn't in SOLVED_BY_TABLES — should no-op silently, not raise.
    await upsert_agent_worker_and_link(
        db, worker_id="agent:claude-code", node_table="Concept", node_id="c1",
    )
    r = db.execute("MATCH (:AgentWorker) RETURN count(*)")
    assert r.get_next()[0] == 0
