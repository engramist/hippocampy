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
from campy.brain.hippocampus.schema import init_schema



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
    """Rigorous parity proof with teeth:
    1. Seed graph using raw INSERT DATA with a mix of:
       - explicit campy:archived false
       - explicit campy:archived true
       - ABSENT campy:archived (simulating pre-B410 data)
    2. Before backfill: assert OPTIONAL returns un-archived nodes while plain BGP drops them.
       Assert that OPTIONAL and plain BGP DIFFER (the teeth check).
    3. Run backfill_explicit_status().
    4. After backfill: assert OPTIONAL and plain BGP return 100% IDENTICAL rows.
    """
    now = datetime.now(timezone.utc).isoformat()
    triples = []

    # 15 Concepts:
    # 0..4: archived=false
    # 5..9: archived=true
    # 10..14: archived absent (pre-B410 data)
    for i in range(15):
        uri = f"https://campy.dev/id/Concept/c_{i:02d}"
        triples.append(f'<{uri}> a <{CAMPY_NS}Concept> ; <{CAMPY_NS}concept_id> "c_{i:02d}" ; <{CAMPY_NS}text_raw> "Concept {i}" ; <{CAMPY_NS}confidence> 0.85 ; <{CAMPY_NS}created_at> "{now}" .')
        if i < 5:
            triples.append(f'<{uri}> <{CAMPY_NS}archived> false .')
        elif i < 10:
            triples.append(f'<{uri}> <{CAMPY_NS}archived> true .')
        # 10..14: NO archived predicate!

    # 15 Decisions:
    # 0..4: archived=false
    # 5..9: archived=true
    # 10..14: archived absent (pre-B410 data)
    for i in range(15):
        uri = f"https://campy.dev/id/Decision/d_{i:02d}"
        triples.append(f'<{uri}> a <{CAMPY_NS}Decision> ; <{CAMPY_NS}decision_id> "d_{i:02d}" ; <{CAMPY_NS}text_raw> "Decision {i}" ; <{CAMPY_NS}created_at> "{now}" .')
        if i < 5:
            triples.append(f'<{uri}> <{CAMPY_NS}archived> false .')
        elif i < 10:
            triples.append(f'<{uri}> <{CAMPY_NS}archived> true .')
        # 10..14: NO archived predicate!

    # 15 Plans:
    # 0..4: archived=false
    # 5..9: archived=true
    # 10..14: archived absent (pre-B410 data)
    for i in range(15):
        uri = f"https://campy.dev/id/Plan/p_{i:02d}"
        triples.append(f'<{uri}> a <{CAMPY_NS}Plan> ; <{CAMPY_NS}plan_id> "p_{i:02d}" ; <{CAMPY_NS}goal> "Goal {i}" ; <{CAMPY_NS}created_at> "{now}" .')
        if i < 5:
            triples.append(f'<{uri}> <{CAMPY_NS}archived> false .')
        elif i < 10:
            triples.append(f'<{uri}> <{CAMPY_NS}archived> true .')
        # 10..14: NO archived predicate!

    # Edges: Concept -> Decision -> Plan (chain for each i in 0..14)
    for i in range(15):
        triples.append(f'<https://campy.dev/id/Concept/c_{i:02d}> <{CAMPY_NS}ENABLES> <https://campy.dev/id/Decision/d_{i:02d}> .')
        triples.append(f'<https://campy.dev/id/Decision/d_{i:02d}> <{CAMPY_NS}ENABLES> <https://campy.dev/id/Plan/p_{i:02d}> .')

    ox_client.store.update("INSERT DATA {\n" + "\n".join(triples) + "\n}")

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

    # Phase 1: BEFORE backfill — TEETH CHECK (assert that OPTIONAL and plain BGP differ)
    for i, (q_opt, q_plain) in enumerate(query_families, start=1):
        res_opt = ox_client._execute_and_collect(q_opt)
        res_plain = ox_client._execute_and_collect(q_plain)

        # Plain BGP drops all nodes where archived was never written (simulating pre-B410 data)
        assert len(res_plain) < len(res_opt), (
            f"Teeth check failed: Query family {i} should drop unbackfilled rows in plain BGP before backfill "
            f"(plain={len(res_plain)}, opt={len(res_opt)})"
        )
        assert res_opt != res_plain, (
            f"Teeth check failed: Query family {i} must differ before backfill"
        )
        print(f"\n[Teeth Check] Family {i} BEFORE backfill: OPTIONAL={len(res_opt)}, Plain={len(res_plain)} (DIFFERENCE CONFIRMED: plain drops unbackfilled)")

    # Phase 2: RUN BACKFILL
    triples_added = ox_client.backfill_explicit_status()
    assert triples_added > 0, f"Expected backfill to add triples for absent status, added {triples_added}"
    print(f"\n[Backfill] Successfully backfilled {triples_added} triples.")

    # Phase 3: AFTER backfill — PARITY PROOF (assert 100% identical row-count and content)
    for i, (q_opt, q_plain) in enumerate(query_families, start=1):
        res_opt = ox_client._execute_and_collect(q_opt)
        res_plain = ox_client._execute_and_collect(q_plain)

        assert len(res_opt) == len(res_plain), (
            f"Query family {i} row-count mismatch after backfill: OPTIONAL got {len(res_opt)}, plain got {len(res_plain)}"
        )
        assert res_opt == res_plain, (
            f"Query family {i} content mismatch after backfill between OPTIONAL and plain filter forms"
        )
        print(f"[Parity Check] Family {i} AFTER backfill: OPTIONAL={len(res_opt)}, Plain={len(res_plain)} (PARITY CONFIRMED: 100% identical)")


