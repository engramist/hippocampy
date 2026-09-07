"""
tests/test_b405_alt_label_dedup.py — Tests for B405 Concept Dedup & Alt-Label Link Fix.

Verifies:
1. `quests.link_concept_has_alt_label` succeeds against real Kùzu (no BinderException).
2. End-to-end concept merge:
   - Creates HAS_ALT_LABEL edge from canonical Concept to Label node with duplicate's text.
   - Redirects edges (REQUIRES, CO_OCCURS_WITH, etc.) from duplicate to canonical.
   - Archives the duplicate Concept.
   - Leaves zero orphan Label nodes.
3. Partial failure rollback:
   - Mid-merge failure triggers cleanup of the newly minted Label node.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.tools.quests import resolve_disambiguation


@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        client = KuzuClient(db_path=db_path)
        # Initialize full schema
        seed_path = str(Path(__file__).resolve().parent.parent / "campy" / "data" / "GistSeedExamples.md")
        init_schema(client, seed_examples_path=seed_path, embedding_model="sentence-transformers/all-MiniLM-L6-v2")
        yield client
        client.close()


@pytest.mark.asyncio
async def test_link_concept_has_alt_label_named_query_kuzu(test_db: KuzuClient) -> None:
    """Ensure link_concept_has_alt_label succeeds on real Kuzu without BinderException."""
    gw = GraphGateway(test_db, REGISTRY)
    cid = f"test_concept_{uuid.uuid4().hex[:8]}"
    lid = f"test_label_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    # Create Concept node
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid=cid,
        text="Primary Concept",
        emb=[0.0] * 384,
        gist="Category",
        stype="DefinedTerm",
        now=now,
    )

    # Create Label node
    await gw.run(
        "quests.create_alt_label",
        lid=lid,
        txt="Secondary Alias",
        now=now.isoformat(),
    )

    # Wire canonical -> altLabel (this raised BinderException prior to B405)
    await gw.run(
        "quests.link_concept_has_alt_label",
        cid=cid,
        lid=lid,
    )

    # Verify edge exists
    rows = test_db.execute(
        f"MATCH (c:Concept {{concept_id: '{cid}'}})-[:HAS_ALT_LABEL]->(l:Label) RETURN l.text"
    )
    assert rows.has_next()
    assert rows.get_next()[0] == "Secondary Alias"


@pytest.mark.asyncio
async def test_resolve_disambiguation_merge_end_to_end(test_db: KuzuClient) -> None:
    """Verify full dedup merge: edge creation, edge redirection, duplicate archival."""
    gw = GraphGateway(test_db, REGISTRY)
    cid_a = f"concept_canonical_{uuid.uuid4().hex[:8]}"
    cid_b = f"concept_duplicate_{uuid.uuid4().hex[:8]}"
    cid_target = f"concept_target_{uuid.uuid4().hex[:8]}"
    eid = f"event_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    # 1. Create canonical Concept A (older timestamp)
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid=cid_a,
        text="OAuth 2.0",
        emb=[0.0] * 384,
        gist="Category",
        stype="DefinedTerm",
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    # 2. Create duplicate Concept B (newer timestamp)
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid=cid_b,
        text="OAuth2",
        emb=[0.0] * 384,
        gist="Category",
        stype="DefinedTerm",
        now=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    # 3. Create target Concept C
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid=cid_target,
        text="Token Service",
        emb=[0.0] * 384,
        gist="Category",
        stype="DefinedTerm",
        now=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )

    # 4. Attach relationships from duplicate B -> target C
    test_db.execute(
        f"MATCH (b:Concept {{concept_id: '{cid_b}'}}), (c:Concept {{concept_id: '{cid_target}'}}) "
        f"CREATE (b)-[:REQUIRES {{confidence: 0.9, inferred_by: 'test', inferred_at: timestamp('{now.isoformat()}')}}]->(c)"
    )
    test_db.execute(
        f"MATCH (b:Concept {{concept_id: '{cid_b}'}}), (c:Concept {{concept_id: '{cid_target}'}}) "
        f"CREATE (b)-[:CO_OCCURS_WITH {{count: 5, strength: 0.8}}]->(c)"
    )

    # 5. Create pending DisambiguationEvent
    test_db.execute(
        f"CREATE (:DisambiguationEvent {{event_id: '{eid}', concept_id_a: '{cid_a}', "
        f"concept_id_b: '{cid_b}', status: 'pending', created_at: timestamp('{now.isoformat()}')}})"
    )

    # 6. Resolve disambiguation via merge
    result = await resolve_disambiguation({"event_id": eid, "resolution": "merge"}, test_db, config={})
    assert "error" not in result
    assert "Merged: 'OAuth2' → altLabel of canonical concept" in result.get("result", "")

    # 7. Assert HAS_ALT_LABEL edge created on canonical A
    alt_rows = test_db.execute(
        f"MATCH (c:Concept {{concept_id: '{cid_a}'}})-[:HAS_ALT_LABEL]->(l:Label) RETURN l.text"
    )
    assert alt_rows.has_next()
    assert alt_rows.get_next()[0] == "OAuth2"

    # 8. Assert REQUIRES edge was redirected from B to A
    req_check = test_db.execute(
        f"MATCH (a:Concept {{concept_id: '{cid_a}'}})-[:REQUIRES]->(c:Concept {{concept_id: '{cid_target}'}}) "
        f"RETURN count(*)"
    )
    assert req_check.get_next()[0] == 1

    # 9. Assert CO_OCCURS_WITH edge was redirected from B to A
    co_check = test_db.execute(
        f"MATCH (a:Concept {{concept_id: '{cid_a}'}})-[:CO_OCCURS_WITH]->(c:Concept {{concept_id: '{cid_target}'}}) "
        f"RETURN count(*)"
    )
    assert co_check.get_next()[0] == 1

    # 10. Assert duplicate B is archived
    b_check = test_db.execute(
        f"MATCH (b:Concept {{concept_id: '{cid_b}'}}) RETURN b.archived"
    )
    assert b_check.get_next()[0] is True

    # 11. Assert DisambiguationEvent status is updated
    ev_check = test_db.execute(
        f"MATCH (e:DisambiguationEvent {{event_id: '{eid}'}}) RETURN e.status"
    )
    assert ev_check.get_next()[0] == "merge"

    # 12. Assert zero orphan labels
    orphan_check = test_db.execute(
        "MATCH (l:Label) WHERE NOT EXISTS { MATCH ()-[:HAS_PREF_LABEL|HAS_ALT_LABEL|HAS_HIDDEN_LABEL]->(l) } "
        "RETURN count(l)"
    )
    assert orphan_check.get_next()[0] == 0


@pytest.mark.asyncio
async def test_merge_rollback_cleans_orphan_label(test_db: KuzuClient) -> None:
    """Verify partial merge failure does not leak an orphan Label node."""
    cid_a = f"concept_a_{uuid.uuid4().hex[:8]}"
    cid_b = f"concept_b_{uuid.uuid4().hex[:8]}"
    eid = f"event_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    # Create Concept A & B
    gw = GraphGateway(test_db, REGISTRY)
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid=cid_a,
        text="Concept A",
        emb=[0.0] * 384,
        gist="Category",
        stype="DefinedTerm",
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid=cid_b,
        text="Concept B",
        emb=[0.0] * 384,
        gist="Category",
        stype="DefinedTerm",
        now=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    test_db.execute(
        f"CREATE (:DisambiguationEvent {{event_id: '{eid}', concept_id_a: '{cid_a}', "
        f"concept_id_b: '{cid_b}', status: 'pending', created_at: timestamp('{now.isoformat()}')}})"
    )

    # Simulate failure during edge redirection by mocking archive_concept to fail
    orig_run = GraphGateway.run

    async def mock_run(self, name, *args, **kwargs):
        if name == "quests.archive_concept":
            raise RuntimeError("Simulated archive failure")
        return await orig_run(self, name, *args, **kwargs)

    with patch.object(GraphGateway, "run", new=mock_run):
        result = await resolve_disambiguation({"event_id": eid, "resolution": "merge"}, test_db, config={})
        assert "error" in result

    # Assert no orphan label was leaked
    orphan_check = test_db.execute(
        "MATCH (l:Label) WHERE NOT EXISTS { MATCH ()-[:HAS_PREF_LABEL|HAS_ALT_LABEL|HAS_HIDDEN_LABEL]->(l) } "
        "RETURN count(l)"
    )
    assert orphan_check.get_next()[0] == 0
