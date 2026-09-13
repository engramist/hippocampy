"""tests/test_b418b_uri_base_unification.py — B418b proof.

B418 found two instance-URI bases coexisting: `mint_uri()`/`CID_BASE`/
`vector_search()` use `https://campy.dev/id/`, but 26 `sparql=` create
templates across 7 query modules minted at `https://campy.dev/data/` instead.

While scoping the unification, this surfaced a LIVE bug, not just drift: six
node tables (Concept, Dataset, Label, Lesson, Plan, Procedure) were *only ever
created* via the `/data/`-minting templates — `write_node()` (the only thing
that mints at `/id/` for a fresh node) is never called for any of them. But
several `gateway.py` edge-writing handlers construct their endpoints via
`mint_uri("Concept", ...)` / `mint_uri("Plan", ...)` / etc., which always
assumes `/id/`. So `quests.link_distinct_from` (reachable from
`quests.py:901`, production code) — and by the same pattern
`ingest.link_concept_dataset`, `sweep.link_generalizes_lesson`,
`quests.link_plan_applied_procedure` — wrote their edges onto a PHANTOM `/id/`
subject that no real `campy:Concept`/`campy:Plan`/`campy:Lesson` node
occupies, since every real instance of those tables lived at `/data/`. The
edge existed in the store but was unreachable from the real node — the same
"handler writes to a URI/table the node doesn't live at" class as B420/B421.

Fix: all 26 `/data/` create templates now mint at the canonical `/id/` base,
matching `mint_uri()`. This test proves the previously-phantom edge now
attaches to the real node.
"""

from __future__ import annotations

import uuid

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b418b.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


def _now():
    return "2026-01-01T00:00:00Z"


async def _create_minimal_concept(gw, cid: str, emb):
    await gw.run(
        "orchestrator.create_minimal_concept",
        concept_id=cid, text_raw=f"concept {cid}", embedding=emb,
        embedding_model="test", embedding_dim=len(emb), created_at=_now(),
    )


def _emb():
    return [0.1] * 384


@pytest.mark.asyncio
async def test_concept_create_mints_at_canonical_id_base(gw, ox_client):
    """The node-creation URI itself is now /id/, not /data/."""
    cid = f"c_{uuid.uuid4().hex[:8]}"
    await _create_minimal_concept(gw, cid, _emb())

    subject = ox_client.find_subject_uri("Concept", "concept_id", cid)
    assert subject == f"https://campy.dev/id/Concept/{cid}"


@pytest.mark.asyncio
async def test_distinct_from_edge_reaches_the_real_concept_node(gw, ox_client):
    """Regression for the phantom-edge bug: quests.link_distinct_from's
    gateway handler mints its endpoints via mint_uri("Concept", ...) — before
    B418b that was /id/ while every real Concept lived at /data/, so the edge
    silently attached to no node. It must now be readable FROM the real,
    created Concept nodes via the ordinary read query."""
    a, b = f"c_{uuid.uuid4().hex[:8]}", f"c_{uuid.uuid4().hex[:8]}"
    await _create_minimal_concept(gw, a, _emb())
    await _create_minimal_concept(gw, b, _emb())

    await gw.run("quests.link_distinct_from", a=a, b=b, now=_now())

    rows = await gw.run("retrieval.get_distinct_pairs", ids=[a])
    ids = {r["concept_id"] for r in rows}
    assert b in ids, (
        "DISTINCT_FROM edge did not reach the real Concept node — "
        "phantom-URI regression"
    )


@pytest.mark.asyncio
async def test_lesson_generalizes_edge_reaches_the_real_lesson_nodes(gw, ox_client):
    """Same phantom-edge pattern for sweep.link_generalizes_lesson: Lesson is
    also create-only-at-/data/-historically, and GENERALIZES_LESSON's
    endpoints are minted via mint_uri("Lesson", ...) in the gateway handler."""
    mid, cid = f"l_{uuid.uuid4().hex[:8]}", f"l_{uuid.uuid4().hex[:8]}"
    for lid in (mid, cid):
        await gw.run(
            "lessons.create_lesson", lid=lid, text=f"lesson {lid}", emb=_emb(),
            model="test", dim=384, domain="test", type="optimization",
            scene_wl_hash=None, scene_graph_vector=None, archetype=None,
            progress_score=None, valence=0.5, now=_now(), trig_pattern=None,
            trig_hook_type=None, trig_tool=None, trig_scope=None,
            prov_source="test", prov_source_version=None, prov_observed_at=_now(),
            prov_evidence_ref=None, content_hash=None,
        )

    await gw.run("sweep.link_generalizes_lesson", mid=mid, cid=cid, now=_now(), cluster_size=2)

    subj = ox_client.find_subject_uri("Lesson", "lesson_id", mid)
    assert subj == f"https://campy.dev/id/Lesson/{mid}"
    n = list(ox_client.store.query(
        f'SELECT (COUNT(*) AS ?n) WHERE {{ <{subj}> <https://campy.dev/ns#GENERALIZES_LESSON> ?o }}'
    ))[0]["n"].value
    assert int(n) == 1, "GENERALIZES_LESSON edge did not attach to the real Lesson node"


def test_no_residual_data_base_in_query_templates():
    """No sparql= template should mint an instance at the drifted /data/ base
    any more — the whole point of B418b."""
    offenders = [
        q.name for q in REGISTRY
        if q.sparql and "https://campy.dev/data/" in q.sparql
    ]
    assert not offenders, f"still minting at /data/: {offenders}"