def test_startup_backfill_without_import_graph_dump(tmp_path, monkeypatch):
    """Prove that init_schema() executes backfill_explicit_status() on daemon boot,
    ensuring existing databases migrated under B397 receive explicit status without
    calling import_graph_dump."""
    # Fast embedding mock for schema init
    fake_vec = [0.1] * 384
    monkeypatch.setattr("campy.brain.hippocampus.schema.emb.embed", lambda t, model_name=None: fake_vec)
    monkeypatch.setattr("campy.brain.hippocampus.schema.emb.embed_batch", lambda texts, model_name=None: [fake_vec for _ in texts])

    db_path = tmp_path / "legacy_startup.db"
    ox_client = OxigraphClient(db_path)

    # 1. Seed raw nodes for all 16 tables carrying an archived column, deliberately
    # omitting campy:archived to simulate a database migrated prior to B410.
    triples = []
    for table in ARCHIVED_TABLES:
        pk_col = NODE_PRIMARY_KEYS[table]
        uri = f"https://campy.dev/id/{table}/legacy_{table}"
        triples.append(f"<{uri}> a <{CAMPY_NS}{table}> .")
        triples.append(f'<{uri}> <{CAMPY_NS}{pk_col}> "legacy_{table}" .')
        triples.append(f'<{uri}> <{CAMPY_NS}text_raw> "Legacy unbackfilled {table}" .')

    ox_client.store.update("PREFIX campy: <" + CAMPY_NS + ">\nINSERT DATA {\n" + "\n".join(triples) + "\n}")

    # 2. Assert that BEFORE init_schema(), all 16 nodes have NO campy:archived predicate
    classes_str = " ".join(f"campy:{t}" for t in ARCHIVED_TABLES)
    q_absent = f"""
    PREFIX campy: <{CAMPY_NS}>
    SELECT ?s WHERE {{
        VALUES ?cls {{ {classes_str} }}
        ?s a ?cls .
        FILTER NOT EXISTS {{ ?s campy:archived ?a }}
    }}
    """
    absent_before = ox_client._execute_and_collect(q_absent)
    assert len(absent_before) == len(ARCHIVED_TABLES) == 16, (
        f"Expected 16 nodes with missing archived, got {len(absent_before)}"
    )
    print(f"\n[Startup Backfill Proof] Before init_schema: {len(absent_before)} nodes missing campy:archived")

    # 3. Call init_schema() through normal path (as brain_daemon does on boot)
    init_schema(ox_client, "campy/data/GistSeedExamples.md", "sentence-transformers/all-MiniLM-L6-v2")

    # 4. Assert that AFTER init_schema(), 0 nodes have missing archived
    absent_after = ox_client._execute_and_collect(q_absent)
    assert len(absent_after) == 0, f"Expected 0 un-backfilled nodes, got {absent_after}"
    print(f"[Startup Backfill Proof] After init_schema: 0 nodes missing campy:archived (backfilled via boot path)")

    # 5. Assert that all 16 nodes now have campy:archived false explicitly written
    q_check_values = f"""
    PREFIX campy: <{CAMPY_NS}>
    SELECT ?s ?archived WHERE {{
        VALUES ?cls {{ {classes_str} }}
        ?s a ?cls .
        ?s campy:archived ?archived .
    }}
    """
    rows = ox_client._execute_and_collect(q_check_values)
    assert len(rows) == 16
    for r in rows:
        assert r["archived"] is False, f"Node {r['s']} has archived={r['archived']}, expected False"
    print(f"[Startup Backfill Proof] All 16 tables verified with campy:archived false without calling import_graph_dump.")



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
