"""
tests/test_migration_roundtrip.py — B397 / B411 Acceptance Gate: Round-trip migration test.

Verifies:
  Kùzu -> JSONL export -> Oxigraph + sqlite-vec import -> JSONL export
yields set-equal nodes, edges, and edge properties against populated graphs:
  1. Patent conformance graph fixture (test_patent_conformance_roundtrip_migration)
  2. B411 exhaustive migration graph fixture covering all 57 node tables and 95 classified edge tables
     (test_exhaustive_graph_roundtrip_migration)
  3. B411 proof that unclassified edge tables raise ValueError during import as designed (§4.2d)
     (test_unclassified_edges_raise_during_migration)
Unordered STRING[] differences are permitted per docs/rdf-schema-mapping.md §3.3.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

try:
    from campy.brain.hippocampus.graph.export import (
        _is_oxigraph,
        export_graph_dump,
        import_graph_dump,
    )
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.hippocampus.graph.vector_store import VectorStore
    from tests.kuzu_test_client import KuzuClient

    CUTOVER_AVAILABLE = True
except ImportError:
    CUTOVER_AVAILABLE = False

if not CUTOVER_AVAILABLE:
    pytest.skip(
        "Round-trip migration requires B397 Oxigraph export/import cutover",
        allow_module_level=True,
    )

from campy.brain.hippocampus.schema import init_schema
from tests.patent_claims.conftest import (
    EMBEDDING_MODEL,
    FIXTURE_PATH,
    SEED_PATH,
    load_patent_conformance_graph,
)

EXHAUSTIVE_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "exhaustive_migration_graph.jsonl"
)
EXHAUSTIVE_ALL_110_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "exhaustive_migration_graph_all_110.jsonl"
)


def _parse_dt(v: Any) -> Any:
    if isinstance(v, str) and ("T" in v or ("-" in v and len(v) >= 10)):
        try:
            t = v[:-1] + "+00:00" if v.endswith("Z") else v
            return datetime.fromisoformat(t).replace(tzinfo=None)
        except Exception:
            return v
    return v


def _vals_equal(v1: Any, v2: Any) -> bool:
    if v1 is None and v2 is None:
        return True
    if v1 is None or v2 is None:
        return False
    if isinstance(v1, list) and isinstance(v2, list):
        if len(v1) != len(v2):
            return False
        if len(v1) > 0 and isinstance(v1[0], float):
            return all(math.isclose(a, b, abs_tol=1e-4) for a, b in zip(v1, v2))
        # STRING[] ordering differences permitted per spec §3.3
        return sorted(str(x) for x in v1) == sorted(str(x) for x in v2)
    if isinstance(v1, float) or isinstance(v2, float):
        try:
            return math.isclose(float(v1), float(v2), abs_tol=1e-4)
        except Exception:
            return False
    dt1, dt2 = _parse_dt(v1), _parse_dt(v2)
    if isinstance(dt1, datetime) and isinstance(dt2, datetime):
        return dt1 == dt2
    return v1 == v2


def _run_roundtrip_migration(
    tmp_path: Path,
    fixture_path: Path,
    extra_nodes: bool = False,
) -> None:
    """Run full Kùzu -> JSONL -> Oxigraph -> JSONL round-trip equality assertion."""
    # 1. Initialize Kùzu and load populated fixture
    kuzu_dir = tmp_path / "kuzu.db"
    k_db = KuzuClient(str(kuzu_dir))
    try:
        init_schema(k_db, str(SEED_PATH), EMBEDDING_MODEL)
        load_res = load_patent_conformance_graph(k_db, fixture_path)
        assert load_res["nodes_loaded"] > 0
        assert load_res["rels_loaded"] > 0

        if extra_nodes:
            # Also insert a node with STRING[] property (GridSnapshot) to test list serialization parity
            k_db.execute(
                "CREATE (s:GridSnapshot {"
                "snapshot_id: 'snap-1', "
                "task_id: 'task-1', "
                "level: 1, "
                "step: 0, "
                "grid_hash: 'hash-abc', "
                "rows: 3, "
                "cols: 3, "
                "n_entities: 2, "
                "symmetry_axes: ['horizontal', 'vertical']"
                "})"
            )

        # 2. Export Kùzu graph dump
        dump_kuzu = tmp_path / "dump_kuzu"
        manifest_kuzu = export_graph_dump(k_db, dump_kuzu, include_projected=True)
    finally:
        k_db.close()

    # 3. Import Kùzu dump into Oxigraph + sqlite-vec
    ox_dir = tmp_path / "oxigraph.db"
    vs_dir = tmp_path / "vectors.db"
    vs = VectorStore(vs_dir)
    ox_client = OxigraphClient(ox_dir, vector_store=vs)
    try:
        import_res = import_graph_dump(ox_client, dump_kuzu, vector_store=vs)
        assert import_res["ok"] is True
        assert import_res["node_rows_loaded"] > 0
        assert import_res["rel_rows_loaded"] > 0

        # 4. Export Oxigraph graph dump
        dump_ox = tmp_path / "dump_ox"
        manifest_ox = export_graph_dump(
            ox_client, dump_ox, include_projected=True, vector_store=vs
        )
    finally:
        ox_client.close()

    # 5. Assert set-equality of manifest tables
    assert manifest_kuzu["node_tables"].keys() == manifest_ox["node_tables"].keys()
    assert manifest_kuzu["rel_tables"].keys() == manifest_ox["rel_tables"].keys()

    diffs: list[str] = []

    # 6. Assert set-equality of all nodes and properties
    k_nodes_dir = dump_kuzu / "nodes"
    ox_nodes_dir = dump_ox / "nodes"
    for k_file in k_nodes_dir.glob("*.jsonl"):
        tname = k_file.stem
        ox_file = ox_nodes_dir / k_file.name
        if not ox_file.exists():
            diffs.append(f"Missing node file in Oxigraph export: {ox_file.name}")
            continue

        k_rows = [json.loads(line) for line in k_file.read_text().splitlines() if line.strip()]
        ox_rows = [json.loads(line) for line in ox_file.read_text().splitlines() if line.strip()]
        if len(k_rows) != len(ox_rows):
            diffs.append(
                f"Node table {tname}: row count mismatch {len(k_rows)} (kuzu) vs {len(ox_rows)} (ox)"
            )
            continue

        pk = manifest_kuzu["node_tables"][tname]["pk"]
        k_by_pk = {str(r[pk]): r for r in k_rows}
        ox_by_pk = {str(r[pk]): r for r in ox_rows}

        if set(k_by_pk.keys()) != set(ox_by_pk.keys()):
            diffs.append(
                f"Node table {tname}: PK set mismatch {set(k_by_pk.keys()) ^ set(ox_by_pk.keys())}"
            )
            continue

        for key, r_k in k_by_pk.items():
            r_ox = ox_by_pk[key]
            all_cols = set(r_k.keys()) | set(r_ox.keys())
            for col in all_cols:
                vk = r_k.get(col)
                vox = r_ox.get(col)
                if not _vals_equal(vk, vox):
                    diffs.append(f"Node {tname}[{key}].{col} mismatch: kuzu={vk!r} vs ox={vox!r}")

    # 7. Assert set-equality of all rels and properties
    k_rels_dir = dump_kuzu / "rels"
    ox_rels_dir = dump_ox / "rels"
    for k_file in k_rels_dir.glob("*.jsonl"):
        rname = k_file.stem
        ox_file = ox_rels_dir / k_file.name
        if not ox_file.exists():
            diffs.append(f"Missing rel file in Oxigraph export: {ox_file.name}")
            continue

        k_rows = [json.loads(line) for line in k_file.read_text().splitlines() if line.strip()]
        ox_rows = [json.loads(line) for line in ox_file.read_text().splitlines() if line.strip()]
        if len(k_rows) != len(ox_rows):
            diffs.append(
                f"Rel table {rname}: row count mismatch {len(k_rows)} (kuzu) vs {len(ox_rows)} (ox)"
            )
            continue

        matched_ox_indices = set()
        for kr in k_rows:
            matched = False
            for idx, oxr in enumerate(ox_rows):
                if idx in matched_ox_indices:
                    continue
                if (
                    kr["_from_table"] == oxr["_from_table"]
                    and str(kr["_from_pk"]) == str(oxr["_from_pk"])
                    and kr["_to_table"] == oxr["_to_table"]
                    and str(kr["_to_pk"]) == str(oxr["_to_pk"])
                ):
                    all_cols = set(kr.keys()) | set(oxr.keys())
                    if all(_vals_equal(kr.get(c), oxr.get(c)) for c in all_cols):
                        matched = True
                        matched_ox_indices.add(idx)
                        break
            if not matched:
                diffs.append(f"Rel {rname} row in kuzu not matched in ox: {kr}")

    assert not diffs, "Round-trip migration differences found:\n" + "\n".join(diffs[:25])


def test_patent_conformance_roundtrip_migration(tmp_path: Path) -> None:
    """Verify full Kùzu -> JSONL -> Oxigraph -> JSONL round-trip equality on patent fixture."""
    _run_roundtrip_migration(tmp_path, FIXTURE_PATH, extra_nodes=True)


def test_exhaustive_graph_roundtrip_migration(tmp_path: Path) -> None:
    """Verify full Kùzu -> JSONL -> Oxigraph -> JSONL round-trip equality on B411 exhaustive fixture."""
    _run_roundtrip_migration(tmp_path, EXHAUSTIVE_FIXTURE_PATH, extra_nodes=False)


def test_unclassified_edges_raise_during_migration(tmp_path: Path) -> None:
    """Verify that importing deliberately unclassified edge tables raises ValueError as designed (§4.2d)."""
    kuzu_dir = tmp_path / "kuzu.db"
    k_db = KuzuClient(str(kuzu_dir))
    try:
        init_schema(k_db, str(SEED_PATH), EMBEDDING_MODEL)
        load_res = load_patent_conformance_graph(k_db, EXHAUSTIVE_ALL_110_FIXTURE_PATH)
        assert load_res["nodes_loaded"] > 0
        assert load_res["rels_loaded"] > 0

        dump_kuzu = tmp_path / "dump_kuzu"
        export_graph_dump(k_db, dump_kuzu, include_projected=True)
    finally:
        k_db.close()

    ox_dir = tmp_path / "oxigraph.db"
    vs_dir = tmp_path / "vectors.db"
    vs = VectorStore(vs_dir)
    ox_client = OxigraphClient(ox_dir, vector_store=vs)
    try:
        with pytest.raises(ValueError, match="is deliberately unclassified in EDGE_REIFICATION"):
            import_graph_dump(ox_client, dump_kuzu, vector_store=vs)
    finally:
        ox_client.close()
