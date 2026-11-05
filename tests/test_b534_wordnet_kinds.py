"""B534: WordNet proposes BROADER links between kinds that already exist.

A tiny in-test WordNet (same interface as NLTK's reader) pins the rule deterministically; a few tests
run against the real corpus when it is installed. Real Oxigraph store, no model, no network. Pins:
- hypernym links go only between EXISTING kinds, nearest first, never to a synonym, never a new kind;
- the sense cutoff (first sense, plus later senses with >= half its count) and compound lookups;
- the reverse direction (a new kind adopts existing narrower kinds);
- provenance: `campy:link_source "wordnet"` on the edge's reifier, read back by
  `kinds.broader_links_by_source` and `kinds.broader_links_detail`; label-rule links read as 'label_rule';
- idempotent; no cycle; an existing path is not duplicated;
- flag off = nothing; WordNet absent = nothing, and nothing breaks.
"""

from __future__ import annotations

import builtins
import uuid

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import entities as ent

DIM = 384


# --- a miniature WordNet (the NLTK reader's interface) ---------------------------------

class _Lemma:
    def __init__(self, name, count):
        self._n, self._c = name, count

    def name(self):
        return self._n

    def count(self):
        return self._c


class _Syn:
    def __init__(self, name, lemmas, lexname="noun.animal"):
        self._name, self._lemmas, self._lex = name, [_Lemma(n, c) for n, c in lemmas], lexname
        self._h: list[_Syn] = []
        self._ih: list[_Syn] = []

    def name(self):
        return self._name

    def lemmas(self):
        return self._lemmas

    def hypernyms(self):
        return self._h

    def instance_hypernyms(self):
        return self._ih

    def lexname(self):
        return self._lex


class _WN:
    def __init__(self):
        self.s: dict[str, _Syn] = {}
        self.index: dict[str, list[str]] = {}

    def add(self, name, lemmas, up=(), lexname="noun.animal"):
        syn = _Syn(name, lemmas, lexname)
        syn._h = [self.s[u] for u in up]
        self.s[name] = syn
        for lem, _ in lemmas:
            self.index.setdefault(lem.lower(), []).append(name)
        return syn

    def synsets(self, word, pos=None):
        return [self.s[n] for n in self.index.get(word.lower(), [])]

    def morphy(self, word, pos=None):
        w = word.lower()
        return w if w in self.index else (w[:-1] if w.endswith("s") and w[:-1] in self.index else None)

    def synset(self, name):
        return self.s[name]

    def ensure_loaded(self):
        return None


def fake_wordnet():
    w = _WN()
    w.add("entity.n.01", [("entity", 0)], lexname="noun.Tops")
    w.add("organism.n.01", [("organism", 0), ("being", 0)], ["entity.n.01"])
    w.add("animal.n.01", [("animal", 5), ("beast", 0)], ["organism.n.01"])
    w.add("canine.n.02", [("canine", 1)], ["animal.n.01"])
    w.add("dog.n.01", [("dog", 40), ("domestic_dog", 0)], ["canine.n.02"])
    w.add("puppy.n.01", [("puppy", 3), ("pup", 1)], ["dog.n.01"])
    w.add("pet.n.01", [("pet", 2)], ["animal.n.01"])
    w.add("cat.n.01", [("cat", 9)], ["animal.n.01"])
    w.add("artifact.n.01", [("artifact", 0)], ["entity.n.01"], "noun.artifact")
    w.add("vehicle.n.01", [("vehicle", 3)], ["artifact.n.01"], "noun.artifact")
    w.add("car.n.01", [("car", 80), ("auto", 5)], ["vehicle.n.01"], "noun.artifact")
    w.add("model_kit.n.01", [("model_kit", 0)], ["artifact.n.01"], "noun.artifact")
    # "bank": a frequent first sense, a half-as-frequent second, a rare third
    w.add("bank.n.01", [("bank", 20)], ["artifact.n.01"], "noun.artifact")      # institution-ish
    w.add("bank.n.02", [("bank", 12)], ["animal.n.01"])                         # >= half of 20
    w.add("bank.n.03", [("bank", 2)], ["vehicle.n.01"], "noun.artifact")        # below half
    return w


