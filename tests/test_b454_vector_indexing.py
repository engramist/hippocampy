"""tests/test_b454_vector_indexing.py -- B454 proof.

Since the SPARQL cutover, `sparql=` node-create queries bypassed
`OxigraphClient.write_node()` -- the only place that populates the sqlite-vec
vector store and FTS5 text index -- so new Concepts/Decisions/Constraints/
Messages were unreachable by similarity or lexical search (live: 5/400 Concepts,
0/82 Decisions had an embedding). And `VectorStore.search_text` passed raw
natural-language questions to FTS5, so any `?` raised a syntax error that every
caller swallowed.
"""

from __future__ import annotations

import re

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import (
    CAMPY_NS,
    NODE_PRIMARY_KEYS,
    OxigraphClient,
    mint_uri,
)
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.queries.vector_indexing import (
    EXEMPT,
    VECTOR_INDEX_SPECS,
)
from campy.brain.hippocampus.graph.vector_store import VectorStore, _fts_match_expression

_CREATE_RE = re.compile(r"CREATE\s*\(\s*\w+:(\w+)\s*\{")


def _embedding_node_creates():
    for name, q in REGISTRY._queries.items():
        if not q.mutating:
            continue
        m = _CREATE_RE.search(q.cypher)
        if m and ("embedding" in q.cypher or any("emb" in p for p in q.params)):
            yield name, m.group(1), q


# ---------------------------------------------------------------------------
# Conformance: no embedding-carrying node-create may skip indexing again
# ---------------------------------------------------------------------------


def test_every_embedding_node_create_is_indexed_or_explicitly_exempt():
    missing = []
    for name, table, q in _embedding_node_creates():
        if q.vector_index is None and not EXEMPT.get(name):
            missing.append(name)
    assert not missing, (
        "these sparql= node-creates carry an embedding but re-attach no "
        f"vector/FTS indexing (add to VECTOR_INDEX_SPECS or EXEMPT): {missing}"
    )


def test_specs_match_the_query_and_schema():
    for name, spec in VECTOR_INDEX_SPECS.items():
        q = REGISTRY.get(name)
        assert q.vector_index == spec
        assert spec.pk_col == NODE_PRIMARY_KEYS[spec.table]
        assert spec.pk_param in q.params and spec.emb_param in q.params
        assert spec.text_param is None or spec.text_param in q.params


# ---------------------------------------------------------------------------
# End to end against a real store
# ---------------------------------------------------------------------------


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b454.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


EMB = [0.05] * 384


@pytest.mark.asyncio
async def test_new_message_is_vector_and_text_indexed(gw, ox_client):
    await gw.run(
        "capture.create_message",
        message_id="m-b454", text_raw="CRITICAL UPDATE: we migrated to PostgreSQL 16.",
        embedding=EMB, embedding_model="m", embedding_dim=384, role="user",
        byte_end=10, created_at="2026-09-24T00:00:00+00:00",
    )
    uri = mint_uri("Message", "m-b454")
    assert ox_client.vector_store.get_vector(uri) is not None
    # a natural-language question ending in '?' now finds it lexically
    hits = ox_client.fts_search("Message", "message_fts_idx",
                                "What is our production database version PostgreSQL?", 5)
    assert [h["node"]["message_id"] for h in hits] == ["m-b454"]


@pytest.mark.asyncio
async def test_new_concept_and_decision_are_vector_indexed(gw, ox_client):
    await gw.run(
        "orchestrator.create_concept",
        concept_id="c-b454", text_raw="PostgreSQL", embedding=EMB,
        embedding_model="m", embedding_dim=384, gist_class="PhysicalThing",
        schema_org_type="SoftwareApplication", confidence=0.7, confidence_low=True,
        pathway_strength=0.5, salience_score=1.0, anomaly_type=None,
        flagged_for_review=False, created_at="2026-09-24T00:00:00+00:00",
    )
    await gw.run(
        "orchestrator.create_artifact_decision",
        artifact_id="d-b454", text_raw="Use PostgreSQL 16", embedding=EMB,
        embedding_model="m", embedding_dim=384, confidence=0.9,
        pathway_strength=0.9, created_at="2026-09-24T00:00:00+00:00",
    )
    assert ox_client.vector_store.get_vector(mint_uri("Concept", "c-b454")) is not None
    assert ox_client.vector_store.get_vector(mint_uri("Decision", "d-b454")) is not None


