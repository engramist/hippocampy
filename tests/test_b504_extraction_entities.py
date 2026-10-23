"""B504: extraction emits object entities and kinds into the graph (flag, default off).

Fake LLM, real Oxigraph store, no model. Pins:
- the flag (default off; env CAMPY_OBSERVATIONS_ENTITIES) and flag-off = unchanged (prompt, token cap, writes);
- rule validation: an entity must be in the turn, no pronouns / stopword-only / over-long names, a kind
  needs a valid entity; a hallucinated entity is dropped and the claim kept;
- Concepts created or reused, with OBSERVATION_ABOUT / MENTIONS / IS_A edges;
- facts inside a request turn, a plan's passing value yielding has_attribute (value must be in the turn);
- end to end: three sessions, three kits, B503's walk from "model kit" gathers all three.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import entities as ent
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.thalamus import bundle_compiler as bc

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
NS = "<https://campy.dev/ns#"
BASE = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600, "retrieval": False},
        "retrieval": {"conversation_token_budget": 0}}
ENT = {**BASE, "observations": {**BASE["observations"], "entities": True}}
BOTH = {**ENT, "retrieval": {"graph_linking": True, "graph_linking_limit": 12, "conversation_token_budget": 0}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b504.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def message(self, text, *, day=3, speaker="Sam"):
        self.n += 1
        mid = f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        return mid

    def edges(self, edge):
        rows = self.db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
        return {(str(r["s"]).rsplit("/", 1)[-1], str(r["o"]).rsplit("/", 1)[-1]) for r in rows}

    async def concepts(self):
        return {r["text_raw"] for r in await self.gw.run("concept_links.live_concepts")}

    async def cid(self, text):
        (cid,) = [r["concept_id"] for r in await self.gw.run("concept_links.live_concepts") if r["text_raw"] == text]
        return cid


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


class LLM:
    def __init__(self, *items):
        self.reply = json.dumps(list(items))
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.reply


def claim(quote, obj, *, predicate="did", entity=None, kind=None, subject="I", **extra):
    c = {"subject": subject, "predicate": predicate, "object": obj, "time": None,
         "polarity": "asserted", "quote": quote, "confidence": 0.9, **extra}
    if entity is not None:
        c["object_entity"] = entity
    if kind is not None:
        c["object_kind"] = kind
    return c


async def run(db, cfg, store, text, llm, day=3):
    mid = await store.message(text, day=day)
    stats = ex.ObservationWorkerStats()
    created = await ex.process_turn(db, cfg, llm, mid, stats)
    return mid, stats, created


# --- flag, and off = unchanged --------------------------------------------------------

def test_flag_default_off_env_on():
    assert _DEFAULT_CONFIG["observations"]["entities"] is False
    assert obs.observations_entities_enabled({}) is False
    assert obs.observations_entities_enabled(_DEFAULT_CONFIG) is False
    assert obs.observations_entities_enabled(apply_env_overrides({}, {"CAMPY_OBSERVATIONS_ENTITIES": "1"})) is True
    assert obs.observations_entities_enabled(
        apply_env_overrides({"observations": {"entities": True}}, {"CAMPY_OBSERVATIONS_ENTITIES": "0"})) is False


def test_flag_off_prompt_is_the_original_and_on_changes_schema_and_rules():
    off = ex.build_messages("I built a Tiger I kit.", "Sam", "2023-05-03")
    assert off[1]["content"] == ex.PROMPT_TEMPLATE.format(speaker="Sam", date="2023-05-03", text="I built a Tiger I kit.")
    assert "object_entity" not in off[1]["content"] and "questions and requests are not facts" in off[1]["content"]
    on = ex.build_messages("I built a Tiger I kit.", "Sam", "2023-05-03", entities=True)[1]["content"]
    assert '"object_entity"' in on and '"object_kind"' in on and "questions and requests are not facts" not in on
    assert "inside it are" in on and "25:50" in on


async def test_flag_off_unchanged_writes_and_ignores_entity_fields(db, gw, store):
    text = "I picked up the Revell F-15 Eagle model kit."
    llm = LLM(claim("I picked up the Revell F-15 Eagle model kit", "picked up the Revell F-15 Eagle model kit",
                    entity="Revell F-15 Eagle", kind="model kit"))
    _, stats, created = await run(db, BASE, store, text, llm)
    assert created == 1 and llm.calls[0][1] == {"max_tokens": ex.MAX_TOKENS}
    assert llm.calls[0][0][1]["content"].count("object_entity") == 0
    assert await store.concepts() == set()
    for e in ("OBSERVATION_ABOUT", "MENTIONS", "IS_A"):
        assert store.edges(e) == set()
    assert stats.entities_linked == 0 and stats.entity_rejected == 0


# --- validation -----------------------------------------------------------------------

def _stats():
    return ex.ObservationWorkerStats()


def test_entity_must_be_in_the_turn_case_insensitively():
    t = "Finished the Tamiya Spitfire this weekend"
    s = _stats()
    got = ent.validate_entity({"object_entity": "tamiya spitfire", "object_kind": "model kit"}, t, s)
    assert got == ent.EntityProposal("tamiya spitfire", "model kit") and s.entity_rejected == 0
    s = _stats()
    assert ent.validate_entity({"object_entity": "Hasegawa Zero", "object_kind": "model kit"}, t, s) is None
    assert (s.entity_rejected, s.kind_rejected) == (1, 1)     # hallucinated: kind goes with it


@pytest.mark.parametrize("name", ["it", "my", "the", "someone", "What", "12:30", "x" * 61,
                                  "one two three four five six seven"])
def test_entity_rejects_pronouns_stopwords_digits_and_long_names(name):
    s = _stats()
    turn = f"I said {name} yesterday and the rest"
    assert ent.validate_entity({"object_entity": name}, turn, s) is None and s.entity_rejected == 1


def test_kind_rules():
    t = "I visited Yellowstone"
    s = _stats()
    assert ent.validate_entity({"object_entity": "Yellowstone", "object_kind": "national park"}, t, s).kind == "national park"
    for bad in ("it", "yellowstone", "a very long kind phrase with many words", "x" * 41, "null"):
        s = _stats()
        got = ent.validate_entity({"object_entity": "Yellowstone", "object_kind": bad}, t, s)
        assert got is not None and got.kind is None
    s = _stats()
    assert ent.validate_entity({"object_kind": "national park"}, t, s) is None and s.kind_rejected == 1


def test_attribute_value_must_be_in_turn():
    t = "I'm hoping to beat my personal best time of 25:50 this year"
    assert ent.value_in_turn("has_attribute", "personal best time: 25:50", t)
    assert not ent.value_in_turn("has_attribute", "personal best time: 24:10", t)
    assert ent.value_in_turn("did", "anything at all", t)


# --- writes ---------------------------------------------------------------------------

async def test_entity_and_kind_become_concepts_with_edges(db, gw, store):
    text = "I picked up the Revell F-15 Eagle model kit."
    llm = LLM(claim("I picked up the Revell F-15 Eagle model kit", "picked up the Revell F-15 Eagle model kit",
                    entity="Revell F-15 Eagle", kind="model kit"))
    mid, stats, created = await run(db, ENT, store, text, llm)
    assert created == 1 and llm.calls[0][1] == {"max_tokens": ex.ENTITY_MAX_TOKENS}
    assert await store.concepts() == {"Revell F-15 Eagle", "model kit"}
    eagle, kit = await store.cid("Revell F-15 Eagle"), await store.cid("model kit")
    assert {c for _, c in store.edges("OBSERVATION_ABOUT")} == {eagle}
    assert store.edges("MENTIONS") == {(mid, eagle)}
    assert store.edges("IS_A") == {(eagle, kit)}
    assert (stats.entities_linked, stats.kinds_linked, stats.entity_concepts_created) == (1, 1, 2)


async def test_existing_concepts_are_reused_by_normalised_key(db, gw, store):
    await gw.run("temporal_lobe.dict_create_concept", cid="c-kit", text="Model Kits", emb=Q, gist="Category",
                 stype="DefinedTerm", now=datetime(2023, 5, 1, tzinfo=timezone.utc))
    text = "Finished the Tamiya Spitfire model kit."
    llm = LLM(claim("Finished the Tamiya Spitfire model kit", "finished the Tamiya Spitfire",
                    entity="Tamiya Spitfire", kind="model kit"))
    _, stats, _ = await run(db, ENT, store, text, llm)
    assert await store.concepts() == {"Model Kits", "Tamiya Spitfire"}
    assert {p for _, p in store.edges("IS_A")} == {"c-kit"} and stats.entity_concepts_created == 1


async def test_hallucinated_entity_is_dropped_but_claim_is_kept(db, gw, store):
    text = "Finished the Tamiya Spitfire model kit."
    llm = LLM(claim("Finished the Tamiya Spitfire model kit", "finished the Tamiya Spitfire",
                    entity="Hasegawa Zero", kind="model kit"))
    _, stats, created = await run(db, ENT, store, text, llm)
    assert created == 1 and stats.entity_rejected == 1
    assert await store.concepts() == set() and store.edges("IS_A") == set() and store.edges("MENTIONS") == set()


async def test_rerun_is_idempotent(db, gw, store):
    text = "I picked up the Revell F-15 Eagle model kit."
    llm = LLM(claim("I picked up the Revell F-15 Eagle model kit", "picked up the Revell F-15 Eagle model kit",
                    entity="Revell F-15 Eagle", kind="model kit"))
    mid, _, _ = await run(db, ENT, store, text, llm)
    await ex.process_turn(db, ENT, llm, mid, _stats())
    assert len(await store.concepts()) == 2 and len(store.edges("IS_A")) == 1


# --- facts inside requests and plans --------------------------------------------------

async def test_request_turn_yields_a_fact(db, gw, store):
    text = "Can you suggest paint for the Tiger I tank model kit I just started?"
    llm = LLM(claim("I just started", "started the Tiger I tank model kit", entity="Tiger I", kind="model kit"))
    _, stats, created = await run(db, ENT, store, text, llm)
    assert created == 1 and await store.concepts() == {"Tiger I", "model kit"}
    assert "inside it are" in llm.calls[0][0][1]["content"]


async def test_plan_with_passing_value_also_yields_has_attribute(db, gw, store):
    text = "I'm hoping to beat my personal best time of 25:50 at the 5K next month."
    llm = LLM(
        claim("hoping to beat my personal best time of 25:50", "beat my personal best", predicate="plans"),
        claim("my personal best time of 25:50", "personal best time: 25:50", predicate="has_attribute"),
        claim("my personal best time of 25:50", "personal best time: 24:10", predicate="has_attribute"))
    mid, stats, created = await run(db, ENT, store, text, llm)
    assert created == 2 and stats.rejected == {"value_not_in_turn": 1}
    rows = await gw.run("observations.list_for_message", mid=mid) if "observations.list_for_message" in REGISTRY else None
    if rows is not None:
        assert sorted(r["predicate"] for r in rows) == ["has_attribute", "plans"]


# --- end to end -----------------------------------------------------------------------

async def test_how_many_model_kits_walk_gathers_all_three(db, gw, store):
    sessions = [("Picked up a Revell F-15 Eagle model kit.", 3, "Revell F-15 Eagle"),
                ("Finished the Tamiya Spitfire model kit.", 11, "Tamiya Spitfire"),
                ("Started a Tiger I tank model kit.", 19, "Tiger I")]
    for text, day, name in sessions:
        llm = LLM(claim(text.rstrip("."), text.rstrip("."), entity=name, kind="model kit"))
        await run(db, BOTH, store, text, llm, day=day)
    assert len(store.edges("IS_A")) == 3
    bundle = await bc.compile_bundle("How many model kits do I own?", db, BOTH)
    (section,) = [s for s in bundle.sections if s.section_type == "linked"]
    turns = [c["text"] for c in section.content if c["type"] == "Message"]
    assert [("Revell" in t, "Spitfire" in t, "Tiger" in t) for t in turns] \
        == [(True, False, False), (False, True, False), (False, False, True)]
