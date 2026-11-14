"""Item 3 (user ruling 2026-11-14): "we" and people named by relation as subjects (flag `[observations]
group_subjects`, default off). Real Oxigraph store and WordNet (skipped when absent), scripted model, made-up names.

Pins: the flag (default off, env, in no profile) and flag-off byte identity of the prompts and the writes; the
prompt's two string replacements; "we" anchored on the speaker with group_subject, partners only when named; a
relation Concept RELATION_OF the speaker, one per speaker and relation, never another speaker's; "her kids" and
"my car" not handled; the SHACL shapes and the schema carry RELATION_OF and group_subject; the read
query_hits.relation_subject returns the owner's relation node only.
"""

from __future__ import annotations

import pyoxigraph as ox
import pytest

from campy.brain.brainstem.config import PROFILES, _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.schema import REL_TABLES, SCHEMA_MIGRATIONS
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.temporal_lobe.observations import subjects as S
from tests.b564_helpers import LLM, NS, Q, World, cfg, claim, extract, flag_off_signature

needs_wordnet = pytest.mark.skipif(not wn_mod.available(), reason="WordNet not installed")
ON = cfg(object_roles=True, group_subjects=True)
OFF = cfg(object_roles=True)


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "item3.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


@pytest.fixture
def world(db, gw):
    return World(db, gw)


async def people(world):
    await world.concept("c-nora", "Nora")
    await world.concept("c-theo", "Theo")


def facts(db):
    """{(quote, subject concept id or None, group_subject)} of every live Observation."""
    rows = db._execute_and_collect(
        f"SELECT ?q ?sid ?g WHERE {{ ?o a {NS}Observation> ; {NS}evidence_text> ?q . "
        f"OPTIONAL {{ ?o {NS}subject_id> ?sid }} OPTIONAL {{ ?o {NS}group_subject> ?g }} }}")
    return {(str(r["q"]), str(r["sid"]) if r.get("sid") else None, str(r.get("g")) in ("true", "True"))
            for r in rows}


def participants(db):
    rows = db._execute_and_collect(
        f"SELECT ?q ?cid WHERE {{ ?o {NS}HAS_PARTICIPANT> ?c ; {NS}evidence_text> ?q . ?c {NS}concept_id> ?cid }}")
    return {(str(r["q"]), str(r["cid"])) for r in rows}


# --- the flag and flag-off identity ---------------------------------------------------------------

def test_flag_default_off_env_on_not_in_a_profile(monkeypatch):
    assert _DEFAULT_CONFIG["observations"]["group_subjects"] is False
    monkeypatch.setenv("CAMPY_OBSERVATION_GROUP_SUBJECTS", "1")
    assert apply_env_overrides({"observations": {}})["observations"]["group_subjects"] is True
    assert all("group_subjects" not in (p.get("observations") or {}) for p in PROFILES.values())


def test_prompt_changes_by_the_two_replacements_only():
    off = ex.build_messages("We went to the lake.", "Nora", "2023-05-03")[1]["content"]
    on = ex.build_messages("We went to the lake.", "Nora", "2023-05-03", group_subjects=True)[1]["content"]
    assert ex._SUBJECTS_OLD in off and ex._SUBJECTS_NEW not in off
    assert on == off.replace(ex._SUBJECTS_OLD, ex._SUBJECTS_NEW).replace(ex._SUBJECT_EXAMPLES_OLD,
                                                                        ex._SUBJECT_EXAMPLES_NEW)
    assert on != off


async def test_flag_off_writes_what_it_wrote_before(tmp_path):
    a = OxigraphClient(tmp_path / "a.db")
    b = OxigraphClient(tmp_path / "b.db")
    base = await flag_off_signature(a, GraphGateway(a, REGISTRY))
    explicit_off = await flag_off_signature(b, GraphGateway(b, REGISTRY), {"group_subjects": False})
    assert base == explicit_off


async def test_flag_off_leaves_we_and_my_kids_unanchored(db, gw, world):
    await people(world)
    await extract(db, OFF, world, "We went to the lake with Theo last week.",
                  LLM(claim("We went to the lake with Theo", "go to the lake", subject="we")), speaker="Nora")
    assert facts(db) == {("We went to the lake with Theo", None, False)}


# --- the rule, on made-up subjects -----------------------------------------------------------------

