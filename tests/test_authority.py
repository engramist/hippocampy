"""
Tests for B313 — Authority Property: Projected vs Earned Memory.

Follows the pattern established by tests/test_provenance.py (B312): a real,
embedded, file-backed Kùzu database via KuzuClient, with embeddings
monkeypatched to a fixed vector so nothing here depends on network access to
a sentence-transformers / Ollama endpoint.
"""

from __future__ import annotations

import uuid

import pytest

from campy.brain.hippocampus.graph.export import export_graph_dump, import_graph_dump
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import (
    AUTHORITY_VALUES,
    NODE_TABLES,
    PROVENANCE_TABLES,
    REL_TABLES,
    init_schema,
)
from campy.brain.hippocampus.provenance import (
    authority_of,
    drop_projections,
    find_stale_projections,
    provenance_fields,
    validate_authority,
)
from campy.brain.thalamus.bundle_compiler import _stage_exact_facts
from campy.brain.thalamus.tools.retrieval import current_truth

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CONFIG = {"embeddings": {"model": EMBEDDING_MODEL}}

_FAKE_VEC = [0.01] * 384


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    """See tests/test_provenance.py's identical fixture for why this patches
    each consuming module's already-bound `emb` object directly rather than
    the dotted import path."""
    from campy.brain.hippocampus import schema as _schema_mod
    from campy.brain.thalamus.tools import retrieval as _retrieval_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    monkeypatch.setattr(_schema_mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)
    monkeypatch.setattr(_retrieval_mod.emb, "embed", _fake_embed)
    # bundle_compiler imports embeddings lazily inside each stage function
    # (`from campy.brain.hippocampus.graph import embeddings as emb`), so
    # patch the shared module object itself.
    from campy.brain.hippocampus.graph import embeddings as _emb_mod
    monkeypatch.setattr(_emb_mod, "embed", _fake_embed)


def _table_columns(db: KuzuClient, table: str) -> set[str]:
    r = db.execute(f"CALL table_info('{table}') RETURN *")
    cols = set()
    while r.has_next():
        cols.add(str(r.get_next()[1]))
    return cols


# ---------------------------------------------------------------------------
# Schema — authority column (AC1)
# ---------------------------------------------------------------------------


def test_authority_values_vocabulary():
    assert AUTHORITY_VALUES == {"earned", "projected"}


