"""B547: the question is analysed once (flag `[retrieval] question_analysis`, default off).

Real spaCy, no model call. Pins:
- the analysis itself (pure function over a hand-built lexicon): shape and the rule that fired, the subject
  (ties, no subject, a name not in the graph, B549's weak persons), the kind asked for (singular, full vs
  head match), the Concepts named (longest first, non-overlapping), the text cut at the first "?" (B551);
- every member of the closed-class word sets;
- the lexicon read through NamedQueries from a real Oxigraph store, with and without B544's `ner_label`;
- the wiring: bundle.analysis, section `reads`, the stages and B524 reading the analysis;
- flag off: nothing changes (no analysis, no `reads`, no lexicon read, same rendered prompt), and the profile.
"""

from __future__ import annotations

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, PROFILE_ENV, apply_env_overrides, load_config
from campy.brain.hippocampus.concept_links import norm_key
from campy.brain.thalamus import question_analysis as qa
from campy.brain.thalamus.question_analysis import QuestionLexicon, analyse_question
from tests._spacy import SPACY_AVAILABLE

pytestmark = pytest.mark.skipif(not SPACY_AVAILABLE, reason="needs a working spaCy with en_core_web_md")


def cid(name: str) -> str:
    return "c-" + name.lower().replace(" ", "-")


def lexicon(people=(), weak=(), kinds=(), entities=()) -> QuestionLexicon:
    labels, index, persons, kind_labels, kind_keys = {}, {}, {}, {}, {}
    for name in [*people, *weak, *entities, *kinds]:
        labels[cid(name)] = name
        index.setdefault(norm_key(name), []).append(cid(name))
    for name in [*people, *weak]:
        persons[name.lower()] = cid(name)
    for name in kinds:
        kind_labels[cid(name)] = name
        kind_keys.setdefault(norm_key(name), []).append(cid(name))
    return QuestionLexicon(
        index={k: tuple(v) for k, v in index.items()}, labels=labels,
        kinds={k: tuple(v) for k, v in kind_keys.items()}, kind_labels=kind_labels, persons=persons,
        weak_person_ids=frozenset(cid(n) for n in weak))


LEX = lexicon(
    people=["Caroline", "Melanie", "Dave", "Nate", "Joanna", "Evan", "Sam", "Maria", "Deborah", "John", "Andrew"],
    weak=["Yoga", "Jean"],
    kinds=["pet", "event", "art", "hobby", "city", "book", "gift", "point", "group"],
    entities=["LGBTQ conference", "LGBTQ", "conversation", "yoga practice", "The Four Seasons", "Pacific Northwest"])


def A(question: str, lex: QuestionLexicon = LEX):
    return analyse_question(question, lex)


# --- shape ------------------------------------------------------------------------------------

@pytest.mark.parametrize("question,shape,rule", [
    ("How many pets does Andrew have?", "count", "how_many"),
    ("What cities have Nate and Joanna visited?", "list", "wh_plural_head"),
    ("What are Dave's hobbies other than fixing cars?", "list", "copular_plural_head"),
    ("What kind of pets does Andrew have?", "list", "wh_plural_head"),
    ("When did Caroline go to the LGBTQ conference?", "when", "when"),
    ("How long have Melanie and Caroline been friends?", "when", "how_long"),
    ("How often does Dave go hiking?", "when", "how_often"),
    ("How many months passed since Caroline moved?", "when", "how_many_time_unit"),
    ("What year did Caroline move?", "when", "wh_time_noun"),
    ("What did Maria do before meeting John?", "before_after", "bound_marker"),
    ("Where does Caroline currently live?", "latest", "recency_marker"),
    ("Does Caroline attend the LGBTQ conference?", "yes_no", "aux_initial"),
    ("Would Melanie enjoy the song \"The Four Seasons\"?", "yes_no", "aux_initial"),
    ("Would Evan like a hike or a dinner?", "open", "aux_initial_or_choice"),
    ("What did Caroline research?", "open", "default"),
    ("Based on the conversation, did Caroline move?", "yes_no", "aux_initial"),
])
def test_shape_and_the_rule_that_fired(question, shape, rule):
    a = A(question)
    assert (a.shape, a.shape_rule) == (shape, rule)


