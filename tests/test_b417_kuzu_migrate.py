"""tests/test_b417_kuzu_migrate.py — B417 item 3 proof.

The real Kùzu->Oxigraph data migrator. `tests.kuzu_test_client` is NOT used
here — this module reads a legacy Kùzu file the way an actual pre-cutover
`brain.db` looks: via the raw `kuzu` package directly, self-describing its
own schema (never assuming today's `schema.py` matches whatever schema the
backup was created under, since the backup may predate months of drift).

Every test constructs its OWN small, real `kuzu.Database` fixture — never
touches the developer's real backup file.
"""

from __future__ import annotations

import os
import tempfile

import pytest

kuzu = pytest.importorskip("kuzu", reason="B417 migrator needs the optional kuzu package to read a legacy DB")

from campy.brain.hippocampus.graph.kuzu_migrate import (
    KuzuNotAvailableError,
    discover_kuzu_schema,
    migrate_kuzu_to_oxigraph,
)
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient


@pytest.fixture
def kuzu_db_path(tmp_path):
    return str(tmp_path / "legacy.kuzu")


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "fresh_oxigraph.db")


def _kuzu_conn(path):
    db = kuzu.Database(path)
    return kuzu.Connection(db)


def test_discover_kuzu_schema_reads_real_tables_and_columns(kuzu_db_path):
    conn = _kuzu_conn(kuzu_db_path)
    conn.execute(
        "CREATE NODE TABLE Concept(concept_id STRING, text_raw STRING, "
        "confidence DOUBLE, PRIMARY KEY(concept_id))"
    )
    conn.execute("CREATE NODE TABLE Label(label_id STRING, text STRING, PRIMARY KEY(label_id))")
    conn.execute("CREATE REL TABLE HAS_PREF_LABEL(FROM Concept TO Label)")

    schema = discover_kuzu_schema(conn)

    assert "Concept" in schema.node_tables
    assert schema.node_tables["Concept"].pk == "concept_id"
    assert set(schema.node_tables["Concept"].columns) == {"concept_id", "text_raw", "confidence"}
    assert "HAS_PREF_LABEL" in schema.rel_tables
    assert schema.rel_tables["HAS_PREF_LABEL"].from_table == "Concept"
    assert schema.rel_tables["HAS_PREF_LABEL"].to_table == "Label"
    assert schema.rel_tables["HAS_PREF_LABEL"].from_pk == "concept_id"
    assert schema.rel_tables["HAS_PREF_LABEL"].to_pk == "label_id"


@pytest.mark.asyncio
async def test_migrates_a_normal_node_and_edge(kuzu_db_path, ox_client):
    conn = _kuzu_conn(kuzu_db_path)
    conn.execute(
        "CREATE NODE TABLE Concept(concept_id STRING, text_raw STRING, "
        "confidence DOUBLE, archived BOOLEAN, PRIMARY KEY(concept_id))"
    )
    conn.execute("CREATE NODE TABLE Label(label_id STRING, text STRING, PRIMARY KEY(label_id))")
    conn.execute("CREATE REL TABLE HAS_PREF_LABEL(FROM Concept TO Label)")
    conn.execute(
        "CREATE (c:Concept {concept_id: 'c1', text_raw: 'a real concept', "
        "confidence: 0.9, archived: false})"
    )
    conn.execute("CREATE (l:Label {label_id: 'l1', text: 'Canonical Name'})")
    conn.execute(
        "MATCH (c:Concept {concept_id:'c1'}), (l:Label {label_id:'l1'}) "
        "CREATE (c)-[:HAS_PREF_LABEL]->(l)"
    )
    conn.close()

    report = migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)

    assert report.nodes_migrated.get("Concept") == 1
    assert report.nodes_migrated.get("Label") == 1
    assert report.edges_migrated.get("HAS_PREF_LABEL") == 1

    subj = ox_client.find_subject_uri("Concept", "concept_id", "c1")
    assert subj == "https://campy.dev/id/Concept/c1"
    rows = list(ox_client.store.query(
        f'SELECT ?v WHERE {{ <{subj}> <https://campy.dev/ns#text_raw> ?v }}'
    ))
    assert rows and rows[0]["v"].value == "a real concept"


