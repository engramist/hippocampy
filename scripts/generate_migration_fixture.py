#!/usr/bin/env python3
"""
scripts/generate_migration_fixture.py — B411 Exhaustive Migration Fixture Generator.

Derives schema coverage directly by importing `campy/brain/hippocampus/schema.py`
(reusing B406 three-source derivation: NODE_TABLES, REL_TABLES, and SCHEMA_MIGRATIONS).
Generates an exhaustive JSONL graph fixture covering:
- All 57 node tables (with every declared property populated)
- All 110 edge types (95 classified + 15 verified unclassified escalated)
- Multiple occurrences per (s,p,o) for all 15 occurrence types
- Plain triples and quoted annotations for all 28 star types
- All §3.1 datatypes (STRING[], TIMESTAMP, DOUBLE, FLOAT[384])
- Verified that classify_edge() raises on all 15 UNCLASSIFIED_ESCALATED_TABLES
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from campy.brain.hippocampus.schema import (
    NODE_TABLES,
    REL_TABLES,
    SCHEMA_MIGRATIONS,
    get_all_table_properties,
)
from campy.brain.hippocampus.graph.export import _parse_column_types
from campy.brain.hippocampus.table_registry import pk_for
from campy.brain.hippocampus.graph.oxigraph_client import (
    EDGE_REIFICATION,
    UNCLASSIFIED_ESCALATED_TABLES,
    classify_edge,
)

DEFAULT_OUTPUT_PATH = REPO_ROOT / "tests" / "fixtures" / "exhaustive_migration_graph.jsonl"
ALL_110_OUTPUT_PATH = REPO_ROOT / "tests" / "fixtures" / "exhaustive_migration_graph_all_110.jsonl"


def generate_384_vector(offset: int = 0) -> list[float]:
    """Generate a real 384-dimensional unit vector with verified L2 norm within 1e-4 of 1.0."""
    raw = [math.sin(i + 1 + offset) + 0.1 * math.cos(2 * (i + 1 + offset)) for i in range(384)]
    norm = math.sqrt(sum(x * x for x in raw))
    vec = [round(x / norm, 6) for x in raw]
    curr_norm = math.sqrt(sum(x * x for x in vec))
    if curr_norm > 0:
        vec[0] += (1.0 - curr_norm)
    return vec


def derive_schema() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    """Derive full node and relationship schemas from schema.py directly.

    Reuses B406 three-source derivation:
    1. NODE_TABLES
    2. REL_TABLES
    3. SCHEMA_MIGRATIONS (including comprehension-generated columns)
    """
    all_table_props = get_all_table_properties()

    # 1. Node tables: map table_name -> {col_name: col_type}
    node_schemas: dict[str, dict[str, str]] = {}
    for table_name, ddl in NODE_TABLES.items():
        cols = _parse_column_types(ddl)
        node_schemas[table_name] = cols

    for table, col, col_type in SCHEMA_MIGRATIONS:
        if table in node_schemas:
            node_schemas[table][col] = col_type

    # 2. Rel tables: map rel_name -> {"endpoints": [(from_t, to_t)], "columns": {col_name: col_type}}
    rel_schemas: dict[str, dict[str, Any]] = {}
    for ddl in REL_TABLES:
        m = re.search(r"(?i)create\s+rel\s+table\s+(?:if\s+not\s+exists\s+)?(\w+)\s*\((.*)\)", ddl, re.DOTALL)
        if not m:
            continue
        rel_name = m.group(1)
        if rel_name in rel_schemas:
            # First DDL wins in Kùzu (e.g. duplicate CONTRADICTS DDL)
            continue
        body = m.group(2)
        endpoints = []
        for ep in re.finditer(r"FROM\s+(\w+)\s+TO\s+(\w+)", body):
            endpoints.append((ep.group(1), ep.group(2)))
        cols = _parse_column_types(ddl)
        rel_schemas[rel_name] = {"endpoints": endpoints, "columns": cols}

    for table, col, col_type in SCHEMA_MIGRATIONS:
        if table in rel_schemas:
            rel_schemas[table]["columns"][col] = col_type

    # Sanity checks against schema.py
    assert len(node_schemas) == 57, f"Expected 57 node tables, got {len(node_schemas)}"
    assert len(rel_schemas) == 110, f"Expected 110 rel tables, got {len(rel_schemas)}"

    return node_schemas, rel_schemas


def generate_node_rows(node_schemas: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Generate at least 2 populated rows per node table with all declared properties populated."""
    rows: list[dict[str, Any]] = []

    for table, cols in node_schemas.items():
        pk = pk_for(table)
        assert pk is not None, f"Missing primary key for table {table}"

        for idx in (1, 2):
            props: dict[str, Any] = {
                "_type": "node",
                "_label": table,
                "_table": table,
            }
            for col, ctype in cols.items():
                if col == pk:
                    props[col] = f"{table.lower()}-fix-{idx}"
                elif ctype.startswith("FLOAT["):
                    props[col] = generate_384_vector(idx)
                elif ctype == "STRING[]":
                    props[col] = [f"tag-{table.lower()}-a-{idx}", f"tag-{table.lower()}-b-{idx}"]
                elif ctype == "TIMESTAMP":
                    props[col] = f"2026-09-0{idx}T12:00:00Z"
                elif ctype in ("DOUBLE", "FLOAT"):
                    props[col] = round(0.80 + 0.05 * idx, 2)
                elif ctype in ("INT32", "INT64"):
                    props[col] = 10 * idx
                elif ctype in ("BOOL", "BOOLEAN"):
                    props[col] = (idx == 1)
                else:  # STRING
                    if col == "authority":
                        props[col] = "earned" if idx == 1 else "projected"
                    elif col == "superseded_by":
                        props[col] = None if idx == 1 else f"{table.lower()}-fix-1"
                    elif col == "supersession_reason":
                        props[col] = None if idx == 1 else "replaced"
                    elif col == "embedding_model":
                        props[col] = "sentence-transformers/all-MiniLM-L6-v2"
                    elif col == "status":
                        props[col] = "active" if idx == 1 else "completed"
                    elif col == "source":
                        props[col] = f"source-{table.lower()}"
                    elif col == "source_version":
                        props[col] = "1.0"
                    elif col == "content_hash":
                        props[col] = f"hash-{table.lower()}-{idx}"
                    elif col == "evidence_ref":
                        props[col] = f"REF-{table.upper()}-{idx}"
                    elif col == "schema_org_type":
                        props[col] = "schema:SoftwareApplication"
                    elif col == "gist_class":
                        props[col] = "gist:Category"
                    else:
                        props[col] = f"{table.lower()}-{col}-{idx}"

            rows.append(props)

    return rows


