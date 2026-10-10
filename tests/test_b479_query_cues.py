"""B479: the question's named speaker / explicit date boosts matching turns.

Parsing is pure (`parse_query_cues`); the boost is applied inside the
conversation stage only when `[retrieval] speaker_boost` / `time_boost` > 0
(off by default). Embeddings are hand-built so the tests don't depend on the
embedding model.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.brainstem.config import apply_env_overrides
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from campy.brain.thalamus.query_cues import QueryCues, parse_query_cues

# --- parse_query_cues ------------------------------------------------------------


def _spk(q, known=()):
    return dict(parse_query_cues(q, known).speakers)


@pytest.mark.parametrize("q,want", [
    ("What did Speaker 1 say about hiking?", {"speaker 1": 1.0}),
    ("what did speaker2 mention about work", {"speaker 2": 1.0}),
    ("Tell me about hiking", {}),
])
def test_speaker_n_forms(q, want):
    assert _spk(q) == want


def test_known_name_matches_whole_word_case_sensitive():
    assert _spk("Where has Melanie camped?", {"Melanie"}) == {"melanie": 1.0}
    assert _spk("Where has Melanie's brother camped?", {"Melanie"}) == {"melanie": 1.0}
    assert _spk("Will it rain?", {"Will"}) == {"will": 1.0}  # sentence start, still the name
    assert _spk("it will rain", {"Will"}) == {}
    assert _spk("Where did Melaniesque camp?", {"Melanie"}) == {}


def test_unknown_name_is_ignored():
    assert _spk("Where has Bob camped?", {"Melanie"}) == {}


def test_two_speakers_the_one_who_said_it_is_evidence():
    q = "Speaker 2 asks Speaker 1 what Speaker 1 said about the trip"
    assert _spk(q) == {"speaker 1": 1.0}
    assert _spk("What did Speaker 1 tell Speaker 2 about the trip?") == {"speaker 1": 1.0}
    assert _spk("According to Speaker 2, where did Speaker 1 go?") == {"speaker 2": 1.0}


def test_two_speakers_asker_is_subject_addressee_dropped():
    assert _spk("What did Speaker 2 ask Speaker 1 about the trip?") == {"speaker 2": 1.0}


def test_two_speakers_ambiguous_share_the_weight():
    assert _spk("Did Speaker 1 and Speaker 2 go to the lake?") == {"speaker 1": 0.5, "speaker 2": 0.5}


def test_only_addressees_are_used_lightly():
    assert _spk("Tell Speaker 1 about the lake") == {"speaker 1": 0.5}


@pytest.mark.parametrize("q,want", [
    ("What happened on 2023-05-08?", (("2023-05-08", "2023-05-09"),)),
    ("What happened on May 8, 2023?", (("2023-05-08", "2023-05-09"),)),
    ("What happened on 8th of May 2023?", (("2023-05-08", "2023-05-09"),)),
    ("What did she do in May 2023?", (("2023-05-01", "2023-06-01"),)),
    ("What did she do in December 2022?", (("2022-12-01", "2023-01-01"),)),
    ("What did she do in 2023?", (("2023-01-01", "2024-01-01"),)),
    ("What happened in May 2023 or June 2023?",
     (("2023-05-01", "2023-06-01"), ("2023-06-01", "2023-07-01"))),
])
def test_explicit_times(q, want):
    assert parse_query_cues(q).time_ranges == want


@pytest.mark.parametrize("q", [
    "What did she do last week?", "What did she do in May?", "What is 2023 times two?",
    "She has 2000 dollars", "What happened on February 31, 2023?", "",
])
def test_unresolvable_times_yield_nothing(q):
    assert parse_query_cues(q).time_ranges == ()


def test_none_is_falsy():
    assert not parse_query_cues("What colour is the sky?")
    assert parse_query_cues(None) == QueryCues()


# --- the stage -----------------------------------------------------------------------

DIM = 384
QUERY_EMB = [1.0] + [0.0] * (DIM - 1)
Q = "zzqx"

# (text, cosine, speaker, occurred_at)
TURNS = [
    ("alpha statement about widgets", 0.90, "Speaker 2", "2023-01-02T10:00:00+00:00"),
    ("bravo statement about gadgets", 0.80, "Speaker 2", "2023-01-03T10:00:00+00:00"),
    ("charlie statement about gizmos", 0.70, "Speaker 1", "2023-05-04T10:00:00+00:00"),
    ("delta statement about doodads", 0.60, "Speaker 1", "2023-05-05T10:00:00+00:00"),
]


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b479.db"), REGISTRY)


async def _store(gw):
    for n, (text, cos, who, when) in enumerate(TURNS, start=1):
        emb = [0.0] * DIM
        emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
        await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                     embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
                     created_at="2026-10-10T00:00:00+00:00")
        await gw.run("capture.set_message_source", message_id=f"m{n}", speaker=who, occurred_at=when)


async def _rank(gw, query, sb=0.0, tb=0.0, limit=2):
    if sb or tb:
        rows = await gw.run("thalamus.bundle_conversation_cued", query_embedding=QUERY_EMB,
                            query_text=query, limit=limit, order="rank",
                            speaker_boost=sb, time_boost=tb)
    else:
        rows = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                            query_text=query, limit=limit, order="rank")
    return [r["text"].split()[0] for r in rows]


@pytest.mark.asyncio
async def test_without_a_boost_the_cue_question_ranks_by_similarity(gw):
    await _store(gw)
    assert await _rank(gw, Q + " Speaker 1") == ["alpha", "bravo"]


@pytest.mark.asyncio
async def test_speaker_boost_lifts_the_named_speakers_turns_into_the_cut(gw):
    await _store(gw)
    assert await _rank(gw, Q + " what did Speaker 1 say", sb=1.0) == ["charlie", "delta"]


@pytest.mark.asyncio
async def test_a_small_speaker_boost_reorders_without_overriding_a_large_gap(gw):
    await _store(gw)
    # charlie 0.70 vs alpha 0.90 / bravo 0.80: a tiny boost cannot cross them
    assert await _rank(gw, Q + " what did Speaker 1 say", sb=0.01) == ["alpha", "bravo"]


@pytest.mark.asyncio
async def test_time_boost_lifts_turns_inside_the_named_month(gw):
    await _store(gw)
    assert await _rank(gw, Q + " what happened in May 2023", tb=1.0) == ["charlie", "delta"]


@pytest.mark.asyncio
async def test_a_question_naming_nothing_is_unchanged_by_the_boost(gw):
    await _store(gw)
    base = await _rank(gw, Q, limit=4)
    assert await _rank(gw, Q, sb=1.0, tb=1.0, limit=4) == base


@pytest.mark.asyncio
async def test_the_boost_never_filters(gw):
    await _store(gw)
    got = await _rank(gw, Q + " what did Speaker 1 say", sb=1.0, limit=4)
    assert set(got) == {"alpha", "bravo", "charlie", "delta"}


# --- the stage threads the settings --------------------------------------------------


class _Recorder:
    def __init__(self):
        self.name = self.params = None

    async def run(self, name, **params):
        self.name, self.params = name, params
        return [{"text": "x", "created_at": "2026-10-09T10:00:00+00:00", "node_id": "m1"}]


@pytest.fixture
def recorder(monkeypatch):
    from campy.brain.hippocampus.graph import embeddings

    rec = _Recorder()
    monkeypatch.setattr(bundle_compiler, "get_gateway", lambda db: rec)
    monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)
    return rec


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", [{}, {"retrieval": {"speaker_boost": 0.0, "time_boost": 0}}])
async def test_boosts_off_calls_the_original_query_unchanged(recorder, cfg):
    await bundle_compiler._stage_conversation(None, "q", cfg)
    assert recorder.name == "thalamus.bundle_conversation"
    assert set(recorder.params) == {"query_embedding", "query_text", "limit", "order"}


@pytest.mark.asyncio
async def test_boosts_on_calls_the_cued_query(recorder):
    await bundle_compiler._stage_conversation(
        None, "q", {"retrieval": {"speaker_boost": 0.5, "time_boost": 0.25}})
    assert recorder.name == "thalamus.bundle_conversation_cued"
    assert recorder.params["speaker_boost"] == 0.5 and recorder.params["time_boost"] == 0.25


def test_env_overrides_set_the_boosts_and_reject_junk():
    cfg = apply_env_overrides({}, {"CAMPY_RETRIEVAL_SPEAKER_BOOST": "0.5",
                                   "CAMPY_RETRIEVAL_TIME_BOOST": "0.25"})
    assert cfg["retrieval"]["speaker_boost"] == 0.5 and cfg["retrieval"]["time_boost"] == 0.25
    with pytest.raises(ValueError):
        apply_env_overrides({}, {"CAMPY_RETRIEVAL_SPEAKER_BOOST": "-1"})


@pytest.mark.asyncio
async def test_cued_query_with_zero_boosts_is_identical_to_the_original(gw):
    await _store(gw)
    q = Q + " what did Speaker 1 say in May 2023"
    for order in ("rank", "time"):
        a = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                         query_text=q, limit=4, order=order)
        b = await gw.run("thalamus.bundle_conversation_cued", query_embedding=QUERY_EMB,
                         query_text=q, limit=4, order=order, speaker_boost=0.0, time_boost=0.0)
        assert [dict(r) for r in a] == [dict(r) for r in b]
