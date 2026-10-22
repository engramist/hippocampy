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
    assert _DEFAULT_CONFIG["retrieval"]["graph_linking"] is False
    assert cl.graph_linking_enabled({}) is False
    assert cl.graph_linking_enabled(_DEFAULT_CONFIG) is False
    assert cl.graph_linking_enabled({"retrieval": {"graph_linking": True}}) is True
    cfg = apply_env_overrides({"retrieval": {}}, {"CAMPY_GRAPH_LINKING": "1"})
    assert cl.graph_linking_enabled(cfg) is True
    cfg = apply_env_overrides({"retrieval": {"graph_linking": True}}, {"CAMPY_GRAPH_LINKING": "0"})
    assert cl.graph_linking_enabled(cfg) is False
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


# --- the walk -----------------------------------------------------------------------

async def _walk(gw, concept_ids, **kw):
    return await gw.run("thalamus.bundle_concept_walk", concept_ids=concept_ids,
                        limit=kw.get("limit", 12), exclude=kw.get("exclude", []), skos=kw.get("skos", False))


async def test_walk_gathers_every_session_through_the_shared_concept(db, gw, store):
    """"How many model kits": three sessions, three different kits, none sharing a word with
    the question but the Concept; all three come back, oldest first."""
    await store.concept("c-kit", "model kit")
    texts = [("Picked up a Revell F-15 Eagle model kit.", 3), ("Finished the Tamiya Spitfire model kit.", 11),
             ("Started a Tiger I tank model kit.", 19)]
    mids = []
    for text, day in texts:
        mid = await store.message(text, day=day)
        await cl.link_message_concepts(gw, mid, text)
        mids.append(mid)
    noise = await store.message("Unrelated chat about cooking.", day=12)
    rows = await _walk(gw, ["c-kit"])
    assert [r["node_id"].rsplit("/", 1)[-1] for r in rows] == mids
    assert all(r["kind"] == "Message" and r["hop"] == 1 for r in rows)
    assert noise not in [r["node_id"].rsplit("/", 1)[-1] for r in rows]


async def test_walk_second_hop_reaches_siblings_parents_and_children(db, gw, store):
    for cid, text in [("c-kit", "model kit"), ("c-f15", "Revell F-15 Eagle"), ("c-spit", "Tamiya Spitfire"),
                      ("c-hobby", "hobby"), ("c-tiger", "Tiger I tank")]:
        await store.concept(cid, text)
    for child, parent in [("c-f15", "c-kit"), ("c-spit", "c-kit"), ("c-kit", "c-hobby")]:
        await gw.run("concept_links.link_is_a", cid=child, pid=parent)
    a = await store.message("The Revell F-15 Eagle is done.", day=3)
    b = await store.message("The Tamiya Spitfire is next.", day=9)
    c = await store.message("I love my hobby.", day=15)
    d = await store.message("A Tiger I tank sits on my shelf.", day=20)      # not related by IS_A
    for mid, text in [(a, "The Revell F-15 Eagle is done."), (b, "The Tamiya Spitfire is next."),
                      (c, "I love my hobby."), (d, "A Tiger I tank sits on my shelf.")]:
        await cl.link_message_concepts(gw, mid, text)
    ids = lambda rows: [r["node_id"].rsplit("/", 1)[-1] for r in rows]       # noqa: E731
    # from the F-15: its sibling (Spitfire) and its category's category (hobby is 2 IS_A away: not walked)
    rows = await _walk(gw, ["c-f15"])
    assert ids(rows) == [a, b] and [r["hop"] for r in rows] == [1, 2]
    # from the category: its children (both kits) and its parent (hobby)
    rows = await _walk(gw, ["c-kit"])
    assert ids(rows) == [a, b, c] and all(r["hop"] == 2 for r in rows)
    assert d not in ids(rows)


async def test_walk_cap_prefers_hop1_then_newest_and_shows_oldest_first(db, gw, store):
    await store.concept("c-kit", "model kit")
    await store.concept("c-f15", "Revell F-15 Eagle")
    await gw.run("concept_links.link_is_a", cid="c-f15", pid="c-kit")
    own = [await store.message(f"model kit number {i}", day=2 + i) for i in range(3)]
    sib = await store.message("Revell F-15 Eagle, finally.", day=25)
    for mid, text in [(m, f"model kit number {i}") for i, m in enumerate(own)] + [(sib, "Revell F-15 Eagle, finally.")]:
        await cl.link_message_concepts(gw, mid, text)
    rows = await _walk(gw, ["c-kit"], limit=3)
    got = [r["node_id"].rsplit("/", 1)[-1] for r in rows]
    # hop 1 = the three "model kit" turns (the F-15 turn is hop 2 and loses to them under the cap)
    assert got == own
    rows = await _walk(gw, ["c-kit"], limit=4)
    assert [r["node_id"].rsplit("/", 1)[-1] for r in rows] == own + [sib]


