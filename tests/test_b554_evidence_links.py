"""B554: an Observation is linked to the admitted entities its evidence names. Real spaCy (en_core_web_md) and a
real Oxigraph store; no LLM (a scripted client), no model call.

Pure rule (spaCy only): quote placement, tier 1 (inside the quote), tier 2 (same clause), the fan-out rule over
several Observations of one turn, list mates, forms of address, speakers, exact-case occurrences.
Graph: flag off / on, the model's wording plays no part, idempotence, the coverage query, the backfill.
"""

from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campy.brain.brainstem.config import PROFILES, _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus.entity_admission import ADMITTED_LABELS
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
from campy.brain.temporal_lobe.observations import evidence_entities as ev
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.temporal_lobe.observations.typed_objects import locate_quote

DIM = 384
T0 = datetime(2023, 8, 11, 12, 0, tzinfo=timezone.utc)
NS = "<https://campy.dev/ns#"


# --- pure rule -----------------------------------------------------------------------------

def _parse(text, *, only=None):
    """(doc, occurrences): the entities spaCy finds in `text` (restricted to the texts in `only`), each admitted
    under its own text as the id."""
    doc, raw = extract_entities(text)
    admitted = []
    for e in raw:
        if e["label"] in ADMITTED_LABELS and (only is None or e["text"] in only) and e["text"] not in {t for t, _ in admitted}:
            admitted.append((e["text"], e["text"]))
    return doc, ev.entity_occurrences(text, admitted, ev.turn_spans(raw, admitted))


def _span(text, quote):
    i = text.index(quote)
    return i, i + len(quote)


def _tiers(text, quote, **kw):
    doc, occ = _parse(text, only=kw.pop("only", None))
    return ev.entities_in_evidence(doc, occ, _span(text, quote), **kw)


def test_locate_quote_is_reused_exact_folded_and_missing():
    text = 'He said “The Great Gatsby” is great.'
    assert locate_quote(text, "is great") == (text.index("is great"), len(text) - 1)
    assert locate_quote(text, '"The Great Gatsby"') == (8, 8 + len('"The Great Gatsby"'))
    assert locate_quote(text, "nothing like it") is None


def test_tier1_inside_the_quote_only():
    text = "I flew to Paris in May. My cousin lives in Boston."
    assert _tiers(text, "I flew to Paris in May") == {"Paris": 1}


def test_tier2_same_clause_outside_the_quote():
    text = "I bought it a year ago in Paris."
    assert _tiers(text, "I bought it a year ago") == {"Paris": 2}


def test_tier2_does_not_cross_a_coordinated_clause():
    text = "I flew to Paris and then I drove to Boston."
    assert _tiers(text, "I flew to Paris") == {"Paris": 1}


def test_tier2_does_not_cross_a_sentence():
    text = "Last year I took a solo trip. I took this pic in Spain."
    assert _tiers(text, "Last year I took a solo trip") == {}


def test_two_observations_two_entities_each_gets_its_own():
    text = "We explored the coast near Seattle. I flew to Paris."
    doc, occ = _parse(text)
    quotes = [("a", _span(text, "I flew to Paris")), ("b", _span(text, "We explored"))]
    got = sorted(ev.plan_turn(doc, occ, quotes))
    assert got == [("a", "Paris"), ("b", "Seattle")]      # Seattle: held by no quote, so tier 2 serves b


def test_an_entity_a_quote_holds_is_not_tier2_linked_to_another_observation():
    text = "I bought it in Paris."
    doc, occ = _parse(text)
    quotes = [("a", _span(text, "in Paris")), ("b", _span(text, "I bought it"))]
    assert ev.plan_turn(doc, occ, quotes) == [("a", "Paris")]
    assert _tiers(text, "I bought it") == {"Paris": 2}     # alone, the fallback does link it


LIST = "The music scene there is awesome, with places like Paradise Rock, House of Blues, and Fenway Park."


def test_list_mate_of_an_entity_inside_the_quote_is_not_linked_at_tier2():
    # the quote selected one member of a list, not the list (a general construction: coordination or apposition)
    got = _tiers(LIST, "places like Paradise Rock")
    assert got == {"Paradise Rock": 1}


