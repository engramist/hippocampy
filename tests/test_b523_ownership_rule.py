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
    ("Garlic is my go-to ingredient.", "not_ownable"),
    ("Nova is my favorite bike.", "not_ownable"),
    ("Last Tuesday, my gf, Sam, and I played board games.", "not_ownable"),
    ("Last Tuesday, my gf, Toby, and I had a really awesome night playing board games.", "not_ownable"),
    ("I got Sam to help me move.", "not_ownable"),
])
def test_negatives_do_not_fire(nlp, text, reason):
    labels, stats = run(nlp, text)
    assert labels == []
    if reason:
        assert stats.skipped.get(reason, 0) >= 1, stats.skipped


def test_a_proper_noun_with_no_concept_is_returned_for_creation_with_its_head_noun(nlp):
    stats = ow.OwnershipStats()
    ms = ow.find_ownership(nlp("My dog Pixie loves walks."), {"buddy": "c-buddy"}, stats)
    assert [(m.label, m.concept_id, m.kind, m.quote) for m in ms] == [("Pixie", None, "dog", "My dog Pixie")]
    ms = ow.find_ownership(nlp("We adopted Pixie."), {}, stats)
    assert [(m.label, m.concept_id, m.kind) for m in ms] == [("Pixie", None, None)]     # no head noun, no kind
    ms = ow.find_ownership(nlp("Pixie, my pups, is a star."), {}, stats)
    assert [m.kind for m in ms] == ["pup"]


def test_negatives_with_an_unknown_proper_noun_still_skip(nlp):
    for text in ("Your dog Pixie is cute.", "I don't have a car named Pixie.", "My friend Pixie called."):
        ms = ow.find_ownership(nlp(text), {}, ow.OwnershipStats())
        assert ms == [], text


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


async def seed(gw, owned_kinds=("dog", "car", "bike", "puppy")):
    from campy.brain.hippocampus import kinds as kinds_mod

    for cid, text in (("c-andrew", "Andrew"), ("c-toby", "Toby"), ("c-civic", "Civic"), ("c-sam", "Sam")):
        await concept(gw, cid, text)
    for kind in owned_kinds:      # real categories: kinds that some entity is INSTANCE_OF (the ownable test)
        await concept(gw, f"k-{kind}", kind)
        await kinds_mod.mark_kind(gw, f"k-{kind}")
        await concept(gw, f"x-{kind}", f"seed {kind} entity")
        await kinds_mod.link_instance_of(gw, f"x-{kind}", f"k-{kind}")


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


async def test_known_concept_not_linked_to_the_message_is_reused_not_duplicated(db, gw):
    await seed(gw)
    await turn(gw, "m1", "My dog Toby is such a sweetheart.")           # Toby exists but is not linked
    before = len(await gw.run("concept_links.live_concepts"))
    stats = ow.OwnershipStats()
    assert await ow.apply_to_message(db, ON, "m1", stats) == 1
    assert [r["object_id"] for r in await owns(gw, "c-andrew")] == ["c-toby"]
    assert [r["text_raw"] for r in await gw.run("concept_links.live_concepts")].count("Toby") == 1


async def test_unknown_proper_noun_creates_one_concept_and_a_kind_second_mention_reuses_it(db, gw):
    await seed(gw)
    await turn(gw, "m1", "We adopted a puppy named Pixie.")
    await turn(gw, "m2", "My dog Pixie is so cute.", day=4)
    s1, s2 = ow.OwnershipStats(), ow.OwnershipStats()
    assert await ow.apply_to_message(db, ON, "m1", s1) == 1
    assert s1.entity_concepts_created == 1 and s1.kinds_linked == 1       # Pixie; the kind "puppy" exists
    assert await ow.apply_to_message(db, ON, "m2", s2) == 0               # same claim: evidence added
    assert s2.duplicate == 1 and s2.entity_concepts_created == 0
    names = [r["text_raw"] for r in await gw.run("concept_links.live_concepts")]
    assert names.count("Pixie") == 1
    rows = await owns(gw, "c-andrew")
    assert {r["object_id"] for r in rows} == {rows[0]["object_id"]}        # one object; one row per evidence turn
    row = rows[0]
    assert row["object_label"] == "Pixie"
    assert "puppy" in row["kinds"].split("|")
    assert len(edges(db, "EVIDENCED_BY")) == 2 and ("m1", row["object_id"]) in edges(db, "MENTIONS")