def test_modifiers():
    assert A("Would Melanie enjoy the song \"The Four Seasons\"?").modifiers == ("inferential",)
    assert A("Would Evan like a hike or a dinner?").modifiers == ("inferential", "choice")
    assert A("How long have Melanie and Caroline been friends?").modifiers == ("duration",)
    assert A("How often does Dave go hiking?").modifiers == ("frequency",)
    assert A("Where does Caroline currently live?").modifiers == ("recency",)
    assert A("What did Caroline research?").modifiers == ()


def test_bound_and_dates():
    a = A("What did Maria do before meeting John in March 2023?")
    assert a.bound == {"rel": "before", "text": "meeting John in March 2023"}
    assert "March 2023" in a.dates


# --- the text analysed (B551) ------------------------------------------------------------------

def test_the_text_is_the_question_up_to_its_first_question_mark():
    q = ("When did Caroline go to the LGBTQ conference? Use the dates of the conversation to answer with an "
         "approximate date.")
    a = A(q)
    assert a.text == "When did Caroline go to the LGBTQ conference?"
    assert a.question == q
    assert "conversation" not in [c["span"] for c in a.concepts]          # a Concept "conversation" exists
    assert [c["label"] for c in A(q.split("?")[0] + "?").concepts] == [c["label"] for c in a.concepts]


def test_a_question_with_no_question_mark_is_taken_whole():
    assert A("Tell me about Caroline").text == "Tell me about Caroline"


def test_backtick_and_curly_apostrophes_are_normalised():
    assert A("Who is Dave`s friend?").subject_id == cid("Dave")
    assert A("Who is Dave’s friend?").subject_id == cid("Dave")


# --- subject -----------------------------------------------------------------------------------

def test_one_subject_and_it_is_the_one_the_clause_is_about():
    a = A("What did Caroline research?")
    assert (a.subject_id, a.subject, a.tie, a.anchor_ids) == (cid("Caroline"), "Caroline", False, (cid("Caroline"),))


def test_coordinated_people_tie_and_both_anchor():
    a = A("What cities have Nate and Joanna visited?")
    assert a.tie and a.anchor_ids == (cid("Nate"), cid("Joanna"))
    assert [s["id"] for s in a.subjects] == [cid("Nate"), cid("Joanna")]
    assert a.subject_id == cid("Nate")


def test_two_people_not_coordinated_do_not_tie():
    a = A("What did Maria tell John about Caroline?")
    assert not a.tie and len(a.anchor_ids) == 1
    assert {s["id"] for s in a.subjects} == {cid("Maria"), cid("John"), cid("Caroline")}


def test_no_person_means_no_anchor():
    a = A("What did the charity race raise awareness for?")
    assert (a.subject_id, a.subjects, a.anchor_ids, a.tie) == (None, (), (), False)


def test_a_name_not_in_the_graph_that_outranks_the_subject_is_reported():
    a = A("What did Jolene tell Maria about Caroline?")
    assert a.subject_id == cid("Maria")                                    # falls to the best resolved person
    assert a.subject_unresolved == ("Jolene",)
    only = A("Who is Jolene`s partner?")
    assert only.subject_id is None and only.subject_unresolved == ("Jolene",)


def test_a_tagger_label_alone_is_not_a_person():
    """B549: ner_label PERSON on Yoga must not make it the subject; Deborah is."""
    lex = lexicon(people=["Deborah"], weak=["Yoga"])
    a = A("What new yoga poses did Deborah try?", lex)
    assert a.subject_id == cid("Deborah") and [s["id"] for s in a.subjects] == [cid("Deborah")]
    assert all(c["role"] != "person" or c["id"] == cid("Deborah") for c in a.concepts)