@needs_wordnet
def test_classify():
    assert S.classify("we", "We went to the lake").kind == "group"
    assert S.classify("We're", "We're going camping").kind == "group"
    assert S.classify("we", "I went to the lake") is None                     # no first-person plural in the quote
    g = S.classify("my partner and I", "my partner and I went hiking")
    assert g.kind == "group" and g.partners == [("partner", "partner")]
    assert S.classify("Theo and I", "Theo and I went hiking").partners == []  # a named partner comes from MENTIONS
    r = S.classify("my kids", "my kids love the beach")
    assert r.kind == "relation" and r.relation == ("kid", "kids")
    assert S.classify("our best friend", "our best friend moved").relation[0] == "friend"
    assert S.classify("my family", "my family came over").relation[0] == "family"
    for subject, quote in (("my car", "my car broke down"), ("my passion for music", "my passion for music grew"),
                           ("her kids", "her kids love the beach"), ("your kids", "your kids are sweet"),
                           ("my kids", "the kids love the beach")):         # not in the quote
        assert S.classify(subject, quote) is None, subject


# --- the writes -----------------------------------------------------------------------------------

@needs_wordnet
async def test_we_with_no_one_named_is_the_speaker_flagged_as_a_group(db, gw, world):
    await people(world)
    _mid, stats = await extract(db, ON, world, "We went to the lake last week and it was lovely.",
                                LLM(claim("We went to the lake", "go to the lake", subject="we")), speaker="Nora")
    assert facts(db) == {("We went to the lake", "c-nora", True)}
    assert participants(db) == set() and stats.subjects["group"] == 1      # fails if mark_group_subject is removed
    assert {o for _s, o in world.edges("HAS_SUBJECT")} == {"c-nora"}


@needs_wordnet
async def test_we_with_a_named_partner_in_the_quote_links_the_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "Theo and I went to the lake last week.",
                  LLM(claim("Theo and I went to the lake", "go to the lake", subject="Theo and I")),
                  speaker="Nora", admit=(("c-theo", "Theo", "PERSON"),))
    assert facts(db) == {("Theo and I went to the lake", "c-nora", True)}
    assert participants(db) == {("Theo and I went to the lake", "c-theo")}


@needs_wordnet
async def test_we_with_a_name_only_outside_the_quote_gets_no_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "Theo called. We went to the lake last week.",
                  LLM(claim("We went to the lake", "go to the lake", subject="we")),
                  speaker="Nora", admit=(("c-theo", "Theo", "PERSON"),))
    assert facts(db) == {("We went to the lake", "c-nora", True)} and participants(db) == set()


@needs_wordnet
async def test_my_partner_and_i_links_the_relation_node_as_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "My partner and I went hiking on Sunday.",
                  LLM(claim("My partner and I went hiking", "go hiking", subject="My partner and I")), speaker="Nora")
    assert participants(db) == {("My partner and I went hiking", "rel:c-nora:partner")}
    assert ("rel:c-nora:partner", "c-nora") in relation_edges(db)


def relation_edges(db):
    rows = db._execute_and_collect(
        f"SELECT ?a ?b WHERE {{ ?r {NS}RELATION_OF> ?s . ?r {NS}concept_id> ?a . ?s {NS}concept_id> ?b }}")
    return {(str(r["a"]), str(r["b"])) for r in rows}


@needs_wordnet
async def test_my_kids_is_a_relation_concept_of_the_speaker(db, gw, world):
    await people(world)
    _m, stats = await extract(db, ON, world, "My kids love the beach so much.",
                              LLM(claim("My kids love the beach", "the beach", subject="My kids",
                                        predicate="prefers")), speaker="Nora")
    assert facts(db) == {("My kids love the beach", "rel:c-nora:kid", False)}
    assert relation_edges(db) == {("rel:c-nora:kid", "c-nora")} and stats.subjects["relation"] == 1
    rows = db._execute_and_collect(
        f"SELECT ?t ?l ?k WHERE {{ ?c {NS}concept_id> 'rel:c-nora:kid' ; {NS}text_raw> ?t ; {NS}relation_label> ?l ; "
        f"{NS}kind_scheme> ?k }}")
    assert [(str(r["t"]), str(r["l"]), str(r["k"])) for r in rows] == [("Nora's kids", "kid", "relation")]
    emb = db._execute_and_collect(f"SELECT ?e WHERE {{ ?c {NS}concept_id> 'rel:c-nora:kid' ; {NS}embedding> ?e }}")
    assert emb == [] and db.vector_store.get_vector(
        "https://campy.dev/id/Concept/rel%3Ac-nora%3Akid") is None