def generate_rel_rows(
    rel_schemas: dict[str, dict[str, Any]],
    include_unclassified: bool = False,
) -> list[dict[str, Any]]:
    """Generate edge rows.

    For occurrence edges (15 types): 2 distinct occurrences between the exact same (s, p, o).
    For star edges (28 types): properties populated to exercise quoted annotation + plain triple.
    For plain edges (52 types): valid endpoints.
    For unclassified edges (15 types): generated only if include_unclassified=True.
    """
    rows: list[dict[str, Any]] = []
    occ_tables = {t for t, c in EDGE_REIFICATION.items() if c == "occurrence"}

    for rname, rinfo in rel_schemas.items():
        is_unclassified = rname in UNCLASSIFIED_ESCALATED_TABLES
        if is_unclassified and not include_unclassified:
            continue

        endpoints = rinfo["endpoints"]
        assert endpoints, f"Rel table {rname} has no endpoints"
        from_t, to_t = endpoints[0]

        num_occ = 2 if rname in occ_tables else 1

        for occ_idx in range(1, num_occ + 1):
            if from_t == to_t:
                from_id = f"{from_t.lower()}-fix-1"
                to_id = f"{to_t.lower()}-fix-2"
            else:
                from_id = f"{from_t.lower()}-fix-1"
                to_id = f"{to_t.lower()}-fix-1"

            props: dict[str, Any] = {
                "_type": "rel",
                "_label": rname,
                "_table": rname,
                "_from_table": from_t,
                "_from_pk": from_id,
                "_to_table": to_t,
                "_to_pk": to_id,
            }

            for col, ctype in rinfo["columns"].items():
                if ctype == "TIMESTAMP":
                    props[col] = f"2026-09-0{occ_idx}T10:00:00Z"
                elif ctype in ("DOUBLE", "FLOAT"):
                    props[col] = round(0.70 + 0.1 * occ_idx, 2)
                elif ctype in ("INT32", "INT64"):
                    props[col] = occ_idx
                elif ctype in ("BOOL", "BOOLEAN"):
                    props[col] = (occ_idx == 1)
                else:
                    props[col] = f"{rname.lower()}-{col}-{occ_idx}"

            rows.append(props)

    return rows


