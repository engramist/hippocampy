"""B477: optional cross-encoder rerank of the conversation stage's candidates.

LoCoMo-10 evidence turns have median fused rank ~28 while the stage keeps 6
(plan M2.1). With `[retrieval] reranker` set, the kept candidates are re-ordered
by a cross-encoder before the top-`limit` cut. The model is replaced by a fake
scorer in every test but the (skipped-when-unavailable) latency test, so the
suite does not depend on a download. Embeddings are hand-built to chosen
cosines, as in the B474 tests.
"""

from __future__ import annotations

import logging
import math
import os
import time

import pytest

from campy.brain.hippocampus.graph import reranker as reranker_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from tests.test_b463_successor_bridge import (
    DB_Q, PG14_ACK, PG16_USER, QUERY_EMB, _db_store)

DIM = 384
Q = "zzqx"  # shares no word with the turns: fused ranking is the vector plane alone
MODEL = "fake/cross-encoder"
RERANKED = "thalamus.bundle_conversation_reranked"

# (text, cosine to the query, created_at, speaker). Fused (vector) order is
# bravo, charlie, alpha, delta; created_at order is alpha, bravo, charlie, delta.
TURNS = [
    ("alpha statement about widgets", 0.50, "2026-10-01T10:00:00+00:00", None),
    ("bravo statement about gadgets", 0.90, "2026-10-02T10:00:00+00:00", None),
    ("charlie statement about gizmos", 0.70, "2026-10-03T10:00:00+00:00", None),
    ("delta statement about doodads", 0.40, "2026-10-04T10:00:00+00:00", None),
]
FUSED = ["bravo", "charlie", "alpha", "delta"]


@pytest.fixture(autouse=True)
def _fresh_reranker():
    reranker_mod.reset()
    yield
    reranker_mod.reset()


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b477.db"), REGISTRY)


def _fake(monkeypatch, scores_by_word, seen=None):
    """A cross-encoder that scores a text by the first word in `scores_by_word` it contains."""
    def load(model_name):
        def fn(query, texts):
            if seen is not None:
                seen.append((query, list(texts)))
            return [next((v for w, v in scores_by_word.items() if w in t), 0.0) for t in texts]
        return fn
    monkeypatch.setattr(reranker_mod, "_load", load)


async def _store(gw, turns=TURNS):
    for n, (text, cos, created, speaker) in enumerate(turns, start=1):
        emb = [0.0] * DIM
        emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
        await gw.run(
            "capture.create_message",
            message_id=f"m{n}", text_raw=text, embedding=emb, embedding_model="m",
            embedding_dim=DIM, role="user", byte_end=len(text), created_at=created,
        )
        if speaker:
            await gw.run("capture.set_message_source", message_id=f"m{n}", speaker=speaker,
                         occurred_at=None)


async def _words(gw, order="time", limit=6, query=Q, model=MODEL, n=50, plain=False):
    if plain:
        rows = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                            query_text=query, limit=limit, order=order)
    else:
        rows = await gw.run(RERANKED, query_embedding=QUERY_EMB, query_text=query, limit=limit,
                            order=order, reranker=model, reranker_candidates=n)
    return [r["text"].split()[0] for r in rows]


@pytest.mark.asyncio
async def test_rerank_changes_which_turns_survive_the_cut(gw, monkeypatch):
    await _store(gw)
    # a scorer that reverses the fused order: the worst fused turns are the best
    _fake(monkeypatch, {"delta": 4, "alpha": 3, "charlie": 2, "bravo": 1})
    assert set(await _words(gw, limit=2, plain=True)) == {"bravo", "charlie"}
    assert set(await _words(gw, limit=2)) == {"delta", "alpha"}


@pytest.mark.asyncio
async def test_rank_order_is_the_reranker_order_and_time_order_sorts_after_the_cut(gw, monkeypatch):
    await _store(gw)
    _fake(monkeypatch, {"delta": 4, "alpha": 3, "charlie": 2, "bravo": 1})
    assert await _words(gw, order="rank") == ["delta", "alpha", "charlie", "bravo"]
    assert await _words(gw, order="time", limit=3) == ["alpha", "charlie", "delta"]


