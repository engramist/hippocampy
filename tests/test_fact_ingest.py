"""
Tests for B317 — fact-envelope ingest (`campy.brain.hippocampus.facts`).

Uses a real (embedded, file-backed) Kùzu database via `KuzuClient` — same
pattern as `tests/test_b64_integration.py` / `tests/test_provenance.py` —
with embeddings monkeypatched to avoid network access to a
sentence-transformers/Ollama endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from campy.brain.hippocampus.facts import (
    FactEntityEnvelope,
    FactEnvelope,
    ingest_entities,
    ingest_facts,
)
from campy.brain.hippocampus.graph.export import export_graph_dump
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.provenance import drop_projections
from campy.brain.hippocampus.schema import init_schema

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    """Patch `emb.embed`/`embed_batch` on every module that binds its own
    reference to `campy.brain.hippocampus.graph.embeddings` (mirrors
    `tests/test_provenance.py`'s fixture — see its docstring for why this
    patches each bound module object rather than the dotted string path)."""
    from campy.brain.hippocampus import facts as _facts_mod
    from campy.brain.hippocampus import schema as _schema_mod

    def _fake_embed(text, model_name=None):
        return [0.01] * 384

    def _fake_embed_batch(texts, model_name=None):
        return [[0.01] * 384 for _ in texts]

    for mod in (_facts_mod, _schema_mod):
        monkeypatch.setattr(mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)


def _gw(db: KuzuClient) -> GraphGateway:
    return GraphGateway(db, REGISTRY)


def _entity(entity_id: str, entity_type: str = "capability", label: str | None = None,
            source: str = "harvest:catalog", source_version: str = "v1") -> FactEntityEnvelope:
    return FactEntityEnvelope(
        entity_id=entity_id, entity_type=entity_type, label=label or entity_id,
        source=source, source_version=source_version, observed_at=_NOW,
    )


def _fact(subject_id: str, predicate: str, object_id: str, *, source: str = "harvest:catalog",
          source_version: str = "v1", properties: dict | None = None) -> FactEnvelope:
    return FactEnvelope(
        subject_id=subject_id, predicate=predicate, object_id=object_id,
        source=source, source_version=source_version, properties=properties or {},
        observed_at=_NOW,
    )


# ---------------------------------------------------------------------------
# ingest_entities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_entities_creates_entity_with_authority_projected(tmp_path):
    db = KuzuClient(str(tmp_path / "entities.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    result = await ingest_entities(gw, [_entity("agent/claude-design", "capability")])
    assert result == {"entities": 1, "rejected": []}

    rows = await gw.run("capability.find_fact_entity", entity_id="agent/claude-design")
    assert len(rows) == 1

    raw = db.execute(
        "MATCH (e:FactEntity {entity_id: $id}) RETURN e.authority",
        {"id": "agent/claude-design"},
    )
    assert raw.get_next()[0] == "projected"


@pytest.mark.asyncio
async def test_ingest_entities_idempotent(tmp_path):
    db = KuzuClient(str(tmp_path / "entities_idem.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    entities = [_entity("agent/claude-design"), _entity("claude-code", "agent")]
    r1 = await ingest_entities(gw, entities)
    r2 = await ingest_entities(gw, entities)
    assert r1 == r2 == {"entities": 2, "rejected": []}

    count = db.execute("MATCH (e:FactEntity) RETURN count(e)").get_next()[0]
    assert count == 2  # no duplicates


@pytest.mark.asyncio
async def test_ingest_entities_without_source_version_raises(tmp_path):
    db = KuzuClient(str(tmp_path / "entities_bad.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    bad = FactEntityEnvelope(
        entity_id="x", entity_type="capability", label="x",
        source="harvest:catalog", source_version="", observed_at=_NOW,
    )
    with pytest.raises(ValueError):
        await ingest_entities(gw, [bad])


# ---------------------------------------------------------------------------
# ingest_facts — core rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_facts_creates_edge_with_authority_projected(tmp_path):
    db = KuzuClient(str(tmp_path / "facts_basic.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    await ingest_entities(gw, [_entity("a"), _entity("b")])
    result = await ingest_facts(gw, [_fact("a", "REQUIRES", "b", properties={"confidence": 0.9})])
    assert result == {"entities": 2, "edges": 1, "rejected": []}

    raw = db.execute(
        "MATCH (:FactEntity {entity_id: 'a'})-[r:FACT_REQUIRES]->(:FactEntity {entity_id: 'b'}) "
        "RETURN r.authority, r.confidence"
    )
    row = raw.get_next()
    assert row[0] == "projected"
    assert row[1] == 0.9


@pytest.mark.asyncio
async def test_ingest_facts_auto_vivifies_missing_entities(tmp_path):
    """ingest_facts never fails on a missing endpoint — it auto-vivifies a
    minimal stub FactEntity (entity_type='unknown') per the module
    docstring's card-gap note."""
    db = KuzuClient(str(tmp_path / "facts_autoviv.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    result = await ingest_facts(gw, [_fact("never-seeded-a", "INVOKES", "never-seeded-b")])
    assert result == {"entities": 2, "edges": 1, "rejected": []}

    row = db.execute(
        "MATCH (e:FactEntity {entity_id: 'never-seeded-a'}) RETURN e.entity_type"
    ).get_next()
    assert row[0] == "unknown"


@pytest.mark.asyncio
async def test_ingest_facts_idempotent(tmp_path):
    db = KuzuClient(str(tmp_path / "facts_idem.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    facts = [_fact("a", "REQUIRES", "b"), _fact("a", "INVOKES", "c")]
    r1 = await ingest_facts(gw, facts)
    r2 = await ingest_facts(gw, facts)
    assert r1 == r2 == {"entities": 3, "edges": 2, "rejected": []}

    count = db.execute("MATCH ()-[r:FACT_REQUIRES]->() RETURN count(r)").get_next()[0]
    assert count == 1  # no duplicate edge


@pytest.mark.asyncio
async def test_ingest_facts_unknown_predicate_rejected_not_raised(tmp_path):
    db = KuzuClient(str(tmp_path / "facts_unknown.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    facts = [
        _fact("a", "REQUIRES", "b"),
        _fact("a", "TOTALLY_MADE_UP", "b"),
    ]
    result = await ingest_facts(gw, facts)  # must not raise
    assert result["edges"] == 1
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["predicate"] == "TOTALLY_MADE_UP"
    assert result["rejected"][0]["subject_id"] == "a"


@pytest.mark.asyncio
async def test_ingest_facts_without_source_version_raises(tmp_path):
    db = KuzuClient(str(tmp_path / "facts_noversion.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    bad = FactEnvelope(
        subject_id="a", predicate="REQUIRES", object_id="b",
        source="harvest:catalog", source_version="", properties={}, observed_at=_NOW,
    )
    with pytest.raises(ValueError):
        await ingest_facts(gw, [bad])

    # nothing was written — the batch-wide validation runs before any write
    count = db.execute("MATCH (e:FactEntity) RETURN count(e)").get_next()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_ingest_facts_without_source_version_does_not_abort_earlier_valid_batch(tmp_path):
    """A ValueError from one bad envelope must not partially-write facts
    that came before it in the same list — validated up front, see the
    module docstring."""
    db = KuzuClient(str(tmp_path / "facts_partial.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    bad = FactEnvelope(
        subject_id="a", predicate="REQUIRES", object_id="b",
        source="harvest:catalog", source_version=None, properties={}, observed_at=_NOW,
    )
    good = _fact("a", "INVOKES", "c")
    with pytest.raises(ValueError):
        await ingest_facts(gw, [good, bad])

    count = db.execute("MATCH ()-[r:FACT_INVOKES]->() RETURN count(r)").get_next()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# Supersession (edge-level, on re-ingest with a newer source_version)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reingest_with_newer_version_supersedes_not_overwrites(tmp_path):
    db = KuzuClient(str(tmp_path / "facts_supersede.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    v1 = _fact("a", "REQUIRES", "b", source_version="v1", properties={"confidence": 0.5})
    v2 = _fact("a", "REQUIRES", "b", source_version="v2", properties={"confidence": 0.9})

    await ingest_facts(gw, [v1])
    await ingest_facts(gw, [v2])

    # exactly two edge rows exist between a and b: the old (superseded) one
    # and the new (live) one — supersession never overwrites in place.
    total = db.execute("MATCH ()-[r:FACT_REQUIRES]->() RETURN count(r)").get_next()[0]
    assert total == 2

    live = db.execute(
        "MATCH (:FactEntity {entity_id:'a'})-[r:FACT_REQUIRES]->(:FactEntity {entity_id:'b'}) "
        "WHERE r.superseded_by IS NULL RETURN r.confidence, r.source_version"
    ).get_next()
    assert live[0] == 0.9
    assert live[1] == "v2"

    old = db.execute(
        "MATCH (:FactEntity {entity_id:'a'})-[r:FACT_REQUIRES]->(:FactEntity {entity_id:'b'}) "
        "WHERE r.superseded_by IS NOT NULL "
        "RETURN r.confidence, r.source_version, r.superseded_by, r.supersession_reason"
    ).get_next()
    assert old[0] == 0.5
    assert old[1] == "v1"
    assert old[2] == "v2"  # superseded_by holds the new source_version (edges have no pk — see facts.py docstring)
    assert old[3] == "replaced"


@pytest.mark.asyncio
async def test_reingest_same_version_is_idempotent_no_op(tmp_path):
    db = KuzuClient(str(tmp_path / "facts_sameversion.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    fact = _fact("a", "REQUIRES", "b", source_version="v1", properties={"confidence": 0.5})
    await ingest_facts(gw, [fact])
    await ingest_facts(gw, [fact])

    total = db.execute("MATCH ()-[r:FACT_REQUIRES]->() RETURN count(r)").get_next()[0]
    assert total == 1  # no supersession, no duplicate — same version is a no-op


# ---------------------------------------------------------------------------
# drop_projections() round trip (B313) — coexistence with earned memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drop_projections_removes_fact_graph_leaves_earned_memory_untouched(tmp_path):
    db = KuzuClient(str(tmp_path / "drop.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    await ingest_entities(gw, [_entity("a"), _entity("b")])
    await ingest_facts(gw, [_fact("a", "REQUIRES", "b")])

    # earned memory in the SAME db: a Lesson written the normal way, with
    # no `source` collision with the fact graph's harvest source.
    from campy.brain.thalamus.tools.lessons import upsert_lesson
    lesson = await upsert_lesson({"text": "earned lesson", "domain": "test"}, db, {"embeddings": {"model": EMBEDDING_MODEL}})

    result = await drop_projections(db, source="harvest:catalog", dry_run=False, tables=["FactEntity"])
    assert result["deleted"] == 2
    assert result["skipped_earned"] == 0

    remaining = db.execute("MATCH (e:FactEntity) RETURN count(e)").get_next()[0]
    assert remaining == 0
    remaining_edges = db.execute("MATCH ()-[r:FACT_REQUIRES]->() RETURN count(r)").get_next()[0]
    assert remaining_edges == 0  # DETACH DELETE cascades edges too

    # earned memory survives untouched
    still_there = db.execute(
        "MATCH (l:Lesson {lesson_id: $id}) RETURN l.text_raw", {"id": lesson["lesson_id"]}
    ).get_next()
    assert still_there[0] == "earned lesson"


# ---------------------------------------------------------------------------
# Export (B313's include_projected) sees the capability graph as projected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_default_excludes_fact_graph_include_projected_includes_it(tmp_path):
    """FactEntity/FACT_* never appear in schema.PROVENANCE_TABLES (see
    facts.py's module docstring — deliberately a separate subgraph), so
    export.py's PROVENANCE_TABLES-keyed default-exclude filter doesn't
    naturally cover them. This is the regression test for the dedicated
    `_ALWAYS_PROJECTED_NODE_TABLES`/`_ALWAYS_PROJECTED_REL_PREFIX` handling
    export.py needed as a result: every FactEntity/FACT_* row is
    unconditionally `authority='projected'`, so `include_projected=False`
    (the default, disaster-recovery-of-earned-memory export) must exclude
    the whole capability graph, not just leave it in because it isn't a
    PROVENANCE_TABLES member."""
    db = KuzuClient(str(tmp_path / "export_fact.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gw = _gw(db)

    await ingest_entities(gw, [_entity("a"), _entity("b")])
    await ingest_facts(gw, [_fact("a", "REQUIRES", "b")])

    default_dump = tmp_path / "dump_default"
    full_dump = tmp_path / "dump_full"

    manifest_default = export_graph_dump(db, default_dump, include_projected=False)
    manifest_full = export_graph_dump(db, full_dump, include_projected=True)

    assert manifest_default["node_tables"]["FactEntity"]["rows"] == 0
    assert manifest_default["rel_tables"]["FACT_REQUIRES"]["rows"] == 0
    assert manifest_full["node_tables"]["FactEntity"]["rows"] == 2
    assert manifest_full["rel_tables"]["FACT_REQUIRES"]["rows"] == 1
