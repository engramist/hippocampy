"""B567: a proposed predicate in another form of an allowed one ("prefer" for "prefers") is kept as the allowed form;
any other predicate ("wrote") is still rejected. Made-up turns, scripted LLM, real Oxigraph store, no model."""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import extract as ex
from tests.b564_helpers import LLM, NS, Q, World, cfg, claim, extract

needs_wordnet = pytest.mark.skipif(not wn_mod.available(), reason="WordNet not installed")


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b567.db")


@pytest.fixture
def world(db):
    return World(db, GraphGateway(db, REGISTRY))


def predicates(db):
    rows = db._execute_and_collect(f"SELECT ?p WHERE {{ ?o a {NS}Observation> ; {NS}predicate> ?p }}")
    return sorted(str(r["p"]) for r in rows)


@needs_wordnet
def test_mapping_is_derived_from_the_nine():
    m = ex.predicate_by_lemma()
    assert set(m.values()) == set(ex.obs.PREDICATES)
    assert m["prefer"] == "prefers" and m["plan"] == "plans" and m["own"] == "owns" and m["do"] == "did"
    assert ex.predicate_lemma_key("relates to") == "relate_to" and m["relate_to"] == "relates_to"
    assert "write" not in m and "be" not in m


@needs_wordnet
async def test_prefer_is_kept_as_prefers_and_wrote_is_rejected(db, world):
    await world.concept("c-nora", "Nora")
    llm = LLM(claim("I prefer green tea", "green tea", predicate="prefer"),
              claim("I wrote a poem", "a poem", predicate="wrote"))
    _mid, stats = await extract(db, cfg(), world, "I prefer green tea and I wrote a poem last night.", llm,
                                speaker="Nora")
    assert predicates(db) == ["prefers"]
    assert stats.predicate_normalised == 1
    assert stats.rejected.get("bad_predicate") == 1


@needs_wordnet
async def test_an_allowed_predicate_is_not_counted(db, world):
    llm = LLM(claim("I prefer green tea", "green tea", predicate="prefers"))
    _mid, stats = await extract(db, cfg(), world, "I prefer green tea over coffee these days.", llm, speaker="Nora")
    assert predicates(db) == ["prefers"] and stats.predicate_normalised == 0
