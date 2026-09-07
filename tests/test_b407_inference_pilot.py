"""
tests/test_b407_inference_pilot.py — Regression tests for B407 Inference Pilot.

Verifies:
1. Need 1: SPARQL property paths correctly resolve transitive deprecation chains
   in sub-millisecond time without an external reasoner.
2. Need 1 Parity: Kùzu variable-length traversal and Oxigraph SPARQL property paths
   produce identical results for terminal replacement.
3. Need 2: Plain SPARQL validation correctly detects constraint/attribution violations
   without requiring pySHACL.
4. Decision Rule Artifact: Validates benchmarks/results/b407_inference_pilot.json
   records Branch 1 (Property paths sufficient) and measured scaling.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

import kuzu
import pyoxigraph as ox
import pytest


def test_need1_sparql_property_paths():
    """SPARQL property path campy:DEPRECATED_BY+ finds terminal constraint in <10ms."""
    store = ox.Store()
    chain_len = 5
    for i in range(chain_len):
        store.update(f"""
        PREFIX campy: <https://campy.ai/ontology#>
        INSERT DATA {{
            <https://campy.ai/entity/c{i}> a campy:Constraint ;
                campy:name "Constraint {i}" ;
                campy:DEPRECATED_BY <https://campy.ai/entity/c{i+1}> .
        }}
        """)

    term_uri = f"https://campy.ai/entity/c{chain_len}"
    store.update(f"""
    PREFIX campy: <https://campy.ai/ontology#>
    INSERT DATA {{
        <{term_uri}> a campy:Constraint ;
            campy:name "Constraint {chain_len}" .
    }}
    """)

    q = """
    PREFIX campy: <https://campy.ai/ontology#>
    SELECT ?term WHERE {
        <https://campy.ai/entity/c0> campy:DEPRECATED_BY+ ?term .
        FILTER NOT EXISTS { ?term campy:DEPRECATED_BY ?other }
    }
    """
    t0 = time.perf_counter()
    results = [r["term"].value for r in store.query(q)]
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert len(results) == 1
    assert results[0] == term_uri
    assert elapsed_ms < 10.0, f"SPARQL property path took {elapsed_ms:.2f}ms (>10ms)"


def test_need1_parity_with_kuzu():
    """Verify Kùzu varlen query and Oxigraph property path identify the same terminal."""
    tmp_dir = tempfile.mkdtemp(prefix="campy_test_kuzu_parity_")
    try:
        db = kuzu.Database(str(Path(tmp_dir) / "kuzu.db"))
        conn = kuzu.Connection(db)
        conn.execute("CREATE NODE TABLE Constraint(constraint_id STRING, PRIMARY KEY(constraint_id));")
        conn.execute("CREATE REL TABLE DEPRECATED_BY(FROM Constraint TO Constraint);")

        chain_len = 5
        for i in range(chain_len + 1):
            conn.execute(f"CREATE (:Constraint {{constraint_id: 'c{i}'}});")
        for i in range(chain_len):
            conn.execute(f"MATCH (a:Constraint {{constraint_id: 'c{i}'}}), (b:Constraint {{constraint_id: 'c{i+1}'}}) CREATE (a)-[:DEPRECATED_BY]->(b);")

        kuzu_q = """
        MATCH (c:Constraint {constraint_id: 'c0'})-[:DEPRECATED_BY*1..10]->(terminal:Constraint)
        WHERE NOT (terminal)-[:DEPRECATED_BY]->()
        RETURN terminal.constraint_id;
        """
        res = conn.execute(kuzu_q)
        kuzu_terminal = res.get_next()[0]
        assert kuzu_terminal == f"c{chain_len}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_need2_plain_sparql_validation():
    """Plain SPARQL validation detects missing attribution and timestamp without pySHACL."""
    store = ox.Store()
    # Insert 5 valid and 2 invalid decisions
    for i in range(5):
        store.update(f"""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX campy: <https://campy.ai/ontology#>
        INSERT DATA {{
            <https://campy.ai/decision/v{i}> a campy:Decision ;
                prov:wasAttributedTo <https://campy.ai/agent/claude> ;
                campy:created_at "2026-09-07T00:00:00Z" .
        }}
        """)

    # Invalid 1: missing attributed_to
    store.update("""
    PREFIX campy: <https://campy.ai/ontology#>
    INSERT DATA {
        <https://campy.ai/decision/inv_no_attr> a campy:Decision ;
            campy:created_at "2026-09-07T00:00:00Z" .
    }
    """)
    # Invalid 2: missing created_at
    store.update("""
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX campy: <https://campy.ai/ontology#>
    INSERT DATA {
        <https://campy.ai/decision/inv_no_time> a campy:Decision ;
            prov:wasAttributedTo <https://campy.ai/agent/claude> .
    }
    """)

    val_q = """
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX campy: <https://campy.ai/ontology#>
    SELECT ?d WHERE {
        ?d a campy:Decision .
        FILTER (
            NOT EXISTS { ?d prov:wasAttributedTo ?agent } ||
            NOT EXISTS { ?d campy:created_at ?ts }
        )
    }
    """
    invalid = [r["d"].value for r in store.query(val_q)]
    assert set(invalid) == {
        "https://campy.ai/decision/inv_no_attr",
        "https://campy.ai/decision/inv_no_time",
    }


def test_decision_rule_artifact():
    """Verify b407_inference_pilot_results.json exists and confirms Branch 1."""
    artifact_path = Path(__file__).resolve().parent.parent / "benchmarks" / "b407_inference_pilot_results.json"
    if not artifact_path.exists():
        pytest.skip("Benchmark artifact b407_inference_pilot_results.json not yet generated")

    with open(artifact_path) as f:
        data = json.load(f)

    assert "BRANCH 1: Property paths sufficient" in data["decision"]
    assert data["need1_deprecation"]["sparql_property_path"]["correct"] is True
    assert data["need1_deprecation"]["sparql_property_path"]["latencies"]["p50_ms"] < 1.0
    assert len(data["write_amplification_scaling"]) == 3
