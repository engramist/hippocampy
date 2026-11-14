"""B565: a closed-class word (we, it, what, something...) is never a Concept.

Made-up data, no model. Pins the rule and its near misses, the refusal in each Concept writer, the cleanup (archive,
count of facts left without a subject) and that step Q's object query stops naming "What" after it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from campy.brain.hippocampus import entity_admission
from campy.brain.hippocampus import entity_hygiene
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.queries.query_hits import question_terms
from campy.brain.temporal_lobe.lexicon.closed_class import CLOSED_CLASS_WORDS, is_closed_class
from campy.brain.temporal_lobe.loop import orchestrator
from campy.brain.temporal_lobe.observations import entities as obs_entities
from tests.b564_helpers import NS, Q, World
from tests.test_query_hits import SESSION, build, fact, sessions


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b565.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def concepts(db):
    rows = db._execute_and_collect(f"SELECT ?t WHERE {{ ?c a {NS}Concept> ; {NS}text_raw> ?t }}")
    return sorted(str(r["t"]) for r in rows)


@pytest.mark.parametrize("word", ["we", "We", "What", "what", "who", "I", "it", "something", "Everyone", "ourselves",
                                  "the", "is", "because", " they "])
def test_closed_class_words(word):
    assert is_closed_class(word)


@pytest.mark.parametrize("word", ["US", "IT", "WHO", "Will", "May", "Mine", "Can", "Ivy", "The Who", "part", "one",
                                  "show", "It Ends with Us", "down", "over", "", None])
def test_names_and_open_class_words_pass(word):
    assert not is_closed_class(word)


def test_list_leaves_out_words_with_a_noun_or_name_reading():
    assert not CLOSED_CLASS_WORDS & {"will", "may", "can", "might", "must", "mine", "do", "does", "down", "past",
                                     "like", "round", "over", "one", "other", "part", "show", "no", "all"}


async def test_loop_store_concept_refuses(db):
    assert await orchestrator._store_concept({"text": "We"}, {"confidence": 0.9}, Q, "m", db, "2023-05-01") is None
    assert concepts(db) == []


async def test_extractor_entity_path_refuses_and_still_creates_names(db, gw):
    stats = SimpleNamespace(entity_concepts_created=0)
    assert await obs_entities._concept_for(gw, "something", {}, stats, embedding_model="m") is None
    assert await obs_entities._concept_for(gw, "Biscuit", {}, stats, embedding_model="m")
    assert concepts(db) == ["Biscuit"] and stats.entity_concepts_created == 1


async def test_entity_admission_refuses(db, gw):
    assert await entity_admission._concept_for(gw, "what", "m") is None
    assert await entity_admission._concept_for(gw, "US", "m")      # an acronym is a name
    assert concepts(db) == ["US"]


async def test_cleanup_archives_closed_class_and_counts_unanchored_facts(db, gw):
    mids, facts = await build(db, gw)
    w = World(db, gw)
    for cid, name in (("c-what", "What"), ("c-we", "we"), ("c-us", "US")):
        await w.concept(cid, name)
        await gw.run("concept_links.link_message_concept", mid=mids["adopt"], cid=cid)
    we_fact = await fact(db, mids["guitar"], "I bought a guitar", "guitar", "c-guitar", subject_id="c-we")

    terms = [t for t, _ in question_terms("What pets does Nora have?")]
    named = lambda: gw.run("query_hits.objects_in_sessions", terms=terms, sid="c-nora", sessions=sessions(SESSION))
    assert sorted(r["kid"] for r in await named()) == ["c-what", "k-pet"]

    dry = await entity_hygiene.archive_closed_class_concepts(gw, dry_run=True)
    assert [(r["label"], int(r["subject_facts"])) for r in dry] == [("What", 0), ("we", 1)]
    assert await entity_hygiene.facts_left_without_subject(gw) == 0          # nothing archived yet

    rows = await entity_hygiene.archive_closed_class_concepts(gw)
    assert [r["concept_id"] for r in rows] == ["c-what", "c-we"]
    assert await entity_hygiene.facts_left_without_subject(gw) == 1
    assert [r["kid"] for r in await named()] == ["k-pet"]                      # "What" is no longer named
    assert await entity_hygiene.archive_closed_class_concepts(gw) == []        # idempotent
    live = db._execute_and_collect(f"ASK {{ ?c {NS}concept_id> \"c-us\" . FILTER NOT EXISTS {{ ?c {NS}archived> true }} }}")
    assert live and we_fact
