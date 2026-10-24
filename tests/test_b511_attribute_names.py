"""B511: attribute facts reach OWL properties (flag CAMPY_OWL_PROPERTIES).

Real Oxigraph store, fake LLM, no model. Pins:
- each written shape gets its name by rule: "name: value", quantity phrase, "my X is Y", bare number
  counted by the noun after it, "N-year-old", the literal key "name";
- shapes the rules cannot name (verb phrase, bare value, a partitive "one of ...") stay unlinked;
- the extractor's structured `attribute` field: validated by rule (short noun phrase, value in the turn),
  rejected when the value is not in the turn, carried to the Observation's property;
- flag off: prompt byte-identical, no property written, B499 rule intact.
"""

from __future__ import annotations

import json

import pytest

from campy.brain.hippocampus import attribute_names as an
from campy.brain.hippocampus import attribute_properties as ap
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import extract as ex

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
NS = "https://campy.dev/ns#"
OWL = {"observations": {"owl_properties": True}}
BASE = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600, "retrieval": False},
        "retrieval": {"conversation_token_budget": 0}}
OWL_CFG = {**BASE, "observations": {**BASE["observations"], "owl_properties": True}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b511.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def write(db, gw, n, quote, obj, *, subject="I", config=OWL, date="2023-05-01", attr=None):
    mid = f"m{n}"
    body = f"Hello. {quote}. Bye."
    stamp = f"{date}T12:00:00+00:00"
    await gw.run("capture.create_message", message_id=mid, text_raw=body, embedding=None, embedding_model="m",
                 embedding_dim=DIM, role="user", byte_end=len(body), created_at=stamp)
    await gw.run("capture.set_message_source", message_id=mid, speaker="Alex", occurred_at=stamp)
    name, value = attr if attr else (None, None)
    res = await obs.record_observation(db, obs.ObservationDraft(
        evidence_ref=mid, evidence_text=quote, subject_text=subject, predicate="has_attribute", object_text=obj,
        extraction_method="llm", confidence=0.9, speaker="Alex", text_raw=f"Alex - has_attribute - {obj}",
        embedding=Q, attr_name=name, attr_value=value), config=config, supersede=False)
    assert res.status == "created", res
    return res.observation_id


async def prop_label(gw, oid):
    rows = await gw.run("properties.property_of", oid=oid)
    if not rows:
        return None
    pid = dict(rows[0])["property_id"]
    return next(str(r["text_raw"]) for r in await gw.run("properties.live_properties") if r["property_id"] == pid)


# --- each shape, by rule ---------------------------------------------------------------------

@pytest.mark.parametrize("obj,quote,subject,name,value,source", [
    ("500 followers", "I have 500 followers now", "I", "followers", "500", "quantity"),
    ("currently on page 200", "I'm currently on page 200", "I", "page", "200", "quantity"),
    ("completed 30 videos", "I completed 30 videos", "I", "completed videos", "30", "quantity"),
    ("blue", "My favorite color is blue", "I", "favorite color", "blue", "copula"),
    ("3", "Max's age is 3 now", "Max", "age", "3", "copula"),
    ("four", "I love my four dogs", "I", "dogs", "four", "count"),
    ("3-year-old", "They're all 3-year-old", "They", "age", "3 years", "age"),
    ("name: Scout", "going with 'Scout' for our pup", "our pup", "name", "Scout", "name"),
    ("job: nurse", "My job: nurse", "I", "job", "nurse", "stated"),
])
def test_shape_gets_a_name(obj, quote, subject, name, value, source):
    key, src = an.derive_key(obj, quote=quote, turn=f"Hi. {quote}. Bye.", subject_text=subject, speaker="Alex")
    assert key is not None and src == source, (key, src)
    assert ok_norm(key.name) == name
    assert ok_norm(key.raw or key.value) == ok_norm(value)


def ok_norm(s):
    return " ".join(s.lower().split())


@pytest.mark.parametrize("obj,quote,subject", [
    ("loves hiking", "She loves hiking", "She"),                      # verb phrase: no name to be had
    ("park", "I'm lucky to have a park near me", "I"),                # bare value
    ("perfect", "It's perfect", "it"),
    ("one of the most rewarding things", "it is one of the most rewarding things", "I"),   # partitive
    ("combine two of my passions", "a way to combine two of my passions", "I"),
    ("attribute: accomplished", "I felt so accomplished", "I"),       # placeholder key
    ("blue", "My sister's favorite color is blue", "I"),              # possessor is not the subject
    ("500 followers", "I wish I had more followers", "I"),            # the value is not in the turn
])
def test_unnameable_shape_stays_unnamed(obj, quote, subject):
    key, src = an.derive_key(obj, quote=quote, turn=f"Hi. {quote}. Bye.", subject_text=subject, speaker="Alex")
    assert key is None and src == "none"


# --- the structured field ------------------------------------------------------------------------

def test_structured_attribute_is_validated_by_rule():
    turn = "I got a promotion and now I have 1,200 followers."
    assert an.validate_structured({"name": "followers", "value": "1,200"}, turn) == (("followers", "1,200"), None)
    assert an.validate_structured({"name": "My Followers", "value": "1200"}, turn) == (("followers", "1200"), None)
    assert an.validate_structured(None, turn) == (None, None)                       # nothing said is no rejection
    assert an.validate_structured("followers: 1200", turn)[1] == "attribute_malformed"


def test_structured_attribute_rejected_when_the_value_is_not_in_the_turn():
    turn = "I got a promotion last week."
    assert an.validate_structured({"name": "job", "value": "manager"}, turn) == (None, "attribute_value_not_in_turn")


@pytest.mark.parametrize("name", ["", "attribute", "value", "she is happy", "the number of followers I have",
                                  "followers: 5", "x" * 50, "is", "5k"])
def test_structured_attribute_rejects_bad_names(name):
    assert an.validate_structured({"name": name, "value": "500"}, "I have 500 followers")[0] is None


def test_structured_attribute_prompt_field_only_with_the_flag():
    off = ex.build_messages("I run a lot.", "Alex", "2023-05-01", cardinality=False)
    assert '"attribute"' not in off[1]["content"]
    on = ex.build_messages("I run a lot.", "Alex", "2023-05-01", cardinality=True)[1]["content"]
    assert '"attribute"' in on and '"cardinality"' in on
    assert on.count('- "confidence"') == 1
    assert off == ex.build_messages("I run a lot.", "Alex", "2023-05-01")


class LLM:
    def __init__(self, *items):
        self.reply = json.dumps(list(items))

    def chat(self, messages, **kwargs):
        return self.reply


def claim(quote, obj, **extra):
    return {"subject": "I", "predicate": "has_attribute", "object": obj, "time": None, "polarity": "asserted",
            "quote": quote, "confidence": 0.9, **extra}


async def turn(db, gw, cfg, text, *items):
    mid = "t1"
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None, embedding_model="m",
                 embedding_dim=DIM, role="user", byte_end=len(text), created_at="2023-05-01T12:00:00+00:00")
    await gw.run("capture.set_message_source", message_id=mid, speaker="Alex",
                 occurred_at="2023-05-01T12:00:00+00:00")
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, cfg, LLM(*items), mid, stats)
    return stats


