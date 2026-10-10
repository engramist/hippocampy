"""B474: the conversation stage presents its turns best-ranked first by default.

Replay R27 (same six turns, same store): rank order gained 5 / lost 1 on DMR
(50 q) and gained 5 / lost 2 on LoCoMo-10 (60 q) against oldest-first.
`[retrieval] conversation_order = "time"` keeps the B454 order. Embeddings are
hand-built to chosen cosines so the tests don't depend on the embedding model.
"""

from __future__ import annotations

import logging
import math

import pytest

from campy.brain.hippocampus.graph import gateway as gateway_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from tests.test_b463_successor_bridge import (
    DB_Q, PG14_ACK, PG16_USER, QUERY_EMB, _db_store, _Store)

DIM = 384
Q = "zzqx"  # shares no word with the turns: ranking is the vector plane alone

# (text, cosine to the query, created_at) -- best match is neither oldest nor newest.
TURNS = [
    ("alpha statement about widgets", 0.50, "2026-10-01T10:00:00+00:00"),
    ("bravo statement about gadgets", 0.90, "2026-10-02T10:00:00+00:00"),
    ("charlie statement about gizmos", 0.70, "2026-10-03T10:00:00+00:00"),
    ("delta statement about doodads", 0.40, "2026-10-04T10:00:00+00:00"),
]
BY_RANK = [t[0] for t in sorted(TURNS, key=lambda t: -t[1])]
BY_TIME = [t[0] for t in sorted(TURNS, key=lambda t: t[2])]


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b474.db"), REGISTRY)


async def _store(gw):
    for n, (text, cos, created) in enumerate(TURNS, start=1):
        emb = [0.0] * DIM
        emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
        await gw.run(
            "capture.create_message",
            message_id=f"m{n}", text_raw=text, embedding=emb, embedding_model="m",
            embedding_dim=DIM, role="user", byte_end=len(text), created_at=created,
        )


async def _texts(gw, order, limit=6, query=Q):
    rows = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                        query_text=query, limit=limit, order=order)
    return [r["text"] for r in rows]


@pytest.mark.asyncio
async def test_rank_mode_returns_the_best_match_first(gw):
    await _store(gw)
    assert await _texts(gw, "rank") == BY_RANK
    assert BY_RANK != BY_TIME  # the fixture can tell the orders apart


@pytest.mark.asyncio
async def test_time_mode_returns_the_oldest_first(gw):
    await _store(gw)
    assert await _texts(gw, "time") == BY_TIME


@pytest.mark.asyncio
async def test_both_orders_pick_the_same_top_limit(gw):
    await _store(gw)
    top3 = set(BY_RANK[:3])
    assert set(await _texts(gw, "rank", limit=3)) == top3
    assert set(await _texts(gw, "time", limit=3)) == top3


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["newest", "", None, "RANKED"])
async def test_an_unknown_order_falls_back_to_rank(gw, bad):
    await _store(gw)
    assert await _texts(gw, bad) == BY_RANK


@pytest.mark.asyncio
async def test_order_is_case_insensitive(gw):
    await _store(gw)
    assert await _texts(gw, "TIME") == BY_TIME


@pytest.mark.asyncio
async def test_an_unknown_order_warns_once(gw, caplog):
    await _store(gw)
    gateway_mod._BAD_ORDER_WARNED.clear()
    with caplog.at_level(logging.WARNING, logger=gateway_mod._logger.name):
        await _texts(gw, "newest")
        await _texts(gw, "newest")
    assert sum("conversation_order" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_a_successor_statement_lands_right_after_its_predecessor_in_rank_mode(gw):
    # B463: PG16_USER is found through the assistant turn that names PostgreSQL
    # 14 (cos 0.339) and inherits that turn's fused score; the on-topic user
    # turn that outranks it stays first. Time mode puts the oldest first.
    s = await _db_store(gw)
    await s.msg("Our database has been slow lately, ask me anything about it.", "user", 0.60)
    rank = await _texts(gw, "rank", query=DB_Q)
    assert rank.index(PG16_USER) == 1 and rank[0].startswith("Our database has been slow")
    time_order = await _texts(gw, "time", query=DB_Q)
    assert time_order.index(PG16_USER) < time_order.index(rank[0])  # created earlier
    assert PG14_ACK not in rank


# -- the compiler stage threads the setting ------------------------------------------------

class _Recorder:
    def __init__(self):
        self.params = None

    async def run(self, name, **params):
        self.params = params
        return [{"text": "x", "created_at": "2026-10-09T10:00:00+00:00", "node_id": "m1"}]


@pytest.fixture
def recorder(monkeypatch):
    from campy.brain.hippocampus.graph import embeddings

    rec = _Recorder()
    monkeypatch.setattr(bundle_compiler, "get_gateway", lambda db: rec)
    monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)
    return rec


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg,expected", [
    ({}, "rank"),
    ({"retrieval": {"conversation_order": "time"}}, "time"),
    ({"retrieval": {"conversation_order": "Rank"}}, "rank"),
    ({"retrieval": {"conversation_order": "bogus"}}, "rank"),
])
async def test_stage_passes_the_configured_order(recorder, cfg, expected):
    section = await bundle_compiler._stage_conversation(None, "q", cfg)
    assert recorder.params["order"] == expected
    assert section.order == expected


def test_ask_prompt_describes_the_order_truthfully():
    from campy.brain.thalamus.ask import _bundle_to_prompt
    from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle

    def prompt(order):
        sec = BundleSection("conversation", [{"text": "[user, 2026-10-01 10:00] hi"}], 5, [], order=order)
        bundle = ContextBundle(query="q", sections=[sec], total_token_estimate=5,
                               token_budget=1000, truncated=False)
        return _bundle_to_prompt(bundle, "q")

    assert "oldest first" in prompt("time")
    rank = prompt("rank")
    assert "best match first" in rank and "oldest first" not in rank
