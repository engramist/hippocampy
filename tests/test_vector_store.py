"""Tests for campy/brain/hippocampus/graph/vector_store.py (B390).

No mocks: every test opens a real temp SQLite file (or `:memory:`) and
exercises the real sqlite-vec extension and real FTS5 virtual tables.

Includes a recall-parity check against `KuzuClient.vector_search` on the
exact fixture `tests/test_vector_calibration.py` (B279) uses, so a drift
between the two engines' cosine-similarity scoring is caught here rather
than discovered later in B397.
"""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path

import pytest

from campy.brain.hippocampus.graph.vector_store import (
    CID_BASE,
    VectorStore,
    mint_uri,
)


# --- mint_uri ---------------------------------------------------------------


def test_mint_uri_matches_spec_example():
    # docs/rdf-schema-mapping.md §2's own worked example.
    assert mint_uri("Concept", "c_01H8XK") == "https://campy.dev/id/Concept/c_01H8XK"


def test_mint_uri_is_pure_function_of_table_and_key():
    # Same (table, key) -> byte-identical URI, always.
    assert mint_uri("Concept", "c_01H8XK") == mint_uri("Concept", "c_01H8XK")


def test_mint_uri_different_tables_same_key_are_different_uris():
    # Table name is part of identity (§2): same PK, different table, must
    # not collide.
    assert mint_uri("Concept", "1") != mint_uri("Decision", "1")


def test_mint_uri_percent_encodes_unsafe_characters():
    # A primary key containing a "/" must not be readable back as a path
    # separator -- percent-encoding is unconditional, not best-effort.
    uri = mint_uri("Concept", "a/b c")
    assert uri == f"{CID_BASE}Concept/a%2Fb%20c"
    # And the slash really is gone from the key segment.
    key_segment = uri[len(f"{CID_BASE}Concept/"):]
    assert "/" not in key_segment


def test_mint_uri_encodes_table_name_too():
    uri = mint_uri("Odd Table", "k1")
    assert uri == f"{CID_BASE}Odd%20Table/k1"


# --- vector plane: upsert / top-k / delete round trip -----------------------


@pytest.fixture()
def tmp_store_path():
    tmp = tempfile.mkdtemp(prefix="vecstore_")
    path = Path(tmp) / "vectors.db"
    yield path
    shutil.rmtree(tmp, ignore_errors=True)


def test_vector_upsert_topk_delete_round_trip(tmp_store_path):
    store = VectorStore(db_path=tmp_store_path, dim=4)
    try:
        u_identical = mint_uri("CalibNode", "identical")
        u_deg45 = mint_uri("CalibNode", "deg45")
        u_orth = mint_uri("CalibNode", "orthogonal")
        u_opp = mint_uri("CalibNode", "opposite")

        store.upsert_vector(u_identical, [1.0, 0.0, 0.0, 0.0])
        store.upsert_vector(u_deg45, [math.sqrt(0.5), math.sqrt(0.5), 0.0, 0.0])
        store.upsert_vector(u_orth, [0.0, 1.0, 0.0, 0.0])
        store.upsert_vector(u_opp, [-1.0, 0.0, 0.0, 0.0])

        results = store.search_vectors([1.0, 0.0, 0.0, 0.0], k=4)
        scores = dict(results)

        assert len(results) == 4
        # best-first ordering
        assert [uri for uri, _ in results][0] == u_identical
        assert abs(scores[u_identical] - 1.0) < 0.01
        assert abs(scores[u_deg45] - 0.7071) < 0.02
        assert abs(scores[u_orth] - 0.0) < 0.02
        assert abs(scores[u_opp] - (-1.0)) < 0.02

        # top-k actually limits
        top2 = store.search_vectors([1.0, 0.0, 0.0, 0.0], k=2)
        assert len(top2) == 2
        assert [uri for uri, _ in top2] == [u_identical, u_deg45]

        # distance threshold via min_score: only near-duplicates survive
        thresholded = store.search_vectors([1.0, 0.0, 0.0, 0.0], k=4, min_score=0.9)
        assert [uri for uri, _ in thresholded] == [u_identical]

        # delete round trip
        store.delete_vector(u_identical)
        after_delete = dict(store.search_vectors([1.0, 0.0, 0.0, 0.0], k=4))
        assert u_identical not in after_delete
        assert len(after_delete) == 3
    finally:
        store.close()


def test_vector_upsert_overwrites_existing_embedding(tmp_store_path):
    store = VectorStore(db_path=tmp_store_path, dim=4)
    try:
        uri = mint_uri("CalibNode", "a")
        store.upsert_vector(uri, [1.0, 0.0, 0.0, 0.0])
        store.upsert_vector(uri, [0.0, 1.0, 0.0, 0.0])  # overwrite, not append

        results = store.search_vectors([0.0, 1.0, 0.0, 0.0], k=10)
        assert len(results) == 1  # not 2 -- confirms replace, not insert-append
        assert results[0][0] == uri
        assert abs(results[0][1] - 1.0) < 0.01
    finally:
        store.close()


def test_vector_dim_mismatch_raises(tmp_store_path):
    store = VectorStore(db_path=tmp_store_path, dim=4)
    try:
        with pytest.raises(ValueError):
            store.upsert_vector(mint_uri("X", "1"), [1.0, 0.0])
        with pytest.raises(ValueError):
            store.search_vectors([1.0, 0.0], k=1)
    finally:
        store.close()


# --- lexical plane: FTS5 index / search round trip --------------------------