@pytest.mark.asyncio
async def test_migrates_embedding_and_indexes_it_for_vector_search(kuzu_db_path, ox_client):
    # sqlite-vec's vec0 table is fixed-width (DEFAULT_DIM=384) per the
    # ox_client fixture's real VectorStore — use a real 384-dim vector so
    # this exercises the actual production path, not a toy dimension.
    conn = _kuzu_conn(kuzu_db_path)
    conn.execute(
        "CREATE NODE TABLE Lesson(lesson_id STRING, text_raw STRING, "
        "embedding FLOAT[384], PRIMARY KEY(lesson_id))"
    )
    emb = [round(0.001 * i, 3) for i in range(384)]
    conn.execute(
        "CREATE (l:Lesson {lesson_id: 'les1', text_raw: 'a migrated lesson', embedding: $emb})",
        {"emb": emb},
    )
    conn.close()

    report = migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)
    assert report.nodes_migrated.get("Lesson") == 1

    subj = ox_client.find_subject_uri("Lesson", "lesson_id", "les1")
    stored = ox_client.vector_store.get_vector(subj) if ox_client.vector_store else None
    assert stored is not None
    assert [round(x, 3) for x in stored] == emb


@pytest.mark.asyncio
async def test_schema_drift_unknown_table_skipped_not_fatal(kuzu_db_path, ox_client):
    """A table that existed in the legacy file but no longer exists in
    today's schema.py (renamed/removed since the backup was taken) must be
    skipped with a report entry, not crash the whole migration."""
    conn = _kuzu_conn(kuzu_db_path)
    conn.execute("CREATE NODE TABLE Concept(concept_id STRING, PRIMARY KEY(concept_id))")
    conn.execute("CREATE (c:Concept {concept_id: 'c1'})")
    conn.execute("CREATE NODE TABLE ThisTableNoLongerExists(id STRING, PRIMARY KEY(id))")
    conn.execute("CREATE (n:ThisTableNoLongerExists {id: 'x1'})")
    conn.close()

    report = migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)

    assert report.nodes_migrated.get("Concept") == 1
    assert "ThisTableNoLongerExists" in report.node_tables_skipped_unknown
    assert ox_client.find_subject_uri("Concept", "concept_id", "c1") is not None


@pytest.mark.asyncio
async def test_schema_drift_unknown_column_dropped_not_fatal(kuzu_db_path, ox_client):
    """A column present in the legacy row but no longer declared in today's
    NODE_COLUMNS (renamed/removed) must be dropped with a report entry, and
    every OTHER column on that same row must still migrate."""
    conn = _kuzu_conn(kuzu_db_path)
    conn.execute(
        "CREATE NODE TABLE Concept(concept_id STRING, text_raw STRING, "
        "this_column_was_removed_long_ago STRING, PRIMARY KEY(concept_id))"
    )
    conn.execute(
        "CREATE (c:Concept {concept_id: 'c1', text_raw: 'still here', "
        "this_column_was_removed_long_ago: 'legacy junk'})"
    )
    conn.close()

    report = migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)

    assert report.nodes_migrated.get("Concept") == 1
    assert "this_column_was_removed_long_ago" in report.dropped_columns.get("Concept", set())
    subj = ox_client.find_subject_uri("Concept", "concept_id", "c1")
    rows = list(ox_client.store.query(
        f'SELECT ?v WHERE {{ <{subj}> <https://campy.dev/ns#text_raw> ?v }}'
    ))
    assert rows and rows[0]["v"].value == "still here"


