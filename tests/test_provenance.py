"""
Tests for B312 — Provenance Fields + Explicit Supersession on Fact-Bearing Nodes.

Uses a real (embedded, file-backed) Kùzu database via KuzuClient — the same
pattern as tests/test_b64_integration.py — with embeddings monkeypatched to
a fixed vector so the tests don't depend on network access to a
sentence-transformers / Ollama endpoint.
"""

from __future__ import annotations

import uuid

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import (
    PROVENANCE_TABLES,
    SUPERSESSION_REASONS,
    init_schema,
)
from campy.brain.hippocampus.provenance import mark_superseded, provenance_fields
from campy.brain.thalamus.tools.lessons import (
    recall_relevant_lessons,
    upsert_lesson,
)
from campy.brain.thalamus.tools.retrieval import current_truth

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CONFIG = {"embeddings": {"model": EMBEDDING_MODEL}}

_FAKE_VEC = [0.01] * 384


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    """Every module exercised here does `from ... import embeddings as emb`
    and calls `emb.embed(...)` / `emb.embed_batch(...)`. Patch the `emb`
    attribute directly on each *consuming* module's already-bound module
    object (matching the pattern in tests/test_plan_tools.py) rather than
    re-resolving "campy.brain.hippocampus.graph.embeddings" by dotted
    string: with enough other test modules loaded first, this codebase's
    test suite ends up with two distinct module objects registered for
    that same dotted path (a pre-existing quirk, unrelated to B312), so a
    string-path patch can silently miss the one a given module actually
    calls. Patching the bound object directly is robust to that."""
    from campy.brain.hippocampus import schema as _schema_mod
    from campy.brain.thalamus.tools import capture as _capture_mod
    from campy.brain.thalamus.tools import lessons as _lessons_mod
    from campy.brain.thalamus.tools import retrieval as _retrieval_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    for mod in (_schema_mod, _capture_mod, _lessons_mod, _retrieval_mod):
        monkeypatch.setattr(mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)


def _table_columns(db: KuzuClient, table: str) -> set[str]:
    r = db.execute(f"CALL table_info('{table}') RETURN *")
    cols = set()
    while r.has_next():
        cols.add(str(r.get_next()[1]))
    return cols


_PROVENANCE_COLS = {
    "source", "source_version", "observed_at", "evidence_ref",
    "superseded_by", "superseded_at", "supersession_reason",
}


# ---------------------------------------------------------------------------
# Fresh-DB test
# ---------------------------------------------------------------------------