def test_a_weak_person_counts_when_spacy_agrees():
    a = A("What did Jean go through before meeting Maria?")
    assert cid("Jean") in [s["id"] for s in a.subjects]


# --- kind --------------------------------------------------------------------------------------

@pytest.mark.parametrize("question,kind_text,kind,match", [
    ("What cities have Nate visited?", "city", "city", "full"),
    ("How many pets does Andrew have?", "pet", "pet", "full"),
    ("What kind of pets does Andrew have?", "pet", "pet", "full"),
    ("What are Dave's hobbies other than fixing cars?", "hobby", "hobby", "full"),
    ("What LGBTQ+ events has Caroline participated in?", "lgbtq+ event", "event", "head"),
    ("What martial arts has John done?", "martial art", "art", "head"),
    ("In light of the changes discussed, what would be an appropriate gift for both Evan and Sam?", "appropriate gift", "gift", "head"),
])
def test_kind_is_singular_and_resolved_in_the_closed_set(question, kind_text, kind, match):
    a = A(question)
    assert (a.kind_text, a.kind_label, a.kind_match) == (kind_text, kind, match)
    assert a.kind_id == cid(kind)


@pytest.mark.parametrize("question", [
    "What is Nate's favorite book series about?",                       # "series" is not a plural
    "What was the highest number of points John scored in a game recently?",   # "number of" is a meta-noun
    "Does Caroline like pets?",                                          # yes/no names a kind, asks for none
    "When did Andrew adopt his pets?",
    "How many months passed since Caroline moved?",
])
def test_no_kind_is_asked_for(question):
    a = A(question)
    assert a.kind_id is None and a.kind_text is None


def test_a_kind_phrase_outside_the_kind_set_has_text_but_no_id():
    a = A("What new yoga poses did Deborah try?", lexicon(people=["Deborah"]))
    assert a.kind_text == "new yoga pose" and a.kind_id is None and a.kind_match == ""


# --- concepts ----------------------------------------------------------------------------------

def test_concepts_are_longest_first_and_do_not_overlap():
    a = A("When did Caroline go to the LGBTQ conference?")
    spans = [c["span"] for c in a.concepts]
    assert "LGBTQ conference" in spans and "LGBTQ" not in spans
    assert a.concepts[0]["role"] == "person"


def test_concept_roles_and_quoted_titles():
    a = A("Would Melanie enjoy the song \"The Four Seasons\"?")
    by_span = {c["span"]: c for c in a.concepts}
    assert by_span["Melanie"]["role"] == "person"
    assert by_span["The Four Seasons"]["role"] == "entity"
    kind = A("How many pets does Andrew have?")
    assert {c["id"]: c["role"] for c in kind.concepts}[cid("pet")] == "kind"
    assert kind.concept_ids == [c["id"] for c in kind.concepts]


def test_plural_folding_finds_the_concept():
    assert cid("event") in A("What events has Caroline attended?").concept_ids


def test_nothing_is_created_for_a_span_the_graph_does_not_hold():
    a = A("What did Caroline say about the Zorblax Institute?")
    assert [c["label"] for c in a.concepts] == ["Caroline"]


def test_the_analysis_serialises():
    d = A("What cities have Nate and Joanna visited?").to_dict()
    assert d["shape"] == "list" and d["tie"] is True and isinstance(d["concepts"], list) and isinstance(d["anchor_ids"], list)
    assert "question" in d and "text" in d


def test_log_fields_carry_no_question_text():
    f = A("What cities have Nate and Joanna visited?").log_fields()
    assert "Nate" not in str(f) and f["shape"] == "list" and f["has_subject"] is True


# --- the closed-class word sets: one test per member -------------------------------------------

@pytest.mark.parametrize("word", sorted(qa.RECENCY))
def test_every_recency_word_marks_recency(word):
    a = A(f"Where does Caroline live {word}?")
    assert "recency" in a.modifiers


@pytest.mark.parametrize("word", sorted(qa.BEFORE_AFTER))
def test_every_before_after_word_makes_a_bound(word):
    a = A(f"What did Maria do {word} meeting John?")
    assert a.bound and a.bound["rel"] == word and a.shape == "before_after"