async def test_created_entity_without_head_noun_has_no_kind(db, gw):
    await seed(gw)
    await turn(gw, "m1", "I adopted Pixie last week.")
    stats = ow.OwnershipStats()
    assert await ow.apply_to_message(db, ON, "m1", stats) == 1
    assert stats.entity_concepts_created == 1 and stats.kinds_linked == 0


async def test_negative_with_unknown_proper_noun_creates_nothing(db, gw):
    await seed(gw)
    before = len(await gw.run("concept_links.live_concepts"))
    await turn(gw, "m1", "Your dog Pixie is cute.")
    await turn(gw, "m2", "I wish I had a dog named Pixie.", day=4)
    for mid in ("m1", "m2"):
        await ow.apply_to_message(db, ON, mid, ow.OwnershipStats())
    assert len(await gw.run("concept_links.live_concepts")) == before and edges(db, "HAS_OBJECT") == set()


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
    assert (first.firings, first.created) == (2, 2)
    assert sorted((label, status) for _, label, _, status, _how in fired) == [("Civic", "created"), ("Toby", "created")]
    second = await ow.backfill_ownership(db, ON)
    assert (second.created, second.duplicate) == (0, 2)
    assert sorted(r["object_id"] for r in await owns(gw, "c-andrew")) == ["c-civic", "c-toby"]


# --- widened grammar (B523): naming, care, coordination ----------------------------------------

def fire(nlp, text, *, ctx=None, confirmed=None, mode="all", known=None):
    stats = ow.OwnershipStats()
    ms = ow.find_ownership(nlp(text), known if known is not None else KNOWN, stats,
                           context_kinds=ctx, confirmed=confirmed, mode=mode)
    return ms, stats


@pytest.mark.parametrize("text,ctx,label,kind", [
    ("We named her Luna last week.", ["cat"], "Luna", "cat"),
    ("I named him Civic.", ["car"], "Civic", "car"),
    ("We call it Nova.", ["bike"], "Nova", "bike"),
    ("Nova is what I named him.", ["bike"], "Nova", "bike"),
    ("Birch is what we named it.", ["house"], "Birch", "house"),
    ("His name is Max and he loves walks.", ["plant"], "Max", "plant"),
    ("Her name is Acme.", ["company"], "Acme", "company"),
])
def test_naming_uses_a_possessed_kind_from_the_previous_turn(nlp, text, ctx, label, kind):
    (m,) = fire(nlp, text, ctx=ctx)[0]
    assert (m.label, m.construction) == (label, "naming")


def test_naming_takes_its_kind_from_the_same_turn(nlp):
    ms, _ = fire(nlp, "I just got a new puppy. His name is Max.")
    assert [(m.label, m.construction) for m in ms] == [("Max", "naming")]
    ms, _ = fire(nlp, "My new bike is great, we named it Nova.")
    assert [(m.label, m.construction) for m in ms] == [("Nova", "naming")]


def test_naming_carries_the_kind_when_the_entity_is_created(nlp):
    ms, _ = fire(nlp, "We named her Pixie.", ctx=["kitten"], known={})
    assert [(m.label, m.concept_id, m.kind, m.construction) for m in ms] == [("Pixie", None, "kitten", "naming")]


@pytest.mark.parametrize("text,ctx,reason", [
    ("I named him Max.", [], "no_kind_context"),                       # no possessed kind noun precedes
    ("His name is Max.", [], "no_kind_context"),
    ("I named the project Atlas.", [], "no_kind_context"),
    ("I named the project Birch.", ["cat"], None),                      # a kind, but not this one
    ("I want to name him Rex.", ["dog"], "irrealis"),
    ("I would name him Rex.", ["dog"], "irrealis"),
    ("They named him Rex.", ["dog"], "not_first_person"),
    ("I didn't name him Rex.", ["dog"], "negated"),
    ("Did you name him Rex?", ["dog"], None),
])
def test_naming_negatives(nlp, text, ctx, reason):
    ms, stats = fire(nlp, text, ctx=ctx, known={**KNOWN, "atlas": "c-atlas"})
    assert ms == []
    if reason:
        assert stats.skipped.get(reason, 0) >= 1, stats.skipped


