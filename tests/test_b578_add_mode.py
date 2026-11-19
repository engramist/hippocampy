"""B578 add mode (`[retrieval] turn_rerank_mode = "add"`, ruled 2026-11-19) and the answer call's token usage.

A stub scorer stands in for the cross-encoder. Proven here: add mode never drops a turn the section has; it adds the
top new turns with the section's own session windows; graph-vote turns are still there; with the flag off the
bundle is the same whatever the mode says; `run_ask` records the server's token usage in `meta`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import turn_rerank as tr
from tests.test_b463_successor_bridge import QUERY_EMB
from tests.test_b487_neighbour_expansion import _add, _session


def _row(n, text, when, speaker="Ann"):
    return {"text": text, "role": "user", "created_at": when, "speaker": speaker,
            "node_id": f"https://campy.dev/id/Message/m{n}", "node_type": "Message"}


def _stub(prefer):
    def score(_q, docs):
        return [float(len(prefer) - prefer.index(d)) if d in prefer else 0.0 for d in docs]
    return score


def _ids(rows):
    return [r["node_id"].rsplit("/", 1)[-1] for r in rows]


def test_mode_defaults_to_window_and_rejects_unknown(caplog):
    tr._warned.clear()
    assert tr.turn_rerank_mode({}) == "window"
    assert tr.turn_rerank_mode({"retrieval": {"turn_rerank_mode": " ADD "}}) == "add"
    assert tr.turn_rerank_mode({"retrieval": {"turn_rerank_mode": "both"}}) == "window"
    assert any("turn_rerank_mode" in r.getMessage() for r in caplog.records)
    tr._warned.clear()


def test_add_seeds_skips_section_turns_and_keeps_the_top_k():
    rows = [_row(1, "a", "2023-01-01")]
    cands = [_row(1, "a", "2023-01-01")] + [_row(n, f"t{n}", f"2023-01-0{n}") for n in range(2, 9)]
    prefer = ["Ann: a"] + [f"Ann: t{n}" for n in (8, 7, 6, 5, 4, 3, 2)]
    seeds = tr.add_seeds(rows, cands, "q", _stub(prefer), k=5)
    assert _ids(seeds) == ["m8", "m7", "m6", "m5", "m4"]


def test_merge_added_keeps_every_section_turn_in_time_order():
    rows = [_row(2, "b", "2023-01-02"), _row(4, "d", "2023-01-04")]
    added = [_row(3, "c", "2023-01-03"), _row(2, "b", "2023-01-02"), _row(9, "z", "2023-01-09")]
    out = tr.merge_added(rows, added)
    assert _ids(out) == ["m2", "m3", "m4", "m9"]
    assert tr.merge_added(rows, added, order="rank")[:2] == rows
    assert tr.merge_added(rows, []) is rows


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b578_add.db"), REGISTRY)


async def _dialogue(gw):
    """One session: m1..m7 in order. m2 is what the section holds; m5 is what the scorer wants (its neighbours
    m4 and m6 come with it); m7 is an assistant turn (never a neighbour)."""
    await _session(gw, "s1")
    for n, text, cos, role in [(1, "hello there", 0.0, "user"), (2, "we hiked the ridge trail", 0.9, "user"),
                               (3, "lunch was soup", 0.1, "user"), (4, "what about pets?", 0.1, "user"),
                               (5, "my cat sleeps all day", 0.4, "user"), (6, "cats are like that", 0.1, "user"),
                               (7, "assistant says hi", 0.1, "assistant")]:
        await _add(gw, n, text, f"2023-05-01T10:0{n}:00+00:00", cos=cos, role=role)


@pytest.mark.asyncio
async def test_add_mode_keeps_the_section_and_adds_seed_windows(gw, monkeypatch):
    await _dialogue(gw)
    import campy.brain.hippocampus.graph.gateway as gmod
    monkeypatch.setattr(gmod, "get_gateway", lambda db: gw)
    rows = [r for r in await gw.run("thalamus.bundle_conversation_rerank_candidates",
                                    query_embedding=QUERY_EMB, limit=10) if r["node_id"].endswith("/m2")]
    monkeypatch.setattr(tr, "ADD_K", 1)   # one seed, so m4 and m6 can only come from its window
    cfg = {"retrieval": {"turn_rerank": True, "turn_rerank_mode": "add"}}
    stub = _stub(["Ann: my cat sleeps all day"])
    out = await tr.rerank_conversation(None, rows, "ridge trail", QUERY_EMB, cfg, scorer=stub, neighbours=1,
                                       graph_turns=[rows[0]["node_id"]])
    ids = _ids(out)
    assert "m2" in ids                                   # the section turn (and the vote turn) stays
    assert set(ids) == {"m2", "m4", "m5", "m6"}          # the seed with its +-1 window, nothing else
    assert "m7" not in ids                               # assistant turns are never neighbours
    assert ids == sorted(ids, key=lambda i: int(i[1:]))  # time order


@pytest.mark.asyncio
async def test_add_mode_never_drops_a_section_turn_even_when_the_scorer_hates_it(gw, monkeypatch):
    await _dialogue(gw)
    import campy.brain.hippocampus.graph.gateway as gmod
    monkeypatch.setattr(gmod, "get_gateway", lambda db: gw)
    rows = list(await gw.run("thalamus.bundle_conversation_rerank_candidates", query_embedding=QUERY_EMB, limit=3))
    cfg = {"retrieval": {"turn_rerank": True, "turn_rerank_mode": "add"}}
    out = await tr.rerank_conversation(None, rows, "q", QUERY_EMB, cfg, scorer=lambda q, d: [0.0] * len(d),
                                       neighbours=2)
    assert set(_ids(rows)) <= set(_ids(out))
    assert len(out) >= len(rows)


@pytest.mark.asyncio
async def test_flag_off_bundle_is_the_same_whatever_the_mode(gw, monkeypatch):
    from campy.brain.thalamus import bundle_compiler as bc
    await _dialogue(gw)
    monkeypatch.setattr("campy.brain.hippocampus.graph.embeddings.embed", lambda q, model_name=None: QUERY_EMB)
    monkeypatch.setattr(tr, "load_scorer", lambda cfg: _stub(["Ann: my cat sleeps all day"]))
    r = {"conversation_limit": 1, "conversation_neighbours": 1, "conversation_token_budget": 0}
    kw = dict(include_tabular=False, include_summaries=False)
    dump = lambda b: [(s.section_type, s.content, s.source_node_ids) for s in b.sections]
    base = await bc.compile_bundle("ridge trail", gw._client, {"retrieval": {**r, "turn_rerank": False}}, **kw)
    off_add = await bc.compile_bundle("ridge trail", gw._client,
                                      {"retrieval": {**r, "turn_rerank": False, "turn_rerank_mode": "add"}}, **kw)
    assert dump(base) == dump(off_add)
    on_add = await bc.compile_bundle("ridge trail", gw._client,
                                     {"retrieval": {**r, "turn_rerank": True, "turn_rerank_mode": "add"}}, **kw)
    conv = lambda b: [c["text"] for s in b.sections if s.section_type == "conversation" for c in s.content]
    assert set(conv(base)) <= set(conv(on_add))
    assert any("cat sleeps" in t for t in conv(on_add))
    assert [x for x in dump(on_add) if x[0] != "conversation"] == [x for x in dump(base) if x[0] != "conversation"]


@pytest.mark.asyncio
async def test_run_ask_records_the_answer_calls_token_usage():
    from campy.brain.thalamus.ask import run_ask

    class LLM:
        last_usage = None

        def chat(self, messages, **kw):
            self.last_usage = {"prompt_tokens": 4096, "completion_tokens": 7, "total_tokens": 4103}
            return "an answer"

        async def achat(self, messages, **kw):
            return self.chat(messages)

    bundle = MagicMock(); bundle.sections = []; bundle.query = "q"
    meta: dict = {}
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=bundle), \
         patch("campy.brain.thalamus.ask._get_llm", return_value=LLM()), \
         patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock):
        await run_ask(query="q", session_id="s", db=MagicMock(), config={"compression": {}, "ask": {}}, meta=meta)
    assert meta["answer_usage"]["prompt_tokens"] == 4096


@pytest.mark.asyncio
async def test_add_mode_places_a_seed_inside_its_sessions_dialogue_when_times_tie(gw, monkeypatch):
    """LoCoMo turns of one session share one timestamp: the order comes from the session sequence, not the time."""
    await _session(gw, "s1")
    for n in range(1, 7):
        await _add(gw, n, f"turn number {n}", "2023-05-01T10:00:00+00:00", cos=0.1 * n)
    import campy.brain.hippocampus.graph.gateway as gmod
    monkeypatch.setattr(gmod, "get_gateway", lambda db: gw)
    monkeypatch.setattr(tr, "ADD_K", 1)
    cands = list(await gw.run("thalamus.bundle_conversation_rerank_candidates", query_embedding=QUERY_EMB, limit=10))
    rows = [r for r in cands if r["node_id"].endswith("/m5")]
    cfg = {"retrieval": {"turn_rerank": True, "turn_rerank_mode": "add"}}
    out = await tr.rerank_conversation(None, rows, "q", QUERY_EMB, cfg, scorer=_stub(["Ann: turn number 2"]),
                                       neighbours=1)
    assert _ids(out) == ["m1", "m2", "m3", "m5"]