@pytest.fixture
def wn(monkeypatch):
    w = fake_wordnet()
    monkeypatch.setattr(wn_mod, "_wn", lambda: w)
    return w


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
    return OxigraphClient(tmp_path / "b534.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _kind(gw, label):
    cid = str(uuid.uuid4())
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=label, emb=[0.0] * DIM, gist="Entity",
                 stype="Thing", now="2026-01-01T00:00:00+00:00")
    await kinds_mod.mark_kind(gw, cid)
    return cid


async def _kinds(gw, *labels):
    return {lab: await _kind(gw, lab) for lab in labels}


async def _links(gw):
    return {(r["child"], r["parent"]): r["source"] for r in await gw.run("kinds.broader_links_detail")}


async def _backfill(gw):
    return await ent.propose_wordnet_links(gw)


# --- plan_links: pure given WordNet ---------------------------------------------------

async def test_links_go_to_the_nearest_existing_hypernym_kinds_only(gw, wn):
    await _kinds(gw, "puppy", "dog", "animal", "cat", "car")
    links = wn_mod.plan_links(await kinds_mod.load_kinds(gw))
    got = {(l.child_label, l.parent_label) for l in links}
    # puppy -> dog (nearest kind; "animal" sits above "dog" so it is not added), dog -> animal ("canine" is no kind),
    # cat -> animal; car has no hypernym kind ("vehicle" is not a kind), and no kind is invented
    assert got == {("puppy", "dog"), ("dog", "animal"), ("cat", "animal")}
    assert all(l.source == "wordnet" for l in links)
    puppy_dog = next(l for l in links if l.child_label == "puppy")
    assert puppy_dog.path == ["puppy.n.01", "dog.n.01"]


async def test_it_never_creates_a_kind(gw, wn):
    await _kinds(gw, "puppy")
    before = await kinds_mod.load_kinds(gw)
    assert wn_mod.plan_links(before) == []
    assert await _backfill(gw) == 0
    assert set(k.pref for k in (await kinds_mod.load_kinds(gw)).values()) == {"puppy"}


async def test_a_synonym_is_not_a_parent(gw, wn):
    await _kinds(gw, "puppy", "pup", "dog")
    got = {(l.child_label, l.parent_label) for l in wn_mod.plan_links(await kinds_mod.load_kinds(gw))}
    assert ("puppy", "pup") not in got and ("pup", "puppy") not in got
    assert {("puppy", "dog"), ("pup", "dog")} <= got


async def test_a_parent_can_be_named_by_an_altlabel(gw, wn):
    ids = await _kinds(gw, "puppy", "pet")
    await kinds_mod.add_alt_label(gw, kinds_mod.Kind(ids["pet"], "pet"), "animal")
    got = {(l.child_label, l.parent_label) for l in wn_mod.plan_links(await kinds_mod.load_kinds(gw))}
    assert ("puppy", "pet") in got


async def test_over_general_hypernyms_are_not_parents(gw, wn):
    await _kinds(gw, "dog", "entity")
    assert wn_mod.plan_links(await kinds_mod.load_kinds(gw)) == []


async def test_compound_labels_use_the_whole_phrase_then_the_head_word(gw, wn):
    await _kinds(gw, "model kit", "artifact", "service dog", "dog")
    got = {(l.child_label, l.parent_label) for l in wn_mod.plan_links(await kinds_mod.load_kinds(gw))}
    assert ("model kit", "artifact") in got              # "model_kit" is a WordNet entry
    assert ("service dog", "dog") not in got             # "service dog" is not in the lexicon; its head noun IS "dog": no link to itself
    assert wn_mod.head_words("my service dogs") == ["service_dogs", "dogs"]
    assert wn_mod.head_words("service dog") == ["service_dog", "dog"]
    assert wn_mod.head_words("my dog") == ["dog"]


# --- sense choice ----------------------------------------------------------------------