def test_fresh_db_creates_authority_column_on_every_provenance_table(tmp_path):
    db = KuzuClient(str(tmp_path / "fresh.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    missing = [table for table in PROVENANCE_TABLES if "authority" not in _table_columns(db, table)]
    assert missing == [], f"tables missing authority column: {missing}"


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
    source              STRING,
    source_version      STRING,
    observed_at         TIMESTAMP,
    evidence_ref        STRING,
    superseded_by       STRING,
    superseded_at       TIMESTAMP,
    supersession_reason STRING,
    PRIMARY KEY (concept_id)
"""


def test_migrated_db_adds_authority_column_and_preserves_rows(tmp_path):
    """Simulate a post-B312/pre-B313 database (has provenance/supersession
    columns but no `authority`), then run the current init_schema() against
    it: the column must appear and no row may be lost (AC1, migrated DB)."""
    db = KuzuClient(str(tmp_path / "upgrade.db"))
    db.execute(f"CREATE NODE TABLE Concept ({_OLD_CONCEPT_DDL})")

    cols_before = _table_columns(db, "Concept")
    assert "authority" not in cols_before

    concept_id = str(uuid.uuid4())
    db.execute(
        "CREATE (c:Concept {concept_id: $id, text_raw: $text, confidence: 0.5, archived: false})",
        {"id": concept_id, "text": "pre-B313 concept"},
    )

    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    cols_after = _table_columns(db, "Concept")
    assert "authority" in cols_after

    r = db.execute(
        "MATCH (c:Concept {concept_id: $id}) RETURN c.text_raw, c.authority",
        {"id": concept_id},
    )
    assert r.has_next()
    row = r.get_next()
    assert row[0] == "pre-B313 concept"
    assert row[1] is None  # migrated in as NULL, not "earned" the string


# ---------------------------------------------------------------------------
# authority_of() — NULL-safe read (AC5)
# ---------------------------------------------------------------------------


def test_authority_of_none_reads_as_earned():
    assert authority_of(None) == "earned"


def test_authority_of_missing_key_reads_as_earned():
    assert authority_of({}) == "earned"


def test_authority_of_null_value_reads_as_earned():
    assert authority_of({"authority": None}) == "earned"


def test_authority_of_explicit_projected():
    assert authority_of({"authority": "projected"}) == "projected"


def test_authority_of_explicit_earned():
    assert authority_of({"authority": "earned"}) == "earned"


def test_authority_of_bare_value():
    assert authority_of("projected") == "projected"
    assert authority_of(None) == "earned"


def test_authority_of_unrecognized_value_reads_as_earned():
    """Corrupt/unexpected values fall back to the conservative default too,
    not just NULL/missing (see the docstring's "when in doubt" rationale)."""
    assert authority_of({"authority": "bogus"}) == "earned"


# ---------------------------------------------------------------------------
# validate_authority() — the write-time invariant (AC2, AC3, AC4)
# ---------------------------------------------------------------------------


def test_validate_authority_projected_without_source_version_raises():
    with pytest.raises(ValueError):
        validate_authority("projected", "harvest:git", None)


def test_validate_authority_projected_without_source_raises():
    with pytest.raises(ValueError):
        validate_authority("projected", None, "v1")


def test_validate_authority_projected_with_empty_string_source_raises():
    with pytest.raises(ValueError):
        validate_authority("projected", "", "v1")


def test_validate_authority_projected_with_both_succeeds():
    validate_authority("projected", "harvest:git", "v1")  # must not raise


def test_validate_authority_earned_with_no_provenance_succeeds():
    validate_authority("earned", None, None)  # must not raise — no regression


def test_validate_authority_rejects_unknown_value():
    with pytest.raises(ValueError):
        validate_authority("bogus", "harvest:git", "v1")


def test_provenance_fields_omits_authority_key_when_not_passed():
    """Backward compatibility: existing callers of provenance_fields() that
    don't pass `authority` get back the exact same 4-key dict as before
    B313 (tests/test_provenance.py pins this with an exact equality check)."""
    result = provenance_fields(source="agent:claude-code")
    assert "authority" not in result


def test_provenance_fields_projected_without_source_version_raises():
    with pytest.raises(ValueError):
        provenance_fields(source="harvest:git", authority="projected")


def test_provenance_fields_projected_with_source_version_included():
    result = provenance_fields(
        source="harvest:git", source_version="v1", authority="projected"
    )
    assert result["authority"] == "projected"
    assert result["source_version"] == "v1"


def test_provenance_fields_earned_with_no_source_version_included():
    result = provenance_fields(source="agent:claude-code", authority="earned")
    assert result["authority"] == "earned"


# ---------------------------------------------------------------------------
# find_stale_projections() (AC6)
# ---------------------------------------------------------------------------


async def _seed_concept(
    db: KuzuClient, *, concept_id: str, authority: str | None,
    source: str | None, source_version: str | None,
) -> None:
    await db.execute_write(
        "CREATE (c:Concept {concept_id: $id, text_raw: $text, embedding: $emb, "
        "embedding_model: 'stub', embedding_dim: 384, confidence: 0.9, "
        "confidence_low: false, pathway_strength: 1.0, archived: false, "
        "created_at: timestamp($now), authority: $authority, source: $source, "
        "source_version: $source_version})",
        {
            "id": concept_id,
            "text": f"concept {concept_id}",
            "emb": list(_FAKE_VEC),
            "now": "2026-01-01T00:00:00+00:00",
            "authority": authority,
            "source": source,
            "source_version": source_version,
        },
    )


@pytest.mark.asyncio
async def test_find_stale_projections_returns_only_version_mismatches(tmp_path):
    db = KuzuClient(str(tmp_path / "stale.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    stale_id = str(uuid.uuid4())
    current_id = str(uuid.uuid4())
    other_source_id = str(uuid.uuid4())
    earned_id = str(uuid.uuid4())

    await _seed_concept(db, concept_id=stale_id, authority="projected", source="harvest:git", source_version="v1")
    await _seed_concept(db, concept_id=current_id, authority="projected", source="harvest:git", source_version="v2")
    await _seed_concept(db, concept_id=other_source_id, authority="projected", source="harvest:other", source_version="v1")
    await _seed_concept(db, concept_id=earned_id, authority="earned", source=None, source_version=None)

    result = await find_stale_projections(
        db, source="harvest:git", current_version="v2", tables=["Concept"]
    )

    assert len(result) == 1
    assert result[0]["node_id"] == stale_id
    assert result[0]["source_version"] == "v1"


@pytest.mark.asyncio
async def test_find_stale_projections_empty_when_everything_current(tmp_path):
    db = KuzuClient(str(tmp_path / "current.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    cid = str(uuid.uuid4())
    await _seed_concept(db, concept_id=cid, authority="projected", source="harvest:git", source_version="v2")

    result = await find_stale_projections(
        db, source="harvest:git", current_version="v2", tables=["Concept"]
    )
    assert result == []


# ---------------------------------------------------------------------------
# drop_projections() — the dangerous one (AC7, AC8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drop_projections_refuses_to_delete_earned_rows(tmp_path):
    """The core safety test: seed one 'earned' and one 'projected' row that
    share the same `source`; only the projected row may be deleted, and
    skipped_earned must report exactly 1."""
    db = KuzuClient(str(tmp_path / "drop.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    earned_id = str(uuid.uuid4())
    projected_id = str(uuid.uuid4())
    await _seed_concept(db, concept_id=earned_id, authority="earned", source="harvest:git", source_version=None)
    await _seed_concept(db, concept_id=projected_id, authority="projected", source="harvest:git", source_version="v1")

    result = await drop_projections(db, source="harvest:git", dry_run=False, tables=["Concept"])

    assert result == {"deleted": 1, "skipped_earned": 1}

    r = db.execute("MATCH (c:Concept {concept_id: $id}) RETURN count(c)", {"id": earned_id})
    assert r.get_next()[0] == 1  # earned row survives

    r2 = db.execute("MATCH (c:Concept {concept_id: $id}) RETURN count(c)", {"id": projected_id})
    assert r2.get_next()[0] == 0  # projected row is gone


@pytest.mark.asyncio
async def test_drop_projections_dry_run_deletes_nothing_but_reports_count(tmp_path):
    db = KuzuClient(str(tmp_path / "dry.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    projected_id = str(uuid.uuid4())
    await _seed_concept(db, concept_id=projected_id, authority="projected", source="harvest:git", source_version="v1")

    result = await drop_projections(db, source="harvest:git", tables=["Concept"])  # dry_run defaults True

    assert result == {"deleted": 1, "skipped_earned": 0}

    r = db.execute("MATCH (c:Concept {concept_id: $id}) RETURN count(c)", {"id": projected_id})
    assert r.get_next()[0] == 1  # still there — dry run must not delete


@pytest.mark.asyncio
async def test_drop_projections_never_touches_a_different_source(tmp_path):
    db = KuzuClient(str(tmp_path / "othersource.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    other_id = str(uuid.uuid4())
    await _seed_concept(db, concept_id=other_id, authority="projected", source="harvest:other", source_version="v1")

    result = await drop_projections(db, source="harvest:git", dry_run=False, tables=["Concept"])

    assert result == {"deleted": 0, "skipped_earned": 0}
    r = db.execute("MATCH (c:Concept {concept_id: $id}) RETURN count(c)", {"id": other_id})
    assert r.get_next()[0] == 1  # untouched


# ---------------------------------------------------------------------------
# Recall surfaces authority (Task 4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_truth_includes_authority_for_earned_and_projected(tmp_path):
    db = KuzuClient(str(tmp_path / "recall_authority.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    earned_id = str(uuid.uuid4())
    projected_id = str(uuid.uuid4())
    await _seed_concept(db, concept_id=earned_id, authority="earned", source=None, source_version=None)
    await _seed_concept(db, concept_id=projected_id, authority="projected", source="harvest:git", source_version="v1")

    result = await current_truth(
        {"query": "concept", "session_id": "unknown", "limit": 10}, db, CONFIG
    )

    by_id = {r["node_id"]: r for r in result["results"]}
    assert earned_id in by_id
    assert projected_id in by_id
    assert by_id[earned_id]["authority"] == "earned"
    assert by_id[projected_id]["authority"] == "projected"


@pytest.mark.asyncio
async def test_stage_exact_facts_includes_authority_when_column_present(tmp_path, monkeypatch):
    def _fake_embed(text, model_name=None):
        return [1.0, 0.0, 0.0, 0.0] if text == "q" else [0.0, 1.0, 0.0, 0.0]

    db = KuzuClient(str(tmp_path / "stage_authority.db"))
    db.execute(
        "CREATE NODE TABLE GlobalConstraint("
        "id STRING, text_raw STRING, confidence DOUBLE, authority STRING, "
        "embedding FLOAT[4], PRIMARY KEY (id))"
    )
    db.execute(
        "CREATE NODE TABLE GlobalPreference("
        "id STRING, text_raw STRING, confidence DOUBLE, authority STRING, "
        "embedding FLOAT[4], PRIMARY KEY (id))"
    )
    db.execute(
        "CREATE (n:GlobalConstraint {id: 'gc1', text_raw: 'never delete prod', "
        "confidence: 0.9, authority: 'projected', embedding: $emb})",
        {"emb": [0.99, 0.01, 0.0, 0.0]},
    )

    from campy.brain.hippocampus.graph import embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed", _fake_embed)

    section = await _stage_exact_facts(db, "q", CONFIG, {"max_semantic": 10})

    assert section is not None
    assert section.content[0]["authority"] == "projected"


@pytest.mark.asyncio
async def test_stage_exact_facts_defaults_authority_when_column_absent(tmp_path, monkeypatch):
    """Regression guard for the exact scenario this card's schema drift
    could otherwise cause: a schema built without the B313 `authority`
    column (e.g. an older test fixture) must not blow up the whole stage —
    it should just default every row to 'earned'."""
    db = KuzuClient(str(tmp_path / "stage_no_authority.db"))
    db.execute(
        "CREATE NODE TABLE GlobalConstraint("
        "id STRING, text_raw STRING, confidence DOUBLE, "
        "embedding FLOAT[4], PRIMARY KEY (id))"
    )
    db.execute(
        "CREATE NODE TABLE GlobalPreference("
        "id STRING, text_raw STRING, confidence DOUBLE, "
        "embedding FLOAT[4], PRIMARY KEY (id))"
    )
    db.execute(
        "CREATE (n:GlobalConstraint {id: 'gc1', text_raw: 'never delete prod', "
        "confidence: 0.9, embedding: $emb})",
        {"emb": [0.99, 0.01, 0.0, 0.0]},
    )

    def _fake_embed(text, model_name=None):
        return [1.0, 0.0, 0.0, 0.0] if text == "q" else [0.0, 1.0, 0.0, 0.0]

    from campy.brain.hippocampus.graph import embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed", _fake_embed)

    section = await _stage_exact_facts(db, "q", CONFIG, {"max_semantic": 10})

    assert section is not None
    assert section.content[0]["authority"] == "earned"


# ---------------------------------------------------------------------------
# Export/import — earned-only default (Task 5)
# ---------------------------------------------------------------------------


def _create_export_schema(db: KuzuClient) -> None:
    """Same pattern as tests/test_graph_export.py's `_create_schema`: build
    tables directly from NODE_TABLES/REL_TABLES rather than going through
    init_schema(). init_schema() also applies _MIGRATIONS (e.g.
    Concept.salience_score), which `export.py`'s `_ensure_graph_schema()`
    does not replay on import — a pre-existing gap unrelated to B313, not
    something this card's tests should trip over."""
    for table, ddl in NODE_TABLES.items():
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table} ({ddl})")
    for ddl in REL_TABLES:
        db.execute(ddl)


def _seed_export_graph(db: KuzuClient) -> tuple[str, str]:
    _create_export_schema(db)
    earned_id = str(uuid.uuid4())
    projected_id = str(uuid.uuid4())
    db.execute(
        "CREATE (c:Concept {concept_id: $id, text_raw: 'earned concept', "
        "embedding: $emb, embedding_model: 'stub', embedding_dim: 384, "
        "confidence: 0.9, confidence_low: false, pathway_strength: 1.0, "
        "archived: false, created_at: timestamp('2026-01-01T00:00:00'), "
        "authority: 'earned'})",
        {"id": earned_id, "emb": list(_FAKE_VEC)},
    )
    db.execute(
        "CREATE (c:Concept {concept_id: $id, text_raw: 'projected concept', "
        "embedding: $emb, embedding_model: 'stub', embedding_dim: 384, "
        "confidence: 0.9, confidence_low: false, pathway_strength: 1.0, "
        "archived: false, created_at: timestamp('2026-01-01T00:00:00'), "
        "authority: 'projected', source: 'harvest:git', source_version: 'v1'})",
        {"id": projected_id, "emb": list(_FAKE_VEC)},
    )
    return earned_id, projected_id


def test_export_default_excludes_projected_rows(tmp_path):
    db = KuzuClient(str(tmp_path / "src.db"))
    try:
        earned_id, projected_id = _seed_export_graph(db)
        dump_dir = tmp_path / "dump"
        manifest = export_graph_dump(db, dump_dir)

        assert manifest["include_projected"] is False
        assert manifest["node_tables"]["Concept"]["rows"] == 1

        lines = (dump_dir / "nodes" / "Concept.jsonl").read_text().splitlines()
        assert len(lines) == 1
        assert earned_id in lines[0]
        assert projected_id not in lines[0]
    finally:
        db.close()


def test_export_include_projected_true_includes_both(tmp_path):
    db = KuzuClient(str(tmp_path / "src2.db"))
    try:
        earned_id, projected_id = _seed_export_graph(db)
        dump_dir = tmp_path / "dump2"
        manifest = export_graph_dump(db, dump_dir, include_projected=True)

        assert manifest["include_projected"] is True
        assert manifest["node_tables"]["Concept"]["rows"] == 2

        text = (dump_dir / "nodes" / "Concept.jsonl").read_text()
        assert earned_id in text
        assert projected_id in text
    finally:
        db.close()


def test_import_of_projected_omitting_dump_does_not_error(tmp_path):
    """Re-importing a dump that omitted projected facts must not error on
    their absence (Task 5)."""
    db = KuzuClient(str(tmp_path / "src3.db"))
    try:
        _seed_export_graph(db)
        dump_dir = tmp_path / "dump3"
        export_graph_dump(db, dump_dir)  # default: excludes projected
    finally:
        db.close()

    fresh_db = KuzuClient(str(tmp_path / "fresh3.db"))
    try:
        restored = import_graph_dump(fresh_db, dump_dir)
        assert restored["ok"] is True
        assert fresh_db.execute("MATCH (n:Concept) RETURN count(n)").get_next()[0] == 1
    finally:
        fresh_db.close()