@pytest.mark.parametrize("unit", sorted(qa.TIME_UNITS))
def test_every_time_unit_makes_how_many_a_duration(unit):
    a = A(f"How many {unit}s has Caroline lived there?")
    assert a.shape == "when" and "duration" in a.modifiers


@pytest.mark.parametrize("noun", sorted(qa.TYPE_NOUNS))
def test_every_type_noun_is_skipped_on_the_way_to_the_kind(noun):
    a = A(f"What {noun} of pets does Andrew have?")
    assert a.kind_label == "pet"


@pytest.mark.parametrize("aux", sorted(qa.AUX - {"am", "shall"}))
def test_every_auxiliary_opens_a_yes_no_question(aux):
    assert A(f"{aux.capitalize()} Caroline like the LGBTQ conference?").shape == "yes_no"


@pytest.mark.parametrize("modal", sorted(qa.MODAL_INFER))
def test_every_inferential_modal_is_marked(modal):
    assert "inferential" in A(f"{modal.capitalize()} Caroline like the LGBTQ conference?").modifiers


@pytest.mark.parametrize("noun", sorted(qa.META_NOUNS | {"time", "number", "amount", "reason", "idea"} & qa.NOT_KIND))
def test_a_meta_noun_is_never_the_kind(noun):
    lex = lexicon(people=["Caroline"], kinds=[noun])
    assert A(f"What {noun}s did Caroline mention?", lex).kind_id is None


# --- the lexicon, read through NamedQueries from a real store -----------------------------------

from datetime import datetime, timezone                                          # noqa: E402

from campy.brain.hippocampus import kinds                                         # noqa: E402
from campy.brain.hippocampus.graph import embeddings as embeddings_mod          # noqa: E402
from campy.brain.hippocampus.graph.gateway import GraphGateway                    # noqa: E402
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient          # noqa: E402
from campy.brain.hippocampus.graph.queries import REGISTRY                        # noqa: E402

DIM = 384
EMB = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: EMB)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b547.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def concept(gw, c_id, text, stype="Thing", kind=False):
    await gw.run("temporal_lobe.dict_create_concept", cid=c_id, text=text, emb=EMB, gist="Entity", stype=stype, now=T0)
    if kind:
        await kinds.mark_kind(gw, c_id)


def tag_ner(db, c_id, label="PERSON"):
    db.store.update("PREFIX campy: <https://campy.dev/ns#> INSERT { ?c campy:ner_label \"%s\" } "
               "WHERE { ?c a campy:Concept ; campy:concept_id \"%s\" }" % (label, c_id))


async def seed_store(db, gw, with_ner=False):
    await concept(gw, "p-andrew", "Andrew", "Person")
    await concept(gw, "p-audrey", "Audrey", "Person")
    await concept(gw, "k-pet", "pet", kind=True)
    await concept(gw, "k-dog", "dog", kind=True)
    await concept(gw, "e-toby", "Toby")
    await concept(gw, "e-yoga", "Yoga")
    await concept(gw, "e-deb", "Deborah")
    await kinds.link_broader(gw, "k-dog", "k-pet")
    await gw.run("quests.create_alt_label", lid="l1", txt="Andy", now="2023-05-01T00:00:00+00:00")
    await gw.run("quests.link_concept_has_alt_label", cid="p-andrew", lid="l1")
    if with_ner:
        tag_ner(db, "e-yoga")
        tag_ner(db, "e-deb")


async def test_lexicon_from_the_store_without_ner_labels(db, gw):
    await seed_store(db, gw)
    lex = await qa.load_lexicon(gw)
    assert lex.persons == {"andrew": "p-andrew", "audrey": "p-audrey"} and not lex.weak_person_ids
    assert lex.index[norm_key("Andy")] == ("p-andrew",)                    # an altLabel finds its Concept
    assert lex.kinds[norm_key("pets")] == ("k-pet",) and lex.kind_labels["k-pet"] == "pet"
    assert lex.labels["e-toby"] == "Toby"
    a = analyse_question("How many pets does Andrew have?", lex)
    assert a.kind_id == "k-pet" and a.shape == "count" and a.subject_id == "p-andrew"


