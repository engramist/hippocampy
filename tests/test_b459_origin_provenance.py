"""B459 — assistant content can't confirm itself.

Two promotion paths let an assistant-originated Concept (capped below
HARD_LOCK by ISSUE-024) become confirmed (confidence_low = false) with no user
or document involvement:

1. Dedup: `touch_dedup_concept` cleared confidence_low for any repeat mention
   at >= 0.80, so the assistant saying the same thing twice confirmed it.
2. Re-scoring: `rescore_nearby_low_confidence` promoted a confidence_low
   Concept from neighbor count alone, so two Concepts from one assistant turn
   (linked by CO_OCCURS_WITH) confirmed each other.

Both ran against a real Oxigraph store here before the fix.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact
from campy.brain.temporal_lobe.loop.step7_pathway import rescore_nearby_low_confidence

EMB = [0.0] * 383 + [1.0]
NOW = "2026-09-30T00:00:00+00:00"


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b459.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def _state(db, cid):
    rows = list(db.store.query(
        'PREFIX campy: <https://campy.dev/ns#> '
        f'SELECT ?c ?l ?o WHERE {{ ?x campy:concept_id "{cid}" ; campy:confidence ?c ; '
        'campy:confidence_low ?l . OPTIONAL { ?x campy:origin_role ?o } }'
    ))
    assert len(rows) == 1
    r = rows[0]
    return (float(r["c"].value), r["l"].value == "true", r["o"].value if r["o"] else None)


async def _concept(gw, cid, text, conf, origin):
    await gw.run(
        "orchestrator.create_concept", concept_id=cid, text_raw=text, embedding=EMB,
        embedding_model="m", embedding_dim=384, gist_class="PhysicalThing",
        schema_org_type="Product", confidence=conf, confidence_low=True,
        pathway_strength=conf, salience_score=1.0, anomaly_type=None,
        flagged_for_review=False, origin_role=origin, created_at=NOW,
    )


async def _co_occur(gw, a, b):
    await gw.run("pathways.unwind_co_occurs_with",
                 pairs=[{"a_id": a, "b_id": b}], strength=0.85)


ENTITY = {"text": "session tokens in Redis", "gist_class": "PhysicalThing",
          "schema_org_type": "Product"}
TEXT = "We should store session tokens in Redis."


# --- dedup path -------------------------------------------------------------

@pytest.mark.asyncio
async def test_assistant_repeating_itself_stays_tentative(db):
    step4 = classify_artifact(TEXT, "PhysicalThing", "Product",
                              entity_text=ENTITY["text"], role="assistant")
    assert step4["confidence_low"] and step4["confidence"] >= 0.80

    cid = await orch._store_concept(ENTITY, step4, EMB, "m", db, NOW, role="assistant")
    again = await orch._store_concept(ENTITY, step4, EMB, "m", db, NOW, role="assistant")

    assert again == cid
    _conf, low, origin = _state(db, cid)
    assert low is True
    assert origin == "assistant"


@pytest.mark.asyncio
async def test_user_restating_upgrades_origin_but_only_confirms_above_hard_lock(db):
    a_step4 = classify_artifact(TEXT, "PhysicalThing", "Product",
                                entity_text=ENTITY["text"], role="assistant")
    cid = await orch._store_concept(ENTITY, a_step4, EMB, "m", db, NOW, role="assistant")

    # User says it with one keyword hit: 0.82, below HARD_LOCK -> stays tentative.
    u_weak = classify_artifact(TEXT, "PhysicalThing", "Product",
                               entity_text=ENTITY["text"], role="user")
    assert u_weak["confidence_low"]
    await orch._store_concept(ENTITY, u_weak, EMB, "m", db, NOW, role="user")
    _c, low, origin = _state(db, cid)
    assert (low, origin) == (True, "user")

    # User states it as a decision with agreeing signals: clears HARD_LOCK.
    strong = "We decided to go with session tokens in Redis, we chose it over cookies."
    u_strong = classify_artifact(strong, "Category", "DefinedTerm",
                                 entity_text=ENTITY["text"], role="user")
    assert not u_strong["confidence_low"]
    await orch._store_concept(ENTITY, u_strong, EMB, "m", db, NOW, role="user")
    assert _state(db, cid)[1] is False


def test_stronger_origin_rules():
    s = orch._stronger_origin
    assert s("assistant", "user") == "user"
    assert s("user", "assistant") == "user"
    assert s("document", "user") == "user"
    assert s("assistant", "document") == "document"
    assert s(None, "assistant") is None        # unknown is never relabelled assistant
    assert s(None, "user") == "user"
    assert s("assistant", None) == "assistant"


def test_origin_role_only_records_known_roles():
    assert orch._origin_role("user") == "user"
    assert orch._origin_role("assistant") == "assistant"
    assert orch._origin_role("system") is None
    assert orch._origin_role(None) is None


# --- re-scoring path --------------------------------------------------------

@pytest.mark.asyncio
async def test_assistant_concepts_cannot_corroborate_each_other(gw, db):
    await _concept(gw, "a", "Redis cache", 0.85, "assistant")
    await _concept(gw, "b", "session tokens in Redis", 0.85, "assistant")
    await _co_occur(gw, "a", "b")

    await rescore_nearby_low_confidence("a", db)

    assert _state(db, "b") == (0.85, True, "assistant")


@pytest.mark.asyncio
async def test_unknown_origin_neighbor_does_not_corroborate_assistant(gw, db):
    await _concept(gw, "a", "Redis cache", 0.85, None)   # e.g. a relation endpoint
    await _concept(gw, "b", "session tokens in Redis", 0.85, "assistant")
    await _co_occur(gw, "a", "b")

    await rescore_nearby_low_confidence("a", db)

    assert _state(db, "b")[1] is True


@pytest.mark.asyncio
async def test_user_neighbor_can_promote_assistant_concept(gw, db):
    await _concept(gw, "u", "Redis cache", 0.85, "user")
    await _concept(gw, "b", "session tokens in Redis", 0.85, "assistant")
    await _co_occur(gw, "u", "b")

    await rescore_nearby_low_confidence("u", db)

    conf, low, _origin = _state(db, "b")
    assert low is False and conf >= 0.90


@pytest.mark.asyncio
async def test_non_assistant_rescoring_unchanged(gw, db):
    # Pre-B459 nodes (no origin) and user nodes keep the old density rule.
    await _concept(gw, "a", "Redis cache", 0.85, None)
    await _concept(gw, "b", "session tokens in Redis", 0.85, None)
    await _co_occur(gw, "a", "b")

    await rescore_nearby_low_confidence("a", db)

    assert _state(db, "b")[1] is False


# --- relation endpoints -----------------------------------------------------

@pytest.mark.asyncio
async def test_relation_endpoints_record_turn_role(db, monkeypatch):
    monkeypatch.setattr(orch.emb, "embed", lambda text, model_name=None: EMB)
    await orch._ensure_concept_exists("Redis cache", "m", db, NOW, role="assistant")
    rows = list(db.store.query(
        'PREFIX campy: <https://campy.dev/ns#> '
        'SELECT ?o WHERE { ?x campy:text_raw "Redis cache" ; campy:origin_role ?o }'
    ))
    assert [r["o"].value for r in rows] == ["assistant"]