def test_fresh_db_creates_provenance_and_supersession_columns(tmp_path):
    """init_schema() on an empty database creates every PROVENANCE_TABLES
    table with the four provenance columns and the three supersession
    columns present (AC1)."""
    db = KuzuClient(str(tmp_path / "fresh.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    missing: dict[str, set[str]] = {}
    for table in PROVENANCE_TABLES:
        cols = _table_columns(db, table)
        needed = _PROVENANCE_COLS
        gap = needed - cols
        if gap:
            missing[table] = gap

    assert missing == {}, f"tables missing provenance columns: {missing}"


def test_supersedes_rel_table_created(tmp_path):
    """SUPERSEDES rel table exists after init_schema()."""
    db = KuzuClient(str(tmp_path / "fresh_rel.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    r = db.execute("CALL show_tables() RETURN *")
    names = set()
    while r.has_next():
        names.add(r.get_next()[1])
    assert "SUPERSEDES" in names


# ---------------------------------------------------------------------------
# Upgrade test — the important one
# ---------------------------------------------------------------------------

# Pre-B312 DDL (verbatim, minus the seven provenance/supersession columns)
# for two representative tables — one Tier 1, one Tier 2 — used to simulate
# a database created before this card landed.
_OLD_CONCEPT_DDL = """
    concept_id    STRING,
    text_raw      STRING,
    embedding     FLOAT[384],
    embedding_model STRING,
    embedding_dim INT64,
    gist_class    STRING,
    schema_org_type STRING,
    confidence    DOUBLE,
    confidence_low BOOLEAN,
    pathway_strength DOUBLE,
    archived      BOOLEAN,
    anomaly_type  STRING,
    flagged_for_review BOOLEAN,
    created_at    TIMESTAMP,
    last_accessed_at TIMESTAMP,
    PRIMARY KEY (concept_id)
"""

_OLD_ARC_MECHANIC_DDL = """
    mechanic_id STRING,
    name STRING,
    signature STRING,
    confidence DOUBLE,
    terminal_relevance DOUBLE,
    coordinate_relevance DOUBLE,
    source_task_ids STRING,
    evidence_count INT64,
    contradiction_count INT64,
    domain STRING,
    summary STRING,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (mechanic_id)
"""


def test_upgrade_adds_missing_columns_and_preserves_rows(tmp_path):
    """Simulate a pre-B312 database (old-style Concept + ArcMechanic tables,
    each with a pre-existing row), then run the current init_schema()
    against it and assert every new column exists and no row was lost (AC2).
    """
    db = KuzuClient(str(tmp_path / "upgrade.db"))

    # 1. Pre-create old-style tables (no provenance/supersession columns).
    db.execute(f"CREATE NODE TABLE Concept ({_OLD_CONCEPT_DDL})")
    db.execute(f"CREATE NODE TABLE ArcMechanic ({_OLD_ARC_MECHANIC_DDL})")

    old_concept_cols = _table_columns(db, "Concept")
    assert not (_PROVENANCE_COLS & old_concept_cols), "test setup: old DDL should not already have provenance cols"

    # 2. Insert pre-existing rows the "old" way.
    concept_id = str(uuid.uuid4())
    db.execute(
        "CREATE (c:Concept {concept_id: $id, text_raw: $text, confidence: 0.5, archived: false})",
        {"id": concept_id, "text": "pre-B312 concept"},
    )
    mechanic_id = str(uuid.uuid4())
    db.execute(
        "CREATE (m:ArcMechanic {mechanic_id: $id, name: $name})",
        {"id": mechanic_id, "name": "pre-B312 mechanic"},
    )

    # 3. Run the current (post-B312) schema init against this DB.
    #    Node tables use IF NOT EXISTS, so Concept/ArcMechanic are NOT
    #    recreated — only _MIGRATIONS' ALTER TABLE ADD should touch them.
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    # 4. Every new column now exists.
    new_concept_cols = _table_columns(db, "Concept")
    new_mechanic_cols = _table_columns(db, "ArcMechanic")
    assert _PROVENANCE_COLS <= new_concept_cols, new_concept_cols
    assert _PROVENANCE_COLS <= new_mechanic_cols, new_mechanic_cols

    # 5. The pre-existing rows survived, with old data intact and the new
    #    columns NULL.
    r = db.execute(
        "MATCH (c:Concept {concept_id: $id}) "
        "RETURN c.text_raw, c.source, c.observed_at, c.superseded_by",
        {"id": concept_id},
    )
    assert r.has_next()
    row = r.get_next()
    assert row[0] == "pre-B312 concept"
    assert row[1] is None
    assert row[2] is None
    assert row[3] is None

    r2 = db.execute(
        "MATCH (m:ArcMechanic {mechanic_id: $id}) RETURN m.name, m.source",
        {"id": mechanic_id},
    )
    assert r2.has_next()
    row2 = r2.get_next()
    assert row2[0] == "pre-B312 mechanic"
    assert row2[1] is None


# ---------------------------------------------------------------------------
# provenance_fields()
# ---------------------------------------------------------------------------

def test_provenance_fields_defaults_observed_at_to_now():
    result = provenance_fields(source="agent:claude-code")
    assert result["source"] == "agent:claude-code"
    assert result["source_version"] is None
    assert result["evidence_ref"] is None
    assert isinstance(result["observed_at"], str) and result["observed_at"]


def test_provenance_fields_passes_through_explicit_values():
    import datetime as dt

    at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    result = provenance_fields(
        source="harvest:git",
        source_version="abc123",
        observed_at=at,
        evidence_ref="msg-1",
    )
    assert result == {
        "source": "harvest:git",
        "source_version": "abc123",
        "observed_at": at.isoformat(),
        "evidence_ref": "msg-1",
    }


# ---------------------------------------------------------------------------
# mark_superseded()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_superseded_sets_columns_and_creates_edge(tmp_path):
    db = KuzuClient(str(tmp_path / "supersede.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    old_id = (await upsert_lesson({"text": "old lesson", "domain": "test"}, db, CONFIG))["lesson_id"]
    new_id = (await upsert_lesson({"text": "new lesson", "domain": "test"}, db, CONFIG))["lesson_id"]

    await mark_superseded(
        db, table="Lesson", node_id=old_id, superseded_by=new_id, reason="replaced",
    )

    r = db.execute(
        "MATCH (l:Lesson {lesson_id: $id}) "
        "RETURN l.superseded_by, l.superseded_at, l.supersession_reason",
        {"id": old_id},
    )
    assert r.has_next()
    row = r.get_next()
    assert row[0] == new_id
    assert row[1] is not None
    assert row[2] == "replaced"

    r2 = db.execute(
        "MATCH (a:Lesson {lesson_id: $new})-[:SUPERSEDES]->(b:Lesson {lesson_id: $old}) "
        "RETURN count(*)",
        {"new": new_id, "old": old_id},
    )
    assert r2.has_next()
    assert r2.get_next()[0] == 1


@pytest.mark.asyncio
async def test_mark_superseded_invalid_reason_raises_value_error():
    with pytest.raises(ValueError):
        await mark_superseded(
            db=None, table="Lesson", node_id="a", superseded_by="b", reason="bogus",
        )


def test_supersession_reasons_vocabulary():
    assert SUPERSESSION_REASONS == {
        "replaced", "contradicted", "source_removed", "merged", "expired",
    }


# ---------------------------------------------------------------------------
# Capture-path provenance (Task 4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_lesson_writes_non_null_provenance(tmp_path):
    db = KuzuClient(str(tmp_path / "capture_lesson.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    result = await upsert_lesson(
        {"text": "captured lesson", "domain": "test", "session_id": "sess-1"},
        db,
        CONFIG,
    )
    lesson_id = result["lesson_id"]

    r = db.execute(
        "MATCH (l:Lesson {lesson_id: $id}) "
        "RETURN l.source, l.observed_at, l.evidence_ref",
        {"id": lesson_id},
    )
    assert r.has_next()
    row = r.get_next()
    assert row[0] is not None and row[0] != ""
    assert row[1] is not None
    assert row[2] == "sess-1"


@pytest.mark.asyncio
async def test_notify_turn_passive_plan_writes_non_null_provenance(tmp_path):
    """A Plan/PlanStep created via capture.py's notify_turn (passive plan
    detection) carries non-NULL provenance (source_version excepted, per
    the card's Task 4 scope)."""
    from campy.brain.thalamus.tools.capture import notify_turn

    db = KuzuClient(str(tmp_path / "capture_plan.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    session_id = "sess-passive-plan"
    content = (
        "Plan:\n"
        "1. First we will set up the environment.\n"
        "2. Then we will write the code.\n"
        "3. Finally we will run the tests.\n"
    )
    result = await notify_turn(
        {"role": "user", "content": content, "session_id": session_id},
        db,
        CONFIG,
    )

    assert result.get("passive_plan"), result
    plan_id = result["passive_plan"]["plan_id"]

    r = db.execute(
        "MATCH (p:Plan {plan_id: $id}) RETURN p.observed_at, p.evidence_ref",
        {"id": plan_id},
    )
    assert r.has_next()
    row = r.get_next()
    assert row[0] is not None
    assert row[1] == result["message_id"]

    r2 = db.execute(
        "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $id}) "
        "RETURN ps.source, ps.observed_at, ps.evidence_ref LIMIT 1",
        {"id": plan_id},
    )
    assert r2.has_next()
    step_row = r2.get_next()
    assert step_row[0] == "user:direct"
    assert step_row[1] is not None
    assert step_row[2] == result["message_id"]


# ---------------------------------------------------------------------------
# Recall paths tolerate NULL provenance (no NoneType crashes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_relevant_lessons_tolerates_null_provenance(tmp_path):
    db = KuzuClient(str(tmp_path / "recall_lessons.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    lesson_id = str(uuid.uuid4())
    # Written directly (bypassing upsert_lesson) so all four provenance
    # fields are genuinely NULL, simulating a pre-B312 row.
    await db.execute_write(
        "CREATE (l:Lesson {lesson_id: $id, text_raw: $text, embedding: $emb, "
        "embedding_model: 'stub', embedding_dim: 384, domain: 'nullprov', "
        "lesson_type: 'optimization', confidence: 0.9, confidence_low: false, "
        "pathway_strength: 1.0, archived: false, created_at: timestamp($now)})",
        {"id": lesson_id, "text": "null provenance lesson", "emb": list(_FAKE_VEC),
         "now": "2026-01-01T00:00:00+00:00"},
    )

    result = await recall_relevant_lessons({"domain": "nullprov", "limit": 5}, db, CONFIG)
    assert any(l["lesson_id"] == lesson_id for l in result["lessons"])

    # Vector-search path too.
    result_q = await recall_relevant_lessons({"query": "null provenance lesson", "limit": 5}, db, CONFIG)
    assert isinstance(result_q["lessons"], list)


@pytest.mark.asyncio
async def test_current_truth_tolerates_null_provenance(tmp_path):
    db = KuzuClient(str(tmp_path / "recall_truth.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    concept_id = str(uuid.uuid4())
    await db.execute_write(
        "CREATE (c:Concept {concept_id: $id, text_raw: $text, embedding: $emb, "
        "embedding_model: 'stub', embedding_dim: 384, confidence: 0.9, "
        "confidence_low: false, pathway_strength: 1.0, archived: false, "
        "created_at: timestamp($now)})",
        {"id": concept_id, "text": "null provenance concept", "emb": list(_FAKE_VEC),
         "now": "2026-01-01T00:00:00+00:00"},
    )

    result = await current_truth(
        {"query": "null provenance concept", "session_id": "unknown"}, db, CONFIG
    )
    assert isinstance(result["results"], list)
