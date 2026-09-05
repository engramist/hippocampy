"""Tests for campy/brain/hippocampus/graph/oxigraph_client.py (B389).

No mocks: every test runs against a real `pyoxigraph.Store()` (in-memory or
a real temp file). docs/rdf-schema-mapping.md conformance tests live in
tests/test_rdf_mapping_spec.py; this file covers the client's own surface —
schema introspection, EDGE_REIFICATION dispatch/exhaustiveness, the async
execute_read/execute_write mirror of KuzuClient, and persistence to disk.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import (
    EDGE_REIFICATION,
    NODE_COLUMNS,
    NODE_PRIMARY_KEYS,
    REL_COLUMNS,
    UNCLASSIFIED_ESCALATED_TABLES,
    OxigraphClient,
    classify_edge,
    generate_ulid,
    mint_uri,
)
from campy.brain.hippocampus.schema import NODE_TABLES, get_relationship_types


# --- schema introspection ----------------------------------------------------


def test_node_columns_parsed_for_every_node_table():
    assert set(NODE_COLUMNS) == set(NODE_TABLES)
    # spot check a known table's known columns/types
    assert NODE_COLUMNS["Concept"]["concept_id"] == "STRING"
    assert NODE_COLUMNS["Concept"]["confidence"] == "DOUBLE"
    assert NODE_COLUMNS["Concept"]["embedding"] == "FLOAT[384]"


def test_node_primary_keys_parsed_for_every_node_table():
    assert set(NODE_PRIMARY_KEYS) == set(NODE_TABLES)
    assert NODE_PRIMARY_KEYS["Concept"] == "concept_id"
    assert NODE_PRIMARY_KEYS["Session"] == "session_id"


def test_rel_columns_parsed_matches_first_ddl_for_duplicate_name():
    # CONTRADICTS has two colliding CREATE REL TABLE statements in
    # schema.py (a real schema bug, see EDGE_REIFICATION's comment) — the
    # parser must keep the FIRST one, matching Kùzu's own IF NOT EXISTS
    # behavior (the second CREATE is a silent no-op against a live table).
    assert set(REL_COLUMNS["CONTRADICTS"]) == {"confidence", "inferred_by", "inferred_at"}


# --- classify_edge / EDGE_REIFICATION exhaustiveness -------------------------


def test_classify_edge_returns_declared_class_for_known_tables():
    assert classify_edge("BELONGS_TO") == "plain"
    assert classify_edge("ENABLES") == "star"
    assert classify_edge("LOADED") == "occurrence"


def test_classify_edge_raises_for_escalated_table_with_reason_in_message():
    with pytest.raises(ValueError) as excinfo:
        classify_edge("OUTCOME_SIGNAL")
    assert "deliberately unclassified" in str(excinfo.value)
    assert "MERGE" in str(excinfo.value)


def test_classify_edge_raises_for_totally_unknown_table():
    with pytest.raises(ValueError, match="no EDGE_REIFICATION entry"):
        classify_edge("NOT_A_REAL_TABLE")


def test_edge_reification_and_escalated_tables_are_disjoint_and_exhaustive():
    live = set(get_relationship_types())
    classified = set(EDGE_REIFICATION)
    escalated = set(UNCLASSIFIED_ESCALATED_TABLES)
    assert classified.isdisjoint(escalated)
    assert classified | escalated == live


def test_edge_reification_counts():
    # Recorded here so a future schema.py change that silently shifts a
    # table's property-bearing-ness gets caught by a failing count, not by
    # nobody noticing.
    from collections import Counter
    counts = Counter(EDGE_REIFICATION.values())
    assert counts["plain"] == 52
    assert counts["star"] == 25
    assert counts["occurrence"] == 15
    assert len(UNCLASSIFIED_ESCALATED_TABLES) == 18


# --- ULID minting -------------------------------------------------------------


def test_generate_ulid_is_26_chars_crockford_base32():
    ulid = generate_ulid()
    assert len(ulid) == 26
    assert set(ulid) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_generate_ulid_is_lexicographically_time_sortable():
    import time
    a = generate_ulid()
    time.sleep(0.002)
    b = generate_ulid()
    assert a < b


def test_generate_ulid_is_unique_across_many_calls():
    ulids = {generate_ulid() for _ in range(200)}
    assert len(ulids) == 200


# --- write_node validation ----------------------------------------------------


def test_write_node_rejects_unknown_table():
    client = OxigraphClient()
    try:
        with pytest.raises(ValueError, match="unknown node table"):
            client.write_node("NotARealTable", {"id": "x"})
    finally:
        client.close()


def test_write_node_rejects_unknown_column():
    client = OxigraphClient()
    try:
        with pytest.raises(ValueError, match="not a declared column"):
            client.write_node("Concept", {"concept_id": "c1", "bogus_column": 1})
    finally:
        client.close()


def test_write_node_rejects_missing_primary_key():
    client = OxigraphClient()
    try:
        with pytest.raises(ValueError, match="primary key"):
            client.write_node("Concept", {"text_raw": "no id given"})
    finally:
        client.close()


def test_write_node_uses_mint_uri_from_vector_store():
    client = OxigraphClient()
    try:
        uri = client.write_node("Concept", {"concept_id": "c_01H8XK"})
        assert uri == mint_uri("Concept", "c_01H8XK")
    finally:
        client.close()


# --- persistence to disk ------------------------------------------------------


def test_store_persists_to_disk_across_client_instances():
    tmp_dir = tempfile.mkdtemp(prefix="oxigraph_test_")
    try:
        db_path = Path(tmp_dir) / "store"
        c1 = OxigraphClient(db_path=db_path)
        uri = c1.write_node("Concept", {"concept_id": "c1", "text_raw": "persisted"})
        c1.close()

        c2 = OxigraphClient(db_path=db_path)
        rows = list(c2.store.query(
            f'PREFIX campy: <https://campy.dev/ns#> '
            f'SELECT ?o WHERE {{ <{uri}> campy:text_raw ?o }}'
        ))
        assert [str(r["o"]) for r in rows] == ['"persisted"']
        c2.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- async execute_read / execute_write mirror KuzuClient's surface ---------


def test_execute_write_runs_sparql_update_under_the_lock():
    client = OxigraphClient()
    try:
        async def _run():
            await client.execute_write(
                "INSERT DATA { <http://a> <http://b> \"c\" }"
            )
        asyncio.run(_run())
        rows = list(client.store.query("SELECT ?o WHERE { <http://a> <http://b> ?o }"))
        assert [str(r["o"]) for r in rows] == ['"c"']
    finally:
        client.close()


def test_execute_read_returns_list_of_dicts():
    client = OxigraphClient()
    try:
        client.store.update("INSERT DATA { <http://a> <http://b> \"c\" }")

        async def _run():
            return await client.execute_read("SELECT ?o WHERE { <http://a> <http://b> ?o }")

        rows = asyncio.run(_run())
        assert rows == [{"o": rows[0]["o"]}]
        assert str(rows[0]["o"]) == '"c"'
    finally:
        client.close()


def test_execute_rejects_params_for_update_text():
    client = OxigraphClient()
    try:
        with pytest.raises(ValueError, match="does not support parameter substitution"):
            client.execute("INSERT DATA { <http://a> <http://b> \"c\" }", {"x": 1})
    finally:
        client.close()


def test_execute_read_binds_params_via_substitutions_not_string_interpolation():
    client = OxigraphClient()
    try:
        client.store.update(
            'PREFIX campy: <https://campy.dev/ns#> '
            'INSERT DATA { <https://campy.dev/id/Concept/c1> campy:name "widget" }'
        )

        async def _run():
            return await client.execute_read(
                "PREFIX campy: <https://campy.dev/ns#> "
                "SELECT ?name WHERE { ?s campy:name ?name }",
                {"s": "https://campy.dev/id/Concept/c1"},
            )

        rows = asyncio.run(_run())
        assert len(rows) == 1
        assert str(rows[0]["name"]) == '"widget"'
    finally:
        client.close()