def test_sense_cutoff(wn):
    assert [s.name() for s in wn_mod.noun_synsets("bank")] == ["bank.n.01"]                       # the default: first sense only
    assert [s.name() for s in wn_mod.noun_synsets("bank", wn_mod.SENSE_FREQUENT)] == ["bank.n.01", "bank.n.02"]   # 12 >= 0.5 * 20, 2 < 10
    assert [s.name() for s in wn_mod.noun_synsets("bank", wn_mod.SENSE_FIRST_ONLY)] == ["bank.n.01"]
    assert [s.name() for s in wn_mod.noun_synsets("bank", 0.05)] == ["bank.n.01", "bank.n.02", "bank.n.03"]
    assert [s.name() for s in wn_mod.noun_synsets("dog")] == ["dog.n.01"]
    assert wn_mod.noun_synsets("zzz") == []


async def test_the_cutoff_changes_which_hypernyms_are_walked(gw, wn):
    await _kinds(gw, "bank", "animal", "vehicle")
    kinds = await kinds_mod.load_kinds(gw)
    default = {(l.child_label, l.parent_label) for l in wn_mod.plan_links(kinds)}
    frequent = {(l.child_label, l.parent_label) for l in wn_mod.plan_links(kinds, cutoff=wn_mod.SENSE_FREQUENT)}
    assert ("bank", "animal") in frequent and ("bank", "animal") not in default
    assert ("bank", "vehicle") not in frequent and ("bank", "vehicle") not in default


async def test_a_parent_kind_must_mean_the_hypernym_in_its_own_dominant_sense(gw, wn):
    wn.add("country.n.02", [("country", 30), ("nation", 5)], ["entity.n.01"], "noun.group")
    wn.add("area.n.01", [("area", 9), ("country", 0)], ["entity.n.01"], "noun.location")
    wn.add("venue.n.01", [("venue", 4)], ["area.n.01"], "noun.location")
    await _kinds(gw, "venue", "country")
    assert wn_mod.plan_links(await kinds_mod.load_kinds(gw)) == []              # "country" is a lemma of "area", not its main sense


# --- writes: provenance, idempotence, reverse direction -----------------------------------

async def test_the_link_is_written_with_its_source_and_read_back(gw, db, wn):
    ids = await _kinds(gw, "puppy", "dog", "animal")
    await kinds_mod.link_broader(gw, ids["dog"], ids["animal"])           # a label-rule (unsourced) link
    assert await _backfill(gw) == 1                                        # only puppy -> dog is new
    assert await _links(gw) == {("puppy", "dog"): "wordnet", ("dog", "animal"): "label_rule"}
    by_source = {r["source"]: int(r["n"]) for r in await gw.run("kinds.broader_links_by_source")}
    assert by_source == {"wordnet": 1, "label_rule": 1}


async def test_backfill_is_idempotent(gw, db, wn):
    await _kinds(gw, "puppy", "dog", "animal", "cat")
    await _backfill(gw)
    first = await _links(gw)
    reifiers = db._execute_and_collect("SELECT ?r WHERE { ?r <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> ?t }")
    await _backfill(gw)
    assert await _links(gw) == first
    again = db._execute_and_collect("SELECT ?r WHERE { ?r <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> ?t }")
    assert len(again) == len(reifiers) == len(first)


async def test_an_existing_path_is_not_duplicated_and_a_cycle_is_not_closed(gw, wn):
    ids = await _kinds(gw, "puppy", "dog", "animal")
    await kinds_mod.link_broader(gw, ids["puppy"], ids["dog"])
    await kinds_mod.link_broader(gw, ids["dog"], ids["animal"])
    await kinds_mod.link_broader_sourced(gw, ids["puppy"], ids["animal"], "wordnet")      # already implied
    await kinds_mod.link_broader_sourced(gw, ids["animal"], ids["puppy"], "wordnet")      # would close a cycle
    assert set(await _links(gw)) == {("puppy", "dog"), ("dog", "animal")}


async def test_a_new_kind_adopts_existing_narrower_kinds_and_joins_existing_broader_ones(gw, wn):
    ids = await _kinds(gw, "puppy", "animal")
    created = await _kind(gw, "dog")
    assert await ent.propose_wordnet_links(gw, {created}) == 2
    assert set(await _links(gw)) == {("puppy", "dog"), ("dog", "animal")}      # down to puppy, up to animal


