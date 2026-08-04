"""
tests/test_explore_graph_real_kuzu.py — Real-Kuzu regression tests for B280.

`_build_frontier_query` used to build one MATCH branch PER NODE TABLE (12
of them) and UNION ALL them together. Kuzu 0.11.3's binder rejects that
once enough differently-typed node tables are unioned together in one
query - "Binder exception: a has data type NODE but NODE was expected" -
confirmed against the real production schema (12 node tables, 92
relationship types). The exception was caught by a bare
`except Exception: _logger.exception(...)` and silently converted into an
empty result, so every real `explore_graph()` call reported
`exploration_complete: True` while visiting only the start node.

`tests/test_explore_graph.py`'s MockDB pattern-matches on query substrings
and never validates real Kuzu Cypher, so it could not catch this - the
mock and the broken implementation produced identical output. These tests
run the real Cypher against a real Kuzu database built with the full
production schema (`init_schema`), the only way to reproduce this class of
binder-level bug.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
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
    db = KuzuClient(f"{tmp}/db")
    init_schema(db, _SEED_EXAMPLES_PATH, _EMBEDDING_MODEL)
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _concept(db, cid, text="node", confidence=0.9):
    db.execute(
        "CREATE (n:Concept {concept_id: $id, text_raw: $t, confidence: $c})",
        {"id": cid, "t": text, "c": confidence},
    )


def _edge(db, rel, a, b):
    db.execute(
        f"MATCH (a:Concept {{concept_id: $a}}), (b:Concept {{concept_id: $b}}) "
        f"CREATE (a)-[:{rel} {{confidence: 0.9}}]->(b)",
        {"a": a, "b": b},
    )


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
        """AC: a single explore_graph call at depth 3 issues <=30 Cypher
        queries."""

        class CountingDB:
            def __init__(self, inner):
                self._inner = inner
                self.count = 0

            def execute(self, query, params=None):
                self.count += 1
                return self._inner.execute(query, params)

            def close(self):
                self._inner.close()

        db = real_db
        ids = [f"qb_{i}" for i in range(6)]
        for cid in ids:
            _concept(db, cid)
        for a, b in [(0, 1), (1, 2), (2, 3), (3, 4), (1, 5)]:
            _edge(db, "REQUIRES", ids[a], ids[b])

        counting_db = CountingDB(db)
        result = await explore_graph(
            {"start_node_id": ids[0], "session_id": "t", "depth": 3, "edge_types": ["REQUIRES"]},
            counting_db, {},
        )

        assert result["exploration_complete"] is True
        assert counting_db.count <= 30, f"explore_graph issued {counting_db.count} queries"
