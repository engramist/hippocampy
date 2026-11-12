"""B564: the roles of an event fact (flag `[observations] roles`, default off).

Real spaCy and WordNet (skipped when absent), real Oxigraph store, scripted LLM, no model. Pins:
- the flag (default off, env CAMPY_OBSERVATION_ROLES, not in the principled profile) and flag-off byte identity:
  the four prompts hash to the values captured before the change, and a run with role keys in the replies writes
  exactly the structure captured before the change;
- WordNet action senses (most frequent event noun sense, light verbs, chain to event.n.01);
- the rule on hand-written turns taken from the step-1 sample: spans confirmed in the turn and the clause of the
  fact's quote, held by another fact, pronouns, lists, speakers, admitted entities, nameless ObjectPhrases;
- the B546 object path extended to physical values;
- the writes (idempotent, first wins, no embedding, no vector row for an action Concept) and the collision guards;
- the NamedQueries: role_fill, by_action_kind, with_participant, at_place (and the listing forms).
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
    kw = dict(entities=True, cardinality=True)
    assert ex.build_messages("t t t", "Sam", "2023-05-03", roles=False, **kw) == \
        ex.build_messages("t t t", "Sam", "2023-05-03", **kw)


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


def test_flag_on_prompt_adds_the_three_fields_last():
    off = ex.build_messages("I visited Paris.", "Sam", "2023-05-03", entities=True)[1]["content"]
    on = ex.build_messages("I visited Paris.", "Sam", "2023-05-03", entities=True, roles=True)[1]["content"]
    for key in ('- "action":', '- "with":', '- "place":'):
        assert key in on and key not in off
    assert on.index('- "place":') < on.index('- "confidence":') and on.index('- "confidence":') > on.index('- "action":')
    assert on.replace(ex._ROLE_FIELDS, '- "confidence": a number from 0 to 1\n') == off


async def test_flag_on_asks_for_more_tokens_flag_off_does_not(db, gw, world):
    await seed(world)
    llm = LLM(claim("I visited Paris last year", "Paris"))
    await extract(db, ON, world, "I visited Paris last year, it was lovely.", llm)
    assert llm.calls[0][1]["max_tokens"] == ex.ROLES_MAX_TOKENS
    llm = LLM(claim("I visited Paris last year", "Paris"))
    await extract(db, cfg(typed_objects=True), world, "I visited Paris last year, it was lovely.", llm)
    assert llm.calls[0][1]["max_tokens"] == ex.MAX_TOKENS


# --- WordNet action senses -------------------------------------------------------------------

@needs_wordnet
def test_action_sense_is_the_most_frequent_event_noun_sense():
    for words, synset in ((["hike"], "hike.n.01"), (["visit"], "visit.n.01"), (["explore"], "exploration.n.01"),
                          (["collaborate"], "collaboration.n.01"), (["cook"], "cooking.n.01"),
                          (["tell"], "telling.n.02"), (["swim"], "swimming.n.01")):
        s = wn_mod.action_sense(words)
        assert s is not None and s.synset == synset and s.concept_id == "wn:" + synset, words
    assert wn_mod.action_sense(["hike"]).lemma == "hike"


@needs_wordnet
def test_action_without_a_sense_or_a_light_verb_has_none():
    for words in (["bike"], ["volunteer"], ["chat"], ["blog"], ["go"], ["make"], ["xyzzy"], []):
        assert wn_mod.action_sense(words) is None, words
    assert wn_mod.action_sense(["pottery_class", "class"]).synset == "course.n.01"      # whole phrase, then head


@needs_wordnet
def test_chain_runs_to_event_and_every_parent_is_an_event():
    wn = wn_mod._wn()
    root = wn.synset("event.n.01")
    s = wn_mod.action_sense(["hike"])
    children = {c for c, _p in s.chain}
    parents = {p for _c, p in s.chain}
    assert "event.n.01" in parents and "act.n.02" in parents and "hike.n.01" in children
    assert ("walk.n.04", "travel.n.01") in s.chain
    assert all(wn_mod._under(wn.synset(p), root) for p in parents)
    assert {k for k, _l in s.labels} == children | parents
    v = wn_mod.action_sense(["visit"])                                                    # two paths, both reach event
    assert ("group_action.n.01", "event.n.01") in v.chain or ("group_action.n.01", "act.n.02") in v.chain


@needs_wordnet
def test_role_heads_and_places():
    assert wn_mod.first_sense_under("neighbor", wn_mod.PERSON_ROOTS) and wn_mod.first_sense_under("band", wn_mod.PERSON_ROOTS)
    for place in ("park", "house", "beach", "lake", "mountain", "forest", "trail"):
        assert wn_mod.first_sense_under(place, wn_mod.PLACE_ROOTS), place
    assert not wn_mod.first_sense_under("book", wn_mod.PLACE_ROOTS)
    assert wn_mod.first_sense_under("photo", wn_mod.PHYSICAL_ROOTS) and not wn_mod.first_sense_under("job", wn_mod.PHYSICAL_ROOTS)


# --- the proposal ------------------------------------------------------------------------------

def test_propose_cleans_the_three_fields():
    p = R.propose({"action": " hike ", "with": ["Anna", "anna", "my friends", None, {"x": 1}], "place": "null"})
    assert (p.action, p.with_, p.place) == ("hike", ["Anna", "my friends"], None)
    assert R.propose({"with": "Anna"}).with_ == ["Anna"]
    assert not R.propose({"action": None, "with": [], "place": "None"})
    assert R.propose({"action": ["hike"]}).action is None
    assert len(R.propose({"with": [f"p{i}" for i in range(9)]}).with_) == R.MAX_WITH
    assert R.propose({"place": "x" * 80}).place is None


def test_find_spans_folds_backticks_and_case():
    assert R.find_spans("I visited my mom`s house", "my mom's house") == [(10, 24)]
    assert R.find_spans("Visited the Park", "the park") == [(8, 16)]
    assert R.find_spans("a parking lot", "park") == []


# --- the rule and the writes, on turns of the step-1 sample ----------------------------------------

@needs_wordnet
async def test_told_anna_the_story_action_and_admitted_participant(db, gw, world):
    await seed(world)
    text = ("Hey Jolene! Hope you're having a good one. Last Friday I told Anna the story of my life and they were "
            "super kind about it. It was so nice to have a meaningful connection.")
    c = claim("I told Anna the story of my life", "tell", time="Last Friday", action="told", **{"with": ["Anna"]})
    _mid, stats = await extract(db, ON, world, text, LLM(c), admit=[("c-anna", "Anna", "PERSON")], speaker="Deborah")
    q = "I told Anna the story of my life"
    assert targets(db, "HAS_ACTION") == {(q, "wn:telling.n.02")}
    assert targets(db, "HAS_PARTICIPANT") == {(q, "c-anna")}
    assert targets(db, "HAS_PLACE") == set()
    assert stats.roles["action_written"] == 1 and stats.roles["participant_concept_written"] == 1


@needs_wordnet
async def test_visited_my_moms_house_action_and_nameless_place(db, gw, world):
    await seed(world)
    text = "Yep, last month I visited my mom`s house which holds a special place in my heart."
    c = claim("last month I visited my mom`s house", "visit", time="last month", action="visited",
              place="my mom's house")
    await extract(db, ON, world, text, LLM(c), speaker="Deborah")
    q = "last month I visited my mom`s house"
    assert targets(db, "HAS_ACTION") == {(q, "wn:visit.n.01")}
    assert targets(db, "HAS_PLACE") == {(q, "phrase:my mom`s house")}
    assert world.count("ObjectPhrase") == 1
    chain = world.edges("BROADER")
    assert any(o == "wn%3Aevent.n.01" for _s, o in chain) or any(o == "wn%3Aact.n.02" for _s, o in chain)


@needs_wordnet
async def test_planning_sentence_three_facts_one_clause(db, gw, world):
    """One clause holds three facts: a span held by another fact's quote does not attach to this one."""
    await seed(world)
    text = ("I'm planning to explore the city, try out different local cuisines, and perhaps collaborate with "
            "musicians in the area.")
    c1 = claim("I'm planning to explore the city", "explore the city", predicate="plans", action="explore",
               place="the city")
    c2 = claim("try out different local cuisines", "different local cuisines", predicate="plans",
               action="try out", **{"with": ["musicians"]})
    c3 = claim("collaborate with musicians in the area", "collaborate with musicians", predicate="plans",
               action="collaborate", **{"with": ["musicians"]}, place="the area")
    _mid, stats = await extract(db, ON, world, text, LLM(c1, c2, c3), speaker="Calvin")
    got = targets(db, "HAS_ACTION")
    assert {("I'm planning to explore the city", "wn:exploration.n.01"),
            ("collaborate with musicians in the area", "wn:collaboration.n.01")} <= got
    assert not any("audition" in t for _q, t in got)                  # "try out" is a phrasal verb, not "try-out"
    assert targets(db, "HAS_PARTICIPANT") == {("collaborate with musicians in the area", "phrase:musicians")}
    assert targets(db, "HAS_PLACE") == {("I'm planning to explore the city", "phrase:the city"),
                                        ("collaborate with musicians in the area", "phrase:the area")}
    assert stats.roles["rejected:held_by_other_fact"] == 1


