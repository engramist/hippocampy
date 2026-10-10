"""B473: two sources of graph noise found by B472's Phase 0 audit.

campy-benchmarks R20a (DMR, 50 questions, hippocampy 402c96c, llama3.1:8b),
diag_graph_audit.py over the 50 kept stores:

- 943 ALTERNATIVE_TO, 233 CHOSEN_OVER and 162 EXTENDS edges -- types only
  Step 3b's LLM writes -- on personal chat ("Mustang" / "my car");
- 1,784 of 2,047 Concepts (87%) with no gist class: `_store_relation`
  created a bare Concept (`create_minimal_concept`) for every endpoint string
  that matched none, and an LLM's endpoint strings are its own wording.

Fixes: the Loop asks Step 3b only when the sentence has a choice,
replacement, realization or extension cue; an LLM relation is stored only
between Concepts that already exist (by text or label). Step 1b's syntactic
relations still create their endpoints, as B32/B464 need.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.temporal_lobe.loop.step3b_relations import has_relation_cue

DIM = 384
VEC = [1.0] + [0.0] * (DIM - 1)
NOW = "2026-10-10T10:00:00+00:00"


@pytest.mark.parametrize("text", [
    "We migrated from PostgreSQL 14 to PostgreSQL 16.",
    "Zipkin has been replaced by OpenTelemetry.",
    "Final decision: nose2 has been replaced by pytest.",
    "We chose React over Vue.",
    "Let's use Redis instead of Memcached.",
    "Valkey is an alternative to Redis.",
    "React extends JavaScript.",
    "Our service is built on FastAPI.",
    "Alice moved the billing service from Heroku to Fly.io in Berlin.",
    "We switched to uv.",
])
def test_sentences_that_can_state_a_semantic_relation(text):
    assert has_relation_cue(text)


@pytest.mark.parametrize("text", [
    "I spent the day working on my Mustang, my car is great.",
    "I love Taylor Swift and wrestling.",
    "We went to the park over the weekend.",
    "I drove from Boston to Denver.",
    "My sister is a nurse at Mercy Hospital.",
])
def test_chat_without_a_cue(text):
    assert not has_relation_cue(text)


# --- the Loop asks Step 3b only with a cue ----------------------------------------------

def _two_entities(monkeypatch, asked: list):
    ents = [{"text": "Mustang", "label": "PRODUCT", "start": 0, "end": 7},
            {"text": "Taylor Swift", "label": "PERSON", "start": 10, "end": 22}]
    monkeypatch.setattr(orch, "extract_entities", lambda text, model_name=None: (None, [dict(e) for e in ents]))
    monkeypatch.setattr(orch, "extract_relations", lambda doc, entities: [])
    monkeypatch.setattr(orch, "classify_concept",
                        lambda *a, **k: {"gist_class": "PhysicalThing", "confidence": 0.9, "system": "1",
                                         "vector": list(VEC)})
    monkeypatch.setattr(orch, "classify_artifact",
                        lambda *a, **k: {"artifact_type": None, "confidence": 0.1, "confidence_low": True,
                                         "should_proceed": False})

    def relations(entities, text, llm):
        asked.append(text)
        return []

    monkeypatch.setattr(orch, "extract_semantic_relations", relations)


@pytest.mark.asyncio
async def test_no_cue_no_step3b_call(monkeypatch):
    asked: list = []
    _two_entities(monkeypatch, asked)
    summary = await orch.run_loop("m1", "I love my Mustang and Taylor Swift.", None, None, {}, {})
    assert asked == []
    assert summary["step3b_skipped_no_cue"] == 1


@pytest.mark.asyncio
async def test_a_cue_still_reaches_step3b(monkeypatch):
    asked: list = []
    _two_entities(monkeypatch, asked)
    await orch.run_loop("m1", "I chose the Mustang instead of a Taylor Swift ticket.", None, None, {}, {})
    assert len(asked) == 1


# --- an LLM relation needs existing endpoints ----------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(orch.emb, "embed", lambda text, model_name=None: list(VEC))
    return OxigraphClient(tmp_path / "b473.db")


def _concept_texts(db) -> list[str]:
    rows = db._execute_and_collect(
        "SELECT ?t WHERE { ?c a <https://campy.dev/ns#Concept> ; <https://campy.dev/ns#text_raw> ?t }")
    return sorted(r["t"] for r in rows)


def _edges(db, rel: str) -> int:
    rows = db._execute_and_collect(
        f"SELECT (COUNT(*) AS ?n) WHERE {{ ?a <https://campy.dev/ns#{rel}> ?b }}")
    return int(rows[0]["n"]) if rows else 0


async def _concept(db, text: str) -> str:
    return await orch._store_concept({"text": text}, {"confidence": 0.9, "confidence_low": False},
                                     list(VEC), "m", db, NOW)


@pytest.mark.asyncio
async def test_an_llm_relation_with_an_unknown_endpoint_creates_nothing(db):
    await _concept(db, "Mustang")
    rel = {"head": "my car", "relation_type": "ALTERNATIVE_TO", "tail": "Mustang", "inferred_by": "LLM"}
    assert await orch._store_relation(rel, db, NOW, embedding_model="m") == "unresolved"
    assert _concept_texts(db) == ["Mustang"]  # no bare "my car" Concept
    assert _edges(db, "ALTERNATIVE_TO") == 0


@pytest.mark.asyncio
async def test_an_llm_relation_between_existing_concepts_is_stored(db):
    await _concept(db, "Redis")
    vk = await _concept(db, "Valkey")
    # one endpoint known only by an alternative label (B472 Phase 2)
    await orch._attach_alt_label({"concept_id": vk, "text_raw": "Valkey"}, "valkey-server", VEC, db, NOW)
    rel = {"head": "valkey-server", "relation_type": "ALTERNATIVE_TO", "tail": "Redis", "inferred_by": "LLM"}
    assert await orch._store_relation(rel, db, NOW, embedding_model="m") != "unresolved"
    assert _concept_texts(db) == ["Redis", "Valkey"]
    assert _edges(db, "ALTERNATIVE_TO") == 1


@pytest.mark.asyncio
async def test_a_step1b_relation_still_creates_its_endpoints(db):
    # B464: "Final decision: nose2 has been replaced by pytest" -- the
    # relation can be the only place the current value is named
    rel = {"head": "pytest", "relation_type": "REPLACES", "tail": "nose2", "inferred_by": "system", "names": True}
    await orch._store_relation(rel, db, NOW, embedding_model="m")
    assert _concept_texts(db) == ["nose2", "pytest"]
    assert _edges(db, "REPLACES") == 1


def test_endpoint_lookup_prefers_exact_text_then_labels(db):
    gw = GraphGateway(db, REGISTRY)
    assert orch._endpoint_concept_id("nothing here", gw) is None
