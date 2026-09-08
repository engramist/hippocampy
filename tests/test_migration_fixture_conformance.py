"""
tests/test_migration_fixture_conformance.py — B411 Acceptance Gate: Fixture conformance guard.

Asserts:
- Fixture covers all 57 node tables and all 110 edge types (95 classified + 15 verified unclassified).
- Coverage asserted programmatically against schema.py, so newly added tables fail until represented.
- Every occurrence type round-trips multiple occurrences on one (s, p, o).
- Every star type has properties populated for plain triple and quoted annotation.
- Every §3.1 datatype exercised (STRING[], TIMESTAMP, DOUBLE, FLOAT[384]).
- classify_edge() proven to raise for all 15 UNCLASSIFIED_ESCALATED_TABLES.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from campy.brain.hippocampus.schema import (
    NODE_TABLES,
    REL_TABLES,
    SCHEMA_MIGRATIONS,
    get_all_table_properties,
)
from campy.brain.hippocampus.graph.oxigraph_client import (
    EDGE_REIFICATION,
    UNCLASSIFIED_ESCALATED_TABLES,
    classify_edge,
)
from scripts.generate_migration_fixture import (
    DEFAULT_OUTPUT_PATH,
    derive_schema,
    generate_node_rows,
    generate_rel_rows,
    verify_conformance,
)


def test_schema_coverage_derivation():
    """Verify that schema derivation extracts all 57 node tables and 110 rel tables from schema.py."""
    node_schemas, rel_schemas = derive_schema()

    assert len(node_schemas) == 57, f"Expected 57 node tables, got {len(node_schemas)}"
    assert len(rel_schemas) == 110, f"Expected 110 rel tables, got {len(rel_schemas)}"

    all_props = get_all_table_properties()
    for t, cols in node_schemas.items():
        assert set(cols.keys()) == all_props[t], f"Mismatch on node table {t}"
    for r, rinfo in rel_schemas.items():
        if r == "CONTRADICTS":
            assert set(rinfo["columns"].keys()) == {"confidence", "inferred_by", "inferred_at"}
        else:
            assert set(rinfo["columns"].keys()) == all_props[r], f"Mismatch on rel table {r}"


def test_classify_edge_raises_for_unclassified_escalated_tables():
    """Assert that classify_edge() raises KeyError or ValueError for all 15 UNCLASSIFIED_ESCALATED_TABLES."""
    assert len(UNCLASSIFIED_ESCALATED_TABLES) == 15
    for table_name in UNCLASSIFIED_ESCALATED_TABLES:
        with pytest.raises((KeyError, ValueError)):
            classify_edge(table_name)


def test_reification_classification_partition():
    """Verify that EDGE_REIFICATION and UNCLASSIFIED_ESCALATED_TABLES partition all 110 edge tables."""
    _, rel_schemas = derive_schema()
    all_rel_names = set(rel_schemas.keys())

    classified_names = set(EDGE_REIFICATION.keys())
    unclassified_names = set(UNCLASSIFIED_ESCALATED_TABLES)

    assert classified_names.isdisjoint(unclassified_names), "Classified and unclassified tables overlap"
    assert classified_names | unclassified_names == all_rel_names, (
        f"Missing tables: {all_rel_names - (classified_names | unclassified_names)}"
    )

    occ_count = sum(1 for c in EDGE_REIFICATION.values() if c == "occurrence")
    star_count = sum(1 for c in EDGE_REIFICATION.values() if c == "star")
    plain_count = sum(1 for c in EDGE_REIFICATION.values() if c == "plain")

    assert occ_count == 15, f"Expected 15 occurrence tables, got {occ_count}"
    assert star_count == 28, f"Expected 28 star tables, got {star_count}"
    assert plain_count == 52, f"Expected 52 plain tables, got {plain_count}"


def test_exhaustive_migration_fixture_file_conformance():
    """Verify the generated fixture file satisfies all acceptance criteria."""
    assert DEFAULT_OUTPUT_PATH.exists(), f"Fixture file not found at {DEFAULT_OUTPUT_PATH}"

    node_schemas, rel_schemas = derive_schema()

    node_rows = []
    rel_rows = []
    with DEFAULT_OUTPUT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item.get("_type") == "node":
                node_rows.append(item)
            elif item.get("_type") == "rel":
                rel_rows.append(item)

    verify_conformance(node_schemas, rel_schemas, node_rows, rel_rows)


def test_vector_norm_and_datatype_fidelity():
    """Verify that FLOAT[384] vectors in the fixture are real unit vectors within 1e-4 tolerance."""
    with DEFAULT_OUTPUT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            for k, v in item.items():
                if isinstance(v, list) and len(v) == 384 and isinstance(v[0], float):
                    norm = math.sqrt(sum(x * x for x in v))
                    assert math.isclose(norm, 1.0, abs_tol=1e-4), f"Vector norm {norm} exceeds 1e-4 tolerance on {k}"
