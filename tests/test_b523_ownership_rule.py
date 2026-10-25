"""B523: ownership decided by a first-person possession rule, not by the extractor's verb.

- the matcher (spaCy parse, no store): the general construction on made-up sentences across object
  kinds, and the negatives (wish, other owner, negation, question, person roles, unknown entity);
- the flag `[observations] ownership_rule` (default off; env CAMPY_OBSERVATIONS_OWNERSHIP_RULE);
- the writer on a real Oxigraph store: an `owns` Observation, speaker -> entity Concept, evidence =
  the Message, HAS_SUBJECT / HAS_OBJECT, read back by `observations.objects_of_subject`;
  idempotent; flag off writes nothing; the entity must already be linked to the Message.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.temporal_lobe.observations import ownership as ow

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 1, tzinfo=timezone.utc)
NS = "<https://campy.dev/ns#"
OFF = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600, "retrieval": False}}
ON = {"observations": {**OFF["observations"], "ownership_rule": True}}

spacy = pytest.importorskip("spacy")


@pytest.fixture(scope="module")
def nlp():
    try:
        return spacy.load("en_core_web_md")
    except OSError:
        pytest.skip("en_core_web_md not installed")


NAMES = ["Toby", "Buddy", "Luna", "Max", "Rex", "Sam", "Anna", "Civic", "Acme", "Nova", "Birch"]
KNOWN = {n.lower(): f"c-{n.lower()}" for n in NAMES}


def run(nlp, text, known=None):
    stats = ow.OwnershipStats()
    matches = ow.find_ownership(nlp(text), known if known is not None else KNOWN, stats)
    return [m.label for m in matches], stats


# --- the matcher: positives, across kinds of object -----------------------------------

@pytest.mark.parametrize("text,label,quote", [
    ("My dog Toby loves long walks.", "Toby", "My dog Toby"),
    ("Toby, my pup, loves long walks.", "Toby", "Toby, my pup"),
    ("We have our cat Luna.", "Luna", "our cat Luna"),
    ("I just washed my car Civic.", "Civic", "my car Civic"),
    ("I really love my bike Nova.", "Nova", "my bike Nova"),
    ("Birch is my house, and I love it.", "Birch", "Birch is my house"),
    ("I have my own company Acme.", "Acme", "my own company Acme"),
    ("I adopted Buddy last spring.", "Buddy", "I adopted Buddy"),
    ("We got Luna from a shelter.", "Luna", "We got Luna"),
    ("I bought a red bike named Nova.", "Nova", "I bought a red bike named Nova"),
    ("I bought a puppy, Buddy.", "Buddy", "I bought a puppy, Buddy"),
    ("I rescued a cat named Luna.", "Luna", "I rescued a cat named Luna"),
    ("I own the house Birch.", "Birch", "I own the house Birch"),
    ("My pup Toby is German Shephard and loves cute sweaters!", "Toby", "My pup Toby"),
])
def test_first_person_possession_fires(nlp, text, label, quote):
    stats = ow.OwnershipStats()
    (m,) = ow.find_ownership(nlp(text), KNOWN, stats)
    assert (m.label, m.quote) == (label, quote)
    assert text[m.start:m.end] == quote          # the quote is a verbatim span of the turn
    assert not stats.skipped


def test_a_list_of_entities_each_fires_once(nlp):
    labels, _ = run(nlp, "My dogs Toby and Buddy are great.")
    assert sorted(labels) == ["Buddy", "Toby"]
    labels, _ = run(nlp, "I adopted Buddy and Luna.")
    assert sorted(labels) == ["Buddy", "Luna"]


def test_the_same_entity_twice_fires_once(nlp):
    labels, _ = run(nlp, "My dog Toby is old. I adopted Toby in 2019.")
    assert labels == ["Toby"]


# --- the matcher: negatives -----------------------------------------------------------

@pytest.mark.parametrize("text,reason", [
    ("I want a dog named Max.", None),                       # wanting is not having: no possession verb
    ("I'm looking for a cat named Luna.", None),
    ("My friend's dog Rex is huge.", "not_first_person"),
    ("Your dog Toby is cute.", "not_first_person"),
    ("Her cat Luna is shy.", "not_first_person"),
    ("She adopted Buddy.", "not_first_person"),
    ("Anna adopted Buddy last year.", "not_first_person"),
    ("I don't have a car named Civic.", "negated"),
    ("I never owned a bike named Nova.", "negated"),
    ("That is not my dog Toby.", "negated"),
    ("Do you like my dog Toby?", "question"),
    ("Did I adopt Buddy?", "question"),
    ("I would adopt Buddy.", "irrealis"),
    ("I wish I had a car named Civic.", "irrealis"),
    ("If I adopt Buddy, I will tell you.", "irrealis"),
    ("I'm going to adopt Buddy.", "irrealis"),
    ("My friend Sam owns a car.", "not_ownable"),
    ("My sister Anna lives nearby.", "not_ownable"),
    ("Last Tuesday, my gf, Sam, and I played board games.", "not_ownable"),
    ("Last Tuesday, my gf, Toby, and I had a really awesome night playing board games.", "not_ownable"),
    ("I got Sam to help me move.", "not_ownable"),
])
def test_negatives_do_not_fire(nlp, text, reason):
    labels, stats = run(nlp, text)
    assert labels == []
    if reason:
        assert stats.skipped.get(reason, 0) >= 1, stats.skipped


def test_an_entity_that_is_not_a_known_concept_is_skipped_and_counted(nlp):
    labels, stats = run(nlp, "My dog Toby loves walks.", known={"buddy": "c-buddy"})
    assert labels == [] and stats.skipped == {"no_concept": 1}


def test_a_kind_word_alone_is_not_an_entity(nlp):
    labels, _ = run(nlp, "I adopted a dog last spring.")
    assert labels == []


# --- flag -----------------------------------------------------------------------------

def test_flag_default_off_env_on():
    assert _DEFAULT_CONFIG["observations"]["ownership_rule"] is False
    assert obs.ownership_rule_enabled({}) is False
    assert obs.ownership_rule_enabled(_DEFAULT_CONFIG) is False
    assert obs.ownership_rule_enabled(apply_env_overrides({}, {"CAMPY_OBSERVATIONS_OWNERSHIP_RULE": "1"})) is True
    assert obs.ownership_rule_enabled(apply_env_overrides(
        {"observations": {"ownership_rule": True}}, {"CAMPY_OBSERVATIONS_OWNERSHIP_RULE": "0"})) is False


def test_shipped_toml_declares_the_flag_off():
    import tomllib

    path = Path(__file__).resolve().parents[1] / "campy" / "data" / "config" / "campy.toml"
    assert tomllib.loads(path.read_text())["observations"]["ownership_rule"] is False


# --- the writer, on a real store ---------------------------------------------------------

@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b523.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def edges(db, edge):
    rows = db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
    return {(str(r["s"]).rsplit("/", 1)[-1], str(r["o"]).rsplit("/", 1)[-1]) for r in rows}


async def concept(gw, cid, text):
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=Q, gist="Entity", stype="Thing", now=T0)


async def turn(gw, mid, text, *, speaker="Andrew", mentions=(), day=3):
    stamp = f"2023-05-{day:02d}T12:00:00+00:00"
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
    await gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
    for cid in mentions:
        await gw.run("concept_links.link_message_concept", mid=mid, cid=cid)
    return mid


async def owns(gw, speaker_id):
    return [dict(r) for r in await gw.run("observations.objects_of_subject", sid=speaker_id, predicate="owns")]


async def seed(gw):
    for cid, text in (("c-andrew", "Andrew"), ("c-toby", "Toby"), ("c-civic", "Civic"), ("c-sam", "Sam")):
        await concept(gw, cid, text)


async def test_rule_writes_an_owns_observation_the_query_reads(db, gw):
    await seed(gw)
    await turn(gw, "m1", "My dog Toby is such a sweetheart.", mentions=("c-toby",))
    stats = ow.OwnershipStats()
    assert await ow.apply_to_message(db, ON, "m1", stats) == 1
    assert (stats.firings, stats.created, stats.duplicate) == (1, 1, 0)
    (row,) = await owns(gw, "c-andrew")
    assert (row["object_id"], row["object_label"], row["predicate"]) == ("c-toby", "Toby", "owns")
    assert row["evidence_message_id"] == "m1"
    ((oid, _),) = edges(db, "HAS_SUBJECT")
    got = dict((await gw.run("observations.get_observation", oid=oid))[0])
    assert got["evidence_text"] == "My dog Toby" and got["rule_version"] == ow.RULE_ID
    assert got["polarity"] == "asserted" and got["subject_id"] == "c-andrew" and got["object_id"] == "c-toby"
    assert edges(db, "EVIDENCED_BY") == {(oid, "m1")}


async def test_rule_is_idempotent(db, gw):
    await seed(gw)
    await turn(gw, "m1", "My dog Toby is such a sweetheart.", mentions=("c-toby",))
    await ow.apply_to_message(db, ON, "m1", ow.OwnershipStats())
    again = ow.OwnershipStats()
    assert await ow.apply_to_message(db, ON, "m1", again) == 0
    assert (again.created, again.duplicate) == (0, 1)
    assert len(await owns(gw, "c-andrew")) == 1
    assert len(edges(db, "HAS_SUBJECT")) == len(edges(db, "HAS_OBJECT")) == 1


async def test_a_second_turn_adds_evidence_not_a_second_claim(db, gw):
    await seed(gw)
    await turn(gw, "m1", "My dog Toby is such a sweetheart.", mentions=("c-toby",))
    await turn(gw, "m2", "I adopted Toby two years ago.", mentions=("c-toby",), day=4)
    for mid in ("m1", "m2"):
        await ow.apply_to_message(db, ON, mid, ow.OwnershipStats())
    assert len(edges(db, "HAS_OBJECT")) == 1
    assert len(edges(db, "EVIDENCED_BY")) == 2


async def test_entity_must_already_be_linked_to_the_message(db, gw):
    await seed(gw)
    await turn(gw, "m1", "My dog Toby is such a sweetheart.")           # Toby exists but is not linked
    stats = ow.OwnershipStats()
    assert await ow.apply_to_message(db, ON, "m1", stats) == 0
    assert await owns(gw, "c-andrew") == [] and stats.skipped == {"no_concept": 1}
    concepts_before = len(await gw.run("concept_links.live_concepts"))
    await ow.apply_to_message(db, ON, "m1", stats)
    assert len(await gw.run("concept_links.live_concepts")) == concepts_before    # never creates one


async def test_a_concept_linked_through_an_observation_is_in_the_closed_set(db, gw):
    await seed(gw)
    await turn(gw, "m1", "I just washed my car Civic.")
    res = await obs.record_observation(db, obs.ObservationDraft(
        evidence_ref="m1", evidence_text="I just washed my car Civic", subject_text="I", predicate="did",
        object_text="washed Civic", extraction_method="llm", confidence=0.9, subject_id="c-andrew"))
    await gw.run("observations.link_about_concept", oid=res.observation_id, cid="c-civic")
    assert await ow.apply_to_message(db, ON, "m1", ow.OwnershipStats()) == 1
    assert [r["object_id"] for r in await owns(gw, "c-andrew")] == ["c-civic"]


async def test_negatives_write_nothing(db, gw):
    await seed(gw)
    for i, text in enumerate(["I want a dog named Toby.", "Your dog Toby is cute.", "I don't have a car named Civic.",
                              "My friend Sam owns a car.", "Do you like my dog Toby?"]):
        await turn(gw, f"n{i}", text, mentions=("c-toby", "c-civic", "c-sam"), day=3 + i)
        await ow.apply_to_message(db, ON, f"n{i}", ow.OwnershipStats())
    assert await owns(gw, "c-andrew") == [] and edges(db, "HAS_OBJECT") == set()


async def test_unnamed_speaker_or_unknown_speaker_concept_writes_nothing(db, gw):
    await seed(gw)
    await turn(gw, "m1", "My dog Toby is sweet.", speaker="user", mentions=("c-toby",))
    await turn(gw, "m2", "My dog Toby is sweet.", speaker="Zed", mentions=("c-toby",), day=4)   # no Concept "Zed"
    stats = ow.OwnershipStats()
    for mid in ("m1", "m2"):
        await ow.apply_to_message(db, ON, mid, stats)
    assert stats.skipped == {"no_speaker": 2} and edges(db, "HAS_OBJECT") == set()


class _NoLLM:
    def chat(self, *a, **k):
        raise AssertionError("the ownership rule must not call the LLM")


@pytest.mark.parametrize("on", [False, True])
async def test_process_turn_runs_the_rule_only_with_the_flag(db, gw, on):
    await seed(gw)
    await turn(gw, "m1", "My dog Toby is such a sweetheart.", mentions=("c-toby",))
    cfg = {"observations": {**(ON if on else OFF)["observations"], "llm_enabled": False}}
    created = await ex.process_turn(db, cfg, _NoLLM(), "m1", ex.ObservationWorkerStats())
    assert created == (1 if on else 0)
    assert len(await owns(gw, "c-andrew")) == (1 if on else 0)
    assert (len(edges(db, "HAS_OBJECT")) == 1) is on


async def test_backfill_over_existing_messages_and_idempotent(db, gw):
    await seed(gw)
    await turn(gw, "m1", "My dog Toby is such a sweetheart.", mentions=("c-toby",))
    await turn(gw, "m2", "Your dog Toby is cute.", mentions=("c-toby",), day=4)
    await turn(gw, "m3", "I bought a bike named Civic.", mentions=("c-civic",), day=5)
    await turn(gw, "m4", "No entity here at all.", day=6)
    fired: list = []
    first = await ow.backfill_ownership(db, ON, record=fired)
    assert (first.firings, first.created) == (2, 2) and first.skipped.get("not_first_person") == 1
    assert sorted((label, status) for _, label, _, status in fired) == [("Civic", "created"), ("Toby", "created")]
    second = await ow.backfill_ownership(db, ON)
    assert (second.created, second.duplicate) == (0, 2)
    assert sorted(r["object_id"] for r in await owns(gw, "c-andrew")) == ["c-civic", "c-toby"]