async def test_lexicon_from_the_store_with_ner_labels_marks_weak_persons(db, gw):
    await seed_store(db, gw, with_ner=True)
    lex = await qa.load_lexicon(gw)
    assert lex.weak_person_ids == {"e-yoga", "e-deb"} and lex.persons["yoga"] == "e-yoga"
    a = analyse_question("What new yoga poses did Deborah try?", lex)
    assert a.subject_id == "e-deb"                                         # spaCy agrees on Deborah, not on yoga
    assert "e-yoga" not in [s["id"] for s in a.subjects]


async def test_a_graph_person_beats_a_tagger_label_on_the_same_name(db, gw):
    await seed_store(db, gw)
    tag_ner(db, "p-andrew")
    lex = await qa.load_lexicon(gw)
    assert "p-andrew" not in lex.weak_person_ids


async def test_archived_concepts_are_not_in_the_lexicon(db, gw):
    await seed_store(db, gw)
    db.store.update("PREFIX campy: <https://campy.dev/ns#> DELETE { ?c campy:archived false } INSERT { ?c campy:archived true } "
               "WHERE { ?c campy:concept_id \"e-toby\" ; campy:archived false }")
    lex = await qa.load_lexicon(gw)
    assert "e-toby" not in lex.labels


async def test_the_lexicon_reads_only_registered_named_queries(db, gw, monkeypatch):
    await seed_store(db, gw)
    calls = []
    real = gw.run

    async def spy(name, **kw):
        calls.append(name)
        return await real(name, **kw)
    monkeypatch.setattr(gw, "run", spy)
    await qa.load_lexicon(gw)
    assert "question_analysis.concept_lexicon" in calls and "question_analysis.concept_surfaces" in calls
    assert set(calls) == {"question_analysis.concept_lexicon", "question_analysis.concept_surfaces",
                          "kinds.live_kinds", "kinds.kind_alt_labels", "kinds.kind_broader_edges"}


# --- wiring ------------------------------------------------------------------------------------

from campy.brain.thalamus import bundle_compiler as bc                           # noqa: E402
from campy.brain.thalamus import graph_count as gc                               # noqa: E402
from tests.test_b524_graph_count import ROLES, owns                              # noqa: E402

ON = {**ROLES, "retrieval": {"conversation_token_budget": 0, "graph_count": True, "question_analysis": True}}
OFF = {**ROLES, "retrieval": {"conversation_token_budget": 0, "graph_count": True}}


async def seed_pets(db, gw):
    await concept(gw, "c-andrew", "Andrew", "Person")
    await concept(gw, "c-audrey", "Audrey", "Person")
    for c_id, text, is_kind in (("c-toby", "Toby", False), ("c-buddy", "Buddy", False), ("c-pet", "pet", True),
                                ("c-dog", "dog", True), ("c-conv", "conversation", False)):
        await concept(gw, c_id, text, kind=is_kind)
    await kinds.link_broader(gw, "c-dog", "c-pet")
    await kinds.link_instance_of(gw, "c-toby", "c-dog")
    await kinds.link_instance_of(gw, "c-buddy", "c-pet")
    await owns(db, gw, "m1", "05-03", "Andrew", "c-andrew", "c-toby", "Toby", "My pup Toby is great.")
    await owns(db, gw, "m2", "07-10", "Andrew", "c-andrew", "c-buddy", "Buddy", "I adopted Buddy.")