@needs_wordnet
async def test_even_went_on_a_hike_action_chain_and_pronoun_dropped(db, gw, world):
    await seed(world)
    text = "We explored nature, roasted marshmallows around the campfire and even went on a hike. The view was amazing!"
    c = claim("even went on a hike", "go on a hike", action="hike", **{"with": ["We"]})
    _mid, stats = await extract(db, ON, world, text, LLM(c), speaker="Melanie")
    assert targets(db, "HAS_ACTION") == {("even went on a hike", "wn:hike.n.01")}
    assert targets(db, "HAS_PARTICIPANT") == set()
    assert stats.roles["rejected:with_pronoun_or_subject"] == 1
    ids = {unquote(s) for s, _o in world.edges("BROADER")} | {unquote(o) for _s, o in world.edges("BROADER")}
    assert {"wn:hike.n.01", "wn:walk.n.04", "wn:travel.n.01", "wn:act.n.02", "wn:event.n.01"} <= ids


@needs_wordnet
async def test_biking_has_no_sense_but_the_neighbour_is_a_nameless_participant(db, gw, world):
    await seed(world)
    text = "Had a blast biking nearby with my neighbor last week."
    c = claim("Had a blast biking nearby with my neighbor", "bike", action="biking", **{"with": ["my neighbor"]})
    _mid, stats = await extract(db, ON, world, text, LLM(c), speaker="Sam")
    assert targets(db, "HAS_ACTION") == set()
    assert targets(db, "HAS_PARTICIPANT") == {("Had a blast biking nearby with my neighbor", "phrase:my neighbor")}
    assert stats.roles["rejected:action_no_sense"] == 1


