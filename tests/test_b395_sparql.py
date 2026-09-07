"""Automated SPARQL conformance test for B395 (web_cli) queries.

Validates that all NamedQuery objects in web.py, cli.py, explore.py, and capability.py
carry syntactically valid SPARQL 1.1 / RDF-star representations executable against
a real in-memory pyoxigraph Store.
"""

from __future__ import annotations

import pyoxigraph as ox
import pytest

from campy.brain.hippocampus.graph.queries.web import WEB_QUERIES
from campy.brain.hippocampus.graph.queries.cli import CLI_QUERIES
from campy.brain.hippocampus.graph.queries.explore import EXPLORE_QUERIES
from campy.brain.hippocampus.graph.queries.capability import CAPABILITY_QUERIES


@pytest.fixture
def store():
    return ox.Store()


def test_b395_query_counts():
    assert len(WEB_QUERIES) == 75
    assert len(CLI_QUERIES) == 16
    assert len(EXPLORE_QUERIES) == 12
    assert len(CAPABILITY_QUERIES) == 39
    total = len(WEB_QUERIES) + len(CLI_QUERIES) + len(EXPLORE_QUERIES) + len(CAPABILITY_QUERIES)
    assert total == 142


@pytest.mark.parametrize("query", EXPLORE_QUERIES, ids=lambda q: q.name)
def test_explore_queries_sparql(store, query):
    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    store.query(query.sparql)


@pytest.mark.parametrize("query", CLI_QUERIES, ids=lambda q: q.name)
def test_cli_queries_sparql(store, query):
    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", WEB_QUERIES, ids=lambda q: q.name)
def test_web_queries_sparql(store, query):
    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", CAPABILITY_QUERIES, ids=lambda q: q.name)
def test_capability_queries_sparql(store, query):
    if query.name == "capability.reuse_candidates":
        # Spec §5 / B395: vector cosine similarity on FactEntity.embedding (FLOAT[384])
        # is handled by sqlite-vec via Python handler, sparql=None.
        assert query.sparql is None
        return

    if query.name.startswith("capability.create_edge_"):
        # Spec §4.2b: occurrence class writes mint brand-new ULID identities on every call,
        # which cannot be expressed in static SPARQL text. Handled via OxigraphClient.write_edge.
        assert query.sparql is None
        return

    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)
