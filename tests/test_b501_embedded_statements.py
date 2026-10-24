"""B501: `[retrieval] conversation_embedded_statements` -- a user turn that ends in
"?" but states something in the first person is evidence.

LongMemEval single-session-preference turns look like "I'm learning X with Y,
which I enjoy. Can you give me tips?": the stage dropped every turn ending in
"?" ("questions are not evidence"), so the statement never reached the bundle.
Off (default) is the existing stage, byte-identical.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway, is_question_only
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from tests.test_b463_successor_bridge import QUERY_EMB

DIM = 384


@pytest.mark.parametrize("text,embedded,expected", [
    ("What is the capital of France?", False, True),
    ("What is the capital of France?", True, True),
    ("I love dance.", True, False),
    ("I use Premiere Pro, which I enjoy. Can you give me tips?", False, True),
    ("I use Premiere Pro, which I enjoy. Can you give me tips?", True, False),
    ("Can you give me tips? I use Premiere Pro.", True, False),
    ("Besides great views, my favourite hotels have rooftop pools.\nDo any of these?", True, False),
    # no first-person statement: still a question
    ("The report is long. Can you summarise it?", True, True),
    # the first person only inside a question sentence: still a question
    ("Do I need a visa? Can you check?", True, True),
    ("", True, False),
])
def test_is_question_only(text, embedded, expected):
    assert is_question_only(text, embedded_statements=embedded) is expected


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b501.db"), REGISTRY)


async def _add(gw, n, text, when, cos=0.9):
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
                 created_at=when)
    await gw.run("capture.set_message_source", message_id=f"m{n}", speaker="Ann", occurred_at=when)


async def _store(gw):
    await _add(gw, 1, "I'm learning video editing with Adobe Premiere Pro, which I enjoy. "
                      "Can you give me tips on where to start?", "2023-05-01T10:00:00+00:00")
    await _add(gw, 2, "Can you give me tips on where to start?", "2023-05-01T10:01:00+00:00")
    await _add(gw, 3, "I picked up Premiere Pro last week.", "2023-05-01T10:02:00+00:00")


def _ids(rows):
    return {r["node_id"].rsplit("/", 1)[-1] for r in rows}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,extra", [
    ("thalamus.bundle_conversation", {}),
    ("thalamus.bundle_conversation_budget", {"token_budget": 0, "budget_mode": "fit_all"}),
    ("thalamus.bundle_conversation_windows", {"token_budget": 0, "budget_mode": "fit_all", "neighbours": 0, "neighbour_cap": 0}),
])
async def test_flag_admits_only_turns_with_a_first_person_statement(gw, name, extra):
    await _store(gw)
    base = dict(query_embedding=QUERY_EMB, query_text="zzqx", limit=10, order="time", **extra)
    off = await gw.run(name, **base)
    on = await gw.run(name, embedded_statements=True, **base)
    assert _ids(off) == {"m3"}           # default: the "?" turns are dropped
    assert _ids(on) == {"m1", "m3"}      # on: m1 states something; m2 is a bare question


@pytest.mark.asyncio
async def test_flag_off_is_byte_identical(gw):
    await _store(gw)
    base = dict(query_embedding=QUERY_EMB, query_text="zzqx", limit=10, order="time")
    assert [dict(r) for r in await gw.run("thalamus.bundle_conversation", **base)] == \
           [dict(r) for r in await gw.run("thalamus.bundle_conversation", embedded_statements=False, **base)]


@pytest.mark.asyncio
async def test_all_turns_path_honours_the_flag(gw):
    await _store(gw)
    base = dict(query_embedding=QUERY_EMB, query_text="zzqx", limit=10, order="time",
                token_budget=3500, budget_mode="fit_all")
    assert _ids(await gw.run("thalamus.bundle_conversation_budget", **base)) == {"m3"}
    assert _ids(await gw.run("thalamus.bundle_conversation_budget", embedded_statements=True, **base)) \
        == {"m1", "m3"}


class _Recorder:
    name = None
    params = None

    async def run(self, name, **params):
        self.name, self.params = name, params
        return []


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(bundle_compiler, "get_gateway", lambda db: rec)
    from campy.brain.hippocampus.graph import embeddings
    monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)
    return rec


@pytest.mark.asyncio
@pytest.mark.parametrize("retrieval", [
    {}, {"conversation_neighbours": 0, "conversation_token_budget": 0},
    {"conversation_neighbours": 0},
])
async def test_stage_passes_the_flag_only_when_on(recorder, retrieval):
    await bundle_compiler._stage_conversation(None, "q", {"retrieval": retrieval})
    assert "embedded_statements" not in recorder.params
    await bundle_compiler._stage_conversation(
        None, "q", {"retrieval": {**retrieval, "conversation_embedded_statements": True}})
    assert recorder.params["embedded_statements"] is True


def test_env_override_and_default():
    from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
    assert _DEFAULT_CONFIG["retrieval"]["conversation_embedded_statements"] is True  # B514
    cfg = apply_env_overrides({}, {"CAMPY_RETRIEVAL_CONVERSATION_EMBEDDED_STATEMENTS": "0"})
    assert cfg["retrieval"]["conversation_embedded_statements"] is False