async def live_props(gw):
    return {str(r["text_raw"]) for r in await gw.run("properties.live_properties")}


async def test_extractor_carries_a_valid_structured_attribute_to_a_property(db, gw):
    text = "Quick update for everyone here: I have grown my channel and now it has 1,200 followers."
    stats = await turn(db, gw, OWL_CFG, text, claim("it has 1,200 followers", "growing", attribute={
        "name": "channel followers", "value": "1,200"}))
    assert stats.created == 1
    assert await live_props(gw) == {"channel followers"}


async def test_extractor_drops_an_invented_attribute_but_keeps_the_claim(db, gw):
    text = "Quick update for everyone here: I have grown my channel and it is doing really well lately."
    stats = await turn(db, gw, OWL_CFG, text, claim("it is doing really well lately", "doing well", attribute={
        "name": "followers", "value": "1,200"}))
    assert stats.created == 1
    assert stats.rejected.get("attribute_value_not_in_turn") == 1
    assert await live_props(gw) == set()


# --- through the store -----------------------------------------------------------------------------

async def test_rule_named_attributes_link_and_type_their_values(db, gw):
    a = await write(db, gw, 1, "I have 500 followers", "500 followers")
    b = await write(db, gw, 2, "My favorite color is blue", "blue")
    c = await write(db, gw, 3, "I felt so accomplished", "accomplished")
    assert await prop_label(gw, a) == "follower count"       # the seed property of that name
    assert await prop_label(gw, b) == "favorite color"
    assert await prop_label(gw, c) is None                       # no name, no property
    rows = db._execute_and_collect(
        f"SELECT ?k ?n WHERE {{ ?o <{NS}observation_id> '{a}' ; <{NS}attr_value_kind> ?k ; <{NS}attr_value_num> ?n }}")
    assert len(rows) == 1 and str(rows[0]["k"]) == "number" and float(str(rows[0]["n"])) == 500.0


async def test_rule_named_property_supersedes_when_functional(db, gw):
    old = await write(db, gw, 1, "My favorite color is blue", "blue", date="2023-01-01")
    new = await write(db, gw, 2, "My favorite color is green", "green", date="2023-03-01")
    assert (await obs.get_observation(db, old))["superseded_by"] == new     # 'favorite' is a single-valued modifier


async def test_structured_pair_names_a_bare_value_and_is_ignored_with_the_flag_off(db, gw):
    oid = await write(db, gw, 1, "Switched jobs, I am a nurse now", "nurse", attr=("job", "nurse"))
    assert await prop_label(gw, oid) == "occupation"          # seed property, "job" its altLabel
    off = await write(db, gw, 2, "Sam is a nurse these days", "nurse", subject="Sam", attr=("job", "nurse"), config=None)
    assert await prop_label(gw, off) is None
    assert {str(r["text_raw"]) for r in await gw.run("properties.live_properties")} == {"occupation"}


def test_rules_off_is_the_b509_parse():
    # rules=False is the B509 parse of the written object only
    legacy = ap.attribute_key(obs.ObservationDraft(
        evidence_ref="m", evidence_text="x", subject_text="I", predicate="has_attribute",
        object_text="one of the most rewarding things", extraction_method="llm", confidence=1.0),
        {"text_raw": "one of the most rewarding things"}, rules=False)
    assert legacy is not None            # B509 accepted it; B511 rules do not
    assert ap.attribute_key(obs.ObservationDraft(
        evidence_ref="m", evidence_text="x", subject_text="I", predicate="has_attribute",
        object_text="one of the most rewarding things", extraction_method="llm", confidence=1.0),
        {"text_raw": "one of the most rewarding things"}) is None
