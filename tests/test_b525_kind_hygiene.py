"""B525: kind labels are clean singular nouns; meta-nouns are never kinds.

Fake LLM, real Oxigraph store, real spaCy tagger (the one the NER step loads), no model call. Pins:
- the normalisation rule: determiners dropped, last word singular (regular and irregular plurals,
  multiword kinds), possessives dropped, plural-only nouns kept, the suffix fallback without spaCy;
- the write path behind `[observations] kind_hygiene` (env CAMPY_KIND_HYGIENE, default off): the clean
  label is the kind, the surface wording is its altLabel, a meta-noun is dropped and counted; flag off
  leaves B508 exactly;
- the migration: kinds that collapse to one label merge (INSTANCE_OF and BROADER re-pointed, the old
  wording kept as an altLabel, the merged kind archived and not deleted), a meta-noun kind loses its
  INSTANCE_OF edges and is archived, a shadowing altLabel is detached, a second run plans nothing.
"""

from __future__ import annotations

import json
import uuid

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import extract as ex

DIM = 384
NS = "<https://campy.dev/ns#"
BASE = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600,
                         "retrieval": False, "entities": True}}


def cfg(*, hygiene):
    return {"observations": {**BASE["observations"], "kind_hygiene": hygiene},
            "retrieval": {"graph_linking": True, "graph_linking_limit": 12, "conversation_token_budget": 0,
                          "skos_vocab": True, "skos_closematch_threshold": 0.0}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    seen: dict[str, int] = {}

    def embed(text, model_name=None):
        v = [0.0] * DIM
        v[seen.setdefault(text.casefold(), len(seen) % DIM)] = 1.0
        return v

    monkeypatch.setattr(embeddings_mod, "embed", embed)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b525.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


# --- the rule (pure) -----------------------------------------------------------------

@pytest.mark.parametrize("label, clean", [
    ("my dogs", "dog"), ("puppies", "puppy"), ("model kits", "model kit"), ("Model Kits", "Model Kit"),
    ("your students", "student"), ("this dish", "dish"), ("these photos", "photo"), ("their gardens", "garden"),
    ("the children", "child"), ("mice", "mouse"), ("wolves", "wolf"), ("a dance studio", "dance studio"),
    ("business", "business"), ("dog", "dog"), ("binoculars", "binoculars"), ("fashion trends", "fashion trend"),
    ("dog's", "dog"), ("  my  dogs. ", "dog"),
])
def test_normalise_kind_label(label, clean):
    assert kinds_mod.normalise_kind_label(label) == clean


@pytest.mark.parametrize("label", ["name", "names", "my name", "the thing", "things", "type", "kinds", "sort", "stuff",
                                   "one", "item", "examples", "part", "way", "lot", "bit", "", "   ", "...", None])
def test_meta_nouns_and_empties_are_not_kinds(label):
    assert kinds_mod.normalise_kind_label(label) is None


def test_a_meta_noun_inside_a_longer_label_is_still_a_kind():
    assert kinds_mod.normalise_kind_label("flooring types") == "flooring type"
    assert kinds_mod.normalise_kind_label("name tag") == "name tag"


def test_without_spacy_a_suffix_rule_applies(monkeypatch):
    monkeypatch.setattr(kinds_mod, "_default_nlp", lambda: None)
    assert kinds_mod.normalise_kind_label("my puppies") == "puppy"
    assert kinds_mod.normalise_kind_label("model kits") == "model kit"
    assert kinds_mod.normalise_kind_label("business") == "business"
    assert kinds_mod.normalise_kind_label("glasses") == "glasses"


def test_flag_default_off_and_env_on():
    assert _DEFAULT_CONFIG["observations"]["kind_hygiene"] is False
    assert kinds_mod.kind_hygiene_enabled(None) is False
    assert kinds_mod.kind_hygiene_enabled({"observations": {"kind_hygiene": True}}) is True
    assert apply_env_overrides({"observations": {}}, {"CAMPY_KIND_HYGIENE": "1"})["observations"]["kind_hygiene"] is True


# --- the write path ------------------------------------------------------------------

class LLM:
    def __init__(self, *items):
        self.reply = json.dumps(list(items))

    def chat(self, messages, **kwargs):
        return self.reply


async def _feed(db, gw, n, config, text, entity, kind):
    mid = f"m{n}"
    stamp = f"2023-05-{n + 1:02d}T12:00:00+00:00"
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None, embedding_model="m",
                 embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
    await gw.run("capture.set_message_source", message_id=mid, speaker="Sam", occurred_at=stamp)
    q = text.rstrip(".")
    claim = {"subject": "I", "predicate": "did", "object": q, "time": None, "polarity": "asserted", "quote": q,
             "confidence": 0.9, "object_entity": entity, "object_kind": kind}
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, config, LLM(claim), mid, stats)
    return stats


