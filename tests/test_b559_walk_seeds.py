"""B559: the concept walk is seeded with the Concepts the question names other than its subject.

Real Oxigraph store, no model, no LLM. Pins:
- `QuestionAnalysis.walk_seed_ids`: the subject, the anchors (a tie's group) and person Concepts are not seeds;
- the walk adds nothing when the question names only its subject, and still walks from a named entity;
- `concept_links.conversation_common`: a Concept linked to more than 20% of the Messages of one conversation is
  reported, a share of exactly 20% or a conversation under `min_docs` is not, and the test is per conversation
  (a share that is small over the whole store still counts); the walk drops those seeds;
- profile main (walk limit 0): no walk section, the seed query never runs.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient, mint_uri
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler as bc
from campy.brain.thalamus.question_analysis import QuestionAnalysis

pytestmark = pytest.mark.asyncio

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
WALK = {"retrieval": {"graph_linking": True, "graph_linking_limit": 12, "conversation_token_budget": 0},
        "observations": {"retrieval": False}}
MAIN = {"retrieval": {"graph_linking": True, "graph_linking_limit": 0, "conversation_token_budget": 0},
        "observations": {"retrieval": False}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b559.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def concept(self, cid, text):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text,
                          emb=[0.0] * DIM, gist="Category", stype="DefinedTerm", now=T0)

    async def message(self, text, *, session, speaker, mentions=(), day=1):
        self.n += 1
        mid = f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        self.db.write_edge("SENT_IN", mint_uri("Message", mid), mint_uri("Session", session))
        for cid in mentions:
            self.db.write_edge("MENTIONS", mint_uri("Message", mid), mint_uri("Concept", cid))
        return mid


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


def analysis(*concepts, subject=None, anchors=(), subjects=()):
    """concepts: (id, role) pairs."""
    return QuestionAnalysis(
        question="q?", text="q?", subject_id=subject, subject=subject, anchor_ids=tuple(anchors),
        subjects=tuple({"id": s, "label": s} for s in subjects),
        concepts=tuple({"id": c, "label": c, "span": c, "source": "t", "role": r} for c, r in concepts))


async def two_conversations(store, *, ann_hits=3, kyoto_hits=2):
    """Conversation 1 (Ann, Bob; sessions a1, a2) and 2 (Cy, Di; session b1), 10 Messages each."""
    for cid, text in (("c-ann", "Ann"), ("c-kyoto", "Kyoto"), ("c-cy", "Cy")):
        await store.concept(cid, text)
    for i in range(10):
        m = ["c-ann"] * (i < ann_hits) + ["c-kyoto"] * (i < kyoto_hits)
        await store.message(f"conv one turn {i}", session="a1" if i < 5 else "a2",
                            speaker="Ann" if i % 2 else "Bob", mentions=m, day=1 + i)
    for i in range(10):
        await store.message(f"conv two turn {i}", session="b1", speaker="Cy" if i % 2 else "Di",
                            mentions=["c-cy"] if i == 0 else [], day=1 + i)


# --- the seeds ----------------------------------------------------------------------

async def test_the_subject_the_anchors_and_persons_are_not_seeds():
    a = analysis(("c-andrew", "person"), ("c-toby", "entity"), ("c-pet", "kind"), subject="c-andrew",
                 anchors=["c-andrew"], subjects=["c-andrew"])
    assert a.concept_ids == ["c-andrew", "c-toby", "c-pet"]
    assert a.walk_seed_ids() == ["c-toby", "c-pet"]
    tie = analysis(("c-nate", "person"), ("c-joanna", "person"), ("c-city", "kind"), anchors=["c-nate", "c-joanna"])
    assert tie.walk_seed_ids() == ["c-city"]
    other = analysis(("c-mel", "person"), ("c-car", "entity"), subject="c-car")     # a person who is not the subject
    assert other.walk_seed_ids() == []


async def test_the_walk_adds_nothing_when_only_the_subject_is_named(db, gw, store, monkeypatch):
    await store.concept("c-sam", "Sam")
    await store.concept("c-kit", "model kit")
    for i in range(3):
        await store.message(f"Sam says hello {i}", session="s1", speaker="Sam", mentions=["c-sam"], day=1 + i)
    ran = []
    real = gw.run

    async def spy(name, **kw):
        ran.append(name)
        return await real(name, **kw)
    monkeypatch.setattr(bc, "get_gateway", lambda _db: type("G", (), {"run": staticmethod(spy)})())
    a = analysis(("c-sam", "person"), subject="c-sam", anchors=["c-sam"], subjects=["c-sam"])
    assert await bc._stage_concept_walk(db, "What did Sam say?", WALK, set(), analysis=a) is None
    assert "thalamus.bundle_concept_walk" not in ran


async def test_the_walk_still_follows_a_named_entity_and_not_the_subject(db, gw, store):
    await store.concept("c-sam", "Sam")
    await store.concept("c-kit", "model kit")
    await store.message("Sam says hello", session="s1", speaker="Sam", mentions=["c-sam"], day=1)
    await store.message("I finished the Spitfire model kit", session="s1", speaker="Sam",
                        mentions=["c-sam", "c-kit"], day=2)
    await store.message("Sam asks about weather", session="s1", speaker="Sam", mentions=["c-sam"], day=3)
    a = analysis(("c-sam", "person"), ("c-kit", "entity"), subject="c-sam", anchors=["c-sam"], subjects=["c-sam"])
    sec = await bc._stage_concept_walk(db, "What did Sam do with the model kit?", WALK, set(), analysis=a)
    assert [c["text"].split("] ")[-1] for c in sec.content] == ["I finished the Spitfire model kit"]


# --- the per-conversation test --------------------------------------------------------

async def common(gw, ids, **kw):
    rows = await gw.run("concept_links.conversation_common", concept_ids=ids,
                        share=kw.get("share", 0.2), min_docs=kw.get("min_docs", 10))
    return {str(r["concept_id"]) for r in rows}


async def test_a_concept_over_a_fifth_of_one_conversation_is_common_though_rare_in_the_store(gw, store):
    await two_conversations(store, ann_hits=3, kyoto_hits=2)
    # Ann: 3 of conversation 1's 10 Messages (30%), 3 of the store's 20 (15%, under the old store-wide 20%)
    # Kyoto: 2 of 10 is exactly 20%, not more than 20%; Cy: 1 of 10 in its own conversation
    assert await common(gw, ["c-ann", "c-kyoto", "c-cy"]) == {"c-ann"}


async def test_the_share_and_the_minimum_are_parameters(gw, store):
    await two_conversations(store, ann_hits=3, kyoto_hits=2)
    assert await common(gw, ["c-ann", "c-kyoto", "c-cy"], share=0.05) == {"c-ann", "c-kyoto", "c-cy"}
    assert await common(gw, ["c-ann", "c-kyoto", "c-cy"], min_docs=11) == set()          # 10-Message conversations
    assert await common(gw, []) == set()


async def test_the_walk_drops_a_seed_common_in_its_conversation(db, gw, store, monkeypatch):
    await two_conversations(store, ann_hits=0, kyoto_hits=4)         # Kyoto: 4 of 10 in conversation 1
    monkeypatch.setattr(bc, "_WALK_COMMON_MIN_DOCS", 10)
    a = analysis(("c-kyoto", "entity"), ("c-cy", "entity"), subject=None)
    sec = await bc._stage_concept_walk(db, "Kyoto and Cy?", WALK, set(), analysis=a)
    assert [c["text"].split("] ")[-1] for c in sec.content] == ["conv two turn 0"]      # only Cy's turn
    b = analysis(("c-kyoto", "entity"))
    assert await bc._stage_concept_walk(db, "Kyoto?", WALK, set(), analysis=b) is None


async def test_without_speakers_the_store_is_one_conversation(gw, store):
    await store.concept("c-x", "X")
    for i in range(10):
        await store.gw.run("capture.create_message", message_id=f"n{i}", text_raw=f"t{i}", embedding=None,
                           embedding_model="m", embedding_dim=DIM, role="user", byte_end=2,
                           created_at=f"2023-05-{1 + i:02d}T12:00:00+00:00")
        store.db.write_edge("SENT_IN", mint_uri("Message", f"n{i}"), mint_uri("Session", "plain"))
        if i < 3:
            store.db.write_edge("MENTIONS", mint_uri("Message", f"n{i}"), mint_uri("Concept", "c-x"))
    assert await common(gw, ["c-x"]) == {"c-x"}


# --- profile main ---------------------------------------------------------------------

async def test_profile_main_runs_no_walk_and_no_seed_query(db, gw, store, monkeypatch):
    await two_conversations(store)
    ran = []
    real = bc.get_gateway(db).run

    async def spy(name, **kw):
        ran.append(name)
        return await real(name, **kw)
    monkeypatch.setattr(bc, "get_gateway", lambda _db: type("G", (), {"run": staticmethod(spy)})())
    b = await bc.compile_bundle("Kyoto and Cy?", db, MAIN)
    assert "linked" not in [s.section_type for s in b.sections]
    assert "concept_links.conversation_common" not in ran and "thalamus.bundle_concept_walk" not in ran