async def test_bundle_carries_the_analysis_and_each_section_its_reads(db, gw):
    await seed_pets(db, gw)
    b = await bc.compile_bundle("How many pets does Andrew have?", db, ON)
    assert b.analysis["shape"] == "count" and b.analysis["subject_id"] == "c-andrew" and b.analysis["kind_id"] == "c-pet"
    d = b.to_dict()
    assert d["analysis"] == b.analysis
    by_type = {s["type"]: s for s in d["sections"]}
    assert by_type["graph_count"]["reads"] == ["shape", "subject_id", "kind_id", "kind_match", "text"]
    assert "owns 2 of kind pet" in by_type["graph_count"]["content"][0]["text"]


async def test_the_stages_read_concept_ids_from_the_analysis(db, gw, monkeypatch):
    await seed_pets(db, gw)
    seen = {}

    async def boom(*a, **k):
        raise AssertionError("the stage parsed the question itself")
    monkeypatch.setattr(bc, "_question_concept_ids", boom)
    real_run = gw.run

    async def spy(name, **kw):
        if name == "thalamus.bundle_observations":
            seen["concept_ids"] = kw["concept_ids"]
        return await real_run(name, **kw)
    monkeypatch.setattr(bc, "get_gateway", lambda _db: type("G", (), {"run": staticmethod(spy)})())
    a = analyse_question("What did Andrew say about Toby?", await qa.load_lexicon(gw))
    await bc._stage_observations(db, "What did Andrew say about Toby?", ON, analysis=a)
    assert set(seen["concept_ids"]) == {"c-andrew", "c-toby"}


async def test_the_walk_reads_concept_ids_from_the_analysis(db, gw, monkeypatch):
    await seed_pets(db, gw)

    async def boom(*a, **k):
        raise AssertionError("the walk parsed the question itself")
    monkeypatch.setattr(bc, "_question_concept_ids", boom)
    import campy.brain.hippocampus.concept_links as cl
    monkeypatch.setattr(cl, "match_concepts", boom)
    got = {}
    real_run = gw.run

    async def spy(name, **kw):
        if name == "thalamus.bundle_concept_walk":
            got["ids"] = kw["concept_ids"]
        return await real_run(name, **kw)
    monkeypatch.setattr(bc, "get_gateway", lambda _db: type("G", (), {"run": staticmethod(spy)})())
    a = analyse_question("What did Andrew say about Toby?", await qa.load_lexicon(gw))
    cfg = {**ON, "retrieval": {**ON["retrieval"], "graph_linking_limit": 12}}
    await bc._stage_concept_walk(db, "What did Andrew say about Toby?", cfg, set(), analysis=a)
    assert set(got["ids"]) == {"c-andrew", "c-toby"}


async def test_the_instruction_sentence_does_not_resolve_a_concept(db, gw):
    await seed_pets(db, gw)
    q = "When did Andrew adopt Buddy? Use the dates of the conversation to answer with an approximate date."
    on = await bc.compile_bundle(q, db, ON)
    assert "c-conv" not in [c["id"] for c in on.analysis["concepts"]]
    assert "c-conv" in await bc._question_concept_ids(bc.get_gateway(db), q)       # what the old resolver did


async def test_graph_count_reads_shape_subject_and_kind_from_the_analysis(db, gw):
    await seed_pets(db, gw)
    lex = await qa.load_lexicon(gw)
    route = gc.route_question("x", analysis=analyse_question("How many pets does Andrew have?", lex))
    assert route.form == "count" and route.predicate == "owns"
    for q in ("When did Andrew adopt Buddy?", "Does Andrew have pets?", "What did Andrew say?"):
        assert gc.route_question(q, analysis=analyse_question(q, lex)) is None, q
    q = "What pets does Andrew have? Please answer carefully and say how many times he got any."
    assert gc.route_question(q, analysis=analyse_question(q, lex)).form == "list"          # the instruction is not read