@pytest.mark.asyncio
async def test_edge_skipped_if_endpoint_table_unknown(kuzu_db_path, ox_client):
    conn = _kuzu_conn(kuzu_db_path)
    conn.execute("CREATE NODE TABLE Concept(concept_id STRING, PRIMARY KEY(concept_id))")
    conn.execute("CREATE NODE TABLE GoneNow(id STRING, PRIMARY KEY(id))")
    conn.execute("CREATE REL TABLE SOME_OLD_REL(FROM Concept TO GoneNow)")
    conn.execute("CREATE (c:Concept {concept_id: 'c1'})")
    conn.execute("CREATE (g:GoneNow {id: 'g1'})")
    conn.execute(
        "MATCH (c:Concept {concept_id:'c1'}), (g:GoneNow {id:'g1'}) "
        "CREATE (c)-[:SOME_OLD_REL]->(g)"
    )
    conn.close()

    report = migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)

    assert report.nodes_migrated.get("Concept") == 1
    assert "GoneNow" in report.node_tables_skipped_unknown
    assert "SOME_OLD_REL" in report.edge_tables_skipped_unknown


@pytest.mark.asyncio
async def test_edge_migrates_even_when_endpoint_table_has_zero_rows_but_is_valid(kuzu_db_path, ox_client):
    """Regression: a node table can be perfectly valid in today's schema
    (NODE_COLUMNS/NODE_PRIMARY_KEYS both know it) yet have zero rows in THIS
    specific legacy backup — that must not cause every edge touching it to
    be wrongly reported as 'unknown table'. Uses two real, always-declared
    tables (Session has rows here; MainQuest has none) linked by a real
    schema edge (REROUTED_FROM, Session->MainQuest) so the endpoint-table
    validity check is exercised against the actual production schema, not a
    synthetic table."""
    conn = _kuzu_conn(kuzu_db_path)
    conn.execute("CREATE NODE TABLE Session(session_id STRING, PRIMARY KEY(session_id))")
    conn.execute("CREATE NODE TABLE MainQuest(quest_id STRING, PRIMARY KEY(quest_id))")
    conn.execute("CREATE REL TABLE REROUTED_FROM(FROM Session TO MainQuest, reason STRING)")
    conn.execute("CREATE (s:Session {session_id: 's1'})")
    # Deliberately zero MainQuest rows — this table is valid in NODE_COLUMNS
    # today but simply has no instances in this legacy backup.
    conn.close()

    report = migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)

    assert report.nodes_migrated.get("Session") == 1
    assert "MainQuest" not in report.node_tables_skipped_unknown, (
        "a table with zero legacy rows but valid today's schema must not be "
        "reported as unknown"
    )
    assert "REROUTED_FROM" not in report.edge_tables_skipped_unknown, (
        "an edge whose endpoint table is merely empty (not unknown) must "
        "still be attempted"
    )


@pytest.mark.asyncio
async def test_migration_is_idempotent_on_rerun(kuzu_db_path, ox_client):
    conn = _kuzu_conn(kuzu_db_path)
    conn.execute("CREATE NODE TABLE Concept(concept_id STRING, text_raw STRING, PRIMARY KEY(concept_id))")
    conn.execute("CREATE (c:Concept {concept_id: 'c1', text_raw: 'hello'})")
    conn.close()

    migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)
    migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)  # re-run must not duplicate/error

    subj = ox_client.find_subject_uri("Concept", "concept_id", "c1")
    rows = list(ox_client.store.query(
        f'SELECT ?v WHERE {{ <{subj}> <https://campy.dev/ns#text_raw> ?v }}'
    ))
    assert len(rows) == 1, "re-running the migration must not duplicate triples"


def test_missing_kuzu_package_raises_actionable_error(monkeypatch, kuzu_db_path, ox_client):
    import campy.brain.hippocampus.graph.kuzu_migrate as mod
    monkeypatch.setattr(mod, "_import_kuzu", lambda: (_ for _ in ()).throw(
        KuzuNotAvailableError("kuzu package not installed")
    ))
    with pytest.raises(KuzuNotAvailableError, match="kuzu"):
        migrate_kuzu_to_oxigraph(kuzu_db_path, ox_client)