@needs_wordnet
async def test_one_relation_node_per_speaker_and_relation(db, gw, world):
    await people(world)
    await extract(db, ON, world, "My kids love the beach so much.",
                  LLM(claim("My kids love the beach", "the beach", subject="My kids", predicate="prefers")),
                  speaker="Nora")
    await extract(db, ON, world, "My kid started school this week.",
                  LLM(claim("My kid started school", "start school", subject="My kid")), speaker="Nora")
    await extract(db, ON, world, "My kids are learning to swim.",
                  LLM(claim("My kids are learning to swim", "learn to swim", subject="My kids", predicate="plans")),
                  speaker="Theo")
    assert relation_edges(db) == {("rel:c-nora:kid", "c-nora"), ("rel:c-theo:kid", "c-theo")}
    subj = {s for _q, s, _g in facts(db)}
    assert subj == {"rel:c-nora:kid", "rel:c-theo:kid"}


@needs_wordnet
async def test_her_kids_and_my_car_stay_as_before(db, gw, world):
    await people(world)
    await extract(db, ON, world, "Her kids love the beach so much.",
                  LLM(claim("Her kids love the beach", "the beach", subject="Her kids", predicate="prefers")),
                  speaker="Nora")
    await extract(db, ON, world, "My car broke down on the highway.",
                  LLM(claim("My car broke down", "break down", subject="My car")), speaker="Nora")
    assert {s for _q, s, _g in facts(db)} == {None} and relation_edges(db) == set()


@needs_wordnet
async def test_my_son_with_a_name_keeps_two_nodes(db, gw, world):
    await people(world)
    await world.concept("c-kai", "Kai")
    await extract(db, ON, world, "My son Kai won the race yesterday.",
                  LLM(claim("My son Kai won the race", "win the race", subject="My son Kai")),
                  speaker="Nora", admit=(("c-kai", "Kai", "PERSON"),))
    assert relation_edges(db) == {("rel:c-nora:son", "c-nora")}               # not merged with Kai (follow-up card)
    assert {s for _q, s, _g in facts(db)} == {"rel:c-nora:son"}


# --- the read ---------------------------------------------------------------------------------------

@needs_wordnet
async def test_relation_subject_reads_the_owners_node_only(db, gw, world):
    from campy.brain.hippocampus.graph.queries.query_hits import question_terms
    await people(world)
    await extract(db, ON, world, "My kids love the beach so much.",
                  LLM(claim("My kids love the beach", "the beach", subject="My kids", predicate="prefers")),
                  speaker="Nora")
    await extract(db, ON, world, "My kids are learning to swim.",
                  LLM(claim("My kids are learning to swim", "learn to swim", subject="My kids", predicate="plans")),
                  speaker="Theo")
    terms = [t for t, _ in question_terms("What do Nora's kids love?")]
    got = await gw.run("query_hits.relation_subject", terms=terms, sid="c-nora")
    assert [r["rid"] for r in got] == ["rel:c-nora:kid"]
    assert [r["rid"] for r in await gw.run("query_hits.relation_subject", terms=terms, sid="c-theo")] == ["rel:c-theo:kid"]
    assert await gw.run("query_hits.relation_subject", terms=["dog"], sid="c-nora") == []


# --- schema, shapes, and the writes they pin ---------------------------------------------------------

def test_schema_declares_relation_of_and_the_two_columns():
    assert any("REL TABLE IF NOT EXISTS RELATION_OF (FROM Concept TO Concept)" in t for t in REL_TABLES)
    assert ("Concept", "relation_label", "STRING") in SCHEMA_MIGRATIONS
    assert ("Observation", "group_subject", "BOOLEAN") in SCHEMA_MIGRATIONS


def _shapes():
    from pathlib import Path
    import campy.brain.hippocampus as h
    base = Path(h.__file__).parent / "shapes"
    g = ox.Store()
    for f in ("campy_shapes.ttl", "campy_vocab.ttl"):
        g.load(path=str(base / f), format=ox.RdfFormat.TURTLE)
    return g


def test_shapes_and_vocabulary_carry_relation_of_and_group_subject():
    g = _shapes()
    paths = {str(r[0].value) for r in g.query(
        "PREFIX sh:<http://www.w3.org/ns/shacl#> SELECT ?p WHERE { ?s sh:path ?p }")}
    assert "https://campy.dev/ns#RELATION_OF" in paths and "https://campy.dev/ns#group_subject" in paths
    props = {str(r[0].value) for r in g.query(
        "PREFIX owl:<http://www.w3.org/2002/07/owl#> SELECT ?p WHERE { { ?p a owl:ObjectProperty } "
        "UNION { ?p a owl:DatatypeProperty } }")}
    assert {"https://campy.dev/ns#RELATION_OF", "https://campy.dev/ns#group_subject"} <= props
