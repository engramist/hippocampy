"""B546: the object of a fact is a typed entity (flag `[observations] typed_objects`, default off).

Real spaCy and WordNet (skipped when absent), real Oxigraph store, fake LLM, no model. Pins:
- the flag: default off, env CAMPY_TYPED_OBJECTS, a member of the principled profile, absent from the shipped template;
- the rule, step by step: a stated kind, WordNet places, the conversation's speakers, the head noun matched to the
  closed kind set, else a candidate only; each of the two guards (the copula metaphor, the place cue);
- entity object vs nameless object (ObjectPhrase); B544's admitted Concepts present vs absent;
- the evidence span is searched in the turn (B552), never trusted from stored offsets;
- the write path (extractor) and the idempotent backfill; flag off writes nothing and renders the same prompt;
- the NamedQueries: the exact-role query (KX) and the loose one (K+) on a fixture store, and the candidate read;
- an ObjectPhrase is not counted by B524's count of what a subject has.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, PROFILES, apply_env_overrides, load_config
from campy.brain.hippocampus import kinds
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.vector_store import mint_uri
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.temporal_lobe.observations import typed_objects as T

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 1, tzinfo=timezone.utc)
NS = "<https://campy.dev/ns#"
BASE = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600, "retrieval": False,
                         "entities": False},
        "retrieval": {"conversation_token_budget": 0}}
ON = {**BASE, "observations": {**BASE["observations"], "typed_objects": True, "object_roles": True}}


def _nlp():
    try:
        from campy.brain.temporal_lobe.loop.step1_ner import get_nlp
        return get_nlp()
    except Exception:                                  # pragma: no cover
        pytest.skip("spaCy model not installed")


@pytest.fixture(scope="module")
def nlp():
    from campy.brain.temporal_lobe.lexicon import wordnet as wn
    if not wn.available():
        pytest.skip("WordNet not installed")
    return _nlp()


# The typing rule answers "no" to every kind question without WordNet (an optional extra, B523),
# so the end-to-end typing tests need it; CI without the corpus skips them.
def _wordnet_available():
    from campy.brain.temporal_lobe.lexicon import wordnet as wn
    return wn.available()


needs_wordnet = pytest.mark.skipif(not _wordnet_available(), reason="WordNet not installed")


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b546.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


# --- the rule, pure --------------------------------------------------------------------

def rule(nlp, text, quote, obj, pred="did", mentions=(), speakers=(), kinds_=None, subject=("i",)):
    doc = nlp(text)
    i = text.index(quote)
    ctx = T.RuleContext(mentions=list(mentions), speakers=frozenset(speakers), kind_by_key=dict(kinds_ or {}),
                        subject_names=frozenset(subject))
    return T.typed_objects(pred, obj, i, i + len(quote), doc, ctx, nlp)


def one(items):
    assert len(items) == 1, items
    return items[0]


def test_step1_stated_by_hearst_apposition_called_and_copula(nlp):
    it = one(rule(nlp, "I love sports brands like Nike.", "I love sports brands like Nike.", "sports brands like Nike",
                  "prefers", [("c1", "Nike", "ORG")])[0])
    assert (it.obj, it.kind, it.rule, it.cue, it.role) == ("entity", "brand", "stated", "hearst", "object")
    it = one(rule(nlp, "I read a novel called Dune.", "I read a novel called Dune.", "novel called Dune", "did",
                  [("c2", "Dune", "WORK_OF_ART")])[0])
    assert (it.kind, it.rule, it.cue) == ("novel", "stated", "called")
    it = one(rule(nlp, "I met my friend, Josh.", "I met my friend, Josh.", "friend: Josh", "relates_to",
                  [("c3", "Josh", "PERSON")])[0])
    assert (it.kind, it.rule) == ("friend", "stated")
    it = one(rule(nlp, "Harry Potter is my favorite book.", "Harry Potter is my favorite book.", "Harry Potter",
                  "prefers", [("c4", "Harry Potter", "WORK_OF_ART")])[0])
    assert (it.kind, it.rule, it.cue) == ("book", "stated", "copula")


def test_step1_it_is_a_names_the_kind_of_the_thing_in_the_previous_sentence(nlp):
    text = "I finished The Name of the Wind. It's a fantasy novel."
    it = one(rule(nlp, text, "It's a fantasy novel.", "fantasy novel", "did",
                  [("c5", "The Name of the Wind", "WORK_OF_ART")])[0])
    assert (it.surface, it.kind, it.rule, it.cue) == ("The Name of the Wind", "novel", "stated", "copula_ref")


def test_stated_kind_prefers_the_longest_kind_the_store_has(nlp):
    kbk = {"model kit": "k-mk", "kit": "k-kit"}
    it = one(rule(nlp, "I built plastic model kits like Revell.", "I built plastic model kits like Revell.",
                  "plastic model kits like Revell", "did", [("c6", "Revell", "ORG")], kinds_=kbk)[0])
    assert (it.kind, it.kid) == ("model kit", "k-mk")


def test_step2_wordnet_places(nlp):
    it = one(rule(nlp, "I visited Toronto last year.", "I visited Toronto last year.", "Toronto", "did",
                  [("c7", "Toronto", "GPE")])[0])
    assert (it.kind, it.rule) == ("city", "wordnet")
    it = one(rule(nlp, "We went to Mexico.", "We went to Mexico.", "Mexico", "did", [("c8", "Mexico", "GPE")])[0])
    assert (it.kind, it.rule) == ("country", "wordnet")


def test_place_guard_needs_a_place_label_and_a_place_first_sense(nlp):
    # tagged ORG: no place cue even though WordNet's first sense of "Toronto" is a city
    it = one(rule(nlp, "I visited Toronto last year.", "I visited Toronto last year.", "Toronto", "did",
                  [("c7", "Toronto", "ORG")])[0])
    assert it.kind is None
    # tagged GPE but WordNet's first sense is not a place ("jordan" is a river first): untyped
    it = one(rule(nlp, "I loved Jordan a lot.", "I loved Jordan a lot.", "Jordan", "did", [("c9", "Jordan", "GPE")])[0])
    assert it.kind is None
    assert T.wordnet_place_kind("Jordan") is None and T.wordnet_place_kind("Toronto") == "city"


def test_place_guard_refuses_a_name_written_after_an_indefinite_article(nlp):
    # "Labrador" is a place to WordNet and the tagger says GPE; "a Labrador" is a dog
    items, _ = rule(nlp, "One of them, Daisy, is a Labrador.", "One of them, Daisy, is a Labrador.", "Labrador",
                    "is_a", [("c10", "Labrador", "GPE")])
    assert all(i.kind != "region" for i in items)
    items, _ = rule(nlp, "We flew to Labrador.", "We flew to Labrador.", "Labrador", "did", [("c10", "Labrador", "GPE")])
    assert one(items).kind == "region"


def test_step2b_a_speaker_is_a_person_and_a_ner_label_alone_is_not(nlp):
    it = one(rule(nlp, "I talked with Melanie today.", "I talked with Melanie today.", "talked with Melanie", "did",
                  [("c11", "Melanie", "PERSON")], speakers=["melanie"])[0])
    assert (it.kind, it.rule) == ("person", "speaker")
    it = one(rule(nlp, "I talked with Melanie today.", "I talked with Melanie today.", "talked with Melanie", "did",
                  [("c11", "Melanie", "PERSON")])[0])
    assert it.kind is None and it.rule is None                        # B549: the tagger label is evidence only


def test_step3_head_noun_in_the_closed_kind_set_and_the_modifier_never_is(nlp):
    kbk = {"book": "k-book", "game": "k-game", "tournament": "k-t", "plan": "k-plan"}
    it = one(rule(nlp, "I read a good book last week.", "I read a good book last week.", "read a good book", "did",
                  kinds_=kbk)[0])
    assert (it.obj, it.kind, it.rule, it.kid, it.surface) == ("phrase", "book", "head", "k-book", "good book")
    it = one(rule(nlp, "I won a video game tournament.", "I won a video game tournament.", "a video game tournament",
                  "did", kinds_=kbk)[0])
    assert it.kind == "tournament" and it.kid == "k-t"                # not "game"
    it = one(rule(nlp, "I bought a toy car.", "I bought a toy car.", "bought a toy car", "did",
                  kinds_={"toy": "k-toy", "car": "k-car"})[0])
    assert it.kind == "car"                                           # not "toy"


def test_step4_a_head_the_store_has_no_kind_for_is_a_candidate_only(nlp):
    it = one(rule(nlp, "I read a good novel last week.", "I read a good novel last week.", "read a good novel", "did",
                  kinds_={"book": "k-book"})[0])
    assert (it.obj, it.kind, it.rule, it.candidate) == ("phrase", None, None, "novel")


def test_guard_copula_metaphor_is_not_a_kind(nlp):
    # "Nature is my haven", "It is my sanctuary": a possessive predicate nominal is a metaphor
    items, rej = rule(nlp, "Nature's always been my haven.", "Nature's always been my haven.", "nature", "prefers",
                      [("c12", "Nature", "PERSON")])
    assert all(i.kind != "haven" for i in items) and not any(i.obj == "entity" for i in items)
    assert "copula_subject_common_word" in rej
    # "It's my sanctuary" after "I love music.": the referent was written in lower case, so it is no name (B549)
    items, rej = rule(nlp, "I love music. It's my sanctuary that reminds me why I love music.",
                      "It's my sanctuary that reminds me why I love music.", "sanctuary", "has_attribute",
                      [("c14", "music", "ORG")])
    assert all(i.kind != "sanctuary" for i in items)
    # the same words about a capitalised thing do state a kind: the guard is about the referent, not the noun
    it = one(rule(nlp, "I finished Dune. It's my favorite novel.", "It's my favorite novel.", "favorite novel", "prefers",
                  [("c15", "Dune", "WORK_OF_ART")])[0])
    assert (it.kind, it.cue) == ("novel", "copula_ref")


def test_an_entity_object_wins_over_a_nameless_one_and_a_value_has_no_phrase(nlp):
    items, _ = rule(nlp, "I love sports brands like Nike.", "I love sports brands like Nike.", "sports brands like Nike",
                    "prefers", [("c1", "Nike", "ORG")], kinds_={"brand": "k-brand"})
    assert [i.obj for i in items] == ["entity"]
    items, _ = rule(nlp, "My job is nurse at a hospital.", "My job is nurse at a hospital.", "job: nurse", "has_attribute",
                    kinds_={"hospital": "k-h", "nurse": "k-n"})
    assert items == []


def test_without_admitted_entities_a_title_is_not_a_nameless_object(nlp):
    items, rej = rule(nlp, "I read Dune.", "I read Dune.", "Dune", "did", [], kinds_={"book": "k-book"})
    assert items == [] and "capitalised_head_not_admitted" in rej


def test_a_mention_written_in_lower_case_is_not_a_name(nlp):
    items, rej = rule(nlp, "I love yoga.", "I love yoga.", "yoga", "prefers", [("c15", "yoga", "PERSON")])
    assert not any(i.obj == "entity" for i in items) and "mention_written_lowercase" in rej


# --- the evidence span (B552) ------------------------------------------------------------

def test_locate_quote_uses_offsets_only_when_they_select_the_quote():
    text = "Hi. I love Nike shoes. Bye."
    q = "I love Nike shoes."
    assert T.locate_quote(text, q, 4, 22) == (4, 22)
    assert T.locate_quote(text, q, 0, 10) == (4, 22)            # wrong offsets: searched
    assert T.locate_quote(text, q, None, None) == (4, 22)
    assert T.locate_quote(text, q.lower(), 4, 22) == (4, 22)    # case-insensitive last resort
    assert T.locate_quote(text, "I hate Nike shoes.", 4, 22) is None
    curly = "She said “Dune” was great. It’s a novel."
    assert T.locate_quote(curly, 'She said "Dune" was great.') == (0, 26)    # quotation marks folded one for one


# --- the graph ----------------------------------------------------------------------------

class World:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def message(self, text, *, day=3, speaker="Sam"):
        self.n += 1
        mid = f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        return mid

    async def concept(self, cid, text, *, kind=False):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=Q, gist="Entity", stype="Thing",
                          now=T0)
        if kind:
            await kinds.mark_kind(self.gw, cid)

    async def admit(self, mid, cid, text, label):
        """What B544 does for a named entity of a turn: a Concept with its tagger label, mentioned by the turn."""
        await self.concept(cid, text)
        self.db.store.update(
            f'INSERT DATA {{ <{mint_uri("Concept", cid)}> {NS}ner_label> "{label}" }}')
        await self.gw.run("concept_links.link_message_concept", mid=mid, cid=cid)

    def edges(self, edge):
        rows = self.db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
        return {(str(r["s"]).rsplit("/", 1)[-1], str(r["o"]).rsplit("/", 1)[-1]) for r in rows}

    def triples(self):
        rows = self.db._execute_and_collect("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
        return sorted((str(r["s"]), str(r["p"]), str(r["o"])) for r in rows)

    def count(self, cls):
        return int(self.db._execute_and_collect(f"SELECT (COUNT(*) AS ?n) WHERE {{ ?x a {NS}{cls}> }}")[0]["n"])


@pytest.fixture
def world(db, gw):
    return World(db, gw)


class LLM:
    def __init__(self, *items):
        self.reply = json.dumps(list(items))

    def chat(self, messages, **kwargs):
        return self.reply


def claim(quote, obj, *, predicate="did", subject="I"):
    return {"subject": subject, "predicate": predicate, "object": obj, "time": None, "polarity": "asserted",
            "quote": quote, "confidence": 0.9}


async def extract(db, cfg, world, text, llm, *, admit=(), day=3, speaker="Sam"):
    mid = await world.message(text, day=day, speaker=speaker)
    for cid, name, label in admit:
        await world.admit(mid, cid, name, label)
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, cfg, llm, mid, stats)
    return mid, stats


async def seed_sam(world):
    await world.concept("c-sam", "Sam")


async def kind_ids(gw):
    return {r["text_raw"]: r["concept_id"] for r in await gw.run("kinds.live_kinds")}


@needs_wordnet
async def test_entity_object_is_linked_to_the_admitted_concept_and_typed_by_the_stated_kind(db, gw, world):
    await seed_sam(world)
    llm = LLM(claim("I love sports brands like Nike.", "sports brands like Nike", predicate="prefers"))
    mid, stats = await extract(db, ON, world, "I love sports brands like Nike.", llm, admit=[("c-nike", "Nike", "ORG")])
    ks = await kind_ids(gw)
    assert "brand" in ks
    (oid,) = {s for s, _ in world.edges("HAS_OBJECT")}
    assert ("c-nike" in {o for s, o in world.edges("HAS_OBJECT")})
    assert ("c-nike", ks["brand"]) in world.edges("INSTANCE_OF")
    assert world.count("ObjectPhrase") == 0                        # an entity object has no phrase
    assert stats.typed_objects.get("entity_objects") == 1
    # the Observation's object_id literal is filled from the role (B522's setter), and the turn stays the source
    rows = db._execute_and_collect(f"SELECT ?id ?m WHERE {{ ?o {NS}object_id> ?id ; {NS}EVIDENCED_BY> ?m }}")
    assert rows and str(rows[0]["id"]) == "c-nike" and str(rows[0]["m"]).endswith(mid)


@needs_wordnet
async def test_without_admitted_entities_only_the_nameless_path_runs(db, gw, world):
    """B544 absent: no Concept has `ner_label`, so the entity path finds nothing; a nameless object still works."""
    await seed_sam(world)
    await world.concept("c-nike", "Nike")                           # an ordinary Concept, not admitted
    await world.concept("k-book", "book", kind=True)
    llm = LLM(claim("I love sports brands like Nike.", "sports brands like Nike", predicate="prefers"))
    await extract(db, ON, world, "I love sports brands like Nike.", llm)
    assert ("c-nike" not in {o for s, o in world.edges("HAS_OBJECT")})
    assert world.count("ObjectPhrase") == 1 and world.edges("INSTANCE_OF") == set()   # "sports brands": head "brand", no such kind
    assert [r["lemma"] for r in await gw.run("typed_objects.phrase_kind_candidates")] == ["brand"]
    llm2 = LLM(claim("I read a good book last week.", "read a good book"))
    await extract(db, ON, world, "I read a good book last week.", llm2)
    assert world.count("ObjectPhrase") == 2 and len(world.edges("INSTANCE_OF")) == 1
    assert (await gw.run("typed_objects.message_entities", mid="m1")) == []


@needs_wordnet
async def test_nameless_object_is_one_phrase_per_observation_typed_by_its_head(db, gw, world):
    await seed_sam(world)
    await world.concept("k-book", "book", kind=True)
    for day, text in ((3, "I read a good book last week."), (4, "I bought a book yesterday.")):
        obj = "read a good book" if day == 3 else "bought a book"
        await extract(db, ON, world, text, LLM(claim(text, obj)), day=day)
    assert world.count("ObjectPhrase") == 2                         # "a book" in two facts is two nodes
    assert {o for s, o in world.edges("INSTANCE_OF")} == {"k-book"}
    assert len(world.edges("INSTANCE_OF")) == 2
    rows = db._execute_and_collect(f"SELECT ?t ?r WHERE {{ ?p a {NS}ObjectPhrase> ; {NS}text_raw> ?t ; "
                                   f"{NS}rule_version> ?r }}")
    assert sorted((str(r["t"]), str(r["r"])) for r in rows) == [("book", "b546-1"), ("good book", "b546-1")]


@needs_wordnet
async def test_an_untyped_head_is_a_candidate_read_by_the_steward_query(db, gw, world):
    await seed_sam(world)
    await world.concept("k-book", "book", kind=True)
    await extract(db, ON, world, "I read a good novel last week.", LLM(claim("I read a good novel last week.", "read a good novel")))
    assert world.edges("INSTANCE_OF") == set()                      # nothing is typed
    rows = await gw.run("typed_objects.phrase_kind_candidates")
    assert [(r["lemma"], int(r["n"])) for r in rows] == [("novel", 1)]


async def test_speaker_is_typed_person_and_a_kind_person_is_created_by_the_rule(db, gw, world):
    await seed_sam(world)
    llm = LLM(claim("I talked with Melanie today.", "talked with Melanie"))
    mid = await world.message("Hello.", speaker="Melanie")           # Melanie speaks in the conversation
    await extract(db, ON, world, "I talked with Melanie today.", llm, admit=[("c-mel", "Melanie", "PERSON")])
    ks = await kind_ids(gw)
    assert ("c-mel", ks["person"]) in world.edges("INSTANCE_OF")


async def test_a_tagger_person_who_never_speaks_is_not_typed(db, gw, world):
    await seed_sam(world)
    llm = LLM(claim("I talked with Zed today.", "talked with Zed"))
    await extract(db, ON, world, "I talked with Zed today.", llm, admit=[("c-zed", "Zed", "PERSON")])
    assert ("c-zed" in {o for s, o in world.edges("HAS_OBJECT")})
    assert world.edges("INSTANCE_OF") == set() and "person" not in await kind_ids(gw)


async def test_a_kind_label_a_named_entity_holds_is_not_created(db, gw, world):
    """The kind guard: a stated kind whose label is the text of a named entity is never made a kind."""
    await seed_sam(world)
    await world.concept("c-brand", "brand")                         # a named entity (tagger label) spelled "brand"
    db.store.update(f'INSERT DATA {{ <{mint_uri("Concept", "c-brand")}> {NS}ner_label> "ORG" }}')
    llm = LLM(claim("I love sports brands like Nike.", "sports brands like Nike", predicate="prefers"))
    await extract(db, ON, world, "I love sports brands like Nike.", llm, admit=[("c-nike", "Nike", "ORG")])
    assert "brand" not in await kind_ids(gw)
    assert world.edges("INSTANCE_OF") == set()


@needs_wordnet
async def test_a_quote_whose_stored_offsets_are_wrong_is_still_placed_by_search(db, gw, world):
    await seed_sam(world)
    await world.concept("k-book", "book", kind=True)
    text = "Hi there! Long day. I read a good book last week."
    mid = await world.message(text)
    res = await obs.record_observation(db, obs.ObservationDraft(
        evidence_ref=mid, evidence_text="I read a good book last week.", subject_text="I", predicate="did",
        object_text="read a good book", extraction_method="llm", confidence=0.9, speaker="Sam",
        subject_id="c-sam"), config=BASE)
    assert res.ok
    # corrupt the stored offsets the way B552 describes
    db.store.update(f"DELETE {{ ?o {NS}evidence_start> ?s ; {NS}evidence_end> ?e }} "
                    f"INSERT {{ ?o {NS}evidence_start> 0 ; {NS}evidence_end> 5 }} "
                    f"WHERE {{ ?o a {NS}Observation> ; {NS}evidence_start> ?s ; {NS}evidence_end> ?e }}")
    stats = await T.backfill_typed_objects(db, ON)
    assert stats.phrase_objects == 1 and stats.skipped_no_span == 0
    assert len(world.edges("INSTANCE_OF")) == 1


async def test_the_quote_that_cannot_be_placed_is_skipped_and_counted(db, gw, world):
    await seed_sam(world)
    text = "Hi there! I read a good book last week."
    mid = await world.message(text)
    res = await obs.record_observation(db, obs.ObservationDraft(
        evidence_ref=mid, evidence_text="I read a good book last week.", subject_text="I", predicate="did",
        object_text="read a good book", extraction_method="llm", confidence=0.9, speaker="Sam", subject_id="c-sam"),
        config=BASE)
    db.store.update(f'DELETE {{ ?o {NS}evidence_text> ?q }} INSERT {{ ?o {NS}evidence_text> "something else" }} '
                    f'WHERE {{ ?o a {NS}Observation> ; {NS}evidence_text> ?q }}')
    stats = await T.backfill_typed_objects(db, ON)
    assert stats.skipped_no_span == 1 and world.count("ObjectPhrase") == 0


# --- the backfill -------------------------------------------------------------------------

async def build_flag_off_store(db, gw, world):
    await seed_sam(world)
    await world.concept("k-book", "book", kind=True)
    await extract(db, BASE, world, "I love sports brands like Nike.",
                  LLM(claim("I love sports brands like Nike.", "sports brands like Nike", predicate="prefers")),
                  admit=[("c-nike", "Nike", "ORG")])
    await extract(db, BASE, world, "I read a good book last week.",
                  LLM(claim("I read a good book last week.", "read a good book")), day=4)
    await extract(db, BASE, world, "I read a good novel last week.",
                  LLM(claim("I read a good novel last week.", "read a good novel")), day=5)


@needs_wordnet
async def test_backfill_writes_the_same_rule_and_is_idempotent(db, gw, world):
    await build_flag_off_store(db, gw, world)
    assert world.count("ObjectPhrase") == 0 and world.edges("HAS_OBJECT") == set()
    s1 = await T.backfill_typed_objects(db, ON)
    after_first = world.triples()
    assert s1.entity_objects == 1 and s1.phrase_objects == 2 and s1.candidates == 1
    ks = await kind_ids(gw)
    assert ("c-nike", ks["brand"]) in world.edges("INSTANCE_OF")
    assert world.count("ObjectPhrase") == 2
    s2 = await T.backfill_typed_objects(db, ON)
    assert world.triples() == after_first                            # nothing new on a second run
    assert s2.kinds_created == 0


@needs_wordnet
async def test_flag_off_writes_nothing_and_renders_the_same_prompt(db, gw, world, tmp_path):
    from campy.brain.thalamus import bundle_compiler as bc
    from campy.brain.thalamus.ask import _bundle_to_prompt

    await seed_sam(world)
    await world.concept("k-book", "book", kind=True)
    turns = [("I read a good book last week.", "read a good book"), ("I bought a book yesterday.", "bought a book")]
    for day, (text, obj) in enumerate(turns, start=3):
        await extract(db, BASE, world, text, LLM(claim(text, obj)), day=day)
    assert world.count("ObjectPhrase") == 0 and world.edges("HAS_OBJECT") == set()
    off_false = {**BASE, "observations": {**BASE["observations"], "typed_objects": False}}
    q = "What books has Sam read?"
    prompts = [_bundle_to_prompt(await bc.compile_bundle(q, db, c), q, c) for c in (BASE, off_false)]
    assert prompts[0] == prompts[1]
    # and the same store written with the flag ON renders the same prompt: the typed objects change no text by themselves
    db2 = OxigraphClient(tmp_path / "on.db")
    gw2 = GraphGateway(db2, REGISTRY)
    w2 = World(db2, gw2)
    await seed_sam(w2)
    await w2.concept("k-book", "book", kind=True)
    for day, (text, obj) in enumerate(turns, start=3):
        await extract(db2, ON, w2, text, LLM(claim(text, obj)), day=day)
    assert w2.count("ObjectPhrase") == 2
    assert _bundle_to_prompt(await bc.compile_bundle(q, db2, ON), q, ON) == prompts[0]


# --- the queries -------------------------------------------------------------------------

async def fixture_store(db, gw, world):
    """Sam: two book facts (phrases), a Dune fact (entity), a brand fact; Kim: one book fact."""
    await seed_sam(world)
    await world.concept("c-kim", "Kim")
    await world.concept("k-book", "book", kind=True)
    await world.concept("k-novel", "novel", kind=True)
    await kinds.link_broader(gw, "k-novel", "k-book")
    plan = [("Sam", 3, "I read a good book last week.", "read a good book", [], "did"),
            ("Sam", 4, "I bought a book yesterday.", "bought a book", [], "did"),
            ("Sam", 5, "I read a novel called Dune.", "novel called Dune", [("c-dune", "Dune", "WORK_OF_ART")], "did"),
            ("Sam", 6, "I love sports brands like Nike.", "sports brands like Nike", [("c-nike", "Nike", "ORG")], "prefers"),
            ("Kim", 7, "I read a good book last week.", "read a good book", [], "did")]
    mids = []
    for speaker, day, text, obj, admit, pred in plan:
        cfg = ON
        mid, _ = await extract(db, cfg, world, text, LLM(claim(text, obj, predicate=pred)), admit=admit, day=day,
                               speaker=speaker)
        mids.append(mid)
    return mids


@needs_wordnet
async def test_exact_role_query_returns_the_subjects_book_facts_with_their_turns(db, gw, world):
    mids = await fixture_store(db, gw, world)
    ks = await kind_ids(gw)
    rows = await gw.run("typed_objects.exact_role_turns", sid="c-sam", kind_id=ks["book"])
    turns = {str(r["evidence_message_id"]) for r in rows}
    assert turns == {mids[0], mids[1], mids[2]}                      # two phrases and Dune (a novel is under book)
    assert mids[4] not in turns and mids[3] not in turns             # Kim's turn; the brand fact
    by_turn = {str(r["evidence_message_id"]): r for r in rows}
    assert by_turn[mids[2]]["object_label"] == "Dune" and by_turn[mids[2]]["object_id"] == "c-dune"
    assert by_turn[mids[0]]["object_label"] == "good book" and by_turn[mids[0]].get("object_id") in (None, "")
    assert (await gw.run("typed_objects.exact_role_turns", sid="c-sam", kind_id="no-such-kind")) == []
    assert (await gw.run("typed_objects.exact_role_turns", sid="no-such", kind_id=ks["book"])) == []
    assert {str(r["evidence_message_id"]) for r in await gw.run("typed_objects.exact_role_turns", sid="c-kim", kind_id=ks["book"])} == {mids[4]}


async def test_loose_query_also_takes_an_entity_the_fact_only_names(db, gw, world):
    mids = await fixture_store(db, gw, world)
    ks = await kind_ids(gw)
    # a modifier entity: the fact's object is the brand but the turn also names Dune as a book
    loose = {str(r["evidence_message_id"]) for r in await gw.run("typed_objects.loose_role_turns", sid="c-sam", kind_id=ks["book"])}
    exact = {str(r["evidence_message_id"]) for r in await gw.run("typed_objects.exact_role_turns", sid="c-sam", kind_id=ks["book"])}
    assert exact <= loose


@needs_wordnet
async def test_a_phrase_is_not_a_concept_and_not_counted_as_something_the_subject_has(db, gw, world):
    await fixture_store(db, gw, world)
    ks = await kind_ids(gw)
    # the phrases and Dune are under "book"; B524's count is of entities, so the two phrase nodes are not counted
    n = (await gw.run("observations.count_objects_of_subject", sid="c-sam", kind_id=ks["book"], predicate="did",
                      before=None))[0]["n"]
    assert int(n) == 1                                               # Dune
    live = {r["text_raw"] for r in await gw.run("concept_links.live_concepts")}
    assert "good book" not in live and "book" in live               # "book" still resolves to the kind


@needs_wordnet
async def test_instantiated_kinds_ignore_phrases(db, gw, world):
    await seed_sam(world)
    await world.concept("k-book", "book", kind=True)
    await extract(db, ON, world, "I read a good book last week.", LLM(claim("I read a good book last week.", "read a good book")))
    assert world.edges("INSTANCE_OF")                                # a phrase is INSTANCE_OF book
    assert [r["concept_id"] for r in await gw.run("observations.instantiated_kinds")] == []   # B523's ownable test unchanged


# --- flag, profile, template -----------------------------------------------------------------

def test_flag_default_off_env_on_and_in_the_principled_profile(monkeypatch):
    assert _DEFAULT_CONFIG["observations"]["typed_objects"] is False
    assert obs.typed_objects_enabled({}) is False and obs.typed_objects_enabled(_DEFAULT_CONFIG) is False
    assert obs.typed_objects_enabled(apply_env_overrides({}, {"CAMPY_TYPED_OBJECTS": "1"})) is True
    assert obs.typed_objects_enabled(
        apply_env_overrides({"observations": {"typed_objects": True}}, {"CAMPY_TYPED_OBJECTS": "0"})) is False
    assert PROFILES["principled"]["observations"]["typed_objects"] is True and PROFILES["main"] == {}


def test_shipped_templates_carry_only_a_commented_line():
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root / "campy" / "data" / "config" / "campy.toml",):
        text = path.read_text()
        assert "typed_objects" in text
        assert "typed_objects" not in tomllib.loads(text).get("observations", {})