def test_naming_ignores_a_person_role_or_a_possession_of_someone_else(nlp):
    nouns = ow._kind_nouns(nlp("My friend is lovely. Her dog barks. I met my sister."))
    assert nouns == []
    assert ow._kind_nouns(nlp("A new puppy I adopted is great. I got a plant. My pups run.")) == ["puppy", "plant", "pup"]


@pytest.mark.parametrize("text,label", [
    ("We feel so lucky to have Luna.", "Luna"),
    ("I'm grateful to have Nova.", "Nova"),
    ("I love having Civic around.", "Civic"),
    ("I enjoy having Birch.", "Birch"),
    ("I'm so happy to have Acme.", "Acme"),
])
def test_care_construction_fires(nlp, text, label):
    (m,) = fire(nlp, text)[0]
    assert (m.label, m.construction) == (label, "care")


@pytest.mark.parametrize("text,reason", [
    ("I want to have Nova.", "irrealis"),
    ("I would like to have Nova.", "irrealis"),
    ("I hope to have Luna someday.", "irrealis"),
    ("I'm going to have Nova.", "irrealis"),
    ("She is lucky to have Luna.", "not_first_person"),
    ("I'm not lucky to have Nova.", "irrealis"),
])
def test_care_negatives(nlp, text, reason):
    ms, stats = fire(nlp, text)
    assert ms == []


def test_care_does_not_fire_for_plural_person_role_nouns(nlp):
    ms, _ = fire(nlp, "I'm lucky to have friends like Jo.", known={**KNOWN, "jo": "c-jo"})
    assert ms == []
    ms, _ = fire(nlp, "Lucky to have friends like Jo.", known={**KNOWN, "jo": "c-jo"})
    assert ms == []


def test_coordination_only_confirms(nlp):
    text = "Toby and I went hiking."
    ms, stats = fire(nlp, text, confirmed={"c-toby"})
    assert [(m.label, m.construction) for m in ms] == [("Toby", "coordination")]
    ms, stats = fire(nlp, text, confirmed={"c-buddy"})                 # not confirmed: never creates ownership alone
    assert ms == [] and stats.skipped == {"unconfirmed_coordination": 1}
    ms, _ = fire(nlp, text, confirmed=None)                            # no confirmations given: construction off
    assert ms == []
    ms, _ = fire(nlp, text, confirmed={"c-toby"}, mode="no_coordination")
    assert ms == []
    ms, _ = fire(nlp, "Me and Toby went hiking.", confirmed={"c-toby"})
    assert [m.construction for m in ms] == ["coordination"]


@pytest.mark.parametrize("text", [
    "Sam and I went hiking.",                    # a friend: nothing confirms Sam
    "Toby and Sam went hiking.",                 # not with the speaker
    "Toby and I didn't go hiking.",
    "Did Toby and I go hiking?",
])
def test_coordination_negatives(nlp, text):
    ms, _ = fire(nlp, text, confirmed={"c-toby"})        # Toby is confirmed, Sam is not
    assert ms == []


def test_coordination_never_creates_a_concept(nlp):
    ms, stats = fire(nlp, "Pixie and I went hiking.", confirmed={"c-toby"}, known={})
    assert ms == []


# --- widened grammar on a real store ---------------------------------------------------------

async def test_naming_across_the_speakers_previous_turn_on_a_store(db, gw):
    await seed(gw)
    await turn(gw, "p1", "We just got a new kitten!", day=3)
    await turn(gw, "p2", "That's lovely, congratulations!", speaker="Audrey", day=3)
    await turn(gw, "p3", "We named her Pixie.", day=3)
    for a, b in (("p1", "p2"), ("p2", "p3")):
        db.execute(f"INSERT DATA {{ <https://campy.dev/id/Message/{a}> <https://campy.dev/ns#FOLLOWED_BY> <https://campy.dev/id/Message/{b}> }}")
    await concept(gw, "c-audrey", "Audrey")
    stats = ow.OwnershipStats()
    rec: list = []
    assert await ow.apply_to_message(db, ON, "p3", stats, record=rec) == 1
    assert [(l, c) for _, l, _, _, c in rec] == [("Pixie", "naming")]
    assert stats.entity_concepts_created >= 1
    (row,) = await owns(gw, "c-andrew")
    assert row["object_label"] == "Pixie" and "kitten" in row["kinds"].split("|")


