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
