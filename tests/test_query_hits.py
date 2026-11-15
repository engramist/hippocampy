"""Step Q: the query-hit queries (`query_hits.*`) on a small frozen store, in CI.

A made-up two-speaker conversation is written through the real capture writes: Messages, SENT_IN, SPOKEN_BY,
admitted PERSON mentions, kinds (INSTANCE_OF, BROADER), and facts through `observations.record_observation` with
object roles on (HAS_SUBJECT, HAS_OBJECT, EVIDENCED_BY). No model and no benchmark data. The test pins the exact
subject, object Concepts, fact rows and source turns, so it fails when capture stops writing an edge a query reads,
or a query stops returning its rows.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus import kinds
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.queries.query_hits import question_terms
from campy.brain.hippocampus.graph.vector_store import mint_uri
from tests.b564_helpers import NS, Q, T0, World

SESSION = "demo-chat-1"
OTHER_SESSION = "demo-chat-2"
ROLES_ON = {"observations": {"enabled": True, "object_roles": True}}

# (key, speaker, day, text)
TURNS = [
    ("adopt", "Nora", 1, "I adopted a puppy called Biscuit last spring."),
    ("ivy", "Theo", 2, "My sister Ivy brought a cake to the party."),
    ("guitar", "Nora", 3, "I bought a guitar to learn some songs."),
    ("rex", "Theo", 4, "I have a dog named Rex at home."),
    ("pottery", "Nora", 5, "I took a pottery class on Friday."),
    ("goldie", "Nora", 6, "I had a goldfish called Goldie once."),
    ("mochi", "Nora", 9, "I adopted another puppy, Mochi, this week."),
]


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "query_hits.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def fact(db, mid, quote, obj_text, object_id, *, subject_id, predicate="owns"):
    res = await obs.record_observation(db, obs.ObservationDraft(
        evidence_ref=mid, evidence_text=quote, subject_text="I", predicate=predicate, object_text=obj_text,
        extraction_method="llm", confidence=0.9, subject_id=subject_id, object_id=object_id), config=ROLES_ON)
    assert res.status == "created", res
    return res.observation_id


async def build(db, gw):
    """The frozen store. Returns {turn key: message id} and {fact key: observation id}."""
    w = World(db, gw)
    db.write_node("Session", {"session_id": SESSION})
    db.write_node("Session", {"session_id": OTHER_SESSION})
    for cid, name in (("c-nora", "Nora"), ("c-theo", "Theo")):
        await w.concept(cid, name)
    for cid, name in (("k-pet", "pet"), ("k-dog", "dog"), ("k-fish", "goldfish")):
        await w.concept(cid, name, kind=True)
    await kinds.link_broader(gw, "k-dog", "k-pet")
    await kinds.link_broader(gw, "k-fish", "k-pet")
    for cid, name, kind in (("c-biscuit", "Biscuit", "k-dog"), ("c-rex", "Rex", "k-dog"),
                            ("c-goldie", "Goldie", "k-fish"), ("c-mochi", "Mochi", "k-dog")):
        await w.concept(cid, name)
        await kinds.link_instance_of(gw, cid, kind)
    await w.concept("c-guitar", "guitar")

    mids = {}
    for key, speaker, day, text in TURNS:
        mid = await w.message(text, day=day, speaker=speaker)
        mids[key] = mid
        await gw.run("capture.link_message_sent_in_session", session_id=SESSION, message_id=mid)
        await gw.run("spoken_by.link_spoken_by", mid=mid, cid="c-nora" if speaker == "Nora" else "c-theo")
    await w.admit(mids["ivy"], "c-ivy", "Ivy", "PERSON")
    # a speaker of another conversation, who must not resolve inside this one
    other = await w.message("Nora says hi from elsewhere.", day=1, speaker="Pam")
    await w.concept("c-pam", "Pam")
    await gw.run("capture.link_message_sent_in_session", session_id=OTHER_SESSION, message_id=other)
    await gw.run("spoken_by.link_spoken_by", mid=other, cid="c-pam")

    facts = {
        "biscuit": await fact(db, mids["adopt"], "I adopted a puppy called Biscuit", "Biscuit", "c-biscuit",
                              subject_id="c-nora"),
        "guitar": await fact(db, mids["guitar"], "I bought a guitar", "guitar", "c-guitar", subject_id="c-nora"),
        "rex": await fact(db, mids["rex"], "I have a dog named Rex", "Rex", "c-rex", subject_id="c-theo"),
        "pottery": await fact(db, mids["pottery"], "I took a pottery class", "pottery class", None,
                              subject_id="c-nora", predicate="did"),
        "goldie": await fact(db, mids["goldie"], "I had a goldfish called Goldie", "Goldie", "c-goldie",
                             subject_id="c-nora"),
        "mochi": await fact(db, mids["mochi"], "I adopted another puppy, Mochi", "Mochi", "c-mochi",
                            subject_id="c-nora"),
    }
    goldie = mint_uri("Observation", facts["goldie"])
    db.store.update(f"DELETE {{ <{goldie}> {NS}archived> ?a }} INSERT {{ <{goldie}> {NS}archived> true }} "
                    f"WHERE {{ <{goldie}> {NS}archived> ?a }}")
    return mids, facts


def sessions(name=SESSION):
    return [mint_uri("Session", name)]


async def subject(gw, question, scope=SESSION):
    rows = await gw.run("query_hits.subject_in_sessions", pairs=question_terms(question), sessions=sessions(scope))
    return rows[0]["sid"] if rows else None


async def objects(gw, question, sid):
    rows = await gw.run("query_hits.objects_in_sessions", terms=[t for t, _ in question_terms(question)], sid=sid,
                        sessions=sessions())
    return [r["kid"] for r in rows]


async def test_question_terms():
    terms = dict(question_terms("How many pets does Nora's family have?"))
    assert terms["Nora"] == 4 and terms["nora"] == 4  # positions count from 0
    assert terms["pet"] == 2 and terms["pets"] == 2
    assert "Nora's" not in terms and "have?" not in terms
    assert "clas" not in dict(question_terms("Which class?"))  # a double s is not a plural


async def test_capture_writes_the_edges_the_queries_read(db, gw):
    mids, facts = await build(db, gw)
    for edge in ("HAS_SUBJECT", "HAS_OBJECT", "EVIDENCED_BY", "INSTANCE_OF", "BROADER", "SPOKEN_BY", "MENTIONS",
                 "SENT_IN"):
        n = db._execute_and_collect(f"SELECT (COUNT(*) AS ?n) WHERE {{ ?s {NS}{edge}> ?o }}")[0]["n"]
        assert int(n) > 0, f"capture wrote no {edge} edge"
    biscuit = mint_uri("Observation", facts["biscuit"])
    assert db._execute_and_collect(f"ASK {{ <{biscuit}> {NS}HAS_SUBJECT> ?s . ?s {NS}concept_id> \"c-nora\" }}")


async def test_subject_resolution(db, gw):
    await build(db, gw)
    assert await subject(gw, "How many pets does Nora have?") == "c-nora"
    assert await subject(gw, "Did Theo give Nora a dog?") == "c-theo"        # the earliest term wins
    assert await subject(gw, "What did Ivy bring to the party?") == "c-ivy"  # a mentioned PERSON
    assert await subject(gw, "What does Pam like?") is None                  # another conversation's speaker
    assert await subject(gw, "What does Pam like?", scope=OTHER_SESSION) == "c-pam"
    assert await subject(gw, "What is the weather like?") is None
    unscoped = await gw.run("query_hits.subject", pairs=question_terms("What does Pam like?"))
    assert [r["sid"] for r in unscoped] == ["c-pam"]


async def test_objects(db, gw):
    await build(db, gw)
    assert await objects(gw, "How many pets does Nora have?", "c-nora") == ["k-pet"]
    assert await objects(gw, "Does Nora play the guitar?", "c-nora") == ["c-guitar"]
    assert await objects(gw, "What class did Nora take?", "c-nora") == []  # the object is text only
    assert await objects(gw, "Does Nora have a dog?", "c-nora") == ["k-dog"]


async def test_facts_rows_and_turns(db, gw):
    mids, facts = await build(db, gw)
    rows = await gw.run("query_hits.facts", sid="c-nora", kids=["k-pet"])
    # Biscuit and Mochi are reached through INSTANCE_OF dog then BROADER pet; Rex is Theo's; Goldie is archived
    assert [(r["observation_id"], r["object_id"], r["evidence_message_id"]) for r in rows] == [
        (facts["biscuit"], "c-biscuit", mids["adopt"]),
        (facts["mochi"], "c-mochi", mids["mochi"]),
    ]
    assert rows[0]["message"] == mint_uri("Message", mids["adopt"])
    assert [r["observation_id"] for r in await gw.run("query_hits.facts", sid="c-theo", kids=["k-pet"])] == [
        facts["rex"]]
    assert [r["observation_id"] for r in await gw.run("query_hits.facts", sid="c-nora", kids=["c-guitar"])] == [
        facts["guitar"]]
    assert await gw.run("query_hits.facts", sid="c-nora", kids=["k-fish"]) == []  # only the archived Goldie


async def test_facts_aggregates(db, gw):
    mids, facts = await build(db, gw)
    count = (await gw.run("query_hits.facts_count", sid="c-nora", kids=["k-pet"]))[0]
    assert (int(count["objects"]), int(count["facts"])) == (2, 2)
    latest = (await gw.run("query_hits.facts_latest", sid="c-nora", kids=["k-pet"]))[0]
    assert (latest["observation_id"], latest["evidence_message_id"]) == (facts["mochi"], mids["mochi"])
    assert str(latest["occurred_at"]).startswith("2023-05-09")
    assert (await gw.run("query_hits.facts_exist", sid="c-nora", kids=["k-pet"]))[0]["exists"] is True
    assert (await gw.run("query_hits.facts_exist", sid="c-theo", kids=["c-guitar"]))[0]["exists"] is False


# --- step 1: the role reads ------------------------------------------------------------------------

async def add_roles(db, gw, facts):
    await gw.run("roles.ensure_action_concept", cid="wn:adoption.n.01", text="adoption", now=T0)
    await gw.run("roles.ensure_action_concept", cid="wn:act.n.02", text="act", now=T0)
    await kinds.link_broader(gw, "wn:adoption.n.01", "wn:act.n.02")
    for key in ("biscuit", "mochi", "rex"):
        await gw.run("roles.link_action", oid=facts[key], cid="wn:adoption.n.01")
    await World(db, gw).concept("c-studio", "studio")
    await gw.run("roles.link_place", oid=facts["pottery"], cid="c-studio")
    await gw.run("roles.link_participant", oid=facts["guitar"], cid="c-ivy")


async def role_targets(gw, question, sid):
    rows = await gw.run("query_hits.role_targets", terms=[t for t, _ in question_terms(question)], sid=sid)
    return [(r["kid"], r["role"]) for r in rows]


async def test_role_targets_are_the_subjects_roles(db, gw):
    mids, facts = await build(db, gw)
    await add_roles(db, gw, facts)
    assert await role_targets(gw, "When was Nora's adoption?", "c-nora") == [("wn:adoption.n.01", "action")]
    assert await role_targets(gw, "What act did Nora do?", "c-nora") == [("wn:act.n.02", "action")]  # BROADER*
    assert await role_targets(gw, "Where is Nora's studio?", "c-nora") == [("c-studio", "place")]
    assert await role_targets(gw, "Did Nora play with Ivy?", "c-nora") == [("c-ivy", "participant")]
    assert await role_targets(gw, "Where is Theo's studio?", "c-theo") == []      # not one of Theo's facts
    rows = await gw.run("facts.by_action_kind", sid="c-nora", kid="wn:adoption.n.01")
    assert [(r["observation_id"], r["evidence_message_id"]) for r in rows] == [
        (facts["biscuit"], mids["adopt"]), (facts["mochi"], mids["mochi"])]
