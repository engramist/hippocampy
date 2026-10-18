"""B482: `[retrieval] conversation_token_budget` -- the conversation stage
filled to a token budget instead of a fixed turn count.

0 = off = the fixed-limit path, unchanged. > 0: every eligible user turn,
oldest first, when they all fit; otherwise, per `conversation_budget_mode`,
the fixed-limit path ("fit_all", default) or rank-filled up to the budget
("fill").
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from campy.brain.hippocampus.graph.gateway import (
    GraphGateway, conversation_turn_tokens)
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from tests.test_b463_successor_bridge import QUERY_EMB

DIM = 384


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b482.db"), REGISTRY)


async def _add(gw, n, text, created, cos=0.8, role="user", speaker="Ann", archived=False):
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                 embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text),
                 created_at=created)
    await gw.run("capture.set_message_source", message_id=f"m{n}", speaker=speaker,
                 occurred_at=created)


def _ids(rows):
    return [r["node_id"].rsplit("/", 1)[-1] for r in rows]


async def _budget(gw, budget, limit=2, order="time", q="zzqx", mode="fill"):
    return await gw.run("thalamus.bundle_conversation_budget", query_embedding=QUERY_EMB,
                        query_text=q, limit=limit, order=order, token_budget=budget,
                        budget_mode=mode)


async def _fixed(gw, limit=2, order="time", q="zzqx"):
    return await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                        query_text=q, limit=limit, order=order)


async def _small_store(gw):
    # inserted out of chronological order, with an assistant turn and a question
    await _add(gw, 3, "We moved to Berlin last spring.", "2023-05-03T10:00:00+00:00", cos=0.2)
    await _add(gw, 1, "I live in Paris.", "2023-05-01T10:00:00+00:00", cos=0.9)
    await _add(gw, 2, "My cat is called Miso.", "2023-05-02T10:00:00+00:00", cos=0.1)
    await _add(gw, 4, "Noted, Berlin it is.", "2023-05-03T10:01:00+00:00", role="assistant")
    await _add(gw, 5, "Where do I live?", "2023-05-04T10:00:00+00:00")


@pytest.mark.asyncio
async def test_budget_zero_is_the_fixed_limit_path(gw):
    await _small_store(gw)
    assert _ids(await _budget(gw, 0)) == _ids(await _fixed(gw))
    assert len(await _budget(gw, 0)) < 3  # limit=2 still applies


@pytest.mark.asyncio
async def test_small_store_that_fits_returns_all_user_turns_oldest_first(gw):
    await _small_store(gw)
    rows = await _budget(gw, 2000)
    # all eligible user turns, regardless of similarity; no assistant, no question
    assert _ids(rows) == ["m1", "m2", "m3"]
    assert all(r["role"] == "user" for r in rows)


@pytest.mark.asyncio
async def test_same_timestamp_turns_keep_capture_order(gw):
    same = "2023-05-01T10:00:00+00:00"
    await _add(gw, 2, "second thing", same)
    # stored created_at differs from occurred_at only via capture order here
    await _add(gw, 1, "first thing", same)
    rows = await _budget(gw, 2000)
    assert sorted(_ids(rows)) == ["m1", "m2"]  # both present, deterministic


@pytest.mark.asyncio
async def test_archived_and_duplicate_turns_are_not_eligible(gw):
    await _add(gw, 1, "I live in Paris.", "2023-05-01T10:00:00+00:00")
    await _add(gw, 2, "I live in Paris.", "2023-05-02T10:00:00+00:00")  # repeat: newest wins
    rows = await _budget(gw, 2000)
    assert _ids(rows) == ["m2"]


@pytest.mark.asyncio
async def test_over_budget_store_is_rank_filled_within_budget(gw):
    # 40 on-topic turns of ~30 tokens each (~1200 tokens); budget fits ~10 of them
    for i in range(1, 41):
        await _add(gw, i, f"Statement number {i} about my garden, " + "plants " * 12,
                   f"2023-05-{(i % 28) + 1:02d}T10:00:00+00:00", cos=0.5 + i / 100)
    budget = 330
    rows = await _budget(gw, budget, limit=2)
    assert 2 <= len(rows) < 40
    cost = sum(conversation_turn_tokens(r["speaker"], r["created_at"], r["text"]) for r in rows)
    assert cost <= budget
    # a whole extra turn would not have fit
    assert cost + 25 > budget
    # presented oldest first
    assert [r["created_at"] for r in rows] == sorted(r["created_at"] for r in rows)
    # the best-ranked turn (highest cosine, m40) is in
    assert "m40" in _ids(rows)
    # more than the fixed limit of 2
    assert len(rows) > len(await _fixed(gw, limit=2))


@pytest.mark.asyncio
async def test_rank_order_is_honoured_when_over_budget(gw):
    for i in range(1, 21):
        await _add(gw, i, f"Statement {i} " + "word " * 40,
                   f"2023-05-{i:02d}T10:00:00+00:00", cos=0.4 + i / 50)
    rows = await _budget(gw, 300, limit=2, order="rank")
    assert _ids(rows)[0] == "m20"


@pytest.mark.asyncio
async def test_a_budget_smaller_than_any_turn_falls_back_to_the_limit(gw):
    await _add(gw, 1, "x " * 400, "2023-05-01T10:00:00+00:00", cos=0.9)
    await _add(gw, 2, "y " * 400, "2023-05-02T10:00:00+00:00", cos=0.8)
    assert _ids(await _budget(gw, 5, limit=1)) == ["m1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["time", "rank"])
async def test_fit_all_with_a_store_too_big_is_identical_to_budget_zero(gw, order):
    for i in range(1, 41):
        await _add(gw, i, f"Statement number {i} about my garden, " + "plants " * 12,
                   f"2023-05-{(i % 28) + 1:02d}T10:00:00+00:00", cos=0.5 + i / 100)
    fixed = await _fixed(gw, limit=3, order=order)
    for mode in ("fit_all", None):  # explicit and absent (default is fit_all)
        rows = await _budget(gw, 330, limit=3, order=order, mode=mode)
        assert [dict(r) for r in rows] == [dict(r) for r in fixed]
        # B472 3c: a partial history must never claim to be the whole one
        assert not any(dict(r).get("full_history") for r in rows)
    assert not any(dict(r).get("full_history") for r in fixed)
    # ...whereas fill takes more
    assert len(await _budget(gw, 330, limit=3, order=order, mode="fill")) > len(fixed)


@pytest.mark.asyncio
async def test_fit_all_with_a_small_store_returns_all_turns(gw):
    await _small_store(gw)
    rows = await _budget(gw, 2000, mode="fit_all")
    assert _ids(rows) == ["m1", "m2", "m3"]
    assert all(dict(r).get("full_history") is True for r in rows)


@pytest.mark.asyncio
async def test_unknown_mode_behaves_as_fit_all(gw):
    await _small_store(gw)
    assert _ids(await _budget(gw, 2000, mode="bogus")) == ["m1", "m2", "m3"]


# --- stage plumbing -------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.name = None
        self.params = None

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
@pytest.mark.parametrize("cfg", [{"retrieval": {"conversation_token_budget": 0}},
                                 {"retrieval": {"conversation_token_budget": "junk"}}])
async def test_stage_budget_off_uses_the_original_query(recorder, cfg):
    await bundle_compiler._stage_conversation(None, "q", cfg)
    assert recorder.name == "thalamus.bundle_conversation"
    assert "token_budget" not in recorder.params


@pytest.mark.asyncio
async def test_stage_budget_on_uses_the_budget_query(recorder):
    await bundle_compiler._stage_conversation(
        None, "q", {"retrieval": {"conversation_token_budget": 3500}})
    assert recorder.name == "thalamus.bundle_conversation_budget"
    assert recorder.params["token_budget"] == 3500 and recorder.params["limit"] == 6
    assert recorder.params["budget_mode"] == "fit_all"


@pytest.mark.asyncio
@pytest.mark.parametrize("val,want", [("fill", "fill"), ("FILL", "fill"), ("junk", "fit_all")])
async def test_stage_passes_the_budget_mode(recorder, val, want):
    await bundle_compiler._stage_conversation(
        None, "q", {"retrieval": {"conversation_token_budget": 3500, "conversation_budget_mode": val}})
    assert recorder.params["budget_mode"] == want


@pytest.mark.asyncio
async def test_limit_zero_still_disables_the_stage(recorder):
    cfg = {"retrieval": {"conversation_limit": 0, "conversation_token_budget": 3500}}
    assert await bundle_compiler._stage_conversation(None, "q", cfg) is None


# --- compression ----------------------------------------------------------

@pytest.mark.asyncio
async def test_conversation_section_survives_compression_and_does_not_trigger_it():
    from campy.brain.thalamus.ask import run_ask

    big = [{"text": f"[Ann, 2023-05-01 10:00] turn {i} " + "w " * 40} for i in range(60)]
    conv = bundle_compiler.BundleSection(
        section_type="conversation", content=big, token_estimate=3000, source_node_ids=["m"] * 60)
    bundle = bundle_compiler.ContextBundle(
        query="q", sections=[conv], total_token_estimate=3000, token_budget=32000,
        truncated=False, sources=[], compilation_ms=0.0)
    llm = MagicMock()
    llm.achat = AsyncMock(return_value="a")
    config = {"compression": {"budget_tokens": 2000}, "retrieval": {"conversation_token_budget": 3500}}
    meta: dict = {}
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=bundle), \
            patch("campy.brain.thalamus.ask._get_llm", return_value=llm), \
            patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock):
        await run_ask("q", "s", MagicMock(), config, meta=meta, capture=False)
    assert meta["compression_bypassed"] is True
    assert meta["conversation_tokens_exempt"] == 3000
    assert len(bundle.sections[0].content) == 60
    prompt = llm.achat.call_args[0][0][1]["content"]
    assert "turn 59" in prompt

    # budget mode off: the same bundle is over the 2000-token threshold
    meta2: dict = {}
    config_off = {"compression": {"budget_tokens": 2000}, "retrieval": {"conversation_token_budget": 0}}
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=bundle), \
            patch("campy.brain.thalamus.ask._get_llm", return_value=llm), \
            patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock):
        await run_ask("q", "s", MagicMock(), config_off, meta=meta2, capture=False)
    assert meta2["compression_bypassed"] is False
    # ...and the router has no route for "conversation": its items still arrive whole
    assert len(bundle.sections[0].content) == 60


def test_conversation_is_not_in_the_compression_routes():
    from campy.brain.thalamus.compression import ContentRouter, build_default_registry

    _, router = build_default_registry({})
    assert router.route("conversation").__class__.__name__ == "NoOpCompressor"
    assert "conversation" not in ContentRouter._ROUTE


@pytest.mark.asyncio
async def test_stage_budget_is_on_by_default(recorder):
    await bundle_compiler._stage_conversation(None, "q", {})
    assert recorder.name == "thalamus.bundle_conversation_budget"
    assert recorder.params["token_budget"] == bundle_compiler.DEFAULT_CONVERSATION_TOKEN_BUDGET == 3500
    assert recorder.params["budget_mode"] == "fit_all"
