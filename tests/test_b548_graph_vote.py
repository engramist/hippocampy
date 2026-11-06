"""B548: the graph votes in fusion (flag `[retrieval] graph_vote`, default off).

Pins:
- the flag: default off, env CAMPY_GRAPH_VOTE, a member of the principled profile, in the shipped template;
- the NamedQuery `thalamus.graph_vote_turns` on a fixture store: the subject's live evidence turns, ranked kind,
  entity, support, newest; strict when a kind is asked (the bound `need_kind` filters in the query, not in Python);
  other subjects, archived and
  superseded Observations stay out; a kind is matched through BROADER;
- the parameters from the B547 analysis: no vote for a tie, no subject, or nothing asked;
- fusion: a graph turn that is neither a vector hit nor passes the lexical-only gate is selected; no `graph_turns`
  is the old behaviour; the top GRAPH_VOTE_TOP only;
- the stage: flag off or `question_analysis` off means no vote.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, PROFILES, apply_env_overrides
from campy.brain.hippocampus.graph import gateway as gateway_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import graph_vote as gv

DIM = 384
QUERY_EMB = [1.0] + [0.0] * (DIM - 1)
NS = "https://campy.dev/ns#"
ID = "https://campy.dev/id/"


def msg(i):
    return f"{ID}Message/{i}"


# --- the flag -------------------------------------------------------------------------

def test_flag_default_off_env_and_profile():
    assert _DEFAULT_CONFIG["retrieval"]["graph_vote"] is False
    assert PROFILES["principled"]["retrieval"]["graph_vote"] is True
    assert gv.graph_vote_enabled({}) is False
    assert gv.graph_vote_enabled(apply_env_overrides({"retrieval": {}}, {"CAMPY_GRAPH_VOTE": "1"})) is True


def test_template_names_the_flag():
    from pathlib import Path
    import campy
    text = (Path(campy.__file__).parent / "data" / "config" / "campy.toml").read_text()
    assert "CAMPY_GRAPH_VOTE" in text and "graph_vote" in text


# --- the query ------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b548.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def concept(cid, label, ner=None, kind=False, instance_of=(), broader=()):
    t = f'<{ID}Concept/{cid}> a <{NS}Concept> ; <{NS}concept_id> "{cid}" ; <{NS}text_raw> "{label}" .\n'
    if ner:
        t += f'<{ID}Concept/{cid}> <{NS}ner_label> "{ner}" .\n'
    if kind:
        t += f'<{ID}Concept/{cid}> <{NS}kind_scheme> "kind" .\n'
    for k in instance_of:
        t += f'<{ID}Concept/{cid}> <{NS}INSTANCE_OF> <{ID}Concept/{k}> .\n'
    for k in broader:
        t += f'<{ID}Concept/{cid}> <{NS}BROADER> <{ID}Concept/{k}> .\n'
    return t


def observation(oid, subject, mid, day, obj=None, about=(), archived=False, superseded_by=None):
    o = f"<{ID}Observation/{oid}>"
    t = (f'{o} a <{NS}Observation> ; <{NS}observation_id> "{oid}" ; <{NS}HAS_SUBJECT> <{ID}Concept/{subject}> ;\n'
         f'  <{NS}EVIDENCED_BY> <{msg(mid)}> .\n')
    t += f'<{msg(mid)}> a <{NS}Message> ; <{NS}message_id> "{mid}" ; <{NS}occurred_at> "2023-05-{day:02d}T10:00:00+00:00" .\n'
    if obj:
        t += f"{o} <{NS}HAS_OBJECT> <{ID}Concept/{obj}> .\n"
    for a in about:
        t += f"{o} <{NS}OBSERVATION_ABOUT> <{ID}Concept/{a}> .\n"
    if archived:
        t += f"{o} <{NS}archived> true .\n"
    if superseded_by:
        t += f"{o} <{NS}DEPRECATED_BY> <{ID}Observation/{superseded_by}> .\n"
    return t


@pytest.fixture
def store(db):
    triples = "".join([
        concept("sam", "Sam", ner="PERSON"), concept("kim", "Kim", ner="PERSON"),
        concept("k-book", "book", kind=True), concept("k-novel", "novel", kind=True, broader=["k-book"]),
        concept("k-city", "city", kind=True),
        concept("dune", "Dune", ner="WORK_OF_ART", instance_of=["k-novel"]),
        concept("paris", "Paris", ner="GPE", instance_of=["k-city"]),
        concept("rome", "Rome", instance_of=["k-city"]),            # typed by INSTANCE_OF only
        concept("stuff", "stuff"),                                   # no tagger label, no kind: not an entity
        observation("o1", "sam", "m1", 1, obj="dune"),               # kind fact (novel under book)
        observation("o2", "sam", "m2", 5, about=["paris"]),          # entity facts: m2 carries two, m3 one
        observation("o2b", "sam", "m2", 5, about=["paris"]),
        observation("o3", "sam", "m3", 9, about=["paris"]),
        observation("o4", "sam", "m4", 3, about=["stuff"]),          # names a Concept the graph does not type
        observation("o5", "kim", "m5", 4, obj="dune", about=["paris"]),   # another subject
        observation("o6", "sam", "m6", 6, obj="dune", archived=True),
        observation("o7", "sam", "m7", 7, about=["paris"], superseded_by="o3"),
        observation("o8", "sam", "m8", 2, about=["rome"]),
    ])
    db.store.update(f"INSERT DATA {{ {triples} }}")


async def vote(gw, kinds=(), ents=(), sid="sam"):
    rows = await gw.run("thalamus.graph_vote_turns", sids=[sid], kind_ids=list(kinds), ent_ids=list(ents),
                        need_kind=1 if kinds else 0)
    return [str(r["m"]).rsplit("/", 1)[-1] for r in rows]


@pytest.mark.asyncio
async def test_kind_asked_returns_only_kind_matches_even_when_an_entity_is_named(gw, store):
    # strict: the filter is the bound need_kind inside the query; Paris turns would match the entity branch
    assert await vote(gw, kinds=["k-book"], ents=["paris"]) == ["m1"]


@pytest.mark.asyncio
async def test_the_kind_is_matched_through_broader_and_a_narrower_kind_does_not_match_a_wider_ask(gw, store):
    assert await vote(gw, kinds=["k-novel"]) == ["m1"]
    assert await vote(gw, kinds=["k-city"]) == []                    # Dune is not a city; Paris/Rome are objects of no fact
    # a kind that nothing is under
    assert await vote(gw, kinds=["k-nothing"]) == []


@pytest.mark.asyncio
async def test_entity_only_ranks_by_support_then_newest_and_excludes_dead_and_other_subjects(gw, store):
    got = await vote(gw, ents=["paris"])
    assert got == ["m2", "m3"]          # m2 evidences two facts (support), then m3; m5 is Kim's, m6/m7 are dead
    assert "m5" not in got and "m6" not in got and "m7" not in got


@pytest.mark.asyncio
async def test_any_named_concept_other_than_the_subject_counts_as_an_entity(gw, store):
    # the restriction to tagger-labelled or kind-typed Concepts was measured and lost (backlog/B548.md)
    assert await vote(gw, ents=["rome"]) == ["m8"]
    assert await vote(gw, ents=["stuff"]) == ["m4"]
    assert await vote(gw, ents=["paris", "stuff"]) == ["m2", "m3", "m4"]


@pytest.mark.asyncio
async def test_nothing_asked_and_unknown_subject_return_nothing_and_the_subject_is_not_an_entity(gw, store):
    assert await vote(gw) == []
    assert await vote(gw, ents=["paris"], sid="nobody") == []
    assert await vote(gw, ents=["sam"]) == []                        # the subject never votes for itself
    assert await vote(gw, ents=["paris"], sid="kim") == ["m5"]


@pytest.mark.asyncio
async def test_without_need_kind_the_union_ranks_kind_before_entity(gw, store):
    rows = await gw.run("thalamus.graph_vote_turns", sids=["sam"], kind_ids=["k-book"], ent_ids=["paris"], need_kind=0)
    assert [str(r["m"]).rsplit("/", 1)[-1] for r in rows] == ["m1", "m2", "m3"]


# --- the parameters from the analysis -----------------------------------------------------

def analysis(**kw):
    base = dict(subject_id="sam", anchor_ids=("sam",), tie=False, kind_id=None,
                concepts=({"id": "sam", "role": "person"}, {"id": "paris", "role": "entity"},
                          {"id": "k-book", "role": "kind"}))
    base.update(kw)
    return SimpleNamespace(**base)


def test_parameters_name_the_subject_the_kind_and_the_non_person_concepts():
    p = gv.vote_parameters(analysis())
    assert p == {"sids": ["sam"], "kind_ids": [], "ent_ids": ["paris", "k-book"], "need_kind": 0}
    p = gv.vote_parameters(analysis(kind_id="k-book"))
    assert p == {"sids": ["sam"], "kind_ids": ["k-book"], "ent_ids": ["paris"], "need_kind": 1}


def test_no_parameters_for_no_analysis_no_subject_or_a_tie():
    assert gv.vote_parameters(None) is None
    assert gv.vote_parameters(analysis(subject_id=None)) is None
    assert gv.vote_parameters(analysis(tie=True, anchor_ids=("sam", "kim"))) is None


@pytest.mark.asyncio
async def test_the_stage_helper_votes_only_with_the_flag_the_analysis_and_something_asked(gw, store):
    on = {"retrieval": {"graph_vote": True}}
    got = await gv.graph_vote_turns(gw, on, analysis(kind_id="k-book"))
    assert [u.rsplit("/", 1)[-1] for u in got] == ["m1"]
    assert await gv.graph_vote_turns(gw, {"retrieval": {"graph_vote": False}}, analysis(kind_id="k-book")) == []
    assert await gv.graph_vote_turns(gw, {"retrieval": {}}, analysis(kind_id="k-book")) == []
    # graph_vote on, question_analysis off: the stage has no analysis, so there is no vote
    assert await gv.graph_vote_turns(gw, on, None) == []
    assert await gv.graph_vote_turns(gw, on, analysis(tie=True)) == []
    assert await gv.graph_vote_turns(gw, on, analysis(concepts=({"id": "sam", "role": "person"},))) == []


@pytest.mark.asyncio
async def test_compile_bundle_passes_no_analysis_when_question_analysis_is_off(monkeypatch, tmp_path):
    """graph_vote on with question_analysis off: `_stage_conversation` gets analysis=None and calls the
    two-list path (no `graph_turns` param)."""
    from campy.brain.thalamus import bundle_compiler as bc
    seen = {}

    async def fake_stage(db, query, config, analysis=None):
        seen["analysis"] = analysis
        return None

    monkeypatch.setattr(bc, "_stage_conversation", fake_stage)
    cfg = {"retrieval": {"graph_vote": True, "question_analysis": False}, "observations": {}}
    await bc.compile_bundle("What books has Sam read?", OxigraphClient(tmp_path / "x.db"), cfg)
    assert seen["analysis"] is None


# --- fusion ---------------------------------------------------------------------------

@pytest.fixture
def conv(tmp_path):
    g = GraphGateway(OxigraphClient(tmp_path / "conv.db"), REGISTRY)
    return g


async def add(g, n, text, cos):
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    await g.run("capture.create_message", message_id=f"c{n}", text_raw=text, embedding=emb,
                embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
                created_at=f"2026-10-02T10:{n:02d}:00+00:00")


async def seed_conversation(g, n_noise=10):
    await add(g, 1, "I read Dune last month and loved it.", 0.60)           # a vector hit
    await add(g, 2, "Quarterly zebra inventory is done.", 0.05)              # off topic, no shared word, below the floor
    await add(g, 3, "The orchard produced forty crates.", 0.04)
    for i in range(n_noise):
        await add(g, 4 + i, f"Filler statement number {i} about weather.", 0.50 - 0.01 * i)


def uri(n):
    return f"{ID}Message/c{n}"


async def conv_rows(g, **extra):
    rows = await g.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB, query_text="what did Sam read",
                       limit=6, order="rank", **extra)
    return [str(r["node_id"]) for r in rows]


@pytest.mark.asyncio
async def test_without_graph_turns_the_selection_is_the_old_one(conv):
    await seed_conversation(conv)
    base = await conv_rows(conv)
    assert uri(2) not in base and uri(3) not in base
    assert await conv_rows(conv, graph_turns=[]) == base
    assert await conv_rows(conv, graph_turns=None) == base


@pytest.mark.asyncio
async def test_a_graph_turn_enters_though_neither_vector_nor_lexical_would_pick_it(conv):
    await seed_conversation(conv)
    got = await conv_rows(conv, graph_turns=[uri(2)])
    assert uri(2) in got                                              # skips the lexical-only gate
    assert len(got) == 6                                              # the cut is still the limit


@pytest.mark.asyncio
async def test_only_the_top_of_the_graph_list_votes(conv):
    await seed_conversation(conv)
    top = gateway_mod.GRAPH_VOTE_TOP
    assert top == 6
    assert uri(3) in await conv_rows(conv, graph_turns=[uri(3)])
    # the same turn one place past the cut gets no vote
    beyond = [uri(4 + i) for i in range(top)] + [uri(3)]
    assert uri(3) not in await conv_rows(conv, graph_turns=beyond)


@pytest.mark.asyncio
async def test_a_non_message_uri_in_the_list_is_ignored(conv):
    await seed_conversation(conv)
    base = await conv_rows(conv)
    assert await conv_rows(conv, graph_turns=[f"{ID}Concept/c2", "junk"]) == base
