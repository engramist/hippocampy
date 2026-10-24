"""B505: counts and sums computed by rule for aggregation questions (flag, default off).

B508/B509 adaptations: with skos_vocab on, membership is INSTANCE_OF plus the BROADER narrower
closure; with owl_properties on, sums prefer typed attribute literals.

Real Oxigraph store, no model, no LLM. Pins:
- the flag (default off; env CAMPY_ANSWER_AGGREGATE) and flag-off = unchanged (bundle, prompt);
- detection is structural (interrogative forms, kind noun phrase), not topical;
- kit counting: three sessions, three kits, a duplicate mention (same Concept and a same-name
  twin Concept) -> count 3, ordered by event time, each with date and quote;
- days summing: 3 days + 5 days = 8, parts listed; an unparsable item is named as skipped;
- not an aggregation question -> no section; kind not resolvable -> no section;
- negated claims and assistant turns do not count;
- the answer prompt gains the instruction only when the section is present.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import concept_links as cl
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import aggregation as ag
from campy.brain.thalamus import bundle_compiler as bc
from campy.brain.thalamus.ask import _AGGREGATE_INSTRUCTION, _bundle_to_prompt

pytestmark = pytest.mark.asyncio

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)

BASE = {"retrieval": {"graph_linking": True, "conversation_token_budget": 0},
        "observations": {"retrieval": False}}
ON = {**BASE, "retrieval": {**BASE["retrieval"], "answer_aggregate": True}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b505.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def concept(self, cid, text):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text,
                          emb=[0.0] * DIM, gist="Category", stype="DefinedTerm", now=T0)

    async def message(self, text, *, day, role="user"):
        self.n += 1
        mid = f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker="Sam", occurred_at=stamp)
        return mid

    async def item(self, cid, name, kind_id, quote, *, day, claim=None, polarity="asserted", observe=True,
                   via="is_a", predicate="did", typed=None):
        """An entity Concept `name` IS_A `kind_id`, a user turn saying `quote`, and (optionally)
        an Observation about it, linked the way B503/B504 link them."""
        if not any(r["concept_id"] == cid for r in await self.gw.run("concept_links.live_concepts")):
            await self.concept(cid, name)
        if via == "is_a":
            await self.gw.run("concept_links.link_is_a", cid=cid, pid=kind_id)
        else:                                   # B508: entity INSTANCE_OF kind
            await self.gw.run("kinds.mark_kind", cid=kind_id, scheme="kind")
            await self.gw.run("kinds.link_instance_of", cid=cid, kid=kind_id)
        mid = await self.message(f"Filler. {quote} More.", day=day)
        await self.gw.run("concept_links.link_message_concept", mid=mid, cid=cid)
        if observe:
            res = await obs.record_observation(self.db, obs.ObservationDraft(
                evidence_ref=mid, evidence_text=quote, subject_text="I", predicate=predicate,
                object_text=claim or name, extraction_method="llm", confidence=0.9, polarity=polarity,
                speaker="Sam", text_raw=f"Sam - did - {claim or name}"))
            assert res.ok, res
            await self.gw.run("observations.link_about_concept", oid=res.observation_id, cid=cid)
            if typed:                           # B509: a typed attribute literal on the Observation
                kind, num, unit = typed
                await self.gw.run("properties.set_attribute_value", oid=res.observation_id, value=claim or name,
                                  kind=kind, num=num, unit=unit, time=None)
        return mid


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


async def _kits(store):
    await store.concept("k-kit", "model kit")
    await store.item("e-revell", "Revell F-15 Eagle", "k-kit", "I bought a Revell F-15 Eagle", day=2)
    await store.item("e-spit", "Tamiya Spitfire", "k-kit", "I started the Tamiya Spitfire", day=9)
    await store.item("e-tiger", "Tiger I tank", "k-kit", "I finished the Tiger I tank", day=15)
    # a duplicate mention of the Spitfire, and a same-name twin Concept
    await store.item("e-spit", "Tamiya Spitfire", "k-kit", "The Tamiya Spitfire turned out great", day=20)
    await store.item("e-spit2", "tamiya spitfire", "k-kit", "my tamiya spitfire needs paint", day=21)


# --- flag -------------------------------------------------------------------------------

async def test_flag_default_off_and_env_turns_it_on():
    assert _DEFAULT_CONFIG["retrieval"]["answer_aggregate"] is False
    assert obs.answer_aggregate_enabled({}) is False
    assert obs.answer_aggregate_enabled(_DEFAULT_CONFIG) is False
    assert obs.answer_aggregate_enabled({"retrieval": {"answer_aggregate": True}}) is True
    cfg = apply_env_overrides({"retrieval": {}}, {"CAMPY_ANSWER_AGGREGATE": "1"})
    assert obs.answer_aggregate_enabled(cfg) is True
    cfg = apply_env_overrides({"retrieval": {"answer_aggregate": True}}, {"CAMPY_ANSWER_AGGREGATE": "0"})
    assert obs.answer_aggregate_enabled(cfg) is False


# --- detection --------------------------------------------------------------------------

@pytest.mark.parametrize("question, mode, kind_source, units", [
    ("How many model kits have I worked on or bought?", "count", "model kits", frozenset()),
    ("How many different species of birds have I seen?", "count", "species of birds", frozenset()),
    ("What is the total number of books I read?", "count", "books i read", frozenset()),
    ("How many days did I spend on camping trips in the United States this year?", "sum",
     "did i spend on camping trips in the united states this year", frozenset({"day"})),
    ("How much money did I spend on guitars?", "sum", "did i spend on guitars", frozenset({"dollar"})),
    ("How much did I spend on guitars?", "sum", "i spend on guitars", frozenset({"dollar"})),
    ("How long did I spend hiking in total?", "sum", "did i spend hiking in total", ag.DURATION_UNITS),
])
async def test_detects_aggregation_questions_by_form(question, mode, kind_source, units):
    a = ag.parse_aggregation(question)
    assert a is not None and a.mode == mode and a.units == units
    if mode == "count":
        assert a.kind_source.startswith(kind_source.split(" i ")[0])
    else:
        assert a.kind_source == kind_source


@pytest.mark.parametrize("question", [
    "What model kit did I buy first?",
    "When did I go camping?",
    "How long did the trip to Yellowstone take?",       # a duration, not a total
    "How are you?",
    "",
])
async def test_other_questions_are_not_aggregations(question):
    assert ag.parse_aggregation(question) is None


async def test_units_are_not_confused_with_repetition_counts():
    a = ag.parse_aggregation("How many times did I go to the gym?")
    assert a.mode == "count" and a.kind_source == "times"       # "times" is a noun to look up, not a unit


async def test_parse_amounts_reads_numbers_and_units_only():
    assert ag.parse_amounts("a 3-day trip and five nights, $1,200") == [(3.0, "day"), (5.0, "night"), (1200.0, "dollar")]
    assert ag.parse_amounts("I have 3 kits and a day off") == []
    assert ag.parse_amounts("route 66 days") == [(66.0, "day")]


# --- the section ------------------------------------------------------------------------

async def test_kit_count_is_three_with_dates_and_quotes(db, gw, store):
    await _kits(store)
    section = await ag.build_aggregate_section(db, "How many model kits have I worked on or bought?", ON)
    text = section.content[0]["text"]
    assert section.section_type == "aggregate"
    assert text.startswith('Items of kind "model kit" found in memory (3):')
    assert "Count: 3." in text
    lines = [ln for ln in text.splitlines() if ln[:2] in ("1.", "2.", "3.")]
    assert [ln.split(" [")[0] for ln in lines] == ["1. Revell F-15 Eagle", "2. Tamiya Spitfire", "3. Tiger I tank"]
    assert "[2023-05-02]" in lines[0] and '"I bought a Revell F-15 Eagle"' in lines[0]
    assert "[2023-05-09]" in lines[1]                    # the first mention's date, not the duplicates'
    assert "computed from memory by rule and may be incomplete" in text
    assert "Sum" not in text                             # a count question gets no sum


async def test_days_are_summed_with_the_parts_listed(db, gw, store):
    await store.concept("k-trip", "camping trip")
    await store.item("e-yel", "Yellowstone", "k-trip", "I spent 3 days at Yellowstone", day=3,
                     claim="camped for 3 days at Yellowstone")
    await store.item("e-big", "Big Sur", "k-trip", "We camped 5 days at Big Sur", day=12,
                     claim="camped 5 days at Big Sur")
    section = await ag.build_aggregate_section(
        db, "How many days did I spend on camping trips in the United States this year?", ON)
    text = section.content[0]["text"]
    assert 'Items of kind "camping trip" found in memory (2):' in text
    assert "Sum (added by rule, units not converted): 8 days. Parts: Yellowstone: 3 days, Big Sur: 5 days." in text
    assert "Not in the sum" not in text
    assert "not applied" in text and "may be incomplete" in text


async def test_unparsable_and_ambiguous_items_are_skipped_and_named(db, gw, store):
    await store.concept("k-trip", "camping trip")
    await store.item("e-yel", "Yellowstone", "k-trip", "I spent 3 days at Yellowstone", day=3, claim="3 days at Yellowstone")
    await store.item("e-big", "Big Sur", "k-trip", "We camped at Big Sur", day=12, claim="camped at Big Sur")
    await store.item("e-zion", "Zion", "k-trip", "Zion was 2 days then 4 days", day=14, claim="2 days then 4 days at Zion")
    await store.item("e-bear", "Bear Lake", "k-trip", "Two nights at Bear Lake", day=16, claim="two nights at Bear Lake")
    section = await ag.build_aggregate_section(db, "How many days did I spend on camping trips?", ON)
    text = section.content[0]["text"]
    assert "(4):" in text and "Count: 4." in text
    assert "Sum (added by rule, units not converted): 3 days. Parts: Yellowstone: 3 days." in text
    assert "Big Sur (no amount stated)" in text and "Zion (two different amounts)" in text
    assert "Bear Lake (no amount stated)" in text         # nights are not days


async def test_negated_claims_and_assistant_turns_do_not_count(db, gw, store):
    await store.concept("k-kit", "model kit")
    await store.item("e-a", "Revell F-15 Eagle", "k-kit", "I bought a Revell F-15 Eagle", day=2)
    await store.item("e-b", "Tamiya Spitfire", "k-kit", "I did not buy the Tamiya Spitfire", day=3, polarity="negated")
    await store.concept("e-c", "Tiger I tank")                        # only an assistant turn mentions it
    await gw.run("concept_links.link_is_a", cid="e-c", pid="k-kit")
    mid = await store.message("A Tiger I tank is a fine kit.", day=4, role="assistant")
    await gw.run("concept_links.link_message_concept", mid=mid, cid="e-c")
    section = await ag.build_aggregate_section(db, "How many model kits do I have?", ON)
    text = section.content[0]["text"]
    assert "(1):" in text and "Revell" in text and "Spitfire" not in text and "Tiger" not in text


async def test_sub_kind_members_count_but_the_sub_kind_does_not(db, gw, store):
    await store.concept("k-kit", "model kit")
    await store.concept("k-plane", "plane kit")
    await gw.run("concept_links.link_is_a", cid="k-plane", pid="k-kit")
    await store.item("e-eagle", "Revell F-15 Eagle", "k-plane", "I bought a Revell F-15 Eagle", day=2)
    await store.item("e-tiger", "Tiger I tank", "k-kit", "I finished the Tiger I tank", day=15)
    text = (await ag.build_aggregate_section(db, "How many model kits do I have?", ON)).content[0]["text"]
    assert "(2):" in text and "plane kit" not in text.split("Count")[0]


async def test_non_aggregation_question_produces_no_section(db, gw, store):
    await _kits(store)
    assert await ag.build_aggregate_section(db, "What model kit did I buy on May 2?", ON) is None


async def test_kind_not_resolvable_produces_no_section(db, gw, store):
    await _kits(store)
    assert await ag.build_aggregate_section(db, "How many skateboards have I bought?", ON) is None
    # a Concept exists but has no members: not a kind
    await store.concept("c-lonely", "telescope")
    assert await ag.build_aggregate_section(db, "How many telescopes have I bought?", ON) is None


# --- the bundle and the prompt -------------------------------------------------------------

async def test_bundle_flag_on_adds_the_section_and_off_is_unchanged(db, gw, store):
    await _kits(store)
    q = "How many model kits have I worked on or bought?"
    off = await bc.compile_bundle(q, db, BASE)
    on = await bc.compile_bundle(q, db, ON)
    assert not any(s.section_type == "aggregate" for s in off.sections)
    (agg,) = [s for s in on.sections if s.section_type == "aggregate"]
    assert "Count: 3." in agg.content[0]["text"]
    assert [(s.section_type, s.content) for s in on.sections if s.section_type != "aggregate"] \
        == [(s.section_type, s.content) for s in off.sections]
    # a non-aggregation question: flag on changes nothing
    other_off = await bc.compile_bundle("What model kit did I buy first?", db, BASE)
    other_on = await bc.compile_bundle("What model kit did I buy first?", db, ON)
    assert [(s.section_type, s.content) for s in other_on.sections] \
        == [(s.section_type, s.content) for s in other_off.sections]


def _bundle(*sections):
    return SimpleNamespace(sections=list(sections))


def _section(kind, text):
    return SimpleNamespace(section_type=kind, content=[{"text": text}], token_estimate=1)


async def test_prompt_uses_the_computed_figure_only_when_the_section_is_present():
    plain = _bundle(_section("conversation", "[Sam, 2023-05-02] I bought a kit"))
    with_agg = _bundle(_section("conversation", "[Sam, 2023-05-02] I bought a kit"),
                       _section("aggregate", "Items ... Count: 1."))
    p_plain = _bundle_to_prompt(plain, "How many kits?")
    p_agg = _bundle_to_prompt(with_agg, "How many kits?")
    assert _AGGREGATE_INSTRUCTION not in p_plain and "[aggregate" not in p_plain
    assert _AGGREGATE_INSTRUCTION in p_agg and "[aggregate:" in p_agg
    # the rest of the prompt, with the section absent, is exactly what it was
    assert p_plain == _bundle_to_prompt(plain, "How many kits?")
    assert "Use its Count and Sum as given" in p_agg


# --- B508: SKOS kind membership ---------------------------------------------------------------

SKOS = {**ON, "retrieval": {**ON["retrieval"], "skos_vocab": True}}


async def _skos_kits(store, gw):
    await store.concept("k-kit", "model kit")
    await store.concept("k-plastic", "plastic model kit")
    await gw.run("kinds.mark_kind", cid="k-kit", scheme="kind")
    await gw.run("kinds.mark_kind", cid="k-plastic", scheme="kind")
    await gw.run("kinds.link_broader", cid="k-plastic", pid="k-kit")
    await store.item("e-revell", "Revell F-15 Eagle", "k-plastic", "I bought a Revell F-15 Eagle", day=2, via="instance_of")
    await store.item("e-spit", "Tamiya Spitfire", "k-kit", "I started the Tamiya Spitfire", day=9, via="instance_of")


async def test_skos_instance_of_a_narrower_kind_counts_under_the_broader_kind(db, gw, store):
    await _skos_kits(store, gw)
    text = (await ag.build_aggregate_section(db, "How many model kits have I worked on or bought?", SKOS)).content[0]["text"]
    assert "(2):" in text and "Count: 2." in text
    assert "Revell F-15 Eagle" in text and "Tamiya Spitfire" in text
    assert "plastic model kit" not in text.split("Count")[0].split("\n", 1)[1]    # the sub-kind is not an item


async def test_skos_broader_kind_is_not_counted_the_other_way_round(db, gw, store):
    await _skos_kits(store, gw)
    text = (await ag.build_aggregate_section(db, "How many plastic model kits have I bought?", SKOS)).content[0]["text"]
    assert "(1):" in text and "Revell" in text and "Spitfire" not in text


async def test_skos_with_flag_on_still_counts_legacy_is_a_members(db, gw, store):
    await _kits(store)                                    # IS_A edges only
    text = (await ag.build_aggregate_section(db, "How many model kits have I worked on or bought?", SKOS)).content[0]["text"]
    assert "Count: 3." in text


async def test_skos_edges_without_the_flag_are_not_followed(db, gw, store):
    await _skos_kits(store, gw)
    # flag off: membership is IS_A only, and an INSTANCE_OF store has none
    assert await ag.build_aggregate_section(db, "How many model kits have I worked on or bought?", ON) is None


# --- B509: typed attribute values -------------------------------------------------------------

OWL = {**ON, "observations": {"retrieval": False, "owl_properties": True}}


async def _typed_trips(store):
    await store.concept("k-trip", "camping trip")
    # the claim text states no amount the regex can read; the typed literal does
    await store.item("e-yel", "Yellowstone", "k-trip", "Yellowstone was a long weekend", day=3,
                     claim="Yellowstone duration: a long weekend", predicate="has_attribute",
                     typed=("duration", 3 * 86400.0, "second"))
    await store.item("e-big", "Big Sur", "k-trip", "We camped 5 days at Big Sur", day=12,
                     claim="Big Sur duration: 5 days", predicate="has_attribute",
                     typed=("duration", 5 * 86400.0, "second"))


async def test_owl_typed_values_are_summed_when_the_flag_is_on(db, gw, store):
    await _typed_trips(store)
    q = "How many days did I spend on camping trips?"
    text = (await ag.build_aggregate_section(db, q, OWL)).content[0]["text"]
    assert "Sum (added by rule, units not converted): 8 days. Parts: Yellowstone: 3 days, Big Sur: 5 days." in text
    # without the flag, the text reading: Big Sur only, Yellowstone named as skipped
    plain = (await ag.build_aggregate_section(db, q, ON)).content[0]["text"]
    assert "Sum (added by rule, units not converted): 5 days. Parts: Big Sur: 5 days." in plain
    assert "Yellowstone (no amount stated)" in plain


async def test_owl_money_in_usd_and_untyped_fallback(db, gw, store):
    await store.concept("k-guitar", "guitar")
    await store.item("e-strat", "Stratocaster", "k-guitar", "The Stratocaster was pricey", day=2,
                     claim="Stratocaster price: about twelve hundred", predicate="has_attribute",
                     typed=("money", 1200.0, "USD"))
    await store.item("e-tele", "Telecaster", "k-guitar", "I paid $800 for the Telecaster", day=5, claim="paid $800")
    text = (await ag.build_aggregate_section(db, "How much money did I spend on guitars?", OWL)).content[0]["text"]
    assert "$2000" in text and "Stratocaster: $1200" in text and "Telecaster: $800" in text


async def test_typed_amount_conversions():
    ev = {"attr_kind": "duration", "attr_num": 7200.0, "attr_unit": "second"}
    assert ag.typed_amount(ev, frozenset({"hour"})) == (2.0, "hour")
    assert ag.typed_amount(ev, ag.DURATION_UNITS) == (2.0, "hour")
    assert ag.typed_amount({**ev, "attr_num": 3 * 2629800.0}, frozenset({"month"})) == (3.0, "month")
    assert ag.typed_amount({**ev, "attr_num": 3 * 2629800.0}, ag.DURATION_UNITS) is None      # not guessed
    assert ag.typed_amount({"attr_kind": "money", "attr_num": 5.0, "attr_unit": "EUR"}, frozenset({"dollar"})) is None
    assert ag.typed_amount({"attr_kind": "number", "attr_num": 5.0}, frozenset({"day"})) is None
    assert ag.typed_amount({}, frozenset({"day"})) is None


async def test_flags_off_rows_carry_no_typed_or_skos_extras(db, gw, store):
    await _typed_trips(store)
    ids = ["k-trip"]
    rows = await gw.run("thalamus.bundle_aggregate_items", concept_ids=ids)
    assert rows and all("attr_num" not in e for r in rows for e in r["evidence"])
    rows = await gw.run("thalamus.bundle_aggregate_items", concept_ids=ids, typed=True)
    assert any("attr_num" in e for r in rows for e in r["evidence"])