@pytest.mark.asyncio
async def test_only_the_top_n_fused_candidates_are_reranked(gw, monkeypatch):
    await _store(gw)
    seen = []
    _fake(monkeypatch, {"delta": 9, "alpha": 3, "charlie": 2, "bravo": 1}, seen)
    # window of 2 = bravo, charlie: delta (fused 4th) is never scored, so it
    # cannot jump the queue even though the fake would love it.
    assert await _words(gw, order="rank", n=2) == ["charlie", "bravo", "alpha", "delta"]
    assert len(seen) == 1 and len(seen[0][1]) == 2


@pytest.mark.asyncio
async def test_time_mode_with_no_cut_does_not_pay_for_scoring(gw, monkeypatch):
    await _store(gw)
    seen = []
    _fake(monkeypatch, {}, seen)
    await _words(gw, order="time", limit=6)  # 4 candidates <= limit, order irrelevant
    assert seen == []
    await _words(gw, order="rank", limit=6)  # rank order does depend on scores
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_turns_are_scored_with_their_speaker(gw, monkeypatch):
    await _store(gw, [
        ("alpha statement about widgets", 0.50, "2026-10-01T10:00:00+00:00", "Speaker 1"),
        ("bravo statement about gadgets", 0.90, "2026-10-02T10:00:00+00:00", None),
    ])
    seen = []
    _fake(monkeypatch, {}, seen)
    await _words(gw, order="rank", query="zzqx what did Speaker 1 say")
    texts = seen[0][1]
    assert "Speaker 1: alpha statement about widgets" in texts
    assert "bravo statement about gadgets" in texts  # no speaker -> bare text


@pytest.mark.asyncio
async def test_unavailable_model_keeps_the_fused_order_and_logs_once(gw, monkeypatch, caplog):
    await _store(gw)

    def boom(model_name):
        raise OSError("no network")
    monkeypatch.setattr(reranker_mod, "_load", boom)
    plain = await _words(gw, order="rank", plain=True)
    with caplog.at_level(logging.WARNING, logger=reranker_mod._logger.name):
        first = await _words(gw, order="rank")
        second = await _words(gw, order="rank", limit=2)
    assert first == plain == FUSED
    assert second == FUSED[:2]
    assert sum("reranker" in r.message and "unavailable" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_a_scorer_that_fails_while_scoring_also_falls_back(gw, monkeypatch, caplog):
    await _store(gw)

    def load(model_name):
        def fn(query, texts):
            raise RuntimeError("onnx exploded")
        return fn
    monkeypatch.setattr(reranker_mod, "_load", load)
    with caplog.at_level(logging.WARNING, logger=reranker_mod._logger.name):
        assert await _words(gw, order="rank") == FUSED
    assert any("onnx exploded" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_reranker_off_is_the_same_query_and_same_rows(gw, monkeypatch):
    await _store(gw)
    _fake(monkeypatch, {"delta": 4})
    off = await gw.run(RERANKED, query_embedding=QUERY_EMB, query_text=Q, limit=6,
                       order="rank", reranker="none", reranker_candidates=50)
    plain = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                         query_text=Q, limit=6, order="rank")
    assert [dict(r) for r in off] == [dict(r) for r in plain]


@pytest.mark.asyncio
async def test_a_successor_statement_keeps_its_leading_turns_cross_encoder_score(gw, monkeypatch):
    # B463: PG16_USER shares no word with the question; it is found through the
    # assistant turn naming PostgreSQL 14. A cross-encoder that rates the
    # leading turn high and everything else low must not demote it.
    await _db_store(gw)
    _fake(monkeypatch, {"Noted. Primary database": 8.0})
    rows = await gw.run(RERANKED, query_embedding=QUERY_EMB, query_text=DB_Q, limit=1,
                        order="rank", reranker=MODEL, reranker_candidates=50)
    assert [r["text"] for r in rows] == [PG16_USER]
    assert PG14_ACK not in [r["text"] for r in rows]  # leaders are scored, never returned


# -- the compiler stage -----------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.name, self.params = None, None

    async def run(self, name, **params):
        self.name, self.params = name, params
        return [{"text": "x", "created_at": "2026-10-09T10:00:00+00:00", "node_id": "m1"}]


@pytest.fixture
def recorder(monkeypatch):
    from campy.brain.hippocampus.graph import embeddings

    rec = _Recorder()
    monkeypatch.setattr(bundle_compiler, "get_gateway", lambda db: rec)
    monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)
    monkeypatch.delenv("CAMPY_RETRIEVAL_RERANKER", raising=False)
    return rec


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", [{}, {"retrieval": {"reranker": "none"}}, {"retrieval": {"reranker": ""}},
                                 {"retrieval": {"reranker": "None"}}])
