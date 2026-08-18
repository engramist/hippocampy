"""
Tests for B317 — campy/brain/hippocampus/facts.py: ingest_entities() /
ingest_facts() direct behavior.

Real, embedded, file-backed Kùzu database via KuzuClient — the same pattern
as tests/test_provenance.py / tests/test_capability_queries.py — with
embeddings monkeypatched so nothing here depends on network access to a
sentence-transformers / Ollama endpoint.

Where tests/test_capability_queries.py exercises facts.py indirectly (via
benchmarks/capability_eval/fixtures.py's seed_fixture_graph()), this file
targets ingest_entities()/ingest_facts() directly: idempotency, supersession
on a newer source_version, unknown-predicate rejection without aborting the
batch, missing-source_version rejection (B313's validate_authority), and the
authority='projected' invariant on every row this module writes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from campy.brain.hippocampus.facts import EntityEnvelope, FactEnvelope, ingest_entities, ingest_facts
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.schema import init_schema

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_SOURCE = "harvest:fact-ingest-test"
_OBSERVED_AT = datetime(2026, 8, 1, tzinfo=timezone.utc)

_FAKE_VEC = [0.01] * 384


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    """init_schema()'s startup dimension-validation probe calls emb.embed();
    nothing else in this file touches a real embedding model (FactEnvelope/
    EntityEnvelope carry no embedding in these tests)."""
    from campy.brain.hippocampus import schema as _schema_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    monkeypatch.setattr(_schema_mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)


def _gateway(tmp_path, name: str = "fact_ingest.db") -> tuple[KuzuClient, GraphGateway]:
    db = KuzuClient(str(tmp_path / name))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    return db, GraphGateway(db, REGISTRY)


def _fact(
    subject_id: str,
    predicate: str,
    object_id: str,
    *,
    source_version: str | None = "v1",
    source: str = _SOURCE,
    properties: dict | None = None,
) -> FactEnvelope:
    return FactEnvelope(
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        properties=properties or {},
        source=source,
        source_version=source_version,
        observed_at=_OBSERVED_AT,
        evidence_ref=f"evidence://{subject_id}/{predicate.lower()}/{object_id}",
    )


def _count_edges(db: KuzuClient, subject_id: str, predicate_table: str, object_id: str) -> int:
    r = db.execute(
        f"MATCH (:FactEntity {{entity_id: $s}})-[r:{predicate_table}]->(:FactEntity {{entity_id: $o}}) "
        "RETURN count(r)",
        {"s": subject_id, "o": object_id},
    )
    assert r.has_next()
    return r.get_next()[0]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_facts_idempotent_same_batch_twice(tmp_path):
    db, gateway = _gateway(tmp_path)
    try:
        facts = [_fact("a.one", "REQUIRES", "a.two")]

        result1 = await ingest_facts(gateway, facts)
        result2 = await ingest_facts(gateway, facts)

        assert result1 == {"entities": 2, "edges": 1, "rejected": []}
        assert result2 == {"entities": 2, "edges": 1, "rejected": []}

        assert _count_edges(db, "a.one", "FACT_REQUIRES", "a.two") == 1
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ingest_entities_idempotent_no_duplicate_nodes(tmp_path):
    db, gateway = _gateway(tmp_path)
    try:
        entities = [
            EntityEnvelope(
                entity_id="cap.foo",
                entity_type="capability",
                label="Foo",
                source=_SOURCE,
                source_version="v1",
                observed_at=_OBSERVED_AT,
            )
        ]

        result1 = await ingest_entities(gateway, entities)
        result2 = await ingest_entities(gateway, entities)

        assert result1 == {"entities": 1}
        assert result2 == {"entities": 1}

        r = db.execute("MATCH (n:FactEntity {entity_id: 'cap.foo'}) RETURN count(n)")
        assert r.get_next()[0] == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Supersession on a newer source_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_facts_newer_source_version_supersedes_old_edge(tmp_path):
    db, gateway = _gateway(tmp_path)
    try:
        v1 = [_fact("b.one", "REQUIRES", "b.two", source_version="v1", properties={"confidence": 0.5})]
        v2 = [_fact("b.one", "REQUIRES", "b.two", source_version="v2", properties={"confidence": 0.9})]

        result1 = await ingest_facts(gateway, v1)
        result2 = await ingest_facts(gateway, v2)

        assert result1["edges"] == 1
        assert result2["edges"] == 1

        # Two rows now exist between the same pair: the old (superseded)
        # edge and the new live one. This is the "retrievable with a query
        # that doesn't filter superseded_by IS NULL" proof — a direct read,
        # per the card's own allowed alternative to include_superseded=True.
        r = db.execute(
            "MATCH (:FactEntity {entity_id: 'b.one'})-[r:FACT_REQUIRES]->(:FactEntity {entity_id: 'b.two'}) "
            "RETURN r.source_version AS source_version, r.superseded_by AS superseded_by, "
            "r.confidence AS confidence ORDER BY r.source_version"
        )
        rows = []
        while r.has_next():
            row = r.get_next()
            rows.append({"source_version": row[0], "superseded_by": row[1], "confidence": row[2]})

        assert len(rows) == 2
        old_row = next(row for row in rows if row["source_version"] == "v1")
        new_row = next(row for row in rows if row["source_version"] == "v2")

        assert old_row["superseded_by"] == "v2"
        assert old_row["confidence"] == 0.5
        assert new_row["superseded_by"] is None
        assert new_row["confidence"] == 0.9

        # Live-only query only finds the new edge.
        live = await gateway.run(
            "capability.find_live_edge__requires", subject_id="b.one", object_id="b.two"
        )
        assert len(live) == 1
        assert live[0]["source_version"] == "v2"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ingest_facts_same_source_version_twice_is_a_no_op_not_a_supersession(tmp_path):
    """Re-ingesting the exact same (subject, predicate, object,
    source_version) triple must NOT create a second edge or mark anything
    superseded — that's idempotency's job, distinct from supersession."""
    db, gateway = _gateway(tmp_path)
    try:
        facts = [_fact("c.one", "REQUIRES", "c.two", source_version="v1")]
        await ingest_facts(gateway, facts)
        await ingest_facts(gateway, facts)

        assert _count_edges(db, "c.one", "FACT_REQUIRES", "c.two") == 1
        r = db.execute(
            "MATCH (:FactEntity {entity_id: 'c.one'})-[r:FACT_REQUIRES]->(:FactEntity {entity_id: 'c.two'}) "
            "RETURN r.superseded_by"
        )
        assert r.has_next()
        assert r.get_next()[0] is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Unknown predicate: rejected, not raised, batch continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_facts_unknown_predicate_rejected_without_raising_or_aborting_batch(tmp_path):
    db, gateway = _gateway(tmp_path)
    try:
        facts = [
            _fact("d.one", "BOGUS_PREDICATE", "d.two"),
            _fact("d.three", "REQUIRES", "d.four"),
        ]

        result = await ingest_facts(gateway, facts)  # must not raise

        assert result["rejected"] == [
            {
                "subject_id": "d.one",
                "predicate": "BOGUS_PREDICATE",
                "object_id": "d.two",
                "reason": "unknown_predicate",
            }
        ]
        # The rest of the batch still went through.
        assert result["edges"] == 1
        assert _count_edges(db, "d.three", "FACT_REQUIRES", "d.four") == 1
        # The rejected fact's endpoints were never touched.
        r = db.execute("MATCH (n:FactEntity {entity_id: 'd.one'}) RETURN count(n)")
        assert r.get_next()[0] == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Missing source_version raises (B313's validate_authority)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_facts_missing_source_version_raises(tmp_path):
    db, gateway = _gateway(tmp_path)
    try:
        facts = [_fact("e.one", "REQUIRES", "e.two", source_version=None)]
        with pytest.raises(ValueError):
            await ingest_facts(gateway, facts)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ingest_entities_missing_source_version_raises(tmp_path):
    db, gateway = _gateway(tmp_path)
    try:
        entities = [
            EntityEnvelope(
                entity_id="cap.bar",
                entity_type="capability",
                label="Bar",
                source=_SOURCE,
                source_version=None,
                observed_at=_OBSERVED_AT,
            )
        ]
        with pytest.raises(ValueError):
            await ingest_entities(gateway, entities)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ingest_facts_unknown_predicate_before_missing_version_fact_still_raises(tmp_path):
    """An *accepted* (known-predicate) fact missing source_version raises
    and aborts the whole batch, even when an earlier, unrelated unknown-
    predicate fact in the same batch was merely rejected (not raised)."""
    db, gateway = _gateway(tmp_path)
    try:
        facts = [
            _fact("f.one", "BOGUS_PREDICATE", "f.two"),
            _fact("f.three", "REQUIRES", "f.four", source_version=None),
        ]
        with pytest.raises(ValueError):
            await ingest_facts(gateway, facts)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# authority='projected' on every ingested row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingested_entities_and_edges_carry_authority_projected(tmp_path):
    db, gateway = _gateway(tmp_path)
    try:
        entities = [
            EntityEnvelope(
                entity_id="cap.baz",
                entity_type="capability",
                label="Baz",
                source=_SOURCE,
                source_version="v1",
                observed_at=_OBSERVED_AT,
            )
        ]
        await ingest_entities(gateway, entities)
        await ingest_facts(gateway, [_fact("cap.baz", "REQUIRES", "cap.qux")])

        r = db.execute("MATCH (n:FactEntity {entity_id: 'cap.baz'}) RETURN n.authority")
        assert r.has_next()
        assert r.get_next()[0] == "projected"

        # cap.qux only exists as a bare stub (ingest_facts' endpoint upsert)
        # — it too must carry authority='projected'.
        r2 = db.execute("MATCH (n:FactEntity {entity_id: 'cap.qux'}) RETURN n.authority")
        assert r2.has_next()
        assert r2.get_next()[0] == "projected"

        r3 = db.execute(
            "MATCH (:FactEntity {entity_id: 'cap.baz'})-[r:FACT_REQUIRES]->(:FactEntity {entity_id: 'cap.qux'}) "
            "RETURN r.authority"
        )
        assert r3.has_next()
        assert r3.get_next()[0] == "projected"
    finally:
        db.close()
