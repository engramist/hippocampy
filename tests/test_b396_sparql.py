"""Automated SPARQL conformance test for B396 (core_tail) queries.

Validates that all NamedQuery objects in backup.py, continuity.py, ingest.py,
pathways.py, basal_ganglia.py, task_graph.py, orchestrator.py, lessons.py,
and temporal_lobe.py carry syntactically valid SPARQL 1.1 / RDF-star
representations executable against a real in-memory pyoxigraph Store.
"""

from __future__ import annotations

import pyoxigraph as ox
import pytest

from campy.brain.hippocampus.graph.queries.backup import BACKUP_QUERIES
from campy.brain.hippocampus.graph.queries.continuity import CONTINUITY_QUERIES
from campy.brain.hippocampus.graph.queries.ingest import INGEST_QUERIES
from campy.brain.hippocampus.graph.queries.pathways import PATHWAY_QUERIES
from campy.brain.hippocampus.graph.queries.basal_ganglia import BASAL_GANGLIA_QUERIES
from campy.brain.hippocampus.graph.queries.task_graph import TASK_GRAPH_QUERIES
from campy.brain.hippocampus.graph.queries.orchestrator import ORCHESTRATOR_QUERIES
from campy.brain.hippocampus.graph.queries.lessons import LESSONS_QUERIES
from campy.brain.hippocampus.graph.queries.temporal_lobe import TEMPORAL_LOBE_QUERIES


@pytest.fixture
def store():
    return ox.Store()


def test_b396_query_counts():
    assert len(BACKUP_QUERIES) == 1
    assert len(CONTINUITY_QUERIES) == 7
    assert len(INGEST_QUERIES) == 11
    assert len(PATHWAY_QUERIES) == 12
    assert len(BASAL_GANGLIA_QUERIES) == 17
    assert len(TASK_GRAPH_QUERIES) == 30
    assert len(ORCHESTRATOR_QUERIES) == 55
    assert len(LESSONS_QUERIES) == 27
    # B375 gap 4: Lesson/Procedure joined the "warmable" table set so Step
    # 4b can pre-activate matched Lessons/Procedures in the warm frontier —
    # this grows the per-table warm_link/warm_get/warm_neighbor generator
    # loops from 7 to 9 tables (612 -> 1000).
    assert len(TEMPORAL_LOBE_QUERIES) == 1000
    total = (
        len(BACKUP_QUERIES)
        + len(CONTINUITY_QUERIES)
        + len(INGEST_QUERIES)
        + len(PATHWAY_QUERIES)
        + len(BASAL_GANGLIA_QUERIES)
        + len(TASK_GRAPH_QUERIES)
        + len(ORCHESTRATOR_QUERIES)
        + len(LESSONS_QUERIES)
        + len(TEMPORAL_LOBE_QUERIES)
    )
    assert total == 1160


@pytest.mark.parametrize("query", BACKUP_QUERIES, ids=lambda q: q.name)
def test_backup_queries_sparql(store, query):
    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", CONTINUITY_QUERIES, ids=lambda q: q.name)
def test_continuity_queries_sparql(store, query):
    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", INGEST_QUERIES, ids=lambda q: q.name)
def test_ingest_queries_sparql(store, query):
    if query.name == "ingest.link_concept_dataset":
        # Spec §4.2b: occurrence class write mints a fresh ULID identity,
        # which cannot be expressed in static SPARQL text. Handled via OxigraphClient.write_edge.
        assert query.sparql is None
        return

    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", PATHWAY_QUERIES, ids=lambda q: q.name)
def test_pathway_queries_sparql(store, query):
    if query.name == "pathways.unwind_co_occurs_with":
        # B451: CO_OCCURS_WITH is a star edge; a static SPARQL INSERT mints a
        # fresh blank-node reifier per solution (exponential growth). Handled
        # via OxigraphClient.upsert_co_occurrence / gateway.py Python handler,
        # sparql=None (tests/test_b451_co_occurs_reifier_explosion.py).
        assert query.sparql is None
        return

    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", BASAL_GANGLIA_QUERIES, ids=lambda q: q.name)
def test_basal_ganglia_queries_sparql(store, query):
    if query.name.startswith("basal_ganglia.frustration_get_"):
        # B433: campy:embedding is never asserted as an RDF triple
        # (FLOAT[384] lives in vector_store only), so a static OPTIONAL
        # match for it can never bind. Handled via gateway.py's
        # basal_ganglia.frustration_get_* Python handler, sparql=None.
        assert query.sparql is None
        return

    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", TASK_GRAPH_QUERIES, ids=lambda q: q.name)
def test_task_graph_queries_sparql(store, query):
    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", ORCHESTRATOR_QUERIES, ids=lambda q: q.name)
def test_orchestrator_queries_sparql(store, query):
    if query.name.startswith("orchestrator.merge_semantic_rel_"):
        # B451: star-edge writes; a static SPARQL INSERT mints a reifier per
        # solution. Handled via OxigraphClient.upsert_semantic_relation.
        assert query.sparql is None
        return

    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


@pytest.mark.parametrize("query", LESSONS_QUERIES, ids=lambda q: q.name)
def test_lessons_queries_sparql(store, query):
    assert query.sparql is not None, f"{query.name} must have a sparql representation"
    if query.mutating:
        store.update(query.sparql)
    else:
        store.query(query.sparql)


def test_temporal_lobe_queries_sparql(store):
    for query in TEMPORAL_LOBE_QUERIES:
        if query.name.startswith("temporal_lobe.warm_link_"):
            # Spec §4.2b: occurrence class write mints a fresh ULID identity,
            # which cannot be expressed in static SPARQL text. Handled via OxigraphClient.write_edge.
            assert query.sparql is None
            continue

        assert query.sparql is not None, f"{query.name} must have a sparql representation"
        if query.mutating:
            store.update(query.sparql)
        else:
            store.query(query.sparql)