def test_list_members_inside_the_quote_all_link():
    got = _tiers(LIST, "places like Paradise Rock, House of Blues, and Fenway Park")
    assert got == {"Paradise Rock": 1, "House of Blues": 1, "Fenway Park": 1}


def test_list_mates_helper_follows_conj_and_appos():
    doc, _ = _parse(LIST)
    rock = next(t for t in doc if t.text == "Rock")
    park = next(t for t in doc if t.text == "Park")
    assert park.i in ev.list_mates(rock) and rock.i in ev.list_mates(park)


@pytest.mark.parametrize("text,quote", [
    ("Thanks, Caroline! I painted this after my trip.", "Thanks, Caroline!"),
    ("Wow, Mel, glad you had a blast at the concert.", "Wow, Mel, glad you had a blast at the concert"),
    ("Hey Dave! Been ages since we chatted.", "Hey Dave!"),
])
def test_a_form_of_address_links_nothing(text, quote):
    assert _tiers(text, quote) == {}


@pytest.mark.parametrize("text,quote,name", [
    ("My colleague Rob invited me to a beginner's yoga class.", "My colleague Rob invited me", "Rob"),
    ("Oscar, my guinea pig, is adorable.", "Oscar, my guinea pig, is adorable", "Oscar"),
])
def test_a_name_that_is_not_address_links(text, quote, name):
    assert _tiers(text, quote, only={name}) == {name: 1}


def test_a_speaker_links_at_tier1_only():
    text = "I went hiking with Dave in the Pacific Northwest."
    assert _tiers(text, "I went hiking", only={"Dave"}) == {"Dave": 2}
    assert _tiers(text, "I went hiking", only={"Dave"}, speaker_cids=frozenset({"Dave"})) == {}
    assert _tiers(text, "I went hiking with Dave", only={"Dave"}, speaker_cids=frozenset({"Dave"})) == {"Dave": 1}


def test_occurrences_are_exact_case_whole_words():
    text = "Yoga is great. I do yoga daily, and Yoga again. Yogas too."
    occ = ev.entity_occurrences(text, [("y", "Yoga")], {})
    assert sorted(occ["y"]) == [(0, 4), (text.index("Yoga again"), text.index("Yoga again") + 4)]


def test_the_rule_reads_no_claim_words():
    import inspect
    for fn in (ev.entities_in_evidence, ev.plan_turn, ev.entity_occurrences):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"subject_text", "object_text", "event_text", "claim", "claim_words"}


# --- flag --------------------------------------------------------------------------------------

def test_flag_default_off_keyless_env_profile_and_packaged_template():
    assert ev.evidence_entity_links_enabled(_DEFAULT_CONFIG) is False
    assert ev.evidence_entity_links_enabled({}) is False
    assert ev.evidence_entity_links_enabled({"observations": {}}) is False
    on = apply_env_overrides({"observations": {}}, {"CAMPY_EVIDENCE_ENTITY_LINKS": "1"})
    assert ev.evidence_entity_links_enabled(on) is True
    off = apply_env_overrides({"observations": {"evidence_entity_links": True}}, {"CAMPY_EVIDENCE_ENTITY_LINKS": "0"})
    assert ev.evidence_entity_links_enabled(off) is False
    assert PROFILES["principled"]["observations"]["evidence_entity_links"] is True
    path = Path(orch.__file__).parents[3] / "data/config/campy.toml"
    assert "evidence_entity_links" not in tomllib.loads(path.read_text()).get("observations", {})
    assert "# evidence_entity_links = false" in path.read_text()


def test_the_new_queries_are_registered_with_a_sparql_form():
    for name in ("entity_admission.unlinked_entities", "entity_admission.entity_links"):
        assert name in REGISTRY
        assert REGISTRY.get(name).sparql and not REGISTRY.get(name).mutating


# --- graph -------------------------------------------------------------------------------------

pytestmark_graph = pytest.mark.asyncio

TURN = ('Thanks! "The Name of the Wind" is great. It\'s a fantasy novel with a great magician and '
        "musician protagonist. The world-building and character development are really good.")
QUOTE = '"The Name of the Wind" is great'


def _cfg(admission=True, evidence=True):
    return {"loop": {"entity_admission": admission}, "retrieval": {"graph_linking": False},
            "observations": {"enabled": True, "llm_enabled": True, "evidence_entity_links": evidence}}


