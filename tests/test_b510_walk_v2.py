"""B510: the precise graph walk (flag `CAMPY_GRAPH_WALK_V2`, default off). Real Oxigraph
store, no model, no LLM.

Pins:
- the flag, its env override and its knobs; flag off = B503's walk exactly, v2 on replaces it;
- anchor selection: a typed entity, or a kind with 2..12 instances (through its instances);
  never an untyped Concept, a participant (a Message `speaker`), a Concept linked to more than
  the share cap of the messages, a kind that saturates the store, or a kind with 1 or >12 instances;
- coverage: an anchor the conversation already mentions (edge or words) adds nothing;
- only what is missing: turns already shown (conversation, semantic evidence refs) are dropped,
  de-duplicated by source message, not node id;
- ordering and the cap: hop 1 before hop 2, then anchors hit, then similarity; at most `limit`;
- the budget: conversation + linked never exceeds the conversation alone; the weakest turns go;
  the protected best-matched turns stay; a closer turn is never swapped for a farther one.
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
from campy.brain.hippocampus.graph.vector_store import mint_uri
from campy.brain.hippocampus.graph.walk_v2 import WalkV2
from campy.brain.thalamus import bundle_compiler as bc
from campy.brain.thalamus.bundle_compiler import BundleSection

pytestmark = pytest.mark.asyncio

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
MSG = "https://campy.dev/id/Message/"

V2 = {"retrieval": {"graph_linking": True, "graph_walk_v2": True, "conversation_token_budget": 0},
      "observations": {"retrieval": False}}
V1 = {"retrieval": {"graph_linking": True, "graph_linking_limit": 12, "conversation_token_budget": 0},
      "observations": {"retrieval": False}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b510.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def concept(self, cid, text, *, kind_of=None, is_kind=False):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text,
                          emb=[0.0] * DIM, gist="Category", stype="DefinedTerm", now=T0)
        if is_kind:
            await self.gw.run("kinds.mark_kind", cid=cid, scheme="kind")
        if kind_of:
            await self.gw.run("kinds.link_instance_of", cid=cid, kid=kind_of)

    async def message(self, text, *, day=3, speaker="Sam", role="user", mentions=(), mid=None, vec=None):
        self.n += 1
        mid = mid or f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run(
            "capture.create_message", message_id=mid, text_raw=text, embedding=None,
            embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        for cid in mentions:
            await self.gw.run("concept_links.link_message_concept", mid=mid, cid=cid)
        if vec is not None:
            self.gw._vector_store.upsert_vector(f"{MSG}{mid}", vec)
        return mid

    async def session(self, name, *mids):
        sid = f"https://campy.dev/id/Session/{name}"
        for m in mids:
            await self.db.execute_write(
                f"INSERT DATA {{ <{MSG}{m}> <https://campy.dev/ns#SENT_IN> <{sid}> }}")


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


def walk(gw, **p):
    return WalkV2(gw, {"limit": 4, "max_share": 0.10, **p})


async def rows_for(gw, concept_ids, **p):
    return await gw.run("thalamus.bundle_concept_walk_v2", concept_ids=concept_ids,
                        limit=p.pop("limit", 4), **p)


def ids(rows):
    return [r["node_id"].rsplit("/", 1)[-1] for r in rows]


async def kennel(store):
    """Sam and Lee speak; Pixie, Toby and Buddy are dogs; 'dates' is an untyped Concept."""
    await store.concept("c-sam", "Sam", kind_of="c-person")
    await store.concept("c-person", "person", is_kind=True)
    await store.concept("c-dog", "dog", is_kind=True)
    for cid, text in [("c-pixie", "Pixie"), ("c-toby", "Toby"), ("c-buddy", "Buddy")]:
        await store.concept(cid, text, kind_of="c-dog")
    await store.concept("c-dates", "dates")
    await store.concept("c-solo", "Rex", kind_of="c-puppy")
    await store.concept("c-puppy", "puppy", is_kind=True)


# --- flag and knobs -------------------------------------------------------------------

async def test_flag_default_off_env_and_knobs():
    assert _DEFAULT_CONFIG["retrieval"]["graph_walk_v2"] is False
    assert cl.graph_walk_v2_enabled({}) is False and cl.graph_walk_v2_enabled(_DEFAULT_CONFIG) is False
    assert cl.graph_walk_v2_enabled({"retrieval": {"graph_walk_v2": True}}) is True
    cfg = apply_env_overrides({"retrieval": {}}, {"CAMPY_GRAPH_WALK_V2": "1", "CAMPY_GRAPH_WALK_V2_LIMIT": "2"})
    assert cl.graph_walk_v2_enabled(cfg) is True and cl.graph_walk_v2_limit(cfg) == 2
    assert cl.graph_walk_v2_enabled(apply_env_overrides({"retrieval": {"graph_walk_v2": True}},
                                                        {"CAMPY_GRAPH_WALK_V2": "0"})) is False
    assert (cl.graph_walk_v2_limit({}), cl.graph_walk_v2_max_share({}), cl.graph_walk_v2_protect({}),
            cl.graph_walk_v2_min_similarity({})) == (4, 0.10, 3, 0.0)
    assert cl.graph_walk_v2_limit({"retrieval": {"graph_walk_v2_limit": "x"}}) == 4


# --- anchors --------------------------------------------------------------------------

async def test_typed_entity_anchors_and_untyped_concept_does_not(gw, store):
    await kennel(store)
    await store.message("Pixie is my puppy.", mentions=["c-pixie"])
    await store.message("The dates are fixed.", mentions=["c-dates"])
    w = walk(gw)
    got = w.select_anchors([mint_uri("Concept", c) for c in ("c-pixie", "c-dates")])
    assert [(a.text, a.role) for a in got] == [("Pixie", "entity")]
    assert w.rejected[mint_uri("Concept", "c-dates")] == "untyped"


async def test_kind_anchors_through_its_instances_only_when_it_has_two_to_twelve(gw, store):
    await kennel(store)
    await store.message("Toby barks.", mentions=["c-toby"])
    await store.message("Buddy sleeps.", mentions=["c-buddy"])
    w = walk(gw)
    got = w.select_anchors([mint_uri("Concept", c) for c in ("c-dog", "c-puppy")])
    assert [(a.text, a.role) for a in got] == [("dog", "kind")]
    # Pixie has no linked turn, so she is not a usable instance
    assert {m.rsplit("/", 1)[-1] for m in got[0].members} == {"c-toby", "c-buddy"}
    assert w.rejected[mint_uri("Concept", "c-puppy")] in ("untyped", "kind-without-usable-instances")
    # more than twelve instances is a broad kind ("thing"), never an anchor
    await store.concept("c-thing", "thing", is_kind=True)
    for i in range(13):
        await store.concept(f"c-t{i}", f"gadget {i}", kind_of="c-thing")
    w2 = walk(gw)
    assert w2.select_anchors([mint_uri("Concept", "c-thing")]) == []
    assert w2.rejected[mint_uri("Concept", "c-thing")] == "broad-kind"


async def test_participants_never_anchor(gw, store):
    await kennel(store)
    await store.message("Sam here.", speaker="Sam", mentions=["c-sam"])
    w = walk(gw)
    assert w.select_anchors([mint_uri("Concept", "c-sam")]) == []
    assert w.rejected[mint_uri("Concept", "c-sam")] == "participant"


async def test_a_concept_linked_to_more_than_the_share_cap_is_background(gw, store, monkeypatch):
    await kennel(store)
    monkeypatch.setattr(gw._vector_store, "count_documents", lambda prefixes: 100)    # cap = 10 at 10%
    for i in range(10):
        await store.message(f"Toby {i}", mentions=["c-toby"])
    for i in range(11):
        await store.message(f"Buddy {i}", mentions=["c-buddy"])
    w = walk(gw)
    got = w.select_anchors([mint_uri("Concept", c) for c in ("c-toby", "c-buddy")])
    assert [a.text for a in got] == ["Toby"]
    assert w.rejected[mint_uri("Concept", "c-buddy")] == "too-common"
    # a tighter cap rejects Toby too; a looser one admits Buddy
    assert walk(gw, max_share=0.05).select_anchors([mint_uri("Concept", "c-toby")]) == []
    assert len(walk(gw, max_share=0.2).select_anchors([mint_uri("Concept", c) for c in ("c-toby", "c-buddy")])) == 2


async def test_a_kind_that_saturates_the_store_does_not_anchor(gw, store, monkeypatch):
    await kennel(store)
    monkeypatch.setattr(gw._vector_store, "count_documents", lambda prefixes: 100)
    for i in range(6):      # each instance is under the cap alone (10); together the dogs reach 18
        await store.message(f"Toby {i}", mentions=["c-toby"])
        await store.message(f"Buddy {i}", mentions=["c-buddy"])
        await store.message(f"Pixie {i}", mentions=["c-pixie"])
    w = walk(gw)
    assert w.select_anchors([mint_uri("Concept", "c-dog")]) == []
    assert w.rejected[mint_uri("Concept", "c-dog")] == "saturating-kind"
    assert [a.text for a in walk(gw).select_anchors([mint_uri("Concept", "c-toby")])] == ["Toby"]


async def test_generic_concepts_yield_no_rows_end_to_end(gw, store):
    await kennel(store)
    for i in range(3):
        await store.message(f"The dates {i} are fixed.", mentions=["c-dates"])
        await store.message(f"Sam says {i}", speaker="Sam", mentions=["c-sam"])
    assert await rows_for(gw, ["c-dates", "c-sam", "c-puppy"]) == []


# --- coverage and what is missing -----------------------------------------------------

async def test_covered_anchor_by_edge_adds_nothing(gw, store):
    await kennel(store)
    shown = await store.message("Pixie is my puppy.", mentions=["c-pixie"], day=3)
    await store.message("Pixie chewed a shoe.", mentions=["c-pixie"], day=9)
    assert ids(await rows_for(gw, ["c-pixie"])) != []
    assert await rows_for(gw, ["c-pixie"], conversation_ids=[shown]) == []
    assert await rows_for(gw, ["c-pixie"], conversation_ids=[f"{MSG}{shown}"]) == []


async def test_covered_anchor_by_words_adds_nothing(gw, store):
    """The shown turn was never linked, but it says "Pixie": the anchor is covered."""
    await kennel(store)
    await store.message("Pixie chewed a shoe.", mentions=["c-pixie"], day=9)
    assert await rows_for(gw, ["c-pixie"], conversation_texts=["[Sam, 2023-05-03] pixie is my puppy."]) == []
    assert ids(await rows_for(gw, ["c-pixie"], conversation_texts=["[Sam, 2023-05-03] Toby is my puppy."])) != []


async def test_kind_anchor_keeps_only_the_uncovered_instances(gw, store):
    await kennel(store)
    shown = await store.message("Toby barks.", mentions=["c-toby"], day=3)
    buddy = await store.message("Buddy sleeps.", mentions=["c-buddy"], day=4)
    await store.message("Toby digs.", mentions=["c-toby"], day=5)
    rows = await rows_for(gw, ["c-dog"], conversation_ids=[shown])
    assert ids(rows) == [buddy]                       # Toby is covered, so even his other turn adds nothing


async def test_turns_already_shown_are_left_out_by_source_message_not_node_id(db, gw, store):
    await kennel(store)
    mid = await store.message("Fluffy filler. Pixie is my puppy. More.", mentions=["c-pixie"], day=3)
    other = await store.message("Pixie chewed a shoe.", mentions=["c-pixie"], day=9)
    res = await obs.record_observation(db, obs.ObservationDraft(
        evidence_ref=mid, evidence_text="Pixie is my puppy", subject_text="Pixie", predicate="is_a",
        object_text="puppy", extraction_method="llm", confidence=0.9, speaker="Sam", text_raw="Sam - is_a - puppy"))
    assert res.ok
    await gw.run("observations.link_about_concept", oid=res.observation_id, cid="c-pixie")
    # the semantic section shows the Observation (evidence_ref = the message): the message is shown
    got = await rows_for(gw, ["c-pixie"], semantic_refs=[mid])
    assert ids(got) == [other]
    # without it, the turn and its Observation are one source message: one row
    both = await rows_for(gw, ["c-pixie"])
    assert sorted(ids(both)) == sorted([mid, other])


async def test_questions_archived_assistant_and_echo_turns_are_not_evidence(db, gw, store):
    await kennel(store)
    good = await store.message("Pixie chewed a shoe.", mentions=["c-pixie"], day=4)
    await store.message("Is Pixie friendly?", mentions=["c-pixie"], day=5)
    await store.message("Pixie is sweet.", mentions=["c-pixie"], day=6, role="assistant")
    gone = await store.message("Pixie ran away.", mentions=["c-pixie"], day=7)
    await db.execute_write(f"INSERT DATA {{ <{MSG}{gone}> <https://campy.dev/ns#archived> true }}")
    await store.message("What does Pixie like", mentions=["c-pixie"], day=8)
    assert ids(await rows_for(gw, ["c-pixie"], query_text="What does Pixie like")) == [good]


# --- order, cap, scope ---------------------------------------------------------------

async def test_hop1_before_hop2_then_anchors_hit_then_similarity_and_the_cap(gw, store):
    await kennel(store)
    near = [1.0] + [0.0] * (DIM - 1)
    far = [0.0, 1.0] + [0.0] * (DIM - 2)
    sib = await store.message("Buddy sleeps.", mentions=["c-buddy"], day=2, vec=near)        # hop 2: a sibling
    weak = await store.message("Toby digs.", mentions=["c-toby"], day=3, vec=far)
    strong = await store.message("Toby barks.", mentions=["c-toby"], day=4, vec=near)
    both = await store.message("Pixie and Toby play.", mentions=["c-toby", "c-pixie"], day=5, vec=far)
    # one entity named: Toby's turns are hop 1; Pixie and Buddy are siblings under "dog" (hop 2).
    # The turn that also mentions a sibling has two links, so it leads the hop; then cosine.
    rows = await rows_for(gw, ["c-toby"], query_embedding=Q, limit=10)
    assert [r["hop"] for r in rows] == [1, 1, 1, 2]
    assert ids(rows)[:3] == [both, strong, weak] and ids(rows)[3] == sib
    # anchors-hit outranks similarity: name both Toby and Pixie, the turn with both comes first
    rows = await rows_for(gw, ["c-toby", "c-pixie"], query_embedding=Q, limit=10)
    assert ids(rows)[0] == both
    # the cap
    assert ids(await rows_for(gw, ["c-toby"], query_embedding=Q, limit=2)) == [both, strong]
    assert await rows_for(gw, ["c-toby"], limit=0) == []


async def test_a_named_participant_scopes_the_walk_to_the_sessions_they_spoke_in(gw, store):
    await kennel(store)
    await store.concept("c-lee", "Lee", kind_of="c-person")
    mine = await store.message("Toby barks.", speaker="Sam", mentions=["c-toby"], day=3)
    await store.message("Sam, Toby ate my shoe.", speaker="Sam", mentions=["c-toby"], day=4)
    theirs = await store.message("Lee's Toby is a cat.", speaker="Lee", mentions=["c-toby"], day=5)
    await store.session("conv-a", mine)
    await store.session("conv-b", theirs)
    # no participant named: both conversations' turns qualify
    assert theirs in ids(await rows_for(gw, ["c-toby"]))
    # Lee named: only the sessions Lee spoke in
    assert ids(await rows_for(gw, ["c-toby", "c-lee"])) == [theirs]


# --- the bundle ---------------------------------------------------------------------

def conv_section(texts, *, keeps, neighbours=None, ids_=None):
    neighbours = neighbours or [False] * len(texts)
    content = [{"text": t, "type": "Message", "role": "user", "created_at": "2023-05-02", "keep_rank": k,
                "neighbour": n} for t, k, n in zip(texts, keeps, neighbours)]
    return BundleSection(section_type="conversation", content=content,
                         token_estimate=sum(max(1, len(t) // 4) for t in texts),
                         source_node_ids=ids_ or [f"{MSG}c{i}" for i in range(len(texts))], order="time")


async def test_budget_swap_pays_for_the_linked_turns_out_of_the_weakest_conversation_turns(db, gw, store):
    await kennel(store)
    await store.message("Toby digs in the garden every single day of the week.", mentions=["c-toby"], day=4, vec=Q)
    texts = [f"[Sam, 2023-05-02] filler turn number {i} " + "with some padding words in it " * 4 for i in range(8)]
    # four matched turns (rank 0..3) and four neighbours (rank + 1.5 per step)
    keeps = [0, 1, 2, 3, 1.5, 2.5, 3.5, 4.5]
    nb = [False] * 4 + [True] * 4
    conv = conv_section(texts, keeps=keeps, neighbours=nb)
    before = conv.token_estimate
    cfg = {"retrieval": {"graph_walk_v2": True, "graph_walk_v2_limit": 4, "graph_walk_v2_protect": 3,
                         "graph_walk_v2_max_share": 0.5}}
    linked, new_conv = await bc._stage_concept_walk_v2(db, "What did Toby do?", cfg, conv, None)
    assert linked is not None and len(linked.content) == 1 and linked.section_type == "linked"
    assert new_conv.token_estimate + linked.token_estimate <= before                  # the prompt did not grow
    gone = {t for t in texts} - {c["text"] for c in new_conv.content}
    assert gone == {texts[7]}                                                          # keep_rank 4.5: the weakest
    assert len(new_conv.source_node_ids) == len(new_conv.content) == 7
    assert all("keep_rank" not in c and "neighbour" not in c for c in new_conv.content)


async def test_protected_turns_stay_and_an_item_that_cannot_be_paid_for_is_not_added(db, gw, store):
    await kennel(store)
    await store.message("Toby " + "digs a deep hole in the garden " * 8, mentions=["c-toby"], day=4, vec=Q)
    texts = ["[Sam, 2023-05-02] a short matched turn", "[Sam, 2023-05-02] another matched turn"]
    conv = conv_section(texts, keeps=[0, 1])                      # both inside protect=3
    cfg = {"retrieval": {"graph_walk_v2": True, "graph_walk_v2_protect": 3, "graph_walk_v2_max_share": 0.5}}
    linked, new_conv = await bc._stage_concept_walk_v2(db, "What did Toby do?", cfg, conv, None)
    assert linked is None and new_conv is conv


async def test_a_closer_turn_is_never_swapped_for_a_farther_one(db, gw, store):
    await kennel(store)
    far = [0.0, 1.0] + [0.0] * (DIM - 2)
    await store.message("Toby digs in the garden.", mentions=["c-toby"], day=4, vec=far)        # cosine 0 to Q
    victim = await store.message("filler turn about something else entirely, padding padding", day=2, vec=Q)
    texts = ["[Sam, 2023-05-02] a matched turn that stays here", "[Sam, 2023-05-02] filler turn about something else "
             "entirely, padding padding padding padding"]
    conv = conv_section(texts, keeps=[0, 1.5], neighbours=[False, True], ids_=[f"{MSG}c0", f"{MSG}{victim}"])
    cfg = {"retrieval": {"graph_walk_v2": True, "graph_walk_v2_protect": 1, "graph_walk_v2_max_share": 0.5}}
    linked, new_conv = await bc._stage_concept_walk_v2(db, "What did Toby do?", cfg, conv, None)
    assert linked is None and new_conv is conv
    # the same item swapped against a turn that is farther from the question is allowed
    gw._vector_store.upsert_vector(f"{MSG}{victim}", far)          # the displaced turn is now as far as the item
    await store.message("Toby naps all afternoon in the sun.", mentions=["c-toby"], day=6, vec=Q)
    linked, new_conv = await bc._stage_concept_walk_v2(db, "What did Toby do?", cfg, conv, None)
    assert linked is not None and len(new_conv.content) == 1


async def test_compile_bundle_v2_shows_missing_facts_and_never_grows_the_prompt(db, gw, store):
    await kennel(store)
    await store.message("Toby barks at the mailman every morning.", mentions=["c-toby"], day=3)
    off = await bc.compile_bundle("What does Toby do?", db, {"retrieval": {"graph_linking": True,
                                  "graph_linking_limit": 0, "conversation_token_budget": 0},
                                  "observations": {"retrieval": False}})
    on = await bc.compile_bundle("What does Toby do?", db, V2)
    # the conversation stage already shows the only Toby turn: covered, nothing to add
    assert not any(s.section_type == "linked" for s in on.sections)
    assert on.total_token_estimate <= off.total_token_estimate


async def test_flag_off_is_b503_exactly_and_flag_on_replaces_it(db, gw, store):
    await kennel(store)
    for i in range(3):
        await store.message(f"Toby fact number {i}.", mentions=["c-toby"], day=3 + i)
    off = await bc.compile_bundle("What does Toby do?", db, V1)
    (v1_linked,) = [s for s in off.sections if s.section_type == "linked"]
    assert len(v1_linked.content) == 3 and "hop" in v1_linked.content[0]
    # explicit false is the default
    same = await bc.compile_bundle("What does Toby do?", db, {**V1, "retrieval": {**V1["retrieval"], "graph_walk_v2": False}})
    assert [(s.section_type, s.content) for s in same.sections] == [(s.section_type, s.content) for s in off.sections]
    # conversation rows carry no rank annotation unless the walk is on
    assert all("keep_rank" not in c for s in off.sections if s.section_type == "conversation" for c in s.content)
    on = await bc.compile_bundle("What does Toby do?", db, V2)
    assert all("keep_rank" not in c and "neighbour" not in c
               for s in on.sections if s.section_type == "conversation" for c in s.content)


async def test_walk_v2_is_skipped_when_the_conversation_holds_the_whole_history(db, gw, store):
    await kennel(store)
    await store.message("Toby barks.", mentions=["c-toby"], day=3)
    cfg = {"retrieval": {"graph_linking": True, "graph_walk_v2": True, "conversation_token_budget": 3500},
           "observations": {"retrieval": False}}
    bundle = await bc.compile_bundle("What does Toby do?", db, cfg)
    (conv,) = [s for s in bundle.sections if s.section_type == "conversation"]
    assert conv.full_history and not any(s.section_type == "linked" for s in bundle.sections)
