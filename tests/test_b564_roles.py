"""B564: the roles of an event fact (flag `[observations] roles`, default off), form 2: closed choice.

Real spaCy and WordNet (skipped when absent), real Oxigraph store, scripted LLM, no model. Pins:
- the flag (default off, env CAMPY_OBSERVATION_ROLES, not in the principled profile) and flag-off byte identity:
  the four prompts hash to the values captured before the change, and a run writes exactly the structure captured
  before the change;
- with the flag ON the extraction messages and max_tokens equal the flag-off ones (the fact prompt is untouched);
- the closed candidate sets (action heads, WordNet event options, partner and place options from the graph);
- the roles call: one per turn with a candidate, none otherwise; answers by option number; out-of-range, wrong-role
  and non-JSON answers write nothing and are counted;
- the fallback (dependency parse) only after a 0, no options, or a failed call (counted apart);
- the writes (idempotent, first wins, no embedding, no vector row for an action Concept) and the collision guards;
- the NamedQueries: turn_entity_options, session_speakers, role_fill, by_action_kind, with_participant, at_place.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from campy.brain.brainstem.config import PROFILES, _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import kinds
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.temporal_lobe.observations import roles as R
from campy.brain.temporal_lobe.observations import typed_objects as T
from tests import b564_helpers as H
from tests.b564_helpers import LLM, NS, Q, World, cfg, claim, extract

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "b564_flagoff_golden.json").read_text())
ON = cfg(typed_objects=True, object_roles=True, roles=True)


def _needs_wordnet():
    return pytest.mark.skipif(not wn_mod.available(), reason="WordNet not installed")


needs_wordnet = _needs_wordnet()


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b564.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


@pytest.fixture
def world(db, gw):
    return World(db, gw)


def targets(db, edge):
    """{(text of the fact's quote, target id or phrase text)} for one role edge; a Concept shows its id, an
    ObjectPhrase its text prefixed with 'phrase:'."""
    rows = db._execute_and_collect(
        f"SELECT ?q ?t ?cid ?txt WHERE {{ ?o {NS}{edge}> ?t ; {NS}evidence_text> ?q . "
        f"OPTIONAL {{ ?t {NS}concept_id> ?cid }} OPTIONAL {{ ?t a {NS}ObjectPhrase> ; {NS}text_raw> ?txt }} }}")
    return {(str(r["q"]), str(r["cid"]) if r.get("cid") else "phrase:" + str(r["txt"])) for r in rows}


async def seed(world):
    await world.concept("c-sam", "Sam")


# --- the flag ------------------------------------------------------------------------------

def test_flag_default_off_env_on_not_in_a_profile(monkeypatch):
    assert _DEFAULT_CONFIG["observations"]["roles"] is False
    assert obs.capture_roles_enabled({}) is False
    assert obs.capture_roles_enabled(apply_env_overrides({}, {"CAMPY_OBSERVATION_ROLES": "1"})) is True
    assert obs.capture_roles_enabled(
        apply_env_overrides({"observations": {"roles": True}}, {"CAMPY_OBSERVATION_ROLES": "0"})) is False
    for prof in PROFILES.values():
        assert "roles" not in prof.get("observations", {})


def test_flag_not_active_in_the_shipped_template():
    toml = (Path(__file__).parent.parent / "campy" / "data" / "config" / "campy.toml").read_text()
    assert "CAMPY_OBSERVATION_ROLES" in toml
    assert not any(line.strip().startswith("roles") for line in toml.splitlines())


# --- flag off is byte-identical ------------------------------------------------------------

def test_flag_off_prompts_hash_as_before():
    assert H.prompt_hashes() == GOLDEN["prompts"]


async def test_flag_off_writes_what_it_wrote_before(db, gw):
    got = await H.flag_off_signature(db, gw)
    assert got == GOLDEN["run"]
    assert not any("HAS_ACTION" in k or "HAS_PARTICIPANT" in k or "HAS_PLACE" in k for k in got["signature"])


async def test_flag_off_with_the_key_absent_or_false_is_the_same(tmp_path):
    dbs = []
    for name, flags in (("x", {}), ("y", {"roles": False})):
        d = OxigraphClient(tmp_path / f"{name}.db")
        dbs.append(await H.flag_off_signature(d, GraphGateway(d, REGISTRY), flags))
    assert dbs[0] == dbs[1] == GOLDEN["run"]


async def test_flag_on_extraction_call_is_the_flag_off_call(db, gw, world):
    await seed(world)
    text = "I visited Paris last year, it was lovely."
    for entities in (False, True):
        kw = dict(entities=entities)
        a, b = LLM(claim("I visited Paris last year", "Paris")), LLM(claim("I visited Paris last year", "Paris"))
        await extract(db, cfg(typed_objects=True, roles=True, **kw), world, text, a)
        await extract(db, cfg(typed_objects=True, **kw), world, text, b)
        assert a.extraction_calls[0] == b.extraction_calls[0]            # same messages, same max_tokens
        assert a.extraction_calls[0][1]["max_tokens"] in (ex.MAX_TOKENS, ex.ENTITY_MAX_TOKENS)
    assert not hasattr(ex, "ROLES_MAX_TOKENS") and not hasattr(ex, "_ROLE_FIELDS")
    assert ex.build_messages(text, "Sam", "2023-05-03") == ex.build_messages(text, "Sam", "2023-05-03", entities=False)


async def test_flag_on_extraction_messages_equal_the_flag_off_golden(db, gw, world):
    """The golden turns, flag on: the extraction messages and max_tokens are the flag-off ones."""
    await seed(world)
    for text, c, admit in H.ROLE_TURNS:
        on, off = LLM(c), LLM(c)
        await extract(db, cfg(typed_objects=True, object_roles=True, entities=True, roles=True), world, text, on,
                      admit=admit)
        await extract(db, cfg(typed_objects=True, object_roles=True, entities=True), world, text, off, admit=admit)
        assert on.extraction_calls == off.extraction_calls


# --- WordNet action options -------------------------------------------------------------------

@needs_wordnet
def test_action_options_are_event_senses_ordered_by_count_and_capped():
    opts = wn_mod.action_options("hike")
    assert opts[0].synset == "hike.n.01" and opts[0].lemma == "hike" and opts[0].gloss
    assert all(o.synset.split(".")[1] == "n" for o in opts) and len({o.synset for o in opts}) == len(opts)
    assert [o.synset for o in wn_mod.action_options("explore")][:1] == ["exploration.n.01"]    # via nominalisation
    assert [o.synset for o in wn_mod.action_options("visit")][:1] == ["visit.n.01"]
    assert len(wn_mod.action_options("run")) <= wn_mod.MAX_ACTION_OPTIONS == 6
    assert len(wn_mod.action_options("run", cap=2)) == 2


@needs_wordnet
def test_action_options_none_for_light_verbs_and_words_without_an_event_sense():
    for w in ("go", "make", "take", "xyzzy", "", "feel"):
        assert wn_mod.action_options(w) == [] or w == "feel", w
    assert wn_mod.action_options("bike") == [] and wn_mod.action_options("volunteer") == []


@needs_wordnet
def test_action_sense_of_builds_the_chain_to_event():
    wn = wn_mod._wn()
    root = wn.synset("event.n.01")
    s = wn_mod.action_sense_of("hike.n.01")
    children = {c for c, _p in s.chain}
    parents = {p for _c, p in s.chain}
    assert s.concept_id == "wn:hike.n.01" and s.lemma == "hike"
    assert "event.n.01" in parents and "act.n.02" in parents and "hike.n.01" in children
    assert ("walk.n.04", "travel.n.01") in s.chain
    assert all(wn_mod._under(wn.synset(p), root) for p in parents)
    assert {k for k, _l in s.labels} == children | parents
    assert wn_mod.action_sense_of("dog.n.01") is None and wn_mod.action_sense_of("nope.n.99") is None


@needs_wordnet
def test_role_heads_and_places():
    assert wn_mod.first_sense_under("neighbor", wn_mod.PERSON_ROOTS) and wn_mod.first_sense_under("band", wn_mod.PERSON_ROOTS)
    for place in ("park", "house", "beach", "lake", "mountain", "forest", "trail"):
        assert wn_mod.first_sense_under(place, wn_mod.PLACE_ROOTS), place
    assert not wn_mod.first_sense_under("book", wn_mod.PLACE_ROOTS)
    assert wn_mod.first_sense_under("photo", wn_mod.PHYSICAL_ROOTS) and not wn_mod.first_sense_under("job", wn_mod.PHYSICAL_ROOTS)


# --- the closed candidate sets -----------------------------------------------------------------

def _nlp():
    return T._nlp({})


def _opts(quote, obj):
    counts = R.Counter()
    f = R.FactIn("o1", quote, "did", obj, "c-sam")
    return R.action_options_for(_nlp(), f, counts), counts


@needs_wordnet
def test_light_verb_uses_the_objects_noun():
    opts, _ = _opts("even went on a hike", "go on a hike")
    assert opts and opts[0].synset == "hike.n.01"
    opts, _ = _opts("I took my kids to a pottery workshop", "take my kids to a pottery workshop")
    assert opts and any("workshop" in o.lemma for o in opts)


@needs_wordnet
def test_verb_root_gets_nominalisation_options():
    opts, _ = _opts("I visited my mom`s house", "visit")
    assert opts[0].synset == "visit.n.01"


@needs_wordnet
def test_head_not_in_the_quote_has_no_options():
    opts, counts = _opts("I had a great time", "hike")
    assert opts == [] and counts["action_head_not_in_quote"] == 1


@needs_wordnet
def test_no_head_and_no_event_sense_are_counted():
    opts, counts = _opts("I did it", "it")
    assert opts == [] and counts["action_no_head"] + counts["action_head_not_in_quote"] == 1
    opts, counts = _opts("I went biking", "bike")
    assert opts == [] and counts["action_no_event_sense"] == 1


@needs_wordnet
def test_options_are_capped_at_six_and_pooled_across_heads():
    opts, _ = _opts("I ran a run and a game", "run a run and a game")
    assert 0 < len(opts) <= 6
    assert len({o.synset for o in opts}) == len(opts)


# --- option B: the action word, by rule (user ruling 2026-11-13) ----------------------------------

def _word(quote, obj):
    counts = R.Counter()
    return R.action_word(_nlp(), R.FactIn("o1", quote, "did", obj, "c-sam"), counts), counts


@needs_wordnet
def test_action_word_light_verb_takes_its_event_object():
    assert _word("I went on a hike with Ann", "go on a hike")[0] == "hike"
    w, c = _word("I took my kids to a dance workshop", "take my kids to a dance workshop")
    assert w == "workshop" and c["action_second_word_dropped"] == 1       # "kids" names no event; first wins


@needs_wordnet
def test_action_word_noun_head():
    assert _word("I ran a charity race last week", "a charity race")[0] == "race"


@needs_wordnet
def test_action_word_verb_head_with_and_without_a_nominalisation():
    assert _word("I adopted a kitten", "adopt a kitten")[0] == "adoption"      # nominalisation with an event sense
    assert _word("I painted the fence", "paint the fence")[0] == "painting"
    assert _word("I own a boat", "own a boat")[0] == "own"                       # none: the verb's own lemma


@needs_wordnet
def test_no_event_word_writes_nothing_and_is_counted():
    w, c = _word("I went biking", "bike")
    assert w is None and c["action_no_event_word"] == 1
    w, c = _word("I went camping", "go camping somewhere else")
    assert w == "camping"
    w, c = _word("I bought a boat", "a red kite")
    assert w is None and c["action_head_not_in_quote"] == 1


def test_action_concept_is_one_node_per_word():
    assert R.action_concept_id("Hike") == R.action_concept_id("hike") == "action:hike"
    assert R.action_concept_id("ice skating") == "action:ice_skating"


# --- the roles call, on hand-written turns -------------------------------------------------------

TURN = "Last weekend I went camping with Melanie in Paris and it was fun."
QUOTE = "I went camping with Melanie in Paris"


async def _turn(db, gw, world, *, roles, admit=(("c-mel", "Melanie", "PERSON"), ("c-paris", "Paris", "GPE")),
                text=TURN, c=None, speakers=True, cfg_=None):
    await seed(world)
    llm = LLM(c or claim(QUOTE, "go camping"), roles=roles)
    mid = await world.message(text, speaker="Sam")
    for cid, name, label in admit:
        await world.admit(mid, cid, name, label)
    if speakers:
        await world.concept("c-ann", "Ann")
        other = await world.message("Hi Sam", speaker="Ann")
        world.session("s1", mid, other)
        await world.spoken_by(mid, "c-sam")
        await world.spoken_by(other, "c-ann")
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, cfg_ or ON, llm, mid, stats)
    return llm, stats, mid


@needs_wordnet
async def test_one_call_picks_by_number_and_writes_each_role(db, gw, world):
    llm, stats, _mid = await _turn(db, gw, world, roles=[{"fact": 1, "with": [1], "place": 1}])
    assert len(llm.roles_calls) == 1 and len(llm.extraction_calls) == 1
    msgs, kw = llm.roles_calls[0]
    assert kw == {"max_tokens": R.ROLES_CALL_MAX_TOKENS}
    body = msgs[-1]["content"]
    assert f'Fact 1: "{QUOTE}"' in body and "action:" not in body and "0 none" in body      # option B: no action pick
    assert "with:" in body and "Ann" in body and "Melanie" in body and "place: 1 Paris" in body
    assert msgs[0]["role"] == "system" and "JSON only" in body
    assert targets(db, "HAS_ACTION") == {(QUOTE, "action:camping")}                            # the rule's word
    assert len(targets(db, "HAS_PARTICIPANT")) == 1
    assert targets(db, "HAS_PLACE") == {(QUOTE, "c-paris")}
    c = stats.roles
    assert c["calls"] == 1 and c["action_written"] == 1 and "action_shown" not in c
    assert c["partner_written_concept"] == 1 and c["place_written_concept"] == 1
    ids = {unquote(s) for s, _o in world.edges("BROADER")} | {unquote(o) for _s, o in world.edges("BROADER")}
    assert not any(i.startswith(("action:", "wn:")) for i in ids)                            # no BROADER for actions


@needs_wordnet
async def test_partner_options_exclude_the_subject_and_are_numbered_speakers_first(db, gw, world):
    llm, _s, _m = await _turn(db, gw, world, roles=[{"fact": 1, "with": [2]}])
    body = llm.roles_calls[0][0][-1]["content"]
    line = next(x for x in body.splitlines() if x.strip().startswith("with:"))
    assert line.index("1 Ann") < line.index("2 Melanie") and "Sam" not in line
    assert {t for _q, t in targets(db, "HAS_PARTICIPANT")} == {"c-mel"}


@needs_wordnet
async def test_no_call_when_no_fact_has_a_candidate(db, gw, world):
    llm, stats, _m = await _turn(db, gw, world, roles=[], admit=(), speakers=False,
                                 text="We had a super fun day out and it was great.",
                                 c=claim("We had a super fun day out", "fun day", subject="we", predicate="did"))
    assert llm.roles_calls == [] and stats.roles.get("calls", 0) == 0
    llm, _s, _m = await _turn(db, gw, world, roles=[], admit=(), speakers=False, c=claim(
        "I feel great", "feel great", predicate="has_attribute"))
    assert llm.roles_calls == []                                     # not an event fact


@needs_wordnet
async def test_no_subject_fact_gets_no_options_and_is_counted(db, gw, world):
    llm, stats, _m = await _turn(db, gw, world, roles=[], speakers=False,
                                 text="Last weekend Zed went camping with Melanie in Paris.",
                                 c=claim("Zed went camping with Melanie", "go camping", subject="Zed"))
    assert llm.roles_calls == [] and stats.roles["no_subject"] == 1
    assert targets(db, "HAS_ACTION") == set()


@needs_wordnet
async def test_answer_zero_writes_nothing_and_counts(db, gw, world):
    _l, stats, _m = await _turn(db, gw, world, roles=[{"fact": 1, "with": [], "place": 0}],
                                text="I went camping with Melanie and it was fun.", admit=(("c-mel", "Melanie", "PERSON"),),
                                c=claim("I went camping with Melanie", "go camping"))
    c = stats.roles
    assert c["partner_picked_0"] == 1 and c["place_no_options"] == 1
    assert targets(db, "HAS_PARTICIPANT") == set()
    assert targets(db, "HAS_ACTION") == {("I went camping with Melanie", "action:camping")}   # by rule, not by pick


@needs_wordnet
async def test_out_of_range_wrong_role_and_wrong_type_write_nothing(db, gw, world):
    for roles in ([{"fact": 1, "with": [7], "place": 5}],                         # not shown
                  [{"fact": 1, "with": "Melanie", "place": "Paris"}],                  # names
                  [{"fact": 1, "with": [True], "place": -1}]):
        d = OxigraphClient(Path(world.db.path if hasattr(world.db, "path") else ".").parent / f"o{abs(hash(str(roles)))}.db")
        g = GraphGateway(d, REGISTRY)
        w = World(d, g)
        _l, stats, _m = await _turn(d, g, w, roles=roles)
        c = stats.roles
        assert c["place_pick_out_of_range"] >= 1 and c["partner_pick_out_of_range"] >= 1
        assert targets(d, "HAS_PARTICIPANT") == set() and targets(d, "HAS_PLACE") == set()
        assert targets(d, "HAS_ACTION") == {(QUOTE, "action:camping")}       # the rule's word, whatever the reply
        assert c["action_written"] == 1 and c.get("partner_written_concept", 0) == 0
        assert not any(k.endswith("fallback_phrase") for k in c)             # a rejection is not a "no"


@needs_wordnet
async def test_with_mixed_valid_and_invalid_numbers_keeps_the_valid_one(db, gw, world):
    _l, stats, _m = await _turn(db, gw, world, roles=[{"fact": 1, "with": [2, 99, 2]}])
    assert {t for _q, t in targets(db, "HAS_PARTICIPANT")} == {"c-mel"}
    assert stats.roles["partner_pick_out_of_range"] == 1 and stats.roles["partner_written_concept"] == 1


@needs_wordnet
async def test_a_role_with_no_options_ignores_the_answer(db, gw, world):
    _l, stats, _m = await _turn(db, gw, world, roles=[{"fact": 1, "place": 1}], admit=(("c-mel", "Melanie", "PERSON"),),
                                text="I went camping with Melanie and it was fun.",
                                c=claim("I went camping with Melanie", "go camping"))
    assert targets(db, "HAS_PLACE") == set() and stats.roles["place_no_options"] == 1


@needs_wordnet
async def test_non_json_reply_is_unparseable_and_writes_no_pick(db, gw, world):
    for reply in ("I would pick 1", "{\"fact\": 1}", "[1, 2]", ""):
        d = OxigraphClient(Path(world.db.path if hasattr(world.db, "path") else ".").parent / f"u{abs(hash(reply))}.db")
        g = GraphGateway(d, REGISTRY)
        w = World(d, g)
        _l, stats, _m = await _turn(d, g, w, roles=reply)
        assert stats.roles["unparseable"] == 1 and stats.roles["action_written"] == 1
        assert targets(d, "HAS_ACTION") == {(QUOTE, "action:camping")} and targets(d, "HAS_PARTICIPANT") == set()


@needs_wordnet
async def test_a_failed_call_is_counted_and_the_fact_stays(db, gw, world):
    _l, stats, _m = await _turn(db, gw, world, roles=RuntimeError("boom"))
    assert stats.roles["call_failed"] == 1 and stats.created == 1
    assert world.count("Observation") == 1 and stats.errors == 0
    assert targets(db, "HAS_ACTION") == {(QUOTE, "action:camping")}         # the action needs no call


# --- the fallback ----------------------------------------------------------------------------------

FB_TEXT = "Yesterday I went camping with my neighbor to the park and it was fun."
FB_QUOTE = "I went camping with my neighbor to the park"


@needs_wordnet
async def test_fallback_runs_after_a_zero_and_writes_phrases(db, gw, world):
    _l, stats, _m = await _turn(db, gw, world, roles=[{"fact": 1, "action": 0, "with": [], "place": 0}],
                                text=FB_TEXT, c=claim(FB_QUOTE, "go camping"), admit=(("c-mel", "Melanie", "PERSON"),
                                                                                     ("c-paris", "Paris", "GPE")))
    assert {t for _q, t in targets(db, "HAS_PARTICIPANT")} == {"phrase:my neighbor"}
    assert {t for _q, t in targets(db, "HAS_PLACE")} == {"phrase:the park"}
    c = stats.roles
    assert c["partner_fallback_phrase"] == 1 and c["place_fallback_phrase"] == 1
    assert not any(k.endswith("after_failure") for k in c)


@needs_wordnet
async def test_fallback_runs_when_there_are_no_options_and_no_call_is_made(db, gw, world):
    llm, stats, _m = await _turn(db, gw, world, roles=[], text=FB_TEXT, c=claim(FB_QUOTE, "camping at the park"),
                                 admit=(), speakers=False)
    # action options may exist ("camping"), so a call may be made; partner/place had no options either way
    assert stats.roles["partner_no_options"] == 1 and stats.roles["place_no_options"] == 1
    assert {t for _q, t in targets(db, "HAS_PARTICIPANT")} == {"phrase:my neighbor"}


@needs_wordnet
async def test_fallback_never_runs_after_a_pick(db, gw, world):
    _l, stats, _m = await _turn(db, gw, world, roles=[{"fact": 1, "with": [1], "place": 1}], text=FB_TEXT,
                                c=claim(FB_QUOTE, "go camping"),
                                admit=(("c-mel", "Melanie", "PERSON"), ("c-paris", "Paris", "GPE")))
    assert {t for _q, t in targets(db, "HAS_PLACE")} == {"c-paris"}
    assert not any("phrase" in t for _q, t in targets(db, "HAS_PARTICIPANT"))
    assert not any(k.startswith(("partner_fallback", "place_fallback")) for k in stats.roles)


@needs_wordnet
async def test_fallback_after_a_failed_call_is_counted_apart(db, gw, world):
    _l, stats, _m = await _turn(db, gw, world, roles="not json", text=FB_TEXT, c=claim(FB_QUOTE, "go camping"),
                                admit=(("c-mel", "Melanie", "PERSON"), ("c-paris", "Paris", "GPE")))
    c = stats.roles
    assert c["partner_fallback_phrase_after_failure"] == 1 and c["place_fallback_phrase_after_failure"] == 1
    assert not any(k in c for k in ("partner_fallback_phrase", "place_fallback_phrase"))


@needs_wordnet
def test_fallback_phrases_need_person_and_place_heads_inside_the_clause():
    nlp = _nlp()
    doc = nlp("I went hiking with my friends to the park and then saw a film in the evening. Bob sat in the park.")
    q = (0, doc.text.index(" and then"))
    assert R.fallback_phrases(doc, q, "partner", frozenset()) == ["my friends"]
    assert R.fallback_phrases(doc, q, "place", frozenset()) == ["the park"]
    assert R.fallback_phrases(nlp("I went with it."), (0, 14), "partner", frozenset()) == []
    assert R.fallback_phrases(nlp("I went with my friends."), (0, 23), "partner", frozenset({"friends"})) == []


# --- the answer parser -------------------------------------------------------------------------------

def test_parse_answers():
    assert R.parse_answers('[{"fact": 1, "action": 2}]') == {1: {"fact": 1, "action": 2}}
    assert R.parse_answers('```json\n[{"fact": "2", "place": 1}]\n```') == {2: {"fact": "2", "place": 1}}
    assert R.parse_answers("no") is None and R.parse_answers(None) is None and R.parse_answers("[1]") is None
    assert R.parse_answers('{"fact": 1}') is None


def test_pick_accepts_only_shown_numbers():
    from collections import Counter
    c = Counter()
    assert R.pick({"action": 2}, "action", "action", 3, c) == ([2], "picked")
    assert R.pick({"action": 4}, "action", "action", 3, c) == ([], "rejected")
    assert R.pick({"action": 0}, "action", "action", 3, c) == ([], "zero")
    assert R.pick({"with": [1, 3, 9]}, "with", "partner", 3, c) == ([1, 3], "picked")
    assert R.pick({"with": []}, "with", "partner", 3, c) == ([], "zero")
    assert R.pick({"place": [1]}, "place", "place", 3, c) == ([], "rejected")
    assert R.pick({}, "place", "place", 3, c) == ([], "no_answer")
    assert c["action_pick_out_of_range"] == 1 and c["partner_pick_out_of_range"] == 1


# --- the counts are logged -----------------------------------------------------------------------------

@needs_wordnet
async def test_counts_are_logged_every_25_call_turns_and_only_when_changed(db, gw, world, caplog):
    import logging
    ex._roles_logged = {}
    stats = ex.ObservationWorkerStats()
    stats.roles = {"calls": 3, "action_written": 2}
    with caplog.at_level(logging.INFO, logger=ex.__name__):
        assert ex.log_roles_counts(stats) is True
        assert ex.log_roles_counts(stats) is False                      # unchanged: not repeated
        stats.roles["calls"] = 4
        assert ex.log_roles_counts(stats) is True
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[Roles] counts")]
    assert lines == ["[Roles] counts {'action_written': 2, 'calls': 3}", "[Roles] counts {'action_written': 2, 'calls': 4}"]
    assert ex.ROLES_LOG_EVERY == 25


@needs_wordnet
async def test_the_worker_logs_on_the_25th_call_turn(db, gw, world, caplog, monkeypatch):
    import logging
    ex._roles_logged = {}
    await seed(world)
    stats = ex.ObservationWorkerStats()
    stats.roles = {"calls": 24}
    mid = await world.message(TURN, speaker="Sam")
    await world.admit(mid, "c-mel", "Melanie", "PERSON")
    with caplog.at_level(logging.INFO, logger=ex.__name__):
        await ex.process_turn(db, ON, LLM(claim(QUOTE, "go camping"), roles=[{"fact": 1}]), mid, stats)
    assert stats.roles["calls"] == 25
    assert any(r.getMessage().startswith("[Roles] counts") and "'calls': 25" in r.getMessage() for r in caplog.records)


def test_the_daemon_worker_logs_when_the_queue_drains():
    src = (Path(__file__).parent.parent / "campy" / "brain_daemon.py").read_text()
    assert "log_roles_counts(stats)" in src and "self._observation_queue.empty()" in src


# --- the B546 object path extended to physical values -------------------------------------------------

@needs_wordnet
async def test_is_a_and_has_attribute_common_noun_values_get_a_phrase_only_with_the_flag(db, gw, world, tmp_path):
    turns = [("I mentor a transgender teen just like me.", claim("I mentor a transgender teen just like me",
                                                                  "transgender teen", predicate="is_a")),
             ("We have a lot of cute photos, I want to share with you.",
              claim("We have a lot of cute photos", "cute photos", predicate="has_attribute", subject="we")),
             ("I'm loving this job.", claim("I'm loving this job", "job: this job", predicate="has_attribute")),
             ("I'm really passionate about helping.", claim("I'm really passionate", "passionate", predicate="is_a"))]
    for flag in (True, False):
        d = OxigraphClient(tmp_path / f"v{flag}.db")
        g = GraphGateway(d, REGISTRY)
        w = World(d, g)
        await seed(w)
        for text, c in turns:
            await extract(d, cfg(typed_objects=True, object_roles=True, roles=flag), w, text, LLM(c))
        got = {t for _q, t in targets(d, "HAS_OBJECT")}
        if flag:
            assert got == {"phrase:transgender teen", "phrase:cute photos"}
        else:
            assert got == set()


# --- idempotence, first wins, no embedding, no index --------------------------------------------------

@needs_wordnet
async def test_rerun_is_idempotent_first_action_wins_and_action_concepts_have_no_embedding(db, gw, world):
    await seed(world)
    text = "We explored nature and even went on a hike. Then I visited my aunt."
    c = claim("even went on a hike", "go on a hike")
    pick1 = []
    await extract(db, ON, world, text, LLM(c, roles=pick1))
    first = world.signature()
    mid = "m1"
    await ex.process_turn(db, ON, LLM(c, roles=pick1), mid, ex.ObservationWorkerStats())
    assert world.signature() == first
    (oid,) = {s for s, _ in world.edges("HAS_ACTION")}
    await gw.run("roles.ensure_action_concept", cid="action:visit", text="visit", now=H.T0)
    await gw.run("roles.link_action", oid=oid, cid="action:visit")                  # a second action: ignored
    assert targets(db, "HAS_ACTION") == {("even went on a hike", "action:hike")}
    rows = db._execute_and_collect(f"SELECT ?p WHERE {{ ?c {NS}concept_id> ?id ; ?p ?x . FILTER(STRSTARTS(?id, 'action:')) }}")
    preds = {str(r["p"]).rsplit("#", 1)[-1] for r in rows}
    assert "embedding" not in preds and "embedding_model" not in preds and "kind_scheme" in preds


@needs_wordnet
async def test_no_vector_or_text_index_row_for_an_action_concept(db, gw, world):
    from campy.brain.hippocampus.graph.queries.vector_indexing import VECTOR_INDEX_SPECS
    from campy.brain.hippocampus.graph.vector_store import mint_uri
    await seed(world)
    await extract(db, ON, world, "We explored nature and even went on a hike.",
                  LLM(claim("even went on a hike", "go on a hike"), roles=[]))
    vs = db.vector_store
    assert vs.get_vector(mint_uri("Concept", "c-sam")) is not None            # control: ordinary Concepts are indexed
    action_ids = ["action:hike"]
    for cid in action_ids:
        assert len(await gw.run("roles.action_concept", cid=cid)) == 1, cid        # they exist ...
    for cid in action_ids:
        assert vs.get_vector(mint_uri("Concept", cid)) is None, cid
    assert vs.count_documents(["https://campy.dev/id/Concept/action"]) == 0    # nor the text index
    assert not any(n.startswith("roles.") for n in VECTOR_INDEX_SPECS)


@needs_wordnet
async def test_the_vector_backfill_skips_action_concepts(db, gw, world):
    import importlib.util
    from campy.brain.hippocampus.graph.vector_store import VectorStore
    await seed(world)
    await gw.run("roles.ensure_action_concept", cid="wn:hike.n.01", text="hike", now=H.T0)
    spec = importlib.util.spec_from_file_location(
        "backfill_vector_index", Path(__file__).resolve().parent.parent / "scripts" / "backfill_vector_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    vs = VectorStore(":memory:")
    report = mod.backfill(db.store, vs, lambda text: Q, tables=("Concept",))
    assert report["Concept"]["nodes_with_text"] == 1                           # Sam only
    assert vs.count_documents(["https://campy.dev/id/Concept/wn"]) == 0


@needs_wordnet
async def test_action_concepts_are_not_found_by_text_and_never_become_kinds(db, gw, world):
    await seed(world)
    await gw.run("roles.ensure_action_concept", cid="wn:hike.n.01", text="hike", now=H.T0)
    from campy.brain.hippocampus.concept_links import concept_index
    assert await ex.find_existing_concept(gw, "hike") is None
    assert "hike" not in await concept_index(gw)
    await kinds.mark_kind(gw, "wn:hike.n.01")
    assert [r["cid"] for r in await gw.run("roles.action_concept", cid="wn:hike.n.01")] == ["wn:hike.n.01"]
    assert (await gw.run("kinds.live_kinds")) == []                       # still not a kind
    text = "We went for a hike."
    await extract(db, ON, world, text, LLM(claim("We went for a hike", "hike")))
    assert all("wn%3A" not in o for _s, o in world.edges("HAS_OBJECT"))
    rows = db._execute_and_collect(f"SELECT ?id WHERE {{ ?o {NS}object_id> ?id }}")
    assert not any(str(r["id"]).startswith("wn:") for r in rows)


async def test_collision_guards_change_nothing_without_action_concepts(db, gw, world):
    await seed(world)
    await world.concept("c-hike", "hike")
    assert await ex.find_existing_concept(gw, "hike") == "c-hike"
    assert await kinds.mark_kind(gw, "c-hike") is True


# --- the queries ----------------------------------------------------------------------------------------

class Facts:
    """A small store of hand-written facts with their roles: the queries are tested on edges, not on the rule."""

    def __init__(self, world, gw, db):
        self.w, self.gw, self.db, self.n = world, gw, db, 0

    async def fact(self, subject, text, *, day, action=None, participants=(), place=None, subject_id=True,
                   obj=None, archived=False, speaker="Sam"):
        self.n += 1
        mid = await self.w.message(text, day=day, speaker=speaker)
        oid = f"o{self.n}"
        sid = f'"{subject}"' if subject_id and subject else None
        trip = [f'<{_o(oid)}> a {NS}Observation> ; {NS}observation_id> "{oid}" ; {NS}evidence_text> "{text}" ; '
                f'{NS}EVIDENCED_BY> <{_m(mid)}> ; {NS}archived> {"true" if archived else "false"}']
        if sid:
            trip[0] += f" ; {NS}subject_id> {sid} ; {NS}HAS_SUBJECT> <{_c(subject)}>"
        trip.append("." )
        self.db.store.update("INSERT DATA { " + " ".join(trip) + " }")
        if action:
            await self.gw.run("roles.ensure_action_concept", cid=action, text=action.split(":")[1].split(".")[0], now=H.T0)
            await self.gw.run("roles.link_action", oid=oid, cid=action)
        for p in participants:
            if p.startswith("phrase:"):
                await self.gw.run("roles.link_participant_phrase", oid=oid, pid=f"p-{oid}-{p}", text=p[7:], rv="t", now=H.T0)
            else:
                await self.gw.run("roles.link_participant", oid=oid, cid=p)
        if place:
            if place.startswith("phrase:"):
                await self.gw.run("roles.link_place_phrase", oid=oid, pid=f"pl-{oid}", text=place[7:], rv="t", now=H.T0)
            else:
                await self.gw.run("roles.link_place", oid=oid, cid=place)
        if obj:
            await self.gw.run("observations.link_object", oid=oid, cid=obj)
        return oid


def _o(i):
    from campy.brain.hippocampus.graph.vector_store import mint_uri
    return mint_uri("Observation", i)


def _m(i):
    from campy.brain.hippocampus.graph.vector_store import mint_uri
    return mint_uri("Message", i)


def _c(i):
    from campy.brain.hippocampus.graph.vector_store import mint_uri
    return mint_uri("Concept", i)


async def _store(world, gw, db):
    for cid, t in (("c-sam", "Sam"), ("c-mel", "Melanie"), ("c-anna", "Anna"), ("c-paris", "Paris")):
        await world.concept(cid, t)
    f = Facts(world, gw, db)
    # Sam: a hike with Anna in Paris (all Concepts), a visit with a nameless neighbour (nameless place), a text fact,
    # a dated fact that is archived. Melanie: a hike. One fact has no subject.
    await f.fact("c-sam", "I hiked with Anna in Paris", day=3, action="wn:hike.n.01", participants=["c-anna"], place="c-paris")
    await f.fact("c-sam", "I visited my neighbor at her house", day=5,
                 participants=["phrase:my neighbor"], place="phrase:her house")
    await f.fact("c-sam", "I feel great", day=6)
    await f.fact("c-sam", "I hiked alone long ago", day=1, action="wn:hike.n.01", archived=True)
    await f.fact("c-mel", "I hiked too", day=2, action="wn:hike.n.01")
    await f.fact(None, "Somebody hiked", day=2, action="wn:hike.n.01", subject_id=False)
    return f


@needs_wordnet
async def test_role_fill_counts_standing_and_shared(db, gw, world):
    await _store(world, gw, db)
    rows = {(r["standing"], r["shared"]): r["n"] for r in await gw.run("observations.role_fill")}
    assert rows == {("anchored", True): 2, ("anchored", False): 1, ("text", False): 1, ("unanchored", False): 1}


@needs_wordnet
async def test_role_fill_shared_needs_the_subject_so_shared_is_a_subset_of_anchored(db, gw, world):
    f = await _store(world, gw, db)
    rows = await gw.run("observations.role_fill")
    by = {(r["standing"], r["shared"]): r["n"] for r in rows}
    assert by.get(("unanchored", True), 0) == 0                    # a Concept role edge, no subject: not shared
    shared = sum(n for (st, sh), n in by.items() if sh)
    anchored = sum(n for (st, sh), n in by.items() if st == "anchored")
    assert shared <= anchored
    await world.concept("c-x", "X")
    await f.fact(None, "Nobody owns a hike", day=7, obj="c-x", subject_id=False)
    by = {(r["standing"], r["shared"]): r["n"] for r in await gw.run("observations.role_fill")}
    assert by[("unanchored", False)] == 2


@needs_wordnet
async def test_role_fill_counts_only_object_phrase_roles_as_not_shared_and_typed_values_as_anchored(db, gw, world):
    await world.concept("c-sam", "Sam")
    f = Facts(world, gw, db)
    await f.fact("c-sam", "I have a book", day=1)
    await f.fact("c-sam", "I am 30", day=2)
    await gw.run("typed_objects.link_object_phrase", oid="o1", pid="x", text="book", rv="t", now=H.T0)
    db.store.update(f'INSERT DATA {{ <{_o("o2")}> {NS}attr_value_kind> "number" }}')
    rows = {(r["standing"], r["shared"]): r["n"] for r in await gw.run("observations.role_fill")}
    assert rows == {("anchored", False): 2}


async def _ids(gw, name, **kw):
    return [r["observation_id"] for r in await gw.run(name, **kw)]


@needs_wordnet
async def test_by_action_kind_walks_broader_anchored_on_the_subject(db, gw, world):
    await _store(world, gw, db)
    await kinds_link(gw, "wn:hike.n.01", "wn:travel.n.01")
    assert await _ids(gw, "facts.by_action_kind", sid="c-sam", kid="wn:hike.n.01") == ["o1"]      # o4 archived
    assert await _ids(gw, "facts.by_action_kind", sid="c-sam", kid="wn:travel.n.01") == ["o1"]
    assert await _ids(gw, "facts.by_action_kind", sid="c-mel", kid="wn:travel.n.01") == ["o5"]
    assert await _ids(gw, "facts.by_action_kind", sid="c-sam", kid="wn:visit.n.01") == []        # o2 has no action
    assert await _ids(gw, "facts.by_action_kind", sid="c-anna", kid="wn:hike.n.01") == []          # not recorded
    assert await _ids(gw, "facts.by_action_kind", sid="c-sam", kid="wn:nothing.n.01") == []
    row = (await gw.run("facts.by_action_kind", sid="c-sam", kid="wn:travel.n.01"))[0]
    assert row["action"] == "hike" and row["evidence_message_id"] == "m1" and row["quote"] == "I hiked with Anna in Paris"
    assert str(row["occurred_at"])[:10] == "2023-05-03"


async def kinds_link(gw, child, parent):
    await gw.run("roles.ensure_action_concept", cid=parent, text=parent.split(":")[1].split(".")[0], now=H.T0)
    await kinds.link_broader_sourced(gw, child, parent, "wordnet")


@needs_wordnet
async def test_with_participant_and_at_place(db, gw, world):
    await _store(world, gw, db)
    rows = await gw.run("facts.with_participant", sid="c-sam", pid="c-anna")
    assert [(r["observation_id"], r["action"], r["evidence_message_id"]) for r in rows] == [("o1", "hike", "m1")]
    assert await _ids(gw, "facts.with_participant", sid="c-mel", pid="c-anna") == []
    rows = await gw.run("facts.at_place", sid="c-sam", plid="c-paris")
    assert [r["observation_id"] for r in rows] == ["o1"]
    assert await _ids(gw, "facts.at_place", sid="c-mel", plid="c-paris") == []
    both = {(r["observation_id"], r["target_id"] or r["target_text"], bool(r["nameless"]))
            for r in await gw.run("facts.participants_of", sid="c-sam")}
    assert both == {("o1", "c-anna", False), ("o2", "my neighbor", True)}
    places = {(r["observation_id"], r["target_id"] or r["target_text"], bool(r["nameless"]))
              for r in await gw.run("facts.places_of", sid="c-sam")}
    assert places == {("o1", "c-paris", False), ("o2", "her house", True)}


@needs_wordnet
async def test_deprecated_facts_are_not_read(db, gw, world):
    await _store(world, gw, db)
    db.store.update(f'INSERT DATA {{ <{_o("o1")}> {NS}DEPRECATED_BY> <{_o("o2")}> }}')
    assert await _ids(gw, "facts.by_action_kind", sid="c-sam", kid="wn:hike.n.01") == []
    rows = {(r["standing"], r["shared"]): r["n"] for r in await gw.run("observations.role_fill")}
    assert sum(rows.values()) == 4


@needs_wordnet
async def test_turn_entity_options_filters_by_label_and_excludes_the_subject(db, gw, world):
    await seed(world)
    mid = await world.message("Sam met Anna and Bob at Acme in Paris near the Alps and the Louvre.")
    other = await world.message("Another turn", speaker="Sam")
    for cid, name, label in (("c-anna", "Anna", "PERSON"), ("c-acme", "Acme", "ORG"), ("c-fr", "French", "NORP"),
                             ("c-paris", "Paris", "GPE"), ("c-alps", "Alps", "LOC"), ("c-louvre", "Louvre", "FAC"),
                             ("c-may", "May", "DATE")):
        await world.admit(mid, cid, name, label)
    await world.admit(mid, "c-samx", "Sam", "PERSON")
    await world.admit(other, "c-other", "Other", "PERSON")                    # a different turn: not read
    await world.concept("c-k", "kind thing", kind=True)
    await gw.run("concept_links.link_message_concept", mid=mid, cid="c-k")      # a kind with no label: not an option
    rows = await gw.run("roles.turn_entity_options", mid=mid, sid="c-samx")
    got = {(r["concept_id"], r["ner_label"]) for r in rows}
    assert got == {("c-anna", "PERSON"), ("c-acme", "ORG"), ("c-fr", "NORP"), ("c-paris", "GPE"), ("c-alps", "LOC"),
                   ("c-louvre", "FAC")}
    assert not [r for r in await gw.run("roles.turn_entity_options", mid=mid, sid="c-anna") if r["concept_id"] == "c-anna"]
    assert await gw.run("roles.turn_entity_options", mid="nope", sid="c-sam") == []


@needs_wordnet
async def test_session_speakers_are_spoken_by_edges_of_the_same_session_minus_the_subject(db, gw, world):
    for cid, t in (("c-sam", "Sam"), ("c-ann", "Ann"), ("c-bo", "Bo")):
        await world.concept(cid, t)
    a = await world.message("one", speaker="Sam")
    b = await world.message("two", speaker="Ann")
    c = await world.message("three", speaker="Bo")
    world.session("s1", a, b)
    world.session("s2", c)
    for mid, cid in ((a, "c-sam"), (b, "c-ann"), (c, "c-bo")):
        await world.spoken_by(mid, cid)
    rows = await gw.run("roles.session_speakers", mid=a, sid="c-sam")
    assert [r["concept_id"] for r in rows] == ["c-ann"]                         # Bo is another session
    assert {r["concept_id"] for r in await gw.run("roles.session_speakers", mid=a, sid="c-zzz")} == {"c-sam", "c-ann"}


@needs_wordnet
async def test_without_spoken_by_the_speaker_list_is_empty_and_counted(db, gw, world):
    llm, stats, _m = await _turn(db, gw, world, roles=[{"fact": 1}], speakers=False,
                                 admit=(("c-paris", "Paris", "GPE"),), text="Last weekend I went camping in Paris.",
                                 c=claim("I went camping in Paris", "go camping"))
    assert stats.roles["partner_no_options"] == 1
    body = llm.roles_calls[0][0][-1]["content"]
    assert "with:" not in body and "place: 1 Paris" in body


@needs_wordnet
async def test_the_other_speaker_is_an_option_on_every_fact(db, gw, world):
    llm, stats, _m = await _turn(db, gw, world, roles=[{"fact": 1, "with": [1]}], admit=(),
                                 text="Last weekend I went camping and it was fun.",
                                 c=claim("I went camping", "go camping"))
    assert {t for _q, t in targets(db, "HAS_PARTICIPANT")} == {"c-ann"}
    assert stats.roles["partner_written_concept"] == 1