async def test_walk_excludes_shown_items_archived_and_assistant_rows(db, gw, store):
    await store.concept("c-kit", "model kit")
    keep = await store.message("model kit A", day=3)
    shown = await store.message("model kit B", day=4)
    gone = await store.message("model kit C", day=5)
    asst = await store.message("model kit D", day=6, role="assistant")
    for mid in (keep, shown, gone, asst):
        await gw.run("concept_links.link_message_concept", mid=mid, cid="c-kit")    # even a stray assistant link
    await db.execute_write(
        f"INSERT DATA {{ <https://campy.dev/id/Message/{gone}> {NS}archived> true }}")
    exclude = [f"https://campy.dev/id/Message/{shown}"]
    rows = await _walk(gw, ["c-kit"], exclude=exclude)
    assert [r["node_id"].rsplit("/", 1)[-1] for r in rows] == [keep]


async def test_walk_includes_observations_and_drops_superseded(db, gw, store):
    await store.concept("c-kit", "model kit")
    oid, mid = await _observe(db, gw, store, quote="I own a model kit", subject="I", predicate="owns",
                              obj="a model kit", day=4)
    await cl.link_observation_concepts(gw, oid, mid, subject_text="I", predicate="owns", object_text="a model kit")
    rows = await _walk(gw, ["c-kit"])
    kinds = {r["kind"]: r for r in rows}
    assert set(kinds) == {"Observation", "Message"}
    assert kinds["Observation"]["observation_id"] == oid and kinds["Observation"]["evidence_ref"] == mid
    await db.execute_write(f"INSERT DATA {{ <https://campy.dev/id/Observation/{oid}> {NS}superseded_by> \"x\" }}")
    assert [r["kind"] for r in await _walk(gw, ["c-kit"])] == ["Message"]


async def test_walk_drops_a_concept_that_is_in_most_of_the_conversation(db, gw, store, monkeypatch):
    await store.concept("c-sam", "Sam")
    for i in range(60):
        await gw.run("capture.create_message", message_id=f"s{i}", text_raw=f"Sam said {i}", embedding=None,
                     embedding_model="m", embedding_dim=DIM, role="user", byte_end=9,
                     created_at="2023-05-02T12:00:00+00:00")
        await gw.run("concept_links.link_message_concept", mid=f"s{i}", cid="c-sam")
    monkeypatch.setattr(gw._vector_store, "count_documents", lambda prefixes: 100)
    assert await _walk(gw, ["c-sam"]) == []
    monkeypatch.setattr(gw._vector_store, "count_documents", lambda prefixes: 10_000)
    assert len(await _walk(gw, ["c-sam"], limit=5)) == 5          # a big store: 60 is not "most"


# --- the bundle ---------------------------------------------------------------------

async def _three_session_store(gw, store):
    await store.concept("c-kit", "model kit")
    for text, day in [("Picked up a Revell F-15 Eagle model kit.", 3), ("Finished the Tamiya Spitfire model kit.", 11),
                      ("Started a Tiger I tank model kit.", 19)]:
        mid = await store.message(text, day=day)
        await cl.link_message_concepts(gw, mid, text)


async def test_bundle_flag_on_adds_a_linked_section_with_every_session(db, gw, store):
    await _three_session_store(gw, store)
    bundle = await bc.compile_bundle("How many model kits do I own?", db, ON)
    (section,) = [s for s in bundle.sections if s.section_type == "linked"]
    assert all(c["text"].startswith("[Sam, 2023-05-") for c in section.content)
    assert [("Revell" in c["text"], "Spitfire" in c["text"], "Tiger" in c["text"]) for c in section.content] \
        == [(True, False, False), (False, True, False), (False, False, True)]
    assert len(section.source_node_ids) == 3 and section.token_estimate > 0


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


async def test_bundle_does_not_repeat_what_the_conversation_stage_shows(db, gw, store):
    await _three_session_store(gw, store)
    on = await bc.compile_bundle("How many model kits do I own?", db, ON)
    shown = {nid for s in on.sections if s.section_type == "conversation" for nid in s.source_node_ids}
    linked = [nid for s in on.sections if s.section_type == "linked" for nid in s.source_node_ids]
    assert not shown & set(linked)


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