async def _kinds(gw):
    return {k.pref: k for k in (await kinds_mod.load_kinds(gw)).values()}


async def _edges(db, gw, edge):
    names = {r["concept_id"]: r["text_raw"] for r in await gw.run("concept_links.live_concepts")}
    rows = db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
    return {(names.get(str(r["s"]).rsplit("/", 1)[-1]), names.get(str(r["o"]).rsplit("/", 1)[-1])) for r in rows}


async def test_write_path_clean_label_with_surface_as_altlabel(db, gw):
    c = cfg(hygiene=True)
    await _feed(db, gw, 1, c, "Adopted Toby from my dogs.", "Toby", "my dogs")
    await _feed(db, gw, 2, c, "Got Pixie, one of the puppies.", "Pixie", "puppies")
    await _feed(db, gw, 3, c, "Walked Buddy with the dogs.", "Buddy", "dogs")
    kinds = await _kinds(gw)
    assert set(kinds) == {"dog", "puppy"}
    assert set(kinds["dog"].alts) == {"my dogs", "dogs"} and kinds["puppy"].alts == ["puppies"]
    assert await _edges(db, gw, "INSTANCE_OF") == {("Toby", "dog"), ("Buddy", "dog"), ("Pixie", "puppy")}


async def test_write_path_meta_noun_is_dropped_and_counted(db, gw):
    stats = await _feed(db, gw, 1, cfg(hygiene=True), "Adopted Scout last week.", "Scout", "name")
    assert await _kinds(gw) == {}
    assert await _edges(db, gw, "INSTANCE_OF") == set()
    assert stats.kinds_dropped_meta == 1


async def test_flag_off_is_the_b508_behaviour(db, gw):
    stats = await _feed(db, gw, 1, cfg(hygiene=False), "Adopted Toby from my dogs.", "Toby", "my dogs")
    await _feed(db, gw, 2, cfg(hygiene=False), "Adopted Scout last week.", "Scout", "name")
    assert set(await _kinds(gw)) == {"my dogs", "name"}
    assert stats.kinds_dropped_meta == 0


# --- the migration -------------------------------------------------------------------

async def _concept(gw, label, *, kind=False):
    cid = str(uuid.uuid4())
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=label, emb=[0.0] * DIM, gist="Entity",
                 stype="Thing", now="2026-01-01T00:00:00+00:00")
    if kind:
        await kinds_mod.mark_kind(gw, cid)
    return cid


async def _live_edges(db, gw, edge):
    """Edges between live OR archived concepts, by label (archived kinds keep their label)."""
    rows = db._execute_and_collect(
        f"SELECT ?a ?b WHERE {{ ?x {NS}{edge}> ?y . ?x {NS}text_raw> ?a . ?y {NS}text_raw> ?b }}")
    return {(str(r["a"]), str(r["b"])) for r in rows}