async def test_naming_without_a_possessed_kind_before_it_writes_nothing(db, gw):
    await seed(gw)
    await turn(gw, "p1", "The weather is nice.", day=3)
    await turn(gw, "p2", "We named her Pixie.", day=3)
    db.execute("INSERT DATA { <https://campy.dev/id/Message/p1> <https://campy.dev/ns#FOLLOWED_BY> <https://campy.dev/id/Message/p2> }")
    stats = ow.OwnershipStats()
    assert await ow.apply_to_message(db, ON, "p2", stats) == 0
    assert stats.skipped.get("no_kind_context") == 1 and await owns(gw, "c-andrew") == []


async def test_coordination_confirmed_by_an_owned_kind_and_two_pass_backfill(db, gw):
    await seed(gw)
    await concept(gw, "c-buddy", "Buddy")
    await concept(gw, "c-dog", "dog")
    from campy.brain.hippocampus import kinds as kinds_mod

    await kinds_mod.mark_kind(gw, "c-dog")
    await kinds_mod.link_instance_of(gw, "c-toby", "c-dog")
    await kinds_mod.link_instance_of(gw, "c-buddy", "c-dog")
    # the coordination turn comes FIRST in time: the two-pass backfill must not depend on order
    await turn(gw, "m1", "Buddy and I went hiking.", mentions=("c-buddy",), day=3)
    await turn(gw, "m2", "Sam and I went hiking.", mentions=("c-sam",), day=4)
    await turn(gw, "m3", "My dog Toby is such a sweetheart.", mentions=("c-toby",), day=5)
    fired: list = []
    stats = await ow.backfill_ownership(db, ON, record=fired)
    got = sorted((label, how) for _, label, _, _, how in fired)
    assert got == [("Buddy", "coordination"), ("Toby", "possessive")]
    assert stats.skipped.get("unconfirmed_coordination") == 1               # Sam
    assert sorted(r["object_id"] for r in await owns(gw, "c-andrew")) == ["c-buddy", "c-toby"]
    again = await ow.backfill_ownership(db, ON)
    assert again.created == 0


async def test_person_like_kind_does_not_confirm_coordination(db, gw):
    await seed(gw)
    await concept(gw, "c-person", "person")
    from campy.brain.hippocampus import kinds as kinds_mod

    await kinds_mod.mark_kind(gw, "c-person")
    await kinds_mod.link_instance_of(gw, "c-toby", "c-person")      # an extractor error seen in real data
    await kinds_mod.link_instance_of(gw, "c-sam", "c-person")
    await turn(gw, "m1", "My dog Toby is such a sweetheart.", mentions=("c-toby",), day=3)
    await turn(gw, "m2", "Sam and I went hiking.", mentions=("c-sam",), day=4)
    await ow.backfill_ownership(db, ON)
    assert [r["object_id"] for r in await owns(gw, "c-andrew")] == ["c-toby"]


def test_a_possessed_noun_must_be_a_known_kind_to_serve_as_naming_context(nlp):
    doc = nlp("Pets bring joy to our lives. My pups run, and I got a plant.")
    assert ow._kind_nouns(doc, vocab={"pup"}) == ["pup", "plant"]        # "our lives" is not a kind; acquired needs none
    assert ow._kind_nouns(doc) == ["life", "pup", "plant"]


def test_naming_list_shares_the_clause(nlp):
    ms, _ = fire(nlp, "Their names are Toby, Buddy and Luna.", ctx=["dog"])
    assert sorted(m.label for m in ms) == ["Buddy", "Luna", "Toby"]


# --- ownable head nouns, compound modifiers, full names (B523 precision) ---------------------------

@pytest.fixture(autouse=True)
def _no_wordnet_unless_a_test_supplies_it(monkeypatch):
    """The ownable test consults WordNet when it is installed (B534 shares the loader). These tests pin the
    rule against the graph kinds alone, so they must not depend on whether the corpus is on the machine
    (real WordNet files "haven" under noun.artifact); tests that want a lexname patch it themselves."""
    monkeypatch.setattr(ow, "_wordnet_lexname", lambda w: None)


