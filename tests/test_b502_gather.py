"""B502: `[retrieval] gather` (env CAMPY_RETRIEVAL_GATHER) -- cross-session
gather of fact-bearing user turns the conversation stage drops.

R61 (LongMemEval multi-session, 0/4 for every system): the missing evidence
turns were never candidates -- under the 0.30 similarity floor, one exact
query word short of the lexical rule ("kits" vs "kit"), or dropped by the
stage's "ends in ?" test although they state a fact.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.brainstem.config import apply_env_overrides
from campy.brain.hippocampus.graph.gateway import GraphGateway, light_stem, turn_states_something
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from tests.test_b463_successor_bridge import QUERY_EMB

DIM = 384
Q = "How many model kits have I worked on or bought?"


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b502.db"), REGISTRY)


async def _add(gw, n, text, day, sid, cos=0.0, role="user"):
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    when = f"2023-05-{day:02d}T10:00:00+00:00"
    await gw.run("quests.merge_session_git_locked", sid=sid, now=when)
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                 embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text), created_at=when)
    await gw.run("capture.set_message_source", message_id=f"m{n}", speaker="Ann", occurred_at=when)
    await gw.run("capture.link_message_sent_in_session", session_id=sid, message_id=f"m{n}")


async def _filler(gw, start=100, n=40):
    """Unrelated turns, so the query's words are rare in the store."""
    for i in range(start, start + n):
        await _add(gw, i, f"Plain filler number {i} about the weather.", 20, f"f{i}")


def _ids(rows):
    return [r["node_id"].rsplit("/", 1)[-1] for r in rows]


async def _gather(gw, q=Q, limit=8, per_session=2):
    return await gw.run("thalamus.bundle_gather", query_embedding=QUERY_EMB, query_text=q,
                        limit=limit, per_session=per_session)


def test_turn_states_something():
    assert turn_states_something("I just got a kit at a show. Any painting tips?")
    assert not turn_states_something("What's the best way to care for a blazer?")
    assert not turn_states_something("Can you help me with my kit?")      # one interrogative sentence
    assert not turn_states_something("Here are some tips. Use thin coats.")  # no speaker reference
    assert not turn_states_something("")


def test_light_stem_folds_forms_of_one_word():
    assert light_stem("kits") == light_stem("kit") == "kit"
    assert light_stem("camping") == light_stem("camp")
    assert light_stem("is") == "is" and light_stem("bus") == "bus"


@pytest.mark.asyncio
async def test_gather_finds_stemmed_and_fact_bearing_turns_across_sessions(gw):
    # no vector match at all (cos 0): only the stemmed lexical rule can find them
    await _add(gw, 1, "I recently finished a Tamiya Spitfire, my first model kit. Any painting tips?", 1, "s1")
    await _add(gw, 2, "I bought a model kit of a Tiger tank at a show.", 2, "s2")
    await _add(gw, 3, "I need new running shoes for the model railway club.", 3, "s3")  # one anchor only
    await _add(gw, 4, "What model kits are best for a beginner?", 4, "s4")             # states nothing
    await _add(gw, 5, "model kits model kits", 5, "s5", role="assistant")              # not a user turn
    await _filler(gw)
    rows = await _gather(gw)
    assert _ids(rows) == ["m1", "m2"]            # oldest first, one per session


@pytest.mark.asyncio
async def test_gather_caps_turns_per_session_and_total(gw):
    for i in range(1, 5):
        await _add(gw, i, f"I built my model kit number {i}.", i, "s1")
    await _add(gw, 5, "I bought a model kit for my nephew.", 6, "s2")
    await _filler(gw)
    assert len(await _gather(gw, per_session=2)) == 3     # two from s1, one from s2
    assert len(await _gather(gw, per_session=1)) == 2
    assert len(await _gather(gw, limit=1)) == 1
    assert await _gather(gw, limit=0) == []


@pytest.mark.asyncio
async def test_gather_skips_an_echo_of_the_question_and_empty_stores(gw):
    assert await _gather(gw) == []
    await _add(gw, 1, "I wonder: " + Q, 1, "s1")
    await _add(gw, 2, Q, 2, "s2")
    assert "m2" not in _ids(await _gather(gw))


class _Recorder:
    def __init__(self, extra=()):
        self.calls, self.extra = [], list(extra)

    async def run(self, name, params=None, /, **kw):
        self.calls.append(name)
        if name == "thalamus.bundle_gather":
            return self.extra
        return [{"text": "I own a kit", "node_id": "n0", "created_at": "2023-05-02T00:00:00+00:00",
                 "role": "user"}]


@pytest.fixture
def recorder(monkeypatch):
    from campy.brain.hippocampus.graph import embeddings

    rec = _Recorder([
        {"text": "I bought a model kit", "node_id": "n1", "created_at": "2023-05-01T00:00:00+00:00"},
        {"text": "I own a kit", "node_id": "n9", "created_at": "2023-05-03T00:00:00+00:00"},  # same text
        {"text": "I built a Spitfire", "node_id": "n2", "created_at": "2023-05-04T00:00:00+00:00"},
    ])
    monkeypatch.setattr(bundle_compiler, "get_gateway", lambda db: rec)
    monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)
    return rec


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", [{}, {"retrieval": {"gather": False}}])
async def test_stage_gather_is_off_by_default(recorder, cfg):
    section = await bundle_compiler._stage_conversation(None, "q", cfg)
    assert "thalamus.bundle_gather" not in recorder.calls
    assert len(section.content) == 1


@pytest.mark.asyncio
async def test_stage_gather_on_merges_new_turns_in_time_order(recorder):
    section = await bundle_compiler._stage_conversation(None, "q", {"retrieval": {"gather": True}})
    assert "thalamus.bundle_gather" in recorder.calls
    texts = [c["text"] for c in section.content]
    assert len(texts) == 3                                  # duplicate text n9 dropped
    assert texts[0].endswith("I bought a model kit") and texts[2].endswith("I built a Spitfire")


@pytest.mark.asyncio
async def test_stage_gather_failure_leaves_the_stage_as_it_was(recorder, monkeypatch):
    base = await bundle_compiler._stage_conversation(None, "q", {})
    orig = recorder.run

    async def run(name, params=None, /, **kw):
        if name == "thalamus.bundle_gather":
            raise RuntimeError("gather down")
        return await orig(name, params, **kw)

    monkeypatch.setattr(recorder, "run", run)
    got = await bundle_compiler._stage_conversation(None, "q", {"retrieval": {"gather": True}})
    assert [c["text"] for c in got.content] == [c["text"] for c in base.content]


def test_env_override():
    assert apply_env_overrides({}, {"CAMPY_RETRIEVAL_GATHER": "1"})["retrieval"]["gather"] is True
    assert apply_env_overrides({}, {"CAMPY_RETRIEVAL_GATHER": "0"})["retrieval"]["gather"] is False
    assert bundle_compiler._gather_enabled({}) is False
