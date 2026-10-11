"""B481: three opt-in conversation-stage retrieval fixes (defaults unchanged).

question_filter="all_questions", fts_query="content", fts_fusion="extra_only".
"""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import (
    GraphGateway, content_fts_query, is_question_turn)
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from tests.test_b463_successor_bridge import QUERY_EMB

DIM = 384


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b481.db"), REGISTRY)


async def _add(gw, n, text, cos=0.8, created="2023-05-01T10:00:00+00:00"):
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
                 created_at=created)


async def _ids(gw, q="flamingo", name="thalamus.bundle_conversation_v2", **kw):
    extra = {"question_filter": "trailing", "fts_query": "full", "fts_fusion": "rrf"}
    extra.update(kw)
    rows = await gw.run(name, query_embedding=QUERY_EMB, query_text=q, limit=6, order="rank", **extra)
    return [r["node_id"].rsplit("/", 1)[-1] for r in rows]


# --- A: question filter -------------------------------------------------------

@pytest.mark.parametrize("text,trailing,all_q", [
    ("She lives in Texas with me. What about you?", True, False),
    ("Where do you live?", True, True),
    ("Where do you live? And what do you do?", True, True),
    ("Where? Texas.", False, False),
    ("I moved to Texas.", False, False),
    ('He asked "why?" and I said no.', False, False),
])
def test_is_question_turn(text, trailing, all_q):
    assert is_question_turn(text, "trailing") is trailing
    assert is_question_turn(text, "all_questions") is all_q


@pytest.mark.asyncio
async def test_all_questions_keeps_fact_then_question_and_drops_pure_questions(gw):
    await _add(gw, 1, "She lives in Texas with me. What about you?", 0.9)
    await _add(gw, 2, "Where does she live? Do you know?", 0.85)
    assert await _ids(gw) == []
    assert await _ids(gw, question_filter="all_questions") == ["m1"]


@pytest.mark.asyncio
async def test_all_questions_still_drops_an_exact_question_echo(gw):
    q = "What does the flamingo eat?"
    await _add(gw, 1, q, 0.99)
    await _add(gw, 2, "The flamingo eats shrimp.", 0.8)
    assert await _ids(gw, q=q, question_filter="all_questions") == ["m2"]


# --- B: content-only FTS query ------------------------------------------------

def test_content_query_strips_stopwords_and_framing():
    assert content_fts_query("What did you say earlier about the time I moved to Austin?").split() == [
        "moved", "Austin?"]
    assert content_fts_query("Do you remember what I told you?") == ""
    assert content_fts_query("Where doesn't she work?").split() == ["work?"]
    assert content_fts_query("my memgym_mysterypath_dbg1 thing").split() == ["memgym_mysterypath_dbg1"]


@pytest.mark.asyncio
async def test_content_query_does_not_let_generic_words_pull_in_turns(gw):
    await _add(gw, 1, "You said that earlier about my time", 0.05)  # generic words only
    await _add(gw, 2, "The flamingo lives in a lagoon", 0.8)
    q = "What did you say earlier about the time with the flamingo"
    assert set(await _ids(gw, q=q)) == {"m1", "m2"}
    assert await _ids(gw, q=q, fts_query="content") == ["m2"]


@pytest.mark.asyncio
async def test_content_query_with_no_content_words_skips_fts(gw):
    await _add(gw, 1, "You said that earlier", 0.05)
    assert await _ids(gw, q="what did you say earlier", fts_query="content") == []


# --- C: extra-only fusion -----------------------------------------------------

@pytest.mark.asyncio
async def test_extra_only_never_demotes_a_vector_hit(gw):
    await _add(gw, 1, "An ordinary vector hit", 0.9)
    await _add(gw, 2, "A second vector hit", 0.8)
    await _add(gw, 3, "A third vector hit about a flamingo", 0.7)
    await _add(gw, 4, "Flamingo only reachable lexically", 0.05)
    assert (await _ids(gw))[0] == "m3"                      # RRF: the FTS boost reorders
    got = await _ids(gw, fts_fusion="extra_only")
    assert got == ["m1", "m2", "m3", "m4"]                  # vector order kept, FTS-only last


@pytest.mark.asyncio
async def test_defaults_match_the_v1_query(gw):
    await _add(gw, 1, "An ordinary vector hit", 0.9)
    await _add(gw, 2, "A third vector hit about a flamingo", 0.7)
    await _add(gw, 3, "Is the flamingo pink?", 0.8)
    v1 = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                      query_text="flamingo", limit=6, order="rank")
    assert [dict(r) for r in v1] == [dict(r) for r in await gw.run(
        "thalamus.bundle_conversation_v2", query_embedding=QUERY_EMB, query_text="flamingo",
        limit=6, order="rank", question_filter="trailing", fts_query="full", fts_fusion="rrf")]


@pytest.mark.asyncio
async def test_unknown_value_falls_back_to_default(gw):
    await _add(gw, 1, "She lives in Texas with me. What about you?", 0.9)
    assert await _ids(gw, question_filter="bogus") == []