class _LLM:
    """A scripted extractor: the claim's words never contain the title, only the quote does."""
    def __init__(self, subject="I", obj="really good"):
        self.reply = json.dumps([{"subject": subject, "predicate": "prefers", "object": obj, "time": None,
                                  "polarity": "asserted", "quote": QUOTE, "confidence": 0.9}])

    def chat(self, messages, **kwargs):
        return self.reply


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    def fake(text, model_name=None):
        v = [0.0] * DIM
        v[hash(text.lower()) % DIM] = 1.0
        return v
    monkeypatch.setattr(embeddings_mod, "embed", fake)
    monkeypatch.setattr(orch.emb, "embed", fake)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b554.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _extract(db, gw, cfg, *, llm=None, mid="x1", text=TURN):
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None, embedding_model="m",
                 embedding_dim=DIM, role="user", byte_end=len(text), created_at=T0.isoformat())
    await gw.run("capture.set_message_source", message_id=mid, speaker="Tim", occurred_at=T0.isoformat())
    return await ex.process_turn(db, cfg, llm or _LLM(), mid, ex.ObservationWorkerStats())


def _about(db):
    rows = db._execute_and_collect(
        f"SELECT ?t WHERE {{ ?o a {NS}Observation> ; {NS}OBSERVATION_ABOUT> ?c . ?c {NS}text_raw> ?t }}")
    return sorted(str(r["t"]) for r in rows)


@pytest.mark.asyncio
async def test_flag_off_writes_no_evidence_link_and_the_title_stays_unlinked(db, gw):
    assert await _extract(db, gw, _cfg(evidence=False)) == 1
    assert "The Name of the Wind" not in _about(db)             # B544 alone: the claim words drop the name
    rows = await gw.run("entity_admission.unlinked_entities")
    assert "The Name of the Wind" in {r["text_raw"] for r in rows}


@pytest.mark.asyncio
async def test_flag_on_links_the_title_the_claim_words_dropped(db, gw):
    assert await _extract(db, gw, _cfg()) == 1
    assert "The Name of the Wind" in _about(db)
    rows = await gw.run("entity_admission.unlinked_entities")
    assert "The Name of the Wind" not in {r["text_raw"] for r in rows}


@pytest.mark.asyncio
async def test_the_models_wording_plays_no_part(tmp_path):
    seen = []
    for i, llm in enumerate((_LLM("I", "really good"), _LLM("I", "a fantasy novel"), _LLM("I", "magician"))):
        d = OxigraphClient(tmp_path / f"w{i}.db")
        g = GraphGateway(d, REGISTRY)
        await _extract(d, g, _cfg(), llm=llm)
        seen.append(tuple(t for t in _about(d) if t == "The Name of the Wind"))
    assert seen == [("The Name of the Wind",)] * 3


@pytest.mark.asyncio
async def test_flag_on_without_admission_writes_nothing_and_does_not_fail(db, gw):
    assert await _extract(db, gw, _cfg(admission=False)) == 1
    assert _about(db) == []


@pytest.mark.asyncio
async def test_backfill_dry_run_writes_nothing_apply_equals_the_plan_and_is_idempotent(db, gw):
    await _extract(db, gw, _cfg(evidence=False))
    assert _about(db) == []
    dry = await ev.backfill_evidence_links(db, _cfg(), dry_run=True)
    assert dry.dry_run and dry.new_links == 1 and dry.gained_entities == 1 and dry.quote_located == 1
    assert _about(db) == []                                      # a dry run writes nothing
    applied = await ev.backfill_evidence_links(db, _cfg(), dry_run=False)
    assert applied.new_links == 1 and applied.unlinked_after == applied.unlinked_before - 1
    assert _about(db) == ["The Name of the Wind"]
    again = await ev.backfill_evidence_links(db, _cfg(), dry_run=False)
    assert again.new_links == 0 and _about(db) == ["The Name of the Wind"]


@pytest.mark.asyncio
async def test_backfill_on_a_store_without_admitted_entities_plans_nothing(db, gw):
    await _extract(db, gw, _cfg(admission=False, evidence=False))
    stats = await ev.backfill_evidence_links(db, _cfg(), dry_run=False)
    assert stats.planned == 0 and stats.new_links == 0 and _about(db) == []
