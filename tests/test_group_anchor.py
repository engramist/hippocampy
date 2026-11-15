"""User ruling 2026-11-15: "we" facts the extractor already proposes are anchored on the speaker by rule, with the
extraction prompt untouched (flag `[observations] group_anchor`, default off). Real Oxigraph store and spaCy/WordNet
(skipped when absent), scripted model, made-up names.

Pins: the flag (default off, env, in no profile); with it ON the extraction messages are byte-identical to flag off;
flag-off writes unchanged; "we" -> HAS_SUBJECT the speaker + group_subject; a partner only as a PERSON in "X and I"
or after "with", never ORG / NORP, never the speaker, never a name merely mentioned; "my partner and I" makes no
relation Concept; "my kids" stays unanchored; the subject-anchored read returns the "we" fact for the speaker.
"""

from __future__ import annotations

import pytest

from campy.brain.brainstem.config import PROFILES, _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import subjects as S
from tests.b564_helpers import LLM, NS, Q, World, cfg, claim, extract, flag_off_signature

needs_wordnet = pytest.mark.skipif(not wn_mod.available(), reason="WordNet not installed")
ON = cfg(object_roles=True, group_anchor=True)
OFF = cfg(object_roles=True)


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "anchor.db")


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
    rows = db._execute_and_collect(
        f"SELECT ?q ?sid ?g WHERE {{ ?o a {NS}Observation> ; {NS}evidence_text> ?q . "
        f"OPTIONAL {{ ?o {NS}subject_id> ?sid }} OPTIONAL {{ ?o {NS}group_subject> ?g }} }}")
    return {(str(r["q"]), str(r["sid"]) if r.get("sid") else None, str(r.get("g")) in ("true", "True")) for r in rows}


def partners(db):
    rows = db._execute_and_collect(f"SELECT ?cid WHERE {{ ?o {NS}HAS_PARTICIPANT> ?c . ?c {NS}concept_id> ?cid }}")
    return {str(r["cid"]) for r in rows}


def relation_concepts(db):
    rows = db._execute_and_collect(f"SELECT ?cid WHERE {{ ?c {NS}concept_id> ?cid FILTER(STRSTARTS(?cid, 'rel:')) }}")
    return {str(r["cid"]) for r in rows}


def test_flag_default_off_env_on_not_in_a_profile(monkeypatch):
    assert _DEFAULT_CONFIG["observations"]["group_anchor"] is False
    monkeypatch.setenv("CAMPY_OBSERVATION_GROUP_ANCHOR", "1")
    assert apply_env_overrides({"observations": {}})["observations"]["group_anchor"] is True
    assert all("group_anchor" not in (p.get("observations") or {}) for p in PROFILES.values())


async def test_flag_on_the_extraction_messages_are_byte_identical(db, gw, world):
    await people(world)
    off, on = LLM(claim("We went to the lake", "go to the lake", subject="we")), \
        LLM(claim("We went to the lake", "go to the lake", subject="we"))
    await extract(db, OFF, world, "We went to the lake last week and it was lovely.", off, speaker="Nora")
    await extract(db, ON, world, "We went to the lake last week and it was lovely.", on, speaker="Nora")
    assert off.calls[0] == on.calls[0]


async def test_flag_off_writes_what_it_wrote_before(tmp_path):
    a, b = OxigraphClient(tmp_path / "a.db"), OxigraphClient(tmp_path / "b.db")
    assert await flag_off_signature(a, GraphGateway(a, REGISTRY)) == \
        await flag_off_signature(b, GraphGateway(b, REGISTRY), {"group_anchor": False})


@needs_wordnet
async def test_we_is_the_speaker_as_a_group_with_no_partner(db, gw, world):
    await people(world)
    _m, stats = await extract(db, ON, world, "We went to the lake last week and it was lovely.",
                              LLM(claim("We went to the lake", "go to the lake", subject="we")), speaker="Nora")
    assert facts(db) == {("We went to the lake", "c-nora", True)}
    assert {o for _s, o in world.edges("HAS_SUBJECT")} == {"c-nora"} and partners(db) == set()
    assert stats.subjects["group"] == 1


@needs_wordnet
async def test_theo_and_i_links_theo(db, gw, world):
    await people(world)
    await extract(db, ON, world, "Theo and I went to the lake last week.",
                  LLM(claim("Theo and I went to the lake", "go to the lake", subject="Theo and I")),
                  speaker="Nora", admit=(("c-theo", "Theo", "PERSON"),))
    assert facts(db) == {("Theo and I went to the lake", "c-nora", True)} and partners(db) == {"c-theo"}