OWNABLE = ow.make_ownable({"dog", "car", "bike", "scarf", "poster", "cat", "plant", "house", "company"})


@pytest.mark.parametrize("text", [
    "I'm so excited about my Nova trip.",                  # the trip is held; Nova modifies it
    "I love my Birch scarf.",
    "I framed my Civic poster.",
    "We packed our Acme mug.",
    "My Luna Park visit was fun.",
])
def test_a_name_that_modifies_the_possessed_noun_is_not_owned(nlp, text):
    ms, stats = fire(nlp, text)
    assert ms == [] and stats.skipped.get("modifier", 0) + stats.skipped.get("partial_name", 0) >= 1, stats.skipped


@pytest.mark.parametrize("text", [
    "Nova is my top pick.",
    "Birch has always been my haven.",
    "Acme is my passion.",
    "Luna is my inspiration.",
    "Civic is my favorite hobby.",
])
def test_a_predicate_nominal_whose_noun_is_not_ownable_does_not_fire(nlp, text):
    ms, stats = ow.find_ownership(nlp(text), KNOWN, ow.OwnershipStats(), ownable=OWNABLE), None
    assert ms == []


@pytest.mark.parametrize("text,label", [
    ("Nova is my bike.", "Nova"),
    ("Birch has always been my house.", "Birch"),
    ("Acme is my company.", "Acme"),
    ("Luna is my cat.", "Luna"),
    ("Civic is my car.", "Civic"),
    ("Toby, my plant, thrives.", "Toby"),
])
def test_a_predicate_nominal_with_an_ownable_noun_fires(nlp, text, label):
    ms = ow.find_ownership(nlp(text), KNOWN, ow.OwnershipStats(), ownable=OWNABLE)
    assert [m.label for m in ms] == [label]


def test_the_acquisition_object_head_noun_must_be_ownable_too(nlp):
    stats = ow.OwnershipStats()
    assert ow.find_ownership(nlp("I started my group called Nova."), KNOWN, stats, ownable=OWNABLE) == []
    assert stats.skipped.get("not_ownable") == 1
    assert [m.label for m in ow.find_ownership(nlp("I bought a bike called Nova."), KNOWN, ow.OwnershipStats(),
                                               ownable=OWNABLE)] == ["Nova"]
    assert ow.find_ownership(nlp("I adopted Nova."), KNOWN, ow.OwnershipStats(), ownable=OWNABLE) != []   # no head noun


def test_ownable_uses_graph_kinds_or_wordnet(monkeypatch):
    graph_only = ow.make_ownable({"dog"})
    assert graph_only("dogs") and not graph_only("haven")
    monkeypatch.setattr(ow, "_wordnet_lexname", lambda w: {"scarf": "noun.artifact", "haven": "noun.location",
                                                           "apple": "noun.food"}.get(w))
    both = ow.make_ownable({"dog"})
    assert both("scarf") and both("apple") and both("dog") and not both("haven")
    monkeypatch.setattr(ow, "_wordnet_lexname", lambda w: {"group": "noun.group", "dog": "noun.animal"}.get(w))
    vetoed = ow.make_ownable({"group", "dog"})                  # a graph kind "group" (filed under people) is vetoed
    assert vetoed("dog") and not vetoed("group")


def test_wordnet_missing_falls_back_to_graph_kinds(monkeypatch):
    import builtins

    real = builtins.__import__

    def deny(name, *a, **k):
        if name.startswith("nltk"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", deny)
    from campy.brain.temporal_lobe.lexicon import wordnet

    assert wordnet.lexname("scarf") is None
    assert ow.make_ownable({"dog"})("dog") and not ow.make_ownable({"dog"})("scarf")


def test_the_whole_proper_noun_span_is_the_entity(nlp):
    known = {**KNOWN, "man": "c-man"}
    ms, stats = fire(nlp, "Iron Man is my cat.", known=known)           # "Man" alone is only part of the name
    assert ms == [] and stats.skipped.get("partial_name") == 1
    ms = ow.find_ownership(nlp("Iron Man is my cat."), {}, ow.OwnershipStats())
    assert [m.label for m in ms] == ["Iron Man"]                          # unknown names are created whole
    ms = ow.find_ownership(nlp("Mount Fuji is my house."), {}, ow.OwnershipStats())
    assert all(m.label != "Fuji" for m in ms)