def test_find_subject_uri_fast_path_matches_scan(ox_client):
    uri = mint_uri("Concept", "fast-1")
    ox_client.store.update(
        f'INSERT DATA {{ <{uri}> a <{CAMPY_NS}Concept> ; <{CAMPY_NS}concept_id> "fast-1" . }}'
    )
    assert ox_client.find_subject_uri("Concept", "concept_id", "fast-1") == uri
    assert ox_client.find_subject_uri("Concept", "concept_id", "nope") is None


# ---------------------------------------------------------------------------
# FTS query sanitization
# ---------------------------------------------------------------------------


def test_natural_language_question_no_longer_raises_and_matches():
    vs = VectorStore(":memory:")
    vs.index_text("u1", "We migrated to PostgreSQL 16 as the production database engine.")
    vs.index_text("u2", "Cache layer is Memcached on port 11211.")
    hits = vs.search_text("What is our active production database engine and version?", 5)
    assert hits and hits[0][0] == "u1"


def test_id_like_token_matches_as_phrase():
    vs = VectorStore(":memory:")
    vs.index_text("u1", "Observation for memgym_mysterypath_dbg1: path (0, 0) -> (0, 1)")
    assert [u for u, _ in vs.search_text("memgym_mysterypath_dbg1", 5)] == ["u1"]


@pytest.mark.parametrize("q", ['("x" : y) -- z\'', "", "   ", "?", "the and of", 'NEAR(a b)', "col:val*"])
def test_hostile_or_degenerate_queries_never_raise(q):
    VectorStore(":memory:").search_text(q, 5)


def test_expression_shape():
    assert _fts_match_expression("PostgreSQL 16?") == '"PostgreSQL" OR "16"'
    assert _fts_match_expression("the and of") == '"the" OR "and" OR "of"'
    assert _fts_match_expression("") is None