async def test_links_involving_other_kinds_are_left_alone(gw, wn):
    await _kinds(gw, "puppy", "dog", "cat", "animal")
    created = await _kind(gw, "car")
    assert await ent.propose_wordnet_links(gw, {created}) == 0
    assert await _links(gw) == {}


async def test_resolve_kind_with_the_flag_links_a_new_kind(gw, wn):
    await _kinds(gw, "puppy", "animal")
    stats = type("S", (), {"kinds_wordnet": 0, "kinds_created": 0, "kinds_reused": 0, "entity_concepts_created": 0,
                           "kinds_broader": 0})()
    from campy.brain.hippocampus.concept_links import concept_index
    index = await concept_index(gw, alt_labels=True)
    await ent.resolve_kind(gw, "dog", index, stats, embedding_model="m", wordnet=True)
    assert stats.kinds_wordnet == 2
    assert await _links(gw) == {("puppy", "dog"): "wordnet", ("dog", "animal"): "wordnet"}


async def test_flag_off_writes_nothing(gw, wn):
    await _kinds(gw, "puppy", "animal")
    from campy.brain.hippocampus.concept_links import concept_index
    index = await concept_index(gw, alt_labels=True)
    stats = type("S", (), {"kinds_wordnet": 0, "kinds_created": 0, "kinds_reused": 0, "entity_concepts_created": 0,
                           "kinds_broader": 0})()
    await ent.resolve_kind(gw, "dog", index, stats, embedding_model="m")            # wordnet defaults to False
    assert await _links(gw) == {} and stats.kinds_wordnet == 0


def test_flag_default_off_and_env_on():
    assert _DEFAULT_CONFIG["observations"]["wordnet_kinds"] is False
    assert kinds_mod.wordnet_kinds_enabled(None) is False
    assert kinds_mod.wordnet_kinds_enabled({"observations": {"wordnet_kinds": True}}) is True
    assert apply_env_overrides({"observations": {}}, {"CAMPY_WORDNET_KINDS": "1"})["observations"]["wordnet_kinds"] is True


# --- WordNet absent -------------------------------------------------------------------

def _deny_nltk(monkeypatch):
    real = builtins.__import__

    def deny(name, *a, **k):
        if name.startswith("nltk"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", deny)


async def test_without_nltk_nothing_is_proposed_and_nothing_breaks(gw, monkeypatch):
    await _kinds(gw, "puppy", "dog", "animal")
    _deny_nltk(monkeypatch)
    assert wn_mod.available() is False
    assert wn_mod.lexname("dog") is None and wn_mod.noun_synsets("dog") == []
    assert wn_mod.plan_links(await kinds_mod.load_kinds(gw)) == []
    assert await _backfill(gw) == 0
    assert await _links(gw) == {}


# --- one loader for B523 and B534 -----------------------------------------------------

def test_the_ownership_test_uses_the_shared_loader(wn):
    from campy.brain.temporal_lobe.observations import ownership as ow

    assert ow._wordnet_lexname("car") == "noun.artifact" == wn_mod.lexname("car")
    assert ow._wordnet_lexname("dog") == "noun.animal"


# --- against the real corpus (skipped when not installed) -------------------------------

real = pytest.mark.skipif(not wn_mod.available(), reason="WordNet corpus not installed (optional extra `wordnet`)")


@real
async def test_real_wordnet_links_a_typical_pet_vocabulary(gw):
    await _kinds(gw, "puppy", "dog", "animal", "pet", "car", "vehicle", "tree", "plant")
    got = {(l.child_label, l.parent_label) for l in wn_mod.plan_links(await kinds_mod.load_kinds(gw))}
    assert {("puppy", "dog"), ("car", "vehicle"), ("pet", "animal")} <= got
    assert ("tree", "plant") not in got        # "plant" means a factory in its dominant sense: no link rather than a wrong one
    assert ("dog", "animal") in got
    assert ("car", "animal") not in got and ("dog", "vehicle") not in got


@real
def test_real_wordnet_lexnames():
    assert wn_mod.lexname("dog") == "noun.animal"
    assert wn_mod.lexname("haven") is not None
