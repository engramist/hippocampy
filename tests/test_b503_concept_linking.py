"""B503: link user turns and Observations to the Concepts they name, walk the
links at retrieval. Real Oxigraph store, no model, no LLM.

Pins:
- the flag (default off, env CAMPY_GRAPH_LINKING) and the writers staying idle when off;
- rule matching of spans against existing Concepts (normalised, never creates one);
- the written edges: Message MENTIONS Concept, Observation OBSERVATION_ABOUT Concept,
  Concept IS_A Concept (is_a claims whose ends both resolve);
- the walk: hop 1 (shared Concept), hop 2 (category / sibling / child), dedup, cap,
  event-time order, exclusion of what the bundle already shows, assistant turns and
  archived rows, and the speaker-like Concept trim;
- a "how many X" fixture: items mentioned across three sessions are all gathered;
- flag off: the bundle is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import concept_links as cl
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.thalamus import bundle_compiler as bc

pytestmark = pytest.mark.asyncio

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
NS = "<https://campy.dev/ns#"

ON = {"retrieval": {"graph_linking": True, "graph_linking_limit": 12, "conversation_token_budget": 0},
      "observations": {"retrieval": False}}
OFF = {"retrieval": {"graph_linking": False, "conversation_token_budget": 0},
       "observations": {"retrieval": False}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b503.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def concept(self, cid, text):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text,
                          emb=[0.0] * DIM, gist="Category", stype="DefinedTerm", now=T0)

    async def message(self, text, *, day, role="user", speaker="Sam", mid=None):
        self.n += 1
        mid = mid or f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run(
            "capture.create_message", message_id=mid, text_raw=text, embedding=None,
            embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        return mid

    def edges(self, edge):
        rows = self.db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
        return {(str(r["s"]).rsplit("/", 1)[-1], str(r["o"]).rsplit("/", 1)[-1]) for r in rows}


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


# --- flag ---------------------------------------------------------------------------

async def test_flag_default_off_and_env_turns_it_on():
    assert _DEFAULT_CONFIG["retrieval"]["graph_linking"] is True   # B514: on, walk limit 0
    assert cl.graph_linking_enabled({}) is False
    assert cl.graph_linking_enabled(_DEFAULT_CONFIG) is True
    assert cl.graph_linking_enabled({"retrieval": {"graph_linking": True}}) is True
    cfg = apply_env_overrides({"retrieval": {}}, {"CAMPY_GRAPH_LINKING": "1"})
    assert cl.graph_linking_enabled(cfg) is True
    cfg = apply_env_overrides({"retrieval": {"graph_linking": True}}, {"CAMPY_GRAPH_LINKING": "0"})
    assert cl.graph_linking_enabled(cfg) is False
    assert _DEFAULT_CONFIG["retrieval"]["graph_linking_limit"] == 0
    assert cl.graph_linking_limit({}) == 12 and cl.graph_linking_limit({"retrieval": {"graph_linking_limit": 5}}) == 5


# --- matching -----------------------------------------------------------------------

async def test_norm_key_is_symmetric_and_drops_function_words():
    assert cl.norm_key("your concert tickets") == cl.norm_key("Concert ticket") == "concert ticket"
    assert cl.norm_key("the Revell F-15 Eagle") == cl.norm_key("revell f-15 eagle")
    assert cl.norm_key("Sam's kayak") == "sam kayak"
    assert cl.norm_key("what") == "" and cl.norm_key("that") == "" and cl.norm_key("") == ""
    assert cl.norm_key("camping trips") == "camping trip"


async def test_spans_start_and_end_on_content_words_longest_first():
    spans = cl.candidate_spans("I built the Revell F-15 Eagle kit")
    assert spans[0].count(" ") == 2                       # 3-word spans lead
    assert "Revell F-15 Eagle" in spans and "Eagle kit" in spans
    assert not any(s.lower().startswith("the ") or s.lower().endswith(" the") for s in spans)


async def test_match_never_creates_and_ignores_stopword_concepts(gw, store):
    await store.concept("c-what", "what")
    await store.concept("c-kit", "model kit")
    await store.concept("c-eagle", "Revell F-15 Eagle")
    before = len(await gw.run("concept_links.live_concepts"))
    ids = await cl.match_concepts(gw, "What model kits? I got the Revell F-15 Eagle.")
    assert set(ids) == {"c-kit", "c-eagle"} and ids[0] == "c-eagle"      # longest span first
    assert len(await gw.run("concept_links.live_concepts")) == before


# --- write path ---------------------------------------------------------------------

async def test_message_links_resolved_and_rule_matched_concepts(gw, store):
    await store.concept("c-kit", "model kit")
    await store.concept("c-other", "kayak")
    await store.concept("c-res", "Resolved Elsewhere")
    mid = await store.message("I finished another model kit last night.", day=8)
    ids = await cl.link_message_concepts(gw, mid, "I finished another model kit last night.", ["c-res"])
    assert set(ids) == {"c-res", "c-kit"}
    assert store.edges("MENTIONS") == {(mid, "c-kit"), (mid, "c-res")}
    await cl.link_message_concepts(gw, mid, "I finished another model kit last night.", ["c-res"])   # idempotent
    assert len(store.edges("MENTIONS")) == 2


async def test_loop_hook_links_user_turns_only_and_only_with_the_flag(db, gw, store):
    await store.concept("c-kit", "model kit")
    u = await store.message("My model kit arrived.", day=8)
    a = await store.message("A model kit is a good hobby.", day=8, role="assistant")
    await orch._link_turn(u, "My model kit arrived.", "user", OFF, db, ())
    assert store.edges("MENTIONS") == set()                                  # flag off: nothing written
    await orch._link_turn(a, "A model kit is a good hobby.", "assistant", ON, db, ())
    assert store.edges("MENTIONS") == set()                                  # assistant turns are not evidence
    await orch._link_turn(u, "My model kit arrived.", "user", ON, db, ())
    assert store.edges("MENTIONS") == {(u, "c-kit")}


async def _observe(db, gw, store, *, quote, subject, predicate, obj, subject_id=None, object_id=None, day=8):
    mid = await store.message(f"Filler. {quote} More.", day=day)
    res = await obs.record_observation(db, obs.ObservationDraft(
        evidence_ref=mid, evidence_text=quote, subject_text=subject, predicate=predicate, object_text=obj,
        extraction_method="llm", confidence=0.9, subject_id=subject_id, object_id=object_id,
        speaker="Sam", text_raw=f"Sam - {predicate} - {obj}"))
    assert res.ok, res
    return res.observation_id, mid


async def test_observation_links_its_words_and_is_a_when_both_ends_resolve(db, gw, store):
    await store.concept("c-kit", "model kit")
    await store.concept("c-tiger", "Tiger I tank")
    await store.concept("c-tank", "tank")
    oid, mid = await _observe(db, gw, store, quote="my Tiger I tank is a tank", subject="Tiger I tank",
                              predicate="is_a", obj="tank")
    ids = await cl.link_observation_concepts(
        gw, oid, mid, subject_text="Tiger I tank", predicate="is_a", object_text="tank")
    assert set(ids) == {"c-tiger", "c-tank"}
    assert store.edges("OBSERVATION_ABOUT") == {(oid, "c-tiger"), (oid, "c-tank")}
    assert store.edges("MENTIONS") == {(mid, "c-tiger"), (mid, "c-tank")}
    assert store.edges("IS_A") == {("c-tiger", "c-tank")}

    # a first-person subject names nobody; a non-is_a claim writes no IS_A
    oid2, mid2 = await _observe(db, gw, store, quote="I own a model kit", subject="I", predicate="owns",
                                obj="a model kit")
    await cl.link_observation_concepts(gw, oid2, mid2, subject_text="I", predicate="owns", object_text="a model kit")
    assert (oid2, "c-kit") in store.edges("OBSERVATION_ABOUT")
    assert store.edges("IS_A") == {("c-tiger", "c-tank")}


async def test_link_existing_backfills_a_store_written_without_linking(db, gw, store):
    await store.concept("c-kit", "model kit")
    m = await store.message("Bought a model kit.", day=8)
    await store.message("Assistant chatter about a model kit.", day=8, role="assistant")
    oid, _ = await _observe(db, gw, store, quote="I own a model kit", subject="I", predicate="owns", obj="a model kit")
    stats = await cl.link_existing(db)
    assert stats["messages"] == 2 and stats["observations"] == 1       # the observation's own turn is a user turn
    assert (m, "c-kit") in store.edges("MENTIONS") and (oid, "c-kit") in store.edges("OBSERVATION_ABOUT")
    assert all(not k.startswith("m2") for k, _ in store.edges("MENTIONS"))   # the assistant turn
    again = await cl.link_existing(db)
    assert len(store.edges("MENTIONS")) == 2 and again["messages"] == 2


# --- the walk ---
# B560 replaced the store-wide walk with one anchored on the question's subject (SPOKEN_BY); its tests are
# in tests/test_b560_anchored_walk.py.


# --- the bundle ---------------------------------------------------------------------

async def _three_session_store(gw, store):
    await store.concept("c-kit", "model kit")
    for text, day in [("Picked up a Revell F-15 Eagle model kit.", 3), ("Finished the Tamiya Spitfire model kit.", 11),
                      ("Started a Tiger I tank model kit.", 19)]:
        mid = await store.message(text, day=day)
        await cl.link_message_concepts(gw, mid, text)


async def test_bundle_flag_off_is_unchanged(db, gw, store):
    await _three_session_store(gw, store)
    off = await bc.compile_bundle("How many model kits do I own?", db, OFF)
    assert not any(s.section_type == "linked" for s in off.sections)
    default = await bc.compile_bundle("How many model kits do I own?", db, {"observations": {"retrieval": False},
                                                                              "retrieval": {"conversation_token_budget": 0}})
    assert [(s.section_type, s.content) for s in off.sections] == [(s.section_type, s.content) for s in default.sections]
    on = await bc.compile_bundle("How many model kits do I own?", db, ON)
    assert [(s.section_type, s.content) for s in on.sections if s.section_type != "linked"] \
        == [(s.section_type, s.content) for s in off.sections]


async def test_bundle_without_question_concepts_has_no_linked_section(db, gw, store):
    await _three_session_store(gw, store)
    bundle = await bc.compile_bundle("Tell me about the weather", db, ON)
    assert not any(s.section_type == "linked" for s in bundle.sections)


# --- the Observation worker ---------------------------------------------------------

async def test_worker_links_claims_only_with_the_flag(db, gw, store, monkeypatch):
    import json
    from campy.brain.temporal_lobe.observations import extract as ex

    monkeypatch.setattr(ex.emb, "embed", lambda text, model_name=None: [0.05] * DIM)
    await store.concept("c-kit", "model kit")
    text = "I finished another model kit last week."
    reply = json.dumps([{"subject": "I", "predicate": "did", "object": "finished another model kit",
                         "time": "last week", "polarity": "asserted",
                         "quote": "I finished another model kit last week", "confidence": 0.9}])

    class LLM:
        def chat(self, messages, **kwargs):
            return reply

    cfg = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600}}
    off_mid = await store.message(text, day=8, mid="off")
    assert await ex.process_turn(db, cfg, LLM(), off_mid, ex.ObservationWorkerStats()) == 1
    assert store.edges("OBSERVATION_ABOUT") == set() and store.edges("MENTIONS") == set()

    on_mid = await store.message(text + " Really.", day=9, mid="on")
    cfg_on = {**cfg, "retrieval": {"graph_linking": True}}
    await ex.process_turn(db, cfg_on, LLM(), on_mid, ex.ObservationWorkerStats())
    assert {m for m, _ in store.edges("MENTIONS")} == {"on"}
    assert {c for _, c in store.edges("OBSERVATION_ABOUT")} == {"c-kit"}