@needs_wordnet
async def test_a_person_after_with_is_a_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "We went hiking with Theo on Sunday.",
                  LLM(claim("We went hiking with Theo", "go hiking", subject="we")),
                  speaker="Nora", admit=(("c-theo", "Theo", "PERSON"),))
    assert partners(db) == {"c-theo"}


@needs_wordnet
async def test_a_person_merely_mentioned_is_not_a_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "We talked about Theo all evening.",
                  LLM(claim("We talked about Theo", "talk about Theo", subject="we")),
                  speaker="Nora", admit=(("c-theo", "Theo", "PERSON"),))
    assert facts(db) == {("We talked about Theo", "c-nora", True)} and partners(db) == set()


@needs_wordnet
async def test_an_org_or_norp_in_the_quote_is_never_a_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "We went to the Lakeside Club with the Volunteers last week.",
                  LLM(claim("We went to the Lakeside Club with the Volunteers", "go to the club", subject="we")),
                  speaker="Nora", admit=(("c-club", "Lakeside Club", "ORG"), ("c-vol", "Volunteers", "NORP")))
    assert partners(db) == set()


@needs_wordnet
async def test_the_speaker_is_never_a_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "Nora and I went hiking on Sunday.",
                  LLM(claim("Nora and I went hiking", "go hiking", subject="Nora and I")),
                  speaker="Nora", admit=(("c-nora", "Nora", "PERSON"),))
    assert "c-nora" not in partners(db)


@needs_wordnet
async def test_my_partner_and_i_makes_no_relation_concept(db, gw, world):
    await people(world)
    await extract(db, ON, world, "My partner and I went hiking on Sunday.",
                  LLM(claim("My partner and I went hiking", "go hiking", subject="My partner and I")), speaker="Nora")
    assert facts(db) == {("My partner and I went hiking", "c-nora", True)}
    assert partners(db) == set() and relation_concepts(db) == set()


@needs_wordnet
async def test_my_kids_stays_unanchored(db, gw, world):
    await people(world)
    await extract(db, ON, world, "My kids love the beach so much.",
                  LLM(claim("My kids love the beach", "the beach", subject="My kids", predicate="prefers")),
                  speaker="Nora")
    assert facts(db) == {("My kids love the beach", None, False)} and relation_concepts(db) == set()


@needs_wordnet
async def test_an_unnamed_speaker_turn_is_unchanged(db, gw, world):
    await extract(db, ON, world, "We went to the lake last week and it was lovely.",
                  LLM(claim("We went to the lake", "go to the lake", subject="we")), speaker="")
    assert all(g is False for _q, _s, g in facts(db))


@needs_wordnet
async def test_the_subject_anchored_read_returns_the_we_fact_for_the_speaker(db, gw, world):
    await people(world)
    await world.concept("c-lake", "lake")
    await extract(db, ON, world, "We went to the lake last week and it was lovely.",
                  LLM(claim("We went to the lake", "lake", subject="we")), speaker="Nora")
    rows = await gw.run("query_hits.facts", sid="c-nora", kids=["c-lake"])
    assert [str(r["quote"]) for r in rows] == ["We went to the lake"]


@needs_wordnet
def test_coparticipant_names():
    assert S.coparticipant_names("Theo and I went hiking") == ["theo"]
    assert S.coparticipant_names("I went hiking with Theo") == ["theo"]
    assert S.coparticipant_names("We talked about Theo") == []
    assert S.coparticipant_names("We used to sing a song by Theo and Mila") == []


@needs_wordnet
async def test_an_addressed_name_is_not_a_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "Yeah Theo, we finally finished the garden yesterday.",
                  LLM(claim("Yeah Theo, we finally finished the garden", "finish the garden", subject="we")),
                  speaker="Nora", admit=(("c-theo", "Theo", "PERSON"),))
    assert partners(db) == set()


@needs_wordnet
async def test_a_name_only_mentioned_in_the_object_is_not_a_partner(db, gw, world):
    await people(world)
    await extract(db, ON, world, "We used to sing a song by Theo every summer.",
                  LLM(claim("We used to sing a song by Theo", "sing a song by Theo", subject="we")),
                  speaker="Nora", admit=(("c-theo", "Theo", "PERSON"),))
    assert partners(db) == set()
