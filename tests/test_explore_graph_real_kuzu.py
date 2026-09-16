"""
tests/test_explore_graph_real_kuzu.py — Real-database regression tests for B280/B432.

`_build_frontier_query` used to build one MATCH branch PER NODE TABLE (12
of them) and UNION ALL them together. Kuzu 0.11.3's binder rejects that
once enough differently-typed node tables are unioned together in one
query - "Binder exception: a has data type NODE but NODE was expected" -
confirmed against the real production schema (12 node tables, 92
relationship types) (B280). `tests/test_explore_graph.py`'s MockDB
pattern-matches on query substrings and never validates real Cypher/SPARQL,
so it cannot catch defects like this - the mock and the broken
implementation produce identical output.

B427/B432 (2026-09-16): migrated off KuzuClient onto the shipped
OxigraphClient. Doing so surfaced a second, independent, more severe bug
(B432): `explore_graph` was structurally broken against Oxigraph entirely
- the start-node lookup returned bare URI strings instead of hydrated node
properties (crashing `_node_payload()`, silently swallowed), and frontier
expansion bypassed the gateway with Kùzu-only Cypher builtins
(`INTERNAL_ID`, `id()`, `label()`) that have no SPARQL translation. Every
real `explore_graph` call reported "start node not found" in production
until both were fixed (`OxigraphClient.get_node()` / `.expand_frontier()`,
`gateway.py`'s `explore.start_node_*` handler). These tests now validate
that fix against the real shipped engine, with full production schema
(`init_schema`) — the only way to reproduce either class of bug.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.vector_store import mint_uri
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.tools.explore_graph import explore_graph

_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_SEED_EXAMPLES_PATH = "campy/data/GistSeedExamples.md"


@pytest.fixture(scope="module")
def real_db():
    """Full production schema (12 node tables, 92 rel types) - the exact
    complexity needed to reproduce the cross-table UNION ALL binder bug.
    Module-scoped because init_schema() is expensive (embedding model load
    + HNSW index creation, ~10s); tests use disjoint node-id prefixes so
    they can safely share one instance.
    """
    tmp = tempfile.mkdtemp(prefix="explore_graph_real_")
    db = OxigraphClient(f"{tmp}/db")
    init_schema(db, _SEED_EXAMPLES_PATH, _EMBEDDING_MODEL)
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _concept(db, cid, text="node", confidence=0.9):
    db.write_node("Concept", {"concept_id": cid, "text_raw": text, "confidence": confidence})


def _edge(db, rel, a, b):
    db.write_edge(rel, mint_uri("Concept", a), mint_uri("Concept", b), {"confidence": 0.9})


class TestMultiHopTraversal:
    """The exact scenario the B280 audit reproduced: a 6-node chain graph
    (n0->n1->n2->n3->n4, n1->n5) via REQUIRES edges. Before the fix, this
    returned total_nodes_visited=1 and paths=[] - the bug visited only the
    start node, at any depth, for any graph, in production.
    """

    def _build_chain(self, db, prefix):
        ids = [f"{prefix}{i}" for i in range(6)]
        for cid in ids:
            _concept(db, cid, text=f"node {cid}")
        edges = [(0, 1), (1, 2), (2, 3), (3, 4), (1, 5)]
        for a, b in edges:
            _edge(db, "REQUIRES", ids[a], ids[b])
        return ids

    async def test_visits_all_reachable_nodes_within_depth(self, real_db):
        db = real_db
        ids = self._build_chain(db, "mh1_")

        result = await explore_graph(
            {"start_node_id": ids[0], "session_id": "t", "depth": 3, "edge_types": ["REQUIRES"]},
            db, {},
        )

        assert result["exploration_complete"] is True
        # n1, n2, n3, n5 are within 3 hops of n0; n4 is 4 hops away and
        # must NOT be visited (depth cap).
        assert result["total_nodes_visited"] == 5
        assert result["paths"]
        visited_ids = {n["node_id"] for p in result["paths"] for n in p["nodes"]}
        assert visited_ids == {ids[0], ids[1], ids[2], ids[3], ids[5]}
        assert ids[4] not in visited_ids

    async def test_depth_one_visits_only_direct_neighbor(self, real_db):
        db = real_db
        ids = self._build_chain(db, "mh2_")

        result = await explore_graph(
            {"start_node_id": ids[0], "session_id": "t", "depth": 1, "edge_types": ["REQUIRES"]},
            db, {},
        )

        assert result["total_nodes_visited"] == 2
        visited_ids = {n["node_id"] for p in result["paths"] for n in p["nodes"]}
        assert visited_ids == {ids[0], ids[1]}

    async def test_edge_metadata_is_correct(self, real_db):
        db = real_db
        ids = self._build_chain(db, "mh3_")

        result = await explore_graph(
            {"start_node_id": ids[0], "session_id": "t", "depth": 1, "edge_types": ["REQUIRES"]},
            db, {},
        )

        path = next(p for p in result["paths"] if p["path_depth"] == 1)
        edge = path["edges"][0]
        assert edge["from"] == ids[0]
        assert edge["to"] == ids[1]
        assert edge["type"] == "REQUIRES"

    async def test_uses_default_edge_types_without_explicit_filter(self, real_db):
        """Regression guard: the full 92-rel-type OR-pattern (no edge_types
        param) must also bind correctly, not just a single-type pattern."""
        db = real_db
        ids = self._build_chain(db, "mh4_")

        result = await explore_graph(
            {"start_node_id": ids[0], "session_id": "t", "depth": 3},
            db, {},
        )

        assert result["total_nodes_visited"] == 5


class TestCyclePrevention:
    async def test_cycle_does_not_infinite_loop_or_duplicate_visits(self, real_db):
        db = real_db
        for cid in ("cyc_a", "cyc_b", "cyc_c"):
            _concept(db, cid)
        _edge(db, "REQUIRES", "cyc_a", "cyc_b")
        _edge(db, "REQUIRES", "cyc_b", "cyc_c")
        _edge(db, "REQUIRES", "cyc_c", "cyc_a")

        result = await explore_graph(
            {"start_node_id": "cyc_a", "session_id": "t", "depth": 5, "edge_types": ["REQUIRES"]},
            db, {},
        )

        assert result["exploration_complete"] is True
        assert result["total_nodes_visited"] == 3
        visited_ids = {n["node_id"] for p in result["paths"] for n in p["nodes"]}
        assert visited_ids == {"cyc_a", "cyc_b", "cyc_c"}


class TestDirectionFiltering:
    async def test_outgoing_direction_does_not_follow_incoming_edges(self, real_db):
        db = real_db
        _concept(db, "dir1_a")
        _concept(db, "dir1_b")
        _edge(db, "REQUIRES", "dir1_b", "dir1_a")  # b -> a, not a -> b

        result = await explore_graph(
            {
                "start_node_id": "dir1_a", "session_id": "t", "depth": 2,
                "edge_types": ["REQUIRES"], "direction": "outgoing",
            },
            db, {},
        )

        assert result["total_nodes_visited"] == 1

    async def test_incoming_direction_follows_incoming_edges(self, real_db):
        db = real_db
        _concept(db, "dir2_a")
        _concept(db, "dir2_b")
        _edge(db, "REQUIRES", "dir2_b", "dir2_a")  # b -> a

        result = await explore_graph(
            {
                "start_node_id": "dir2_a", "session_id": "t", "depth": 2,
                "edge_types": ["REQUIRES"], "direction": "incoming",
            },
            db, {},
        )

        assert result["total_nodes_visited"] == 2
        visited_ids = {n["node_id"] for p in result["paths"] for n in p["nodes"]}
        assert "dir2_b" in visited_ids


class TestQueryBudget:
    async def test_depth_three_stays_within_query_budget(self, real_db):
        """AC: a single explore_graph call at depth 3 issues a bounded
        number of store-traversal calls. Oxigraph has no Cypher-string
        `db.execute()` call to count (unlike the retired Kùzu path) — the
        real per-hop cost unit on this engine is
        `OxigraphClient.expand_frontier()` (one call per direction per
        depth level, same call-count shape the old Kùzu-Cypher-per-call
        budget was protecting against), so that's what's counted here."""
        db = real_db
        ids = [f"qb_{i}" for i in range(6)]
        for cid in ids:
            _concept(db, cid)
        for a, b in [(0, 1), (1, 2), (2, 3), (3, 4), (1, 5)]:
            _edge(db, "REQUIRES", ids[a], ids[b])

        call_count = 0
        real_expand_frontier = db.expand_frontier

        def counting_expand_frontier(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return real_expand_frontier(*args, **kwargs)

        db.expand_frontier = counting_expand_frontier
        try:
            result = await explore_graph(
                {"start_node_id": ids[0], "session_id": "t", "depth": 3, "edge_types": ["REQUIRES"]},
                db, {},
            )
        finally:
            del db.expand_frontier

        assert result["exploration_complete"] is True
        assert call_count <= 30, f"explore_graph issued {call_count} expand_frontier calls"