@needs_wordnet
async def test_made_a_dish_light_verb_writes_no_action(db, gw, world):
    await seed(world)
    text = "The cooking class has been great. Last night I made this yummy grilled dish, so good!"
    c = claim("Last night I made this yummy grilled dish", "made", action="made")
    _mid, stats = await extract(db, ON, world, text, LLM(c), speaker="Sam")
    assert targets(db, "HAS_ACTION") == set() and stats.roles["rejected:action_light_verb"] == 1
    assert world.count("Concept") == 1                                    # no action Concept either


@needs_wordnet
async def test_an_action_is_for_did_and_plans_only(db, gw, world):
    await seed(world)
    text = "Taking a walk around is a great way to destress, too."
    c = claim("Taking a walk around is a great way to destress", "taking a walk around", predicate="prefers",
              action="walk")
    _mid, stats = await extract(db, ON, world, text, LLM(c), speaker="Dave")
    assert targets(db, "HAS_ACTION") == set() and stats.roles["rejected:predicate_not_event"] == 1


@needs_wordnet
async def test_exploring_some_parks_place(db, gw, world):
    await seed(world)
    text = "I love exploring some parks near my house on weekends."
    c = claim("I love exploring some parks near my house", "exploring some parks", action="exploring",
              place="some parks")
    await extract(db, ON, world, text, LLM(c), speaker="Sam")
    assert targets(db, "HAS_ACTION") == {("I love exploring some parks near my house", "wn:exploration.n.01")}
    assert targets(db, "HAS_PLACE") == {("I love exploring some parks near my house", "phrase:some parks")}


@needs_wordnet
async def test_admitted_place_and_an_unknown_person_is_not_a_participant(db, gw, world):
    await seed(world)
    await world.concept("c-mel", "Melanie")
    text = "I went hiking with Melanie in Paris last year."
    c = claim("I went hiking with Melanie in Paris last year", "hiking", action="hiking", **{"with": ["Melanie"]},
              place="Paris")
    await extract(db, ON, world, text, LLM(c), admit=[("c-paris", "Paris", "GPE")], speaker="Sam")
    q = "I went hiking with Melanie in Paris last year"
    assert targets(db, "HAS_PLACE") == {(q, "c-paris")}
    assert targets(db, "HAS_PARTICIPANT") == set()      # Melanie is neither admitted here nor a speaker of the conversation


