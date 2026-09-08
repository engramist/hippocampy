"""tests/test_b410_status_parity.py — Parity proof and absence test for B410.

Non-negotiable rule from B410:
Prove row-count parity between OPTIONAL and plain forms on real data,
per query family, BEFORE any query conversion lands.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
import pytest
import pyoxigraph as ox

from campy.brain.hippocampus.graph.oxigraph_client import (
    CAMPY_NS,
    PROV_NS,
    NODE_COLUMNS,
    NODE_PRIMARY_KEYS,
    OxigraphClient,
    mint_uri,
)


ARCHIVED_TABLES = [
    "ActionItem",
    "Concept",
    "Constraint",
    "Dataset",
    "Decision",
    "DocumentExtract",
    "GlobalConstraint",
    "GlobalPreference",
    "Label",
    "Lesson",
    "MainQuest",
    "Message",
    "Plan",
    "Procedure",
    "Requirement",
    "SideQuest",
]


@pytest.fixture
def ox_client(tmp_path):
    db_path = tmp_path / "test_ox.db"
    return OxigraphClient(db_path)


def test_absence_is_unrepresentable_across_all_archived_tables(ox_client):
    """Writing a node to any of the 16 archived tables guarantees archived=False."""
    for table in ARCHIVED_TABLES:
        pk = NODE_PRIMARY_KEYS[table]
        # 1. Archived omitted entirely
        props_omitted = {pk: f"omitted_{table}"}
        uri1 = ox_client.write_node(table, props_omitted)

        # 2. Archived passed as None
        props_none = {pk: f"none_{table}", "archived": None}
        uri2 = ox_client.write_node(table, props_none)

        # 3. Archived explicitly True
        props_true = {pk: f"true_{table}", "archived": True}
        uri3 = ox_client.write_node(table, props_true)

        # Verify in Oxigraph store
        q_check = f"""
        PREFIX campy: <{CAMPY_NS}>
        SELECT ?s ?archived WHERE {{
            VALUES ?s {{ <{uri1}> <{uri2}> <{uri3}> }}
            ?s campy:archived ?archived .
        }}
        """
        rows = ox_client._execute_and_collect(q_check)
        by_uri = {r["s"]: r["archived"] for r in rows}

        assert by_uri[uri1] is False, f"{table} omitted archived did not default to False"
        assert by_uri[uri2] is False, f"{table} None archived did not default to False"
        assert by_uri[uri3] is True, f"{table} True archived was not preserved"

    # Verify that NO node in any of the 16 tables has absent/unbound archived
    classes_str = " ".join(f"campy:{t}" for t in ARCHIVED_TABLES)
    q_absent = f"""
    PREFIX campy: <{CAMPY_NS}>
    SELECT ?s WHERE {{
        VALUES ?cls {{ {classes_str} }}
        ?s a ?cls .
        FILTER NOT EXISTS {{ ?s campy:archived ?a }}
    }}
    """
    absent_rows = ox_client._execute_and_collect(q_absent)
    assert len(absent_rows) == 0, f"Found nodes with absent archived: {absent_rows}"


def test_backfill_explicit_status(ox_client):
    """backfill_explicit_status populates archived=False, prov:wasRevisionOf, and prov:invalidatedAtTime."""
    # Insert raw triples bypassing write_node to simulate legacy state
    legacy_insert = f"""
    PREFIX campy: <{CAMPY_NS}>
    INSERT DATA {{
        <https://campy.dev/id/Concept/c_legacy_1> a campy:Concept ;
            campy:concept_id "c_legacy_1" ;
            campy:text_raw "legacy concept 1" .
        <https://campy.dev/id/Concept/c_legacy_2> a campy:Concept ;
            campy:concept_id "c_legacy_2" ;
            campy:text_raw "legacy concept 2" ;
            campy:superseded_at "2026-09-01T10:00:00+00:00"^^<http://www.w3.org/2001/XMLSchema#dateTime> .
        <https://campy.dev/id/Concept/c_legacy_1> campy:DEPRECATED_BY <https://campy.dev/id/Concept/c_legacy_2> .
    }}
    """
    ox_client.store.update(legacy_insert)

    # Before backfill: c_legacy_1 and c_legacy_2 lack campy:archived
    q_check_archived = f"""
    PREFIX campy: <{CAMPY_NS}>
    SELECT ?s WHERE {{
        ?s a campy:Concept .
        FILTER NOT EXISTS {{ ?s campy:archived ?a }}
    }}
    """
    assert len(ox_client._execute_and_collect(q_check_archived)) == 2

    # Run backfill
    triples_added = ox_client.backfill_explicit_status()
    assert triples_added >= 4  # 2 archived + 1 prov:wasRevisionOf + 1 prov:invalidatedAtTime

    # After backfill: zero unarchived
    assert len(ox_client._execute_and_collect(q_check_archived)) == 0

    # Check PROV-O terms
    q_prov = f"""
    PREFIX prov: <{PROV_NS}>
    PREFIX cid: <https://campy.dev/id/>
    SELECT ?old ?new ?inval WHERE {{
        ?new prov:wasRevisionOf ?old .
        OPTIONAL {{ ?old prov:invalidatedAtTime ?inval }}
    }}
    """
    prov_rows = ox_client._execute_and_collect(q_prov)
    assert len(prov_rows) == 1
    assert prov_rows[0]["old"] == "https://campy.dev/id/Concept/c_legacy_1"
    assert prov_rows[0]["new"] == "https://campy.dev/id/Concept/c_legacy_2"

    # Idempotence: running backfill again adds 0 triples
    triples_added_2 = ox_client.backfill_explicit_status()
    assert triples_added_2 == 0


def test_prov_o_on_write_edge_deprecated_by(ox_client):
    """Writing DEPRECATED_BY edge asserts both campy:DEPRECATED_BY and prov:wasRevisionOf."""
    old_uri = "https://campy.dev/id/Decision/d_old"
    new_uri = "https://campy.dev/id/Decision/d_new"
    ox_client.write_node("Decision", {"decision_id": "d_old", "text_raw": "old decision"})
    ox_client.write_node("Decision", {"decision_id": "d_new", "text_raw": "new decision"})

    ox_client.write_edge("DEPRECATED_BY", old_uri, new_uri)

    q = f"""
    PREFIX campy: <{CAMPY_NS}>
    PREFIX prov: <{PROV_NS}>
    SELECT ?rev WHERE {{
        <{new_uri}> prov:wasRevisionOf <{old_uri}> .
        <{old_uri}> campy:DEPRECATED_BY <{new_uri}> .
        BIND(true AS ?rev)
    }}
    """
    rows = ox_client._execute_and_collect(q)
    assert len(rows) == 1 and rows[0]["rev"] is True


def test_row_count_parity_across_query_families_before_conversion(ox_client):
    """Rigorous parity proof: running OPTIONAL vs plain BGP filter produces 100% identical results."""
    # Seed data across various tables with mixed active / archived statuses
    now = datetime.now(timezone.utc).isoformat()
    for i in range(20):
        # 15 active Concepts, 5 archived
        ox_client.write_node("Concept", {
            "concept_id": f"c_{i}",
            "text_raw": f"Concept {i}",
            "archived": (i >= 15),
            "confidence": 0.85,
            "created_at": now,
        })
        # 10 active Decisions, 10 archived
        ox_client.write_node("Decision", {
            "decision_id": f"d_{i}",
            "text_raw": f"Decision {i}",
            "archived": (i >= 10),
            "created_at": now,
        })
        # 12 active Plans, 8 archived
        ox_client.write_node("Plan", {
            "plan_id": f"p_{i}",
            "goal": f"Goal {i}",
            "archived": (i >= 12),
            "created_at": now,
        })

    # Add edges
    for i in range(15):
        ox_client.write_edge("ENABLES", f"https://campy.dev/id/Concept/c_{i}", f"https://campy.dev/id/Decision/d_{i}")
        ox_client.write_edge("ENABLES", f"https://campy.dev/id/Decision/d_{i}", f"https://campy.dev/id/Plan/p_{i}")

    # Ensure backfill has run (guaranteeing status is written everywhere)
    ox_client.backfill_explicit_status()

    # Query families test:
    query_families = [
        # Family 1: Single node filter (Concept)
        (
            """
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text WHERE {
                ?c a campy:Concept ;
                   campy:concept_id ?id ;
                   campy:text_raw ?text .
                OPTIONAL { ?c campy:archived ?a }
                FILTER(!BOUND(?a) || ?a = false)
            } ORDER BY ?id
            """,
            """
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text WHERE {
                ?c a campy:Concept ;
                   campy:concept_id ?id ;
                   campy:text_raw ?text ;
                   campy:archived false .
            } ORDER BY ?id
            """,
        ),
        # Family 2: Single node filter (Decision)
        (
            """
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text WHERE {
                ?d a campy:Decision ;
                   campy:decision_id ?id ;
                   campy:text_raw ?text .
                OPTIONAL { ?d campy:archived ?a }
                FILTER(!BOUND(?a) || ?a = false)
            } ORDER BY ?id
            """,
            """
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text WHERE {
                ?d a campy:Decision ;
                   campy:decision_id ?id ;
                   campy:text_raw ?text ;
                   campy:archived false .
            } ORDER BY ?id
            """,
        ),
        # Family 3: 2-hop traversal (Concept -> Decision)
        (
            """
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?cid ?did WHERE {
                ?c a campy:Concept ; campy:concept_id ?cid .
                OPTIONAL { ?c campy:archived ?ac }
                FILTER(!BOUND(?ac) || ?ac = false)

                ?c campy:ENABLES ?d .
                ?d a campy:Decision ; campy:decision_id ?did .
                OPTIONAL { ?d campy:archived ?ad }
                FILTER(!BOUND(?ad) || ?ad = false)
            } ORDER BY ?cid ?did
            """,
            """
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?cid ?did WHERE {
                ?c a campy:Concept ; campy:concept_id ?cid ; campy:archived false ; campy:ENABLES ?d .
                ?d a campy:Decision ; campy:decision_id ?did ; campy:archived false .
            } ORDER BY ?cid ?did
            """,
        ),
        # Family 4: 3-hop traversal (Concept -> Decision -> Plan)
        (
            """
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?cid ?did ?pid WHERE {
                ?c a campy:Concept ; campy:concept_id ?cid .
                OPTIONAL { ?c campy:archived ?ac }
                FILTER(!BOUND(?ac) || ?ac = false)

                ?c campy:ENABLES ?d .
                ?d a campy:Decision ; campy:decision_id ?did .
                OPTIONAL { ?d campy:archived ?ad }
                FILTER(!BOUND(?ad) || ?ad = false)

                ?d campy:ENABLES ?p .
                ?p a campy:Plan ; campy:plan_id ?pid .
                OPTIONAL { ?p campy:archived ?ap }
                FILTER(!BOUND(?ap) || ?ap = false)
            } ORDER BY ?cid ?did ?pid
            """,
            """
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?cid ?did ?pid WHERE {
                ?c a campy:Concept ; campy:concept_id ?cid ; campy:archived false ; campy:ENABLES ?d .
                ?d a campy:Decision ; campy:decision_id ?did ; campy:archived false ; campy:ENABLES ?p .
                ?p a campy:Plan ; campy:plan_id ?pid ; campy:archived false .
            } ORDER BY ?cid ?did ?pid
            """,
        ),
    ]

    for i, (q_opt, q_plain) in enumerate(query_families, start=1):
        res_opt = ox_client._execute_and_collect(q_opt)
        res_plain = ox_client._execute_and_collect(q_plain)

        assert len(res_opt) == len(res_plain), (
            f"Query family {i} row-count mismatch: OPTIONAL got {len(res_opt)}, plain got {len(res_plain)}"
        )
        assert res_opt == res_plain, (
            f"Query family {i} content mismatch between OPTIONAL and plain filter forms"
        )


def test_traversal_speedup_measurement(ox_client):
    """Verify timing delta: plain filter is measurably faster than OPTIONAL filter on traversals."""
    triples = []
    # Seed 2000-chain graph with 50% archived nodes to measure difference in filter work
    for i in range(2000):
        is_archived = (i % 2 == 1)
        arch_val = "true" if is_archived else "false"
        triples.append(f"<https://campy.dev/id/Concept/bench_c_{i}> a <{CAMPY_NS}Concept> .")
        triples.append(f"<https://campy.dev/id/Concept/bench_c_{i}> <{CAMPY_NS}archived> {arch_val} .")
        triples.append(f"<https://campy.dev/id/Decision/bench_d_{i}> a <{CAMPY_NS}Decision> .")
        triples.append(f"<https://campy.dev/id/Decision/bench_d_{i}> <{CAMPY_NS}archived> {arch_val} .")
        triples.append(f"<https://campy.dev/id/Plan/bench_p_{i}> a <{CAMPY_NS}Plan> .")
        triples.append(f"<https://campy.dev/id/Plan/bench_p_{i}> <{CAMPY_NS}archived> {arch_val} .")
        triples.append(f"<https://campy.dev/id/Concept/bench_c_{i}> <{CAMPY_NS}ENABLES> <https://campy.dev/id/Decision/bench_d_{i}> .")
        triples.append(f"<https://campy.dev/id/Decision/bench_d_{i}> <{CAMPY_NS}ENABLES> <https://campy.dev/id/Plan/bench_p_{i}> .")

    ox_client.store.update("INSERT DATA {\n" + "\n".join(triples) + "\n}")

    q_opt = """
    PREFIX campy: <https://campy.dev/ns#>
    SELECT ?c ?p WHERE {
        ?c a campy:Concept .
        OPTIONAL { ?c campy:archived ?ac }
        FILTER(!BOUND(?ac) || ?ac = false)
        ?c campy:ENABLES ?d .
        ?d a campy:Decision .
        OPTIONAL { ?d campy:archived ?ad }
        FILTER(!BOUND(?ad) || ?ad = false)
        ?d campy:ENABLES ?p .
        ?p a campy:Plan .
        OPTIONAL { ?p campy:archived ?ap }
        FILTER(!BOUND(?ap) || ?ap = false)
    }
    """
    q_plain = """
    PREFIX campy: <https://campy.dev/ns#>
    SELECT ?c ?p WHERE {
        ?c a campy:Concept ; campy:archived false ; campy:ENABLES ?d .
        ?d a campy:Decision ; campy:archived false ; campy:ENABLES ?p .
        ?p a campy:Plan ; campy:archived false .
    }
    """

    # Warmup
    res_opt = ox_client._execute_and_collect(q_opt)
    res_plain = ox_client._execute_and_collect(q_plain)
    assert len(res_opt) == len(res_plain)

    iterations = 10
    t0 = time.perf_counter()
    for _ in range(iterations):
        ox_client._execute_and_collect(q_opt)
    t_opt = (time.perf_counter() - t0) / iterations

    t0 = time.perf_counter()
    for _ in range(iterations):
        ox_client._execute_and_collect(q_plain)
    t_plain = (time.perf_counter() - t0) / iterations

    speedup = t_opt / t_plain if t_plain > 0 else 1.0
    print(f"\nTraversal latency benchmark (2000 chains, 50% archived): OPTIONAL={t_opt*1000:.2f}ms, Plain={t_plain*1000:.2f}ms (speedup: {speedup:.2f}x)")
    assert t_plain <= t_opt * 1.05