def test_fts_index_search_round_trip(tmp_store_path):
    store = VectorStore(db_path=tmp_store_path, dim=4)
    try:
        u1 = mint_uri("Concept", "gateway")
        u2 = mint_uri("Concept", "vector")

        store.index_text(u1, "GraphGateway routes every Cypher query")
        store.index_text(u2, "vector search uses cosine similarity")

        results = store.search_text("cosine", k=5)
        assert len(results) == 1
        assert results[0][0] == u2
        assert results[0][1] > 0  # higher-is-better convention

        results_gateway = store.search_text("Cypher", k=5)
        assert [uri for uri, _ in results_gateway] == [u1]
    finally:
        store.close()


def test_fts_delete_round_trip(tmp_store_path):
    store = VectorStore(db_path=tmp_store_path, dim=4)
    try:
        uri = mint_uri("Concept", "gateway")
        store.index_text(uri, "GraphGateway routes every Cypher query")
        assert store.search_text("Cypher", k=5) != []

        store.delete_text(uri)
        assert store.search_text("Cypher", k=5) == []
    finally:
        store.close()


def test_fts_upsert_overwrites_existing_text(tmp_store_path):
    store = VectorStore(db_path=tmp_store_path, dim=4)
    try:
        uri = mint_uri("Concept", "gateway")
        store.index_text(uri, "alpha content")
        store.index_text(uri, "beta content")  # overwrite

        assert store.search_text("alpha", k=5) == []
        results = store.search_text("beta", k=5)
        assert [u for u, _ in results] == [uri]
    finally:
        store.close()


# --- persistence across connections -----------------------------------------


def test_data_persists_across_store_reopen(tmp_store_path):
    uri = mint_uri("CalibNode", "persisted")
    store1 = VectorStore(db_path=tmp_store_path, dim=4)
    store1.upsert_vector(uri, [1.0, 0.0, 0.0, 0.0])
    store1.index_text(uri, "durable row")
    store1.close()

    store2 = VectorStore(db_path=tmp_store_path, dim=4)
    try:
        assert dict(store2.search_vectors([1.0, 0.0, 0.0, 0.0], k=5))[uri] > 0.99
        assert [u for u, _ in store2.search_text("durable", k=5)] == [uri]
    finally:
        store2.close()


# --- context manager ---------------------------------------------------------


def test_context_manager_closes_connection(tmp_store_path):
    with VectorStore(db_path=tmp_store_path, dim=4) as store:
        store.upsert_vector(mint_uri("X", "1"), [1.0, 0.0, 0.0, 0.0])
    # Connection is closed; a further call must fail rather than silently
    # succeed against a live handle.
    with pytest.raises(Exception):
        store.search_vectors([1.0, 0.0, 0.0, 0.0], k=1)


# --- recall parity vs. Kùzu (B279 calibration fixture) -----------------------
#
# This reuses the exact fixture from tests/test_vector_calibration.py so a
# reviewer can diff the two test bodies directly. If KuzuClient is not
# importable in this environment the parity test is skipped (with a clear
# reason), never silently passed.

try:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

    KUZU_AVAILABLE = True
except Exception:
    KUZU_AVAILABLE = False


@pytest.mark.skipif(not KUZU_AVAILABLE, reason="kuzu not importable in this environment")
def test_recall_parity_vs_kuzu_vector_index(tmp_store_path):
    """Same four vectors, same query, both engines -- scores must match
    within the B279 calibration epsilon (0.01-0.02, per
    tests/test_vector_calibration.py)."""
    tmp_kuzu = tempfile.mkdtemp(prefix="kuzu_parity_")
    try:
        kdb = KuzuClient(f"{tmp_kuzu}/db")
        kdb.execute(
            "CREATE NODE TABLE CalibNode(id STRING, embedding FLOAT[4], PRIMARY KEY (id))"
        )
        vectors = {
            "identical": [1.0, 0.0, 0.0, 0.0],
            "deg45": [math.sqrt(0.5), math.sqrt(0.5), 0.0, 0.0],
            "orthogonal": [0.0, 1.0, 0.0, 0.0],
            "opposite": [-1.0, 0.0, 0.0, 0.0],
        }
        for node_id, vec in vectors.items():
            kdb.execute(
                "CREATE (n:CalibNode {id: $id, embedding: $vec})",
                {"id": node_id, "vec": vec},
            )
        kdb.create_vector_index("CalibNode", "embedding", "calib_idx")
        kuzu_rows = kdb.vector_search("CalibNode", "calib_idx", [1.0, 0.0, 0.0, 0.0], 4)
        kuzu_scores = {row["node"]["id"]: row["score"] for row in kuzu_rows}
        kdb.close()

        store = VectorStore(db_path=tmp_store_path, dim=4)
        try:
            for node_id, vec in vectors.items():
                store.upsert_vector(mint_uri("CalibNode", node_id), vec)
            store_rows = store.search_vectors([1.0, 0.0, 0.0, 0.0], k=4)
            store_scores = {
                uri.rsplit("/", 1)[-1]: score for uri, score in store_rows
            }
        finally:
            store.close()

        assert set(kuzu_scores) == set(store_scores)
        max_delta = 0.0
        for node_id in kuzu_scores:
            delta = abs(kuzu_scores[node_id] - store_scores[node_id])
            max_delta = max(max_delta, delta)
            # B279 calibration epsilon for this fixture is 0.01-0.02.
            assert delta < 0.02, (
                f"{node_id}: kuzu={kuzu_scores[node_id]!r} "
                f"sqlite-vec={store_scores[node_id]!r} delta={delta!r}"
            )
        # Surface the actual measured delta for the PR record even on pass.
        print(f"\nrecall parity max |delta| across 4 fixture vectors: {max_delta:.6f}")
    finally:
        shutil.rmtree(tmp_kuzu, ignore_errors=True)