@needs_wordnet
async def test_speaker_of_the_conversation_is_a_participant(db, gw, world):
    await seed(world)
    await world.concept("c-mel", "Melanie")
    await world.message("Hello Sam, how was the week?", speaker="Melanie")       # Melanie speaks in the conversation
    text = "Last weekend I went camping with Melanie and it was fun."
    c = claim("I went camping with Melanie", "camping", action="camping", **{"with": ["Melanie"]})
    await extract(db, ON, world, text, LLM(c), speaker="Sam")
    assert targets(db, "HAS_PARTICIPANT") == {("I went camping with Melanie", "c-mel")}


@needs_wordnet
async def test_rejections_not_in_turn_and_not_in_clause(db, gw, world):
    await seed(world)
    text = "I visited Paris while my sister stayed home and Bob was away."
    c = claim("I visited Paris", "Paris", action="visited", **{"with": ["Bob", "my sister", "Zed"]}, place="home")
    _mid, stats = await extract(db, ON, world, text, LLM(c), speaker="Sam")
    assert stats.roles["rejected:not_in_turn"] == 1                 # Zed
    assert stats.roles["rejected:not_in_clause"] >= 2               # Bob, my sister: other clauses
    assert targets(db, "HAS_PARTICIPANT") == set() and targets(db, "HAS_PLACE") == set()
    assert targets(db, "HAS_ACTION") == {("I visited Paris", "wn:visit.n.01")}


@needs_wordnet
async def test_a_with_list_writes_each_good_member_and_drops_the_bad_one(db, gw, world):
    await seed(world)
    text = "Yesterday I had lunch with Anna, my friends and the weather."
    c = claim("I had lunch with Anna, my friends and the weather", "lunch", action="lunch",
              **{"with": ["Anna", "my friends", "the weather"]})
    _mid, stats = await extract(db, ON, world, text, LLM(c), admit=[("c-anna", "Anna", "PERSON")], speaker="Sam")
    got = {t for _q, t in targets(db, "HAS_PARTICIPANT")}
    assert got == {"c-anna", "phrase:my friends"}
    assert stats.roles["rejected:with_not_person"] == 1


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
    c = claim("even went on a hike", "hike", action="hike")
    await extract(db, ON, world, text, LLM(c))
    first = world.signature()
    mid = "m1"
    await ex.process_turn(db, ON, LLM(c), mid, ex.ObservationWorkerStats())
    assert world.signature() == first
    (oid,) = {s for s, _ in world.edges("HAS_ACTION")}
    await gw.run("roles.ensure_action_concept", cid="wn:visit.n.01", text="visit", now=H.T0)
    await gw.run("roles.link_action", oid=oid, cid="wn:visit.n.01")                 # a second action: ignored
    assert targets(db, "HAS_ACTION") == {("even went on a hike", "wn:hike.n.01")}
    rows = db._execute_and_collect(f"SELECT ?p WHERE {{ ?c {NS}concept_id> ?id ; ?p ?x . FILTER(STRSTARTS(?id, 'wn:')) }}")
    preds = {str(r["p"]).rsplit("#", 1)[-1] for r in rows}
    assert "embedding" not in preds and "embedding_model" not in preds and "kind_scheme" in preds


@needs_wordnet
async def test_no_vector_or_text_index_row_for_an_action_concept(db, gw, world):
    from campy.brain.hippocampus.graph.queries.vector_indexing import VECTOR_INDEX_SPECS
    from campy.brain.hippocampus.graph.vector_store import mint_uri
    await seed(world)
    await extract(db, ON, world, "We explored nature and even went on a hike.",
                  LLM(claim("even went on a hike", "hike", action="hike")))
    vs = db.vector_store
    assert vs.get_vector(mint_uri("Concept", "c-sam")) is not None            # control: ordinary Concepts are indexed
    action_ids = ["wn:hike.n.01", "wn:walk.n.04", "wn:act.n.02", "wn:event.n.01"]
    for cid in action_ids:
        assert len(await gw.run("roles.action_concept", cid=cid)) == 1, cid        # they exist ...
    for cid in action_ids:
        assert vs.get_vector(mint_uri("Concept", cid)) is None, cid
    assert vs.count_documents(["https://campy.dev/id/Concept/wn"]) == 0        # nor the text index
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
    assert rows == {("anchored", True): 2, ("anchored", False): 1, ("text", False): 1, ("unanchored", True): 1}


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