def verify_conformance(
    node_schemas: dict[str, dict[str, str]],
    rel_schemas: dict[str, dict[str, Any]],
    node_rows: list[dict[str, Any]],
    rel_rows: list[dict[str, Any]],
) -> None:
    """Assert all B411 acceptance criteria programmatically."""
    # 1. 57/57 node tables covered
    covered_nodes = {r["_table"] for r in node_rows if r["_type"] == "node"}
    assert covered_nodes == set(node_schemas.keys()), (
        f"Missing node tables in fixture: {set(node_schemas.keys()) - covered_nodes}"
    )
    assert len(covered_nodes) == 57

    # 2. Every node row has all declared properties populated
    for r in node_rows:
        t = r["_table"]
        cols = node_schemas[t]
        for col in cols:
            assert col in r, f"Node table {t} missing declared property {col}"

    # 3. 15 UNCLASSIFIED_ESCALATED_TABLES proven to raise classify_edge()
    for unclass_table in UNCLASSIFIED_ESCALATED_TABLES:
        raised = False
        try:
            classify_edge(unclass_table)
        except (KeyError, ValueError):
            raised = True
        assert raised, f"classify_edge() failed to raise for unclassified table {unclass_table}"

    # 4. Occurrence edges have multiple occurrences per (s,p,o)
    occ_tables = {t for t, c in EDGE_REIFICATION.items() if c == "occurrence"}
    assert len(occ_tables) == 15, f"Expected 15 occurrence tables, got {len(occ_tables)}"
    for occ_t in occ_tables:
        t_rows = [r for r in rel_rows if r["_table"] == occ_t]
        assert len(t_rows) >= 2, f"Occurrence table {occ_t} has fewer than 2 occurrences"
        # Check that at least one (s,p,o) has multiple occurrences
        spo_counts: dict[tuple[str, str, str, str], int] = {}
        for r in t_rows:
            key = (r["_from_table"], r["_from_pk"], r["_to_table"], r["_to_pk"])
            spo_counts[key] = spo_counts.get(key, 0) + 1
        assert any(c >= 2 for c in spo_counts.values()), (
            f"Occurrence table {occ_t} does not have multiple occurrences for same (s,p,o)"
        )

    # 5. Star edges have properties populated for plain + quoted annotation
    star_tables = {t for t, c in EDGE_REIFICATION.items() if c == "star"}
    assert len(star_tables) == 28, f"Expected 28 star tables, got {len(star_tables)}"
    for star_t in star_tables:
        t_rows = [r for r in rel_rows if r["_table"] == star_t]
        assert len(t_rows) >= 1, f"Missing star edge table {star_t}"
        first_row = t_rows[0]
        # Verify edge properties exist
        cols = rel_schemas[star_t]["columns"]
        for col in cols:
            assert col in first_row, f"Star table {star_t} missing property {col}"

    # 6. Datatypes verified
    all_datatypes = set()
    for cols in node_schemas.values():
        all_datatypes.update(cols.values())
    for rinfo in rel_schemas.values():
        all_datatypes.update(rinfo["columns"].values())

    expected_datatypes = {
        "STRING", "INT32", "INT64", "DOUBLE", "FLOAT", "FLOAT[384]",
        "BOOL", "BOOLEAN", "TIMESTAMP", "STRING[]",
    }
    assert expected_datatypes.issubset(all_datatypes), (
        f"Missing expected datatypes: {expected_datatypes - all_datatypes}"
    )

    # 7. Real 384-dim normalized vector verified
    v = generate_384_vector(0)
    assert len(v) == 384
    norm = math.sqrt(sum(x * x for x in v))
    assert math.isclose(norm, 1.0, abs_tol=1e-4), f"Vector norm not within 1e-4 of 1.0: {norm}"


def write_fixture(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows to JSONL format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate exhaustive migration fixture for HippoCampy.")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for output migration fixture JSONL (defaults to tests/fixtures/exhaustive_migration_graph.jsonl)",
    )
    parser.add_argument(
        "--include-unclassified",
        action="store_true",
        help="Include the 15 deliberately unclassified tables in the fixture",
    )
    args = parser.parse_args()

    node_schemas, rel_schemas = derive_schema()
    node_rows = generate_node_rows(node_schemas)
    rel_rows = generate_rel_rows(rel_schemas, include_unclassified=args.include_unclassified)

    verify_conformance(node_schemas, rel_schemas, node_rows, rel_rows)

    write_fixture(args.out, node_rows + rel_rows)
    print(f"Generated exhaustive migration fixture at {args.out}")
    print(f"  Nodes: {len(node_rows)} rows across {len(node_schemas)} tables")
    print(f"  Edges: {len(rel_rows)} rows across {len(set(r['_table'] for r in rel_rows))} tables")
    print(f"  Classified reification: 15 occurrence (multiple occurrences), 28 star (plain+quoted), 52 plain")
    print(f"  Unclassified tables: 15 verified to raise in classify_edge()")


if __name__ == "__main__":
    main()