async def test_graph_count_declines_without_a_subject_a_tie_or_a_whole_kind(db, gw):
    await seed_pets(db, gw)
    lex = await qa.load_lexicon(gw)
    ok = analyse_question("How many pets does Andrew have?", lex)
    assert gc.resolve_from_analysis(ok).kind_id == "c-pet"
    for q in ("How many pets are there?", "How many pets do Andrew and Audrey have?", "How many pets does Jolene have?"):
        assert gc.resolve_from_analysis(analyse_question(q, lex)) is None, q
    head = analyse_question("How many cute dogs does Andrew have?", lex)
    assert (head.kind_id, head.kind_match) == ("c-dog", "head")              # found by dropping "cute"
    assert gc.resolve_from_analysis(head) is None


# --- flag off: nothing changes -----------------------------------------------------------------

QUESTIONS = ["How many pets does Andrew have?", "What pets does Andrew have?", "When did Andrew adopt Buddy?",
             "What did Andrew say about Toby?", "Does Andrew like dogs?",
             "When did Andrew adopt Buddy? Use the dates of the conversation to answer with an approximate date."]


async def test_flag_off_never_touches_the_analysis(db, gw, monkeypatch):
    await seed_pets(db, gw)

    async def boom(*a, **k):
        raise AssertionError("the analysis ran with the flag off")
    monkeypatch.setattr(qa, "load_lexicon", boom)
    monkeypatch.setattr(bc, "analyse_for_bundle", boom)
    for config in (OFF, {**OFF, "retrieval": {**OFF["retrieval"], "question_analysis": False}}):
        b = await bc.compile_bundle("How many pets does Andrew have?", db, config)
        assert b.analysis is None
        d = b.to_dict()
        assert "analysis" not in d and all("reads" not in s for s in d["sections"])
        assert all(s.reads == [] for s in b.sections)


async def test_flag_off_renders_the_same_prompt_with_the_key_absent_or_false(db, gw):
    from campy.brain.thalamus.ask import _bundle_to_prompt
    await seed_pets(db, gw)
    off_false = {**OFF, "retrieval": {**OFF["retrieval"], "question_analysis": False}}
    for q in QUESTIONS:
        a = _bundle_to_prompt(await bc.compile_bundle(q, db, OFF), q, OFF)
        b = _bundle_to_prompt(await bc.compile_bundle(q, db, off_false), q, off_false)
        assert a == b, q


async def test_a_failing_analysis_falls_back_to_the_stages_own_parsing(db, gw, monkeypatch):
    await seed_pets(db, gw)

    async def boom(*a, **k):
        raise RuntimeError("lexicon unavailable")
    monkeypatch.setattr(qa, "load_lexicon", boom)
    b = await bc.compile_bundle("How many pets does Andrew have?", db, ON)
    assert b.analysis is None
    assert "owns 2 of kind pet" in b.sections[0].content[0]["text"]          # B524's own resolver answered


# --- the flag and the profile ------------------------------------------------------------------

def test_flag_default_off_and_env_turns_it_on(monkeypatch):
    assert _DEFAULT_CONFIG["retrieval"]["question_analysis"] is False
    assert qa.question_analysis_enabled({}) is False
    monkeypatch.setenv("CAMPY_QUESTION_ANALYSIS", "1")
    cfg = apply_env_overrides({"retrieval": {"question_analysis": False}})
    assert qa.question_analysis_enabled(cfg) is True


def test_principled_profile_turns_it_on_for_a_keyless_config(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[llm]\nprovider = "ollama"\n')
    monkeypatch.delenv("CAMPY_QUESTION_ANALYSIS", raising=False)
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    assert qa.question_analysis_enabled(load_config(str(path))) is False
    monkeypatch.setenv(PROFILE_ENV, "principled")
    assert qa.question_analysis_enabled(load_config(str(path))) is True
    monkeypatch.setenv("CAMPY_QUESTION_ANALYSIS", "0")
    assert qa.question_analysis_enabled(load_config(str(path))) is False


def test_the_shipped_template_does_not_write_the_key():
    import pathlib
    text = (pathlib.Path(qa.__file__).parents[2] / "data" / "config" / "campy.toml").read_text()
    lines = [l for l in text.splitlines() if "question_analysis" in l and "=" in l]
    assert lines and all(l.lstrip().startswith("#") for l in lines)
