"""B559: the concept walk is seeded with the Concepts the question names other than its subject.

Real Oxigraph store, no model, no LLM. Pins:
- `QuestionAnalysis.walk_seed_ids`: the subject, the anchors (a tie's group) and person Concepts are not seeds;
- the walk adds nothing when the question names only its subject, and still walks from a named entity;
- profile main (walk limit 0): no walk section, the walk query never runs.
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

    async def message(self, text, *, session, speaker, mentions=(), day=1, spoken_by=None):
        self.n += 1
        mid = f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        self.db.write_edge("SENT_IN", mint_uri("Message", mid), mint_uri("Session", session))
        if spoken_by:                                       # B560: the walk anchors on this edge
            self.db.write_edge("SPOKEN_BY", mint_uri("Message", mid), mint_uri("Concept", spoken_by))
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
    await store.message("Sam says hello", session="s1", speaker="Sam", mentions=["c-sam"], day=1, spoken_by="c-sam")
    await store.message("I finished the Spitfire model kit", session="s1", speaker="Sam",
                        mentions=["c-sam", "c-kit"], day=2, spoken_by="c-sam")
    await store.message("Sam asks about weather", session="s1", speaker="Sam", mentions=["c-sam"], day=3,
                        spoken_by="c-sam")
    a = analysis(("c-sam", "person"), ("c-kit", "entity"), subject="c-sam", anchors=["c-sam"], subjects=["c-sam"])
    sec = await bc._stage_concept_walk(db, "What did Sam do with the model kit?", WALK, set(), analysis=a)
    assert [c["text"].split("] ")[-1] for c in sec.content] == ["I finished the Spitfire model kit"]


# --- profile main ---------------------------------------------------------------------

async def test_profile_main_runs_no_walk(db, gw, store, monkeypatch):
    await store.concept("c-kyoto", "Kyoto")
    await store.message("Kyoto was lovely", session="s1", speaker="Sam", mentions=["c-kyoto"])
    ran = []
    real = bc.get_gateway(db).run

    async def spy(name, **kw):
        ran.append(name)
        return await real(name, **kw)
    monkeypatch.setattr(bc, "get_gateway", lambda _db: type("G", (), {"run": staticmethod(spy)})())
    b = await bc.compile_bundle("What about Kyoto?", db, MAIN)
    assert "linked" not in [s.section_type for s in b.sections]
    assert "thalamus.bundle_concept_walk" not in ran
