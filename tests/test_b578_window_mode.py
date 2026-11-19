"""B578 window mode (`[retrieval] turn_rerank_mode = "window"`, ruled 2026-11-19; ND-7).

A stub scorer stands in for the cross-encoder. Proven here: the section keeps its own turn count; graph-vote turns
keep their slots; each seed brings its session window before the next seed is taken; a turn already chosen does not
spend the budget twice; with the flag off the bundle is the same whatever the mode says."""

from __future__ import annotations

import pytest

from campy.brain.thalamus import turn_rerank as tr
from tests.test_b463_successor_bridge import QUERY_EMB
from tests.test_b578_add_mode import _dialogue, _ids, _stub, gw  # noqa: F401  (gw is a fixture)

CFG = {"retrieval": {"turn_rerank": True, "turn_rerank_mode": "window"}}


async def _setup(gw, monkeypatch, keep):
    await _dialogue(gw)
    import campy.brain.hippocampus.graph.gateway as gmod
    monkeypatch.setattr(gmod, "get_gateway", lambda db: gw)
    cands = list(await gw.run("thalamus.bundle_conversation_rerank_candidates", query_embedding=QUERY_EMB, limit=10))
    rows = [r for r in cands if _ids([r])[0] in keep]
    assert sorted(_ids(rows)) == sorted(keep)
    return rows


def test_window_is_a_mode():
    assert tr.turn_rerank_mode({"retrieval": {"turn_rerank_mode": " Window "}}) == "window"


@pytest.mark.asyncio
async def test_window_mode_keeps_the_turn_count_and_brings_the_seed_window(gw, monkeypatch):
    rows = await _setup(gw, monkeypatch, ["m1", "m2", "m3"])
    out = await tr.rerank_conversation(None, rows, "q", QUERY_EMB, CFG, scorer=_stub(["Ann: my cat sleeps all day"]),
                                       neighbours=1)
    ids = _ids(out)
    assert len(ids) == len(rows)
    assert set(ids) == {"m4", "m5", "m6"}               # the seed and its +-1 window
    assert "m7" not in ids                               # assistant turns are never neighbours
    assert ids == sorted(ids, key=lambda i: int(i[1:]))  # session order


@pytest.mark.asyncio
async def test_window_mode_keeps_the_graph_vote_turns(gw, monkeypatch):
    rows = await _setup(gw, monkeypatch, ["m1", "m2", "m3"])
    m2 = next(r["node_id"] for r in rows if r["node_id"].endswith("/m2"))
    out = await tr.rerank_conversation(None, rows, "q", QUERY_EMB, CFG, scorer=_stub(["Ann: my cat sleeps all day"]),
                                       neighbours=1, graph_turns=[m2])
    assert set(_ids(out)) == {"m2", "m4", "m5"}         # pinned m2; the seed's window cut short at the budget


@pytest.mark.asyncio
async def test_window_mode_fills_one_seed_window_before_the_next_seed(gw, monkeypatch):
    rows = await _setup(gw, monkeypatch, ["m1", "m2", "m3"])
    out = await tr.rerank_conversation(None, rows, "q", QUERY_EMB, CFG,
                                       scorer=_stub(["Ann: my cat sleeps all day", "Ann: hello there"]), neighbours=1)
    assert set(_ids(out)) == {"m4", "m5", "m6"}         # rounds by distance would give m5, m1, m4


@pytest.mark.asyncio
async def test_window_mode_does_not_spend_the_budget_twice_on_a_turn(gw, monkeypatch):
    rows = await _setup(gw, monkeypatch, ["m1", "m2", "m3", "m4"])
    # seed m6 is already in m5's window, and so is its own window (m5; m7 is an assistant turn): it costs nothing
    prefer = ["Ann: my cat sleeps all day", "Ann: cats are like that", "Ann: we hiked the ridge trail"]
    out = await tr.rerank_conversation(None, rows, "q", QUERY_EMB, CFG, scorer=_stub(prefer), neighbours=1)
    assert set(_ids(out)) == {"m2", "m4", "m5", "m6"}   # m2, the third seed, still gets a slot


@pytest.mark.asyncio
async def test_flag_off_bundle_is_the_same_in_window_mode(gw, monkeypatch):
    from campy.brain.thalamus import bundle_compiler as bc
    await _dialogue(gw)
    monkeypatch.setattr("campy.brain.hippocampus.graph.embeddings.embed", lambda q, model_name=None: QUERY_EMB)
    monkeypatch.setattr(tr, "load_scorer", lambda cfg: _stub(["Ann: my cat sleeps all day"]))
    r = {"conversation_limit": 1, "conversation_neighbours": 1, "conversation_token_budget": 0}
    kw = dict(include_tabular=False, include_summaries=False)
    dump = lambda b: [(s.section_type, s.content, s.source_node_ids) for s in b.sections]
    base = await bc.compile_bundle("ridge trail", gw._client, {"retrieval": dict(r)}, **kw)
    off = await bc.compile_bundle("ridge trail", gw._client,
                                  {"retrieval": {**r, "turn_rerank": False, "turn_rerank_mode": "window"}}, **kw)
    assert dump(base) == dump(off)
    on = await bc.compile_bundle("ridge trail", gw._client,
                                 {"retrieval": {**r, "turn_rerank": True, "turn_rerank_mode": "window"}}, **kw)
    conv = lambda b: [c["text"] for s in b.sections if s.section_type == "conversation" for c in s.content]
    assert len(conv(on)) == len(conv(base))
    assert any("cat sleeps" in t for t in conv(on))
    assert [x for x in dump(on) if x[0] != "conversation"] == [x for x in dump(base) if x[0] != "conversation"]