async def test_stage_without_a_reranker_runs_the_unchanged_query(recorder, cfg):
    await bundle_compiler._stage_conversation(None, "q", cfg)
    assert recorder.name == "thalamus.bundle_conversation"
    assert set(recorder.params) == {"query_embedding", "query_text", "limit", "order"}


@pytest.mark.asyncio
async def test_stage_with_a_reranker_runs_the_reranked_query(recorder):
    cfg = {"retrieval": {"reranker": MODEL, "reranker_candidates": 30, "conversation_order": "rank"}}
    section = await bundle_compiler._stage_conversation(None, "q", cfg)
    assert recorder.name == RERANKED
    assert recorder.params["reranker"] == MODEL and recorder.params["reranker_candidates"] == 30
    assert recorder.params["order"] == "rank" and section.order == "rank"
    await bundle_compiler._stage_conversation(None, "q", {"retrieval": {"reranker": MODEL}})
    assert recorder.params["reranker_candidates"] == 50


@pytest.mark.asyncio
async def test_env_var_turns_the_reranker_on_and_off(recorder, monkeypatch):
    monkeypatch.setenv("CAMPY_RETRIEVAL_RERANKER", MODEL)
    await bundle_compiler._stage_conversation(None, "q", {})
    assert recorder.name == RERANKED and recorder.params["reranker"] == MODEL


def test_registry_declares_the_reranked_query_without_touching_the_original():
    assert REGISTRY.get("thalamus.bundle_conversation").params == (
        "query_embedding", "query_text", "limit", "order")
    assert set(REGISTRY.get(RERANKED).params) == {
        "query_embedding", "query_text", "limit", "order", "reranker", "reranker_candidates"}


# -- the real model (skipped when it is not cached; CAMPY_TEST_REAL_RERANKER=1 allows download) --

REAL_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


@pytest.fixture(scope="module")
def real_scorer():
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        model = TextCrossEncoder(
            model_name=REAL_MODEL, providers=["CPUExecutionProvider"],
            local_files_only=os.environ.get("CAMPY_TEST_REAL_RERANKER") != "1")
    except Exception as e:  # not cached / no package / no network
        pytest.skip(f"cross-encoder {REAL_MODEL} unavailable: {e}")
    return lambda q, ts: [float(s) for s in model.rerank(q, ts)]


def test_real_model_prefers_the_named_speakers_turn(real_scorer):
    q = "What pasta shape did Speaker 1 say they like?"
    right = "Speaker 1: I really like rigatoni because it holds sauce well."
    wrong = "Speaker 2: I really like rigatoni because it holds sauce well."
    other = "Speaker 1: We went hiking in the mountains last weekend."
    s_right, s_wrong, s_other = real_scorer(q, [right, wrong, other])
    assert s_right > s_wrong and s_right > s_other


def test_real_model_latency_for_50_candidates_on_cpu(real_scorer, capsys):
    q = "What did Speaker 1 say about the summer trip?"
    base = "we went to the store and bought some food then talked about plans for next summer trip"
    docs = [f"Speaker {1 + i % 2}: " + " ".join(base.split()[(i + j) % 17] for j in range(30))
            for i in range(50)]
    real_scorer(q, docs)  # warm up
    times = []
    for _ in range(3):
        t = time.perf_counter()
        real_scorer(q, docs)
        times.append(time.perf_counter() - t)
    best = min(times)
    with capsys.disabled():
        print(f"\n[B477] {REAL_MODEL}: 50 pairs on CPU, best of 3 = {best * 1000:.0f} ms")
    assert best < 3.0
