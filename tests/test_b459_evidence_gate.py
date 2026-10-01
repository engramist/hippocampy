"""B459 Part B — the save gate uses graph evidence for entities just below the floor.

An entity Step 4 would drop at 0.45–0.60 is kept as a tentative Concept when
the graph already holds a confirmed Concept it closely matches. Evidence never
lifts to HARD_LOCK, assistant turns need user/document-backed evidence, and
entities outside the band do no extra retrieval.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph import embeddings as emb_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.temporal_lobe.loop.step4_pattern import (
    HARD_LOCK, NOISE_FLOOR, apply_evidence_rescue, classify_artifact,
    supporting_evidence,
)

EMB = [0.0] * 383 + [1.0]
NOW = "2026-10-01T00:00:00+00:00"
BELOW_FLOOR = {"artifact_type": "decision", "confidence": 0.55,
               "confidence_low": True, "should_proceed": False}


def _cand(**kw):
    base = {"concept_id": "c1", "similarity": 0.95, "confidence_low": False,
            "origin_role": "user", "flagged_for_review": False}
    return {**base, **kw}


# --- pure function ------------------------------------------------------------

def test_rescue_needs_confirmed_unflagged_support():
    assert apply_evidence_rescue(BELOW_FLOOR, [_cand(confidence_low=True)])[2] is False
    assert apply_evidence_rescue(BELOW_FLOOR, [_cand(flagged_for_review=True)])[2] is False
    assert apply_evidence_rescue(BELOW_FLOOR, [])[2] is False

    result, ids, rescued = apply_evidence_rescue(BELOW_FLOOR, [_cand()])
    assert rescued and ids == ["c1"]
    assert result["should_proceed"] and result["confidence_low"]
    assert result["confidence"] == pytest.approx(NOISE_FLOOR + 0.02)
    assert result["confidence"] < HARD_LOCK


def test_rescue_only_in_band():
    deep = dict(BELOW_FLOOR, confidence=0.30)
    assert apply_evidence_rescue(deep, [_cand()])[2] is False
    passing = {"artifact_type": "decision", "confidence": 0.82,
               "confidence_low": True, "should_proceed": True}
    result, _ids, rescued = apply_evidence_rescue(passing, [_cand()])
    assert result is passing and not rescued


def test_assistant_needs_user_or_document_evidence():
    for origin in ("assistant", None):
        assert supporting_evidence([_cand(origin_role=origin)], role="assistant") == []
        assert supporting_evidence([_cand(origin_role=origin)], role="user") != []
    for origin in ("user", "document"):
        assert supporting_evidence([_cand(origin_role=origin)], role="assistant") != []


# --- end to end through run_loop (real Oxigraph, stubbed embedder) --------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(emb_mod, "embed", lambda text, model_name=None, **kw: EMB)
    monkeypatch.setattr(emb_mod, "embed_batch",
                        lambda texts, model_name=None, **kw: [EMB for _ in texts])
    return OxigraphClient(tmp_path / "b459b.db")


async def _seed(db, origin, confidence_low=False):
    await GraphGateway(db, REGISTRY).run(
        "orchestrator.create_concept", concept_id="seed", text_raw="Redis cache",
        embedding=EMB, embedding_model="m", embedding_dim=384,
        gist_class="PhysicalThing", schema_org_type="Product",
        confidence=0.95, confidence_low=confidence_low, pathway_strength=0.9,
        salience_score=1.0, anomaly_type=None, flagged_for_review=False,
        origin_role=origin, created_at=NOW,
    )


TEXT = "The Redis cache handles sessions."
ENTITY = {"text": "Redis cache", "gist_class": "PhysicalThing",
          "schema_org_type": "Product", "label": "PRODUCT"}


async def _run(db, role="user", entity=ENTITY):
    return await orch.run_loop("m1", TEXT, db, None, {}, {}, role=role,
                               precomputed={"entities": [entity], "relations": []})


def test_fixture_entity_lands_in_band():
    step4 = classify_artifact(TEXT, "PhysicalThing", "Product", entity_text="Redis cache")
    assert not step4["should_proceed"] and 0.45 <= step4["confidence"] < NOISE_FLOOR


@pytest.mark.asyncio
async def test_known_confirmed_entity_is_kept(db):
    await _seed(db, "user")
    summary = await _run(db)
    assert summary["evidence_rescues"] == 1
    assert summary["noise_count"] == 0
    # strong match to the seeded node -> reinforces it instead of duplicating
    assert summary["additive_updates"] == 1


@pytest.mark.asyncio
async def test_unknown_entity_is_still_dropped(db):
    summary = await _run(db)
    assert summary["evidence_rescues"] == 0
    assert summary["noise_count"] == 1


@pytest.mark.asyncio
async def test_tentative_neighbor_is_not_evidence(db):
    await _seed(db, "user", confidence_low=True)
    summary = await _run(db)
    assert summary["evidence_rescues"] == 0 and summary["noise_count"] == 1


@pytest.mark.asyncio
async def test_assistant_turn_ignores_unknown_origin_evidence(db):
    await _seed(db, None)            # pre-B459 node: origin unknown
    assert (await _run(db, role="assistant"))["evidence_rescues"] == 0


@pytest.mark.asyncio
async def test_retrieval_reused_and_skipped_outside_band(db, monkeypatch):
    calls = []
    real = orch.retrieve_candidates
    monkeypatch.setattr(orch, "retrieve_candidates",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    await _seed(db, "user")

    await _run(db)                                # in band: one retrieval, reused by Step 5
    assert len(calls) == 1

    calls.clear()
    agent = dict(ENTITY, gist_class="Agent")      # gist prior None -> noise at 0.0
    summary = await _run(db, entity=agent)
    assert calls == [] and summary["noise_count"] == 1