def test_backfill_script_indexes_missing_nodes_and_is_idempotent(tmp_path):
    import importlib.util
    from pathlib import Path

    import pyoxigraph as ox

    spec = importlib.util.spec_from_file_location(
        "backfill_vector_index",
        Path(__file__).resolve().parent.parent / "scripts" / "backfill_vector_index.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    store = ox.Store()
    vs = VectorStore(":memory:")
    a, b = mint_uri("Concept", "bf-a"), mint_uri("Message", "bf-b")
    store.update(
        f'INSERT DATA {{ <{a}> a <{CAMPY_NS}Concept> ; <{CAMPY_NS}text_raw> "Redis cluster" . '
        f'<{b}> a <{CAMPY_NS}Message> ; <{CAMPY_NS}text_raw> "we use Redis on 6379" . }}'
    )
    dry = mod.backfill(store, vs, lambda t: [0.1] * 384, dry_run=True)
    assert dry["Concept"]["missing_vector"] == 1 and vs.get_vector(a) is None

    calls = []
    mod.backfill(store, vs, lambda t: calls.append(t) or [0.1] * 384)
    assert vs.get_vector(a) is not None and vs.get_vector(b) is not None
    assert [u for u, _ in vs.search_text("redis", 5)]
    n = len(calls)
    mod.backfill(store, vs, lambda t: calls.append(t) or [0.1] * 384)
    assert len(calls) == n  # idempotent: nothing re-embedded


# ---------------------------------------------------------------------------
# Conversation evidence stage
# ---------------------------------------------------------------------------


async def _add_msg(gw, mid, text, role, created):
    from campy.brain.hippocampus.graph import embeddings as emb

    await gw.run(
        "capture.create_message",
        message_id=mid, text_raw=text, embedding=emb.embed(text), embedding_model="m",
        embedding_dim=384, role=role, byte_end=len(text), created_at=created,
    )


@pytest.mark.asyncio
async def test_conversation_evidence_returns_user_assertions_oldest_first(gw, ox_client):
    from campy.brain.hippocampus.graph import embeddings as emb

    await _add_msg(gw, "m1", "Our service uses PostgreSQL 14 hosted on AWS RDS.", "user", "2026-09-20T10:00:00+00:00")
    await _add_msg(gw, "m2", "Noted. Primary database is PostgreSQL 14.", "assistant", "2026-09-20T10:00:05+00:00")
    await _add_msg(gw, "m3", "CRITICAL UPDATE: We migrated the production database from PostgreSQL 14 to PostgreSQL 16.", "user", "2026-09-21T10:00:00+00:00")
    await _add_msg(gw, "m4", "What is our active production database engine and version?", "user", "2026-09-22T10:00:00+00:00")
    await _add_msg(gw, "m5", "Cache layer is Memcached on port 11211.", "user", "2026-09-22T11:00:00+00:00")
    q = "What is our active production database engine and version?"
    rows = await gw.run("thalamus.bundle_conversation",
                        query_embedding=emb.embed(q), query_text=q, limit=5)
    texts = [r["text"] for r in rows]
    assert texts[0].startswith("Our service uses PostgreSQL 14")
    assert texts[1].startswith("CRITICAL UPDATE")          # chronological: later supersedes earlier
    assert not any("Primary database" in t for t in texts)  # assistant echo excluded
    assert q not in texts                                   # the question itself excluded
    assert not any("Memcached" in t for t in texts)         # unrelated excluded


@pytest.mark.asyncio
async def test_conversation_evidence_dedupes_repeated_text_keeping_newest(gw, ox_client):
    from campy.brain.hippocampus.graph import embeddings as emb

    await _add_msg(gw, "d1", "We standardized on Redis for caching.", "user", "2026-09-20T10:00:00+00:00")
    await _add_msg(gw, "d2", "We standardized on Redis for caching.", "user", "2026-09-22T10:00:00+00:00")
    q = "What do we use for caching, Redis?"
    rows = await gw.run("thalamus.bundle_conversation", query_embedding=emb.embed(q), query_text=q, limit=5)
    assert len(rows) == 1 and rows[0]["created_at"].startswith("2026-09-22")


@pytest.mark.asyncio
async def test_conversation_evidence_empty_for_unrelated_query(gw, ox_client):
    from campy.brain.hippocampus.graph import embeddings as emb

    await _add_msg(gw, "u1", "Our service uses PostgreSQL 14 hosted on AWS RDS.", "user", "2026-09-20T10:00:00+00:00")
    q = "What is the airspeed velocity of an unladen swallow?"
    assert await gw.run("thalamus.bundle_conversation", query_embedding=emb.embed(q), query_text=q, limit=5) == []


# ---------------------------------------------------------------------------
# Sweep id-list binding (archive / resurrect / session-delete touched EVERY node)
# ---------------------------------------------------------------------------


def test_every_list_param_is_bound_into_its_sparql():
    """A mutating query that takes an id list must actually bind it. The sweep
    templates used `?n a campy:X ; campy:x_id ?ids .` with no `VALUES ?ids { }`
    placeholder, so `?ids` stayed unbound and the UPDATE hit every node of the
    type -- archiving (or un-archiving, or deleting LOADED/WARM edges of) the
    whole table whenever any one id qualified."""
    from campy.brain.hippocampus.graph.oxigraph_client import _bind_params_to_sparql

    unbound = []
    for name, q in REGISTRY._queries.items():
        if not q.mutating or not q.sparql:
            continue
        for p in q.params:
            if p not in ("ids", "cids", "session_ids"):
                continue
            others = {k: "v" for k in q.params if k != p}
            bound = _bind_params_to_sparql(q.sparql, {p: ["ZZ-1", "ZZ-2"], **others})
            if "ZZ-1" not in bound or "ZZ-2" not in bound:
                unbound.append(name)
    assert not unbound, f"list params never bound into SPARQL (would touch every node): {unbound}"


@pytest.mark.asyncio
async def test_archive_by_id_archives_only_that_node(gw, ox_client):
    for m in ("a1", "a2", "a3"):
        u = mint_uri("Message", m)
        ox_client.store.update(
            f'INSERT DATA {{ <{u}> a <{CAMPY_NS}Message> ; <{CAMPY_NS}message_id> "{m}" ; '
            f'<{CAMPY_NS}archived> false . }}'
        )
    await gw.run("sweep.unwind_archive_message", ids=["a1"])

    def archived(m):
        rows = ox_client._execute_and_collect(
            f'SELECT ?a WHERE {{ <{mint_uri("Message", m)}> <{CAMPY_NS}archived> ?a }}'
        )
        return [r["a"] for r in rows]

    assert archived("a1") == [True]
    assert archived("a2") == [False] and archived("a3") == [False]


def test_younger_than_helper():
    from datetime import datetime, timedelta, timezone

    from campy.brain.brainstem.sweep import _younger_than

    now = datetime.now(timezone.utc)
    assert _younger_than(now - timedelta(days=2), now, 30)
    assert not _younger_than(now - timedelta(days=45), now, 30)
    assert _younger_than((now - timedelta(days=2)).isoformat(), now, 30)
    assert not _younger_than(None, now, 30)          # unknown -> normal rules
    assert not _younger_than("garbage", now, 30)
    assert not _younger_than(now, now, 0)            # grace disabled


@pytest.mark.asyncio
async def test_sweep_does_not_archive_young_messages(gw, ox_client):
    from campy.brain.brainstem.sweep import _decay_and_archive

    old = "2026-01-01T00:00:00+00:00"
    from datetime import datetime, timezone

    fresh = datetime.now(timezone.utc).isoformat()
    for mid, created in (("old1", old), ("new1", fresh)):
        u = mint_uri("Message", mid)
        ox_client.store.update(
            f'INSERT DATA {{ <{u}> a <{CAMPY_NS}Message> ; <{CAMPY_NS}message_id> "{mid}" ; '
            f'<{CAMPY_NS}pathway_strength> 0.0 ; <{CAMPY_NS}archived> false ; '
            f'<{CAMPY_NS}created_at> "{created}"^^<http://www.w3.org/2001/XMLSchema#dateTime> . }}'
        )
    await _decay_and_archive(ox_client, {}, 0.0035, 0.10, message_grace_days=30.0)

    def archived(m):
        return [r["a"] for r in ox_client._execute_and_collect(
            f'SELECT ?a WHERE {{ <{mint_uri("Message", m)}> <{CAMPY_NS}archived> ?a }}')]

    assert archived("old1") == [True]     # old + below threshold -> archived
    assert archived("new1") == [False]    # young -> kept despite strength 0.0


@pytest.mark.asyncio
async def test_decay_keeps_zero_strength_and_still_decays_others(gw, ox_client):
    import pyoxigraph as ox

    for mid, ps in (("z0", "0.0"), ("z5", "0.5")):
        u = mint_uri("Message", mid)
        ox_client.store.update(
            f'INSERT DATA {{ <{u}> a <{CAMPY_NS}Message> ; <{CAMPY_NS}message_id> "{mid}" ; '
            f'<{CAMPY_NS}pathway_strength> {ps} ; <{CAMPY_NS}archived> false . }}'
        )

    def strength(mid):
        return [float(q.object.value) for q in ox_client.store.quads_for_pattern(
            ox.NamedNode(mint_uri("Message", mid)), ox.NamedNode(CAMPY_NS + "pathway_strength"), None, None)]

    await gw.run("sweep.decay_pathway_message", factor=0.9999)
    assert strength("z0") == [0.0]                 # was wiped: DELETE+INSERT of the same triple
    assert strength("z5") == [pytest.approx(0.49995)]


def test_repair_script_unarchives_wrongly_archived_only():
    import importlib.util
    from pathlib import Path

    import pyoxigraph as ox

    spec = importlib.util.spec_from_file_location(
        "repair_wrongly_archived",
        Path(__file__).resolve().parent.parent / "scripts" / "repair_wrongly_archived.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    store = ox.Store()
    def node(table, nid, strength, archived, created=None):
        u = mint_uri(table, nid)
        extra = f' ; <{CAMPY_NS}created_at> "{created}"' if created else ""
        st = f' ; <{CAMPY_NS}pathway_strength> {strength}' if strength is not None else ""
        store.update(
            f'INSERT DATA {{ <{u}> a <{CAMPY_NS}{table}> ; <{CAMPY_NS}archived> {archived}{st}{extra} . }}'
        )
        return u

    strong = node("Concept", "c-strong", "0.7", "true")                          # bug victim -> unarchive
    weak = node("Concept", "c-weak", "0.02", "true")                             # legit -> stay archived
    young = node("Message", "m-young", "0.0", "true", datetime_now_iso())        # grace -> unarchive
    old = node("Message", "m-old", "0.0", "true", "2026-01-01T00:00:00+00:00")   # old + weak -> stay
    wiped = node("Message", "m-wiped", None, "true", datetime_now_iso())         # strength restored + unarchived

    rep = mod.repair(store)
    def arch(u):
        return [q.object.value for q in store.quads_for_pattern(
            ox.NamedNode(u), ox.NamedNode(CAMPY_NS + "archived"), None, None)]
    assert arch(strong) == ["false"] and arch(weak) == ["true"]
    assert arch(young) == ["false"] and arch(old) == ["true"] and arch(wiped) == ["false"]
    assert rep["Message"]["strength_restored"] == 1
    again = mod.repair(store)                                                    # idempotent
    assert again["Concept"]["unarchived"] == 0 and again["Message"]["unarchived"] == 0


def datetime_now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
