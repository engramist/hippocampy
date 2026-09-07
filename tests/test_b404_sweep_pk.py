"""
tests/test_b404_sweep_pk.py — Tests for B404 Sweep PK Column Correction.

Verifies:
1. sweep.get_active_pathway_*, sweep.unwind_archive_*,
   sweep.resurrect_active_embeddings_*, and sweep.resurrect_node_*
   reference actual primary key columns (global_constraint_id,
   global_preference_id, requirement_id) rather than the non-existent
   constraint_id, pref_id, req_id.
2. Returned node IDs from get_active_pathway_* are valid non-null strings.
3. Unwind archive actually changes archived state from false to true.
4. Resurrect queries actually find archived nodes and restore archived=false
   and pathway_strength.
5. Full end-to-end _sweep_pathways() decay and archive loop successfully
   archives GlobalConstraint, GlobalPreference, and Requirement nodes.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campy.brain.brainstem.sweep import _decay_and_archive
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.schema import init_schema


@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        client = KuzuClient(db_path=db_path)
        seed_path = str(Path(__file__).resolve().parent.parent / "campy" / "data" / "GistSeedExamples.md")
        init_schema(client, seed_examples_path=seed_path, embedding_model="sentence-transformers/all-MiniLM-L6-v2")
        yield client
        client.close()


@pytest.mark.asyncio
async def test_global_constraint_sweep_queries_lifecycle(test_db: KuzuClient) -> None:
    """Verify GlobalConstraint sweep queries return valid PK and alter archived state."""
    gw = GraphGateway(test_db, REGISTRY)
    gc_id = f"gc_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    # Insert GlobalConstraint with pathway_strength
    test_db.execute(
        f"CREATE (:GlobalConstraint {{global_constraint_id: '{gc_id}', text_raw: 'Test Global Constraint', "
        f"embedding: {[0.0]*384}, pathway_strength: 0.8, archived: false, created_at: timestamp('{now.isoformat()}')}})"
    )

    # 1. get_active_pathway: must return non-null global_constraint_id
    rows = await gw.run("sweep.get_active_pathway_globalconstraint")
    assert len(rows) >= 1
    matching = [r for r in rows if (list(r.values())[0] if isinstance(r, dict) else r[0]) == gc_id]
    assert len(matching) == 1, f"Expected to find {gc_id}, got rows: {rows}"
    m_vals = list(matching[0].values()) if isinstance(matching[0], dict) else matching[0]
    assert m_vals[0] == gc_id
    assert abs(m_vals[1] - 0.8) < 1e-5

    # 2. unwind_archive: must set archived = true
    await gw.run("sweep.unwind_archive_globalconstraint", ids=[gc_id])
    check_archived = test_db.execute(
        f"MATCH (n:GlobalConstraint {{global_constraint_id: '{gc_id}'}}) RETURN n.archived"
    )
    assert check_archived.has_next()
    assert check_archived.get_next()[0] is True

    # Active pathway query should now exclude it
    rows_after = await gw.run("sweep.get_active_pathway_globalconstraint")
    assert not any((list(r.values())[0] if isinstance(r, dict) else r[0]) == gc_id for r in rows_after)

    # 3. resurrect_active_embeddings: should return archived node
    res_rows = await gw.run("sweep.resurrect_active_embeddings_globalconstraint", limit=10)
    assert any((list(r.values())[0] if isinstance(r, dict) else r[0]) == gc_id for r in res_rows)

    # 4. resurrect_node: restore to active with new strength
    await gw.run("sweep.resurrect_node_globalconstraint", ids=[gc_id], strength=0.95)
    check_resurrect = test_db.execute(
        f"MATCH (n:GlobalConstraint {{global_constraint_id: '{gc_id}'}}) RETURN n.archived, n.pathway_strength"
    )
    assert check_resurrect.has_next()
    r_archived, r_strength = check_resurrect.get_next()
    assert r_archived is False
    assert abs(r_strength - 0.95) < 1e-5


@pytest.mark.asyncio
async def test_global_preference_sweep_queries_lifecycle(test_db: KuzuClient) -> None:
    """Verify GlobalPreference sweep queries return valid PK and alter archived state."""
    gw = GraphGateway(test_db, REGISTRY)
    gp_id = f"gp_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    # Insert GlobalPreference
    test_db.execute(
        f"CREATE (:GlobalPreference {{global_preference_id: '{gp_id}', text_raw: 'Test Preference', "
        f"embedding: {[0.0]*384}, pathway_strength: 0.75, archived: false, created_at: timestamp('{now.isoformat()}')}})"
    )

    # 1. get_active_pathway
    rows = await gw.run("sweep.get_active_pathway_globalpreference")
    assert len(rows) >= 1
    matching = [r for r in rows if (list(r.values())[0] if isinstance(r, dict) else r[0]) == gp_id]
    assert len(matching) == 1, f"Expected to find {gp_id}, got rows: {rows}"
    m_vals = list(matching[0].values()) if isinstance(matching[0], dict) else matching[0]
    assert m_vals[0] == gp_id
    assert abs(m_vals[1] - 0.75) < 1e-5

    # 2. unwind_archive
    await gw.run("sweep.unwind_archive_globalpreference", ids=[gp_id])
    check_archived = test_db.execute(
        f"MATCH (n:GlobalPreference {{global_preference_id: '{gp_id}'}}) RETURN n.archived"
    )
    assert check_archived.has_next()
    assert check_archived.get_next()[0] is True

    # 3. resurrect_active_embeddings
    res_rows = await gw.run("sweep.resurrect_active_embeddings_globalpreference", limit=10)
    assert any((list(r.values())[0] if isinstance(r, dict) else r[0]) == gp_id for r in res_rows)

    # 4. resurrect_node
    await gw.run("sweep.resurrect_node_globalpreference", ids=[gp_id], strength=0.90)
    check_resurrect = test_db.execute(
        f"MATCH (n:GlobalPreference {{global_preference_id: '{gp_id}'}}) RETURN n.archived, n.pathway_strength"
    )
    assert check_resurrect.has_next()
    r_archived, r_strength = check_resurrect.get_next()
    assert r_archived is False
    assert abs(r_strength - 0.90) < 1e-5


@pytest.mark.asyncio
async def test_requirement_sweep_queries_lifecycle(test_db: KuzuClient) -> None:
    """Verify Requirement sweep queries return valid PK and alter archived state."""
    gw = GraphGateway(test_db, REGISTRY)
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    # Insert Requirement
    test_db.execute(
        f"CREATE (:Requirement {{requirement_id: '{req_id}', text_raw: 'Test Requirement', "
        f"embedding: {[0.0]*384}, pathway_strength: 0.70, archived: false, created_at: timestamp('{now.isoformat()}')}})"
    )

    # 1. get_active_pathway
    rows = await gw.run("sweep.get_active_pathway_requirement")
    assert len(rows) >= 1
    matching = [r for r in rows if (list(r.values())[0] if isinstance(r, dict) else r[0]) == req_id]
    assert len(matching) == 1, f"Expected to find {req_id}, got rows: {rows}"
    m_vals = list(matching[0].values()) if isinstance(matching[0], dict) else matching[0]
    assert m_vals[0] == req_id
    assert abs(m_vals[1] - 0.70) < 1e-5

    # 2. unwind_archive
    await gw.run("sweep.unwind_archive_requirement", ids=[req_id])
    check_archived = test_db.execute(
        f"MATCH (n:Requirement {{requirement_id: '{req_id}'}}) RETURN n.archived"
    )
    assert check_archived.has_next()
    assert check_archived.get_next()[0] is True

    # 3. resurrect_active_embeddings
    res_rows = await gw.run("sweep.resurrect_active_embeddings_requirement", limit=10)
    assert any((list(r.values())[0] if isinstance(r, dict) else r[0]) == req_id for r in res_rows)

    # 4. resurrect_node
    await gw.run("sweep.resurrect_node_requirement", ids=[req_id], strength=0.88)
    check_resurrect = test_db.execute(
        f"MATCH (n:Requirement {{requirement_id: '{req_id}'}}) RETURN n.archived, n.pathway_strength"
    )
    assert check_resurrect.has_next()
    r_archived, r_strength = check_resurrect.get_next()
    assert r_archived is False
    assert abs(r_strength - 0.88) < 1e-5


@pytest.mark.asyncio
async def test_end_to_end_sweep_pathways_decay_and_archive(test_db: KuzuClient) -> None:
    """Verify full _sweep_pathways() correctly decays and archives these three tables."""
    now = datetime.now(timezone.utc)
    gc_id = f"gc_sweep_{uuid.uuid4().hex[:8]}"
    gp_id = f"gp_sweep_{uuid.uuid4().hex[:8]}"
    req_id = f"req_sweep_{uuid.uuid4().hex[:8]}"

    # Insert one of each table with strength below archive threshold (0.5)
    test_db.execute(
        f"CREATE (:GlobalConstraint {{global_constraint_id: '{gc_id}', text_raw: 'GC Decay', "
        f"embedding: {[0.0]*384}, pathway_strength: 0.30, archived: false, created_at: timestamp('{now.isoformat()}')}})"
    )
    test_db.execute(
        f"CREATE (:GlobalPreference {{global_preference_id: '{gp_id}', text_raw: 'GP Decay', "
        f"embedding: {[0.0]*384}, pathway_strength: 0.25, archived: false, created_at: timestamp('{now.isoformat()}')}})"
    )
    test_db.execute(
        f"CREATE (:Requirement {{requirement_id: '{req_id}', text_raw: 'Req Decay', "
        f"embedding: {[0.0]*384}, pathway_strength: 0.20, archived: false, created_at: timestamp('{now.isoformat()}')}})"
    )

    decayed, archived, errors = await _decay_and_archive(
        test_db,
        decay_rates={},
        interval_days=1.0,
        archive_threshold=0.5,
    )

    assert decayed >= 3
    assert archived >= 3
    assert errors == 0

    # Verify all three nodes are now marked archived = true
    gc_res = test_db.execute(f"MATCH (n:GlobalConstraint {{global_constraint_id: '{gc_id}'}}) RETURN n.archived")
    assert gc_res.get_next()[0] is True

    gp_res = test_db.execute(f"MATCH (n:GlobalPreference {{global_preference_id: '{gp_id}'}}) RETURN n.archived")
    assert gp_res.get_next()[0] is True

    req_res = test_db.execute(f"MATCH (n:Requirement {{requirement_id: '{req_id}'}}) RETURN n.archived")
    assert req_res.get_next()[0] is True