async def _legacy_store(gw):
    """'my dogs' (2 instances) and 'dog' (1) collapse; 'puppies' is narrower than 'my dogs'; 'name' is a meta-noun;
    'animals' carries the altLabel 'dogs', which would make 'dogs' name two kinds."""
    ids = {}
    for label in ("my dogs", "dog", "puppies", "name", "animals", "pet"):
        ids[label] = await _concept(gw, label, kind=True)
    for ent, kind in (("Toby", "my dogs"), ("Buddy", "my dogs"), ("Rex", "dog"), ("Scout", "name"), ("Max", "pet")):
        await kinds_mod.link_instance_of(gw, await _concept(gw, ent), ids[kind])
    await kinds_mod.link_broader(gw, ids["puppies"], ids["my dogs"])
    await kinds_mod.link_broader(gw, ids["my dogs"], ids["pet"])
    await kinds_mod.add_alt_label(gw, kinds_mod.Kind(ids["animals"], "animals"), "dogs")
    return ids


async def _migrate(gw):
    kinds = await kinds_mod.load_kinds(gw)
    counts = {str(r["concept_id"]): int(r["n"]) for r in await gw.run("kinds.instance_counts")}
    plan = kinds_mod.plan_hygiene(kinds, counts)
    return plan, await kinds_mod.apply_hygiene(gw, plan, kinds)


async def test_migration_merges_relabels_drops_meta_and_is_idempotent(db, gw):
    ids = await _legacy_store(gw)
    plan, done = await _migrate(gw)

    assert plan.merge == {ids["my dogs"]: ids["dog"]}                    # two kinds -> one; the clean label survives
    assert plan.relabel == {ids["puppies"]: "puppy", ids["animals"]: "animal"}
    assert plan.drop_meta == [ids["name"]]
    assert done == {"relabelled": 2, "merged": 1, "meta_archived": 1, "alt_labels": 3, "alts_detached": 1}

    kinds = await _kinds(gw)                                              # live kinds only
    assert set(kinds) == {"dog", "puppy", "animal", "pet"}
    assert kinds["dog"].alts == ["my dogs"] and kinds["puppy"].alts == ["puppies"]
    assert kinds["animal"].alts == ["animals"]                            # 'dogs' no longer names 'animal'
    inst = await _live_edges(db, gw, "INSTANCE_OF")
    assert inst == {("Toby", "dog"), ("Buddy", "dog"), ("Rex", "dog"), ("Max", "pet")}
    broader = await _live_edges(db, gw, "BROADER")
    assert broader == {("puppy", "dog"), ("dog", "pet")}                  # re-pointed, no self-loop

    archived = {str(r["t"]) for r in db._execute_and_collect(
        f"SELECT ?t WHERE {{ ?c {NS}archived> true ; {NS}text_raw> ?t ; {NS}kind_scheme> 'kind' }}")}
    assert archived == {"my dogs", "name"}                                # archived, not deleted
    assert {r["text_raw"] for r in await gw.run("concept_links.live_concepts")} >= {"Scout", "Toby"}

    plan2, done2 = await _migrate(gw)                                     # idempotent
    assert (plan2.merge, plan2.relabel, plan2.drop_meta, plan2.detach_alts) == ({}, {}, [], [])
    assert not any(done2.values())


def test_plan_survivor_is_deterministic_and_prefers_the_clean_label():
    k = {"b": kinds_mod.Kind("b", "my dogs"), "a": kinds_mod.Kind("a", "dogs")}
    p = kinds_mod.plan_hygiene(k, {"a": 1, "b": 9})                       # neither is clean: most instances wins
    assert p.merge == {"a": "b"} and p.relabel == {"b": "dog"}
    k["c"] = kinds_mod.Kind("c", "dog")
    p = kinds_mod.plan_hygiene(k, {"a": 1, "b": 9, "c": 0})               # a clean label outranks instance count
    assert p.merge == {"a": "c", "b": "c"} and p.relabel == {}
