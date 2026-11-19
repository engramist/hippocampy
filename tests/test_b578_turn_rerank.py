"""B578: `[retrieval] turn_rerank` -- a cross-encoder reranks the conversation section's turns.

A stub scorer stands in for the model (no download, no ONNX). Proven here: the reorder and the cut (replace mode,
the section's own turn count); a turn from outside the section can enter; graph-vote turns keep their slots and
the other sections are unchanged with the flag on; flag off and a missing model path leave the bundle as it is;
the candidates query reads the vector index and Message nodes only, best first, without the question's echo."""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import turn_rerank as tr
from tests.test_b463_successor_bridge import QUERY_EMB

DIM = 384


def _row(n, text, when, speaker="Ann"):
    return {"text": text, "role": "user", "created_at": when, "speaker": speaker,
            "node_id": f"https://campy.dev/id/Message/m{n}", "node_type": "Message"}


def _stub(prefer):
    """Scores a doc by its position in `prefer` (earlier = higher); unknown docs score 0."""
    def score(_q, docs):
        return [float(len(prefer) - prefer.index(d)) if d in prefer else 0.0 for d in docs]
    return score


def _ids(rows):
    return [r["node_id"].rsplit("/", 1)[-1] for r in rows]


def test_replace_mode_keeps_the_section_count_and_lets_an_outside_turn_in():
    rows = [_row(1, "a", "2023-01-01"), _row(2, "b", "2023-01-02"), _row(3, "c", "2023-01-03")]
    cands = [_row(4, "d", "2023-01-04"), _row(2, "b", "2023-01-02")]   # m2 is in both: counted once
    out = tr.rerank_rows(rows, cands, "q", _stub(["Ann: d", "Ann: c", "Ann: a"]), pinned=set())
    assert _ids(out) == ["m1", "m3", "m4"]            # top 3 by the stub, then oldest first
    assert len(out) == len(rows)


def test_rank_order_puts_pinned_first_then_by_score():
    rows = [_row(1, "a", "2023-01-01"), _row(2, "b", "2023-01-02")]
    cands = [_row(3, "c", "2023-01-03")]
    pinned = {"https://campy.dev/id/Message/m1"}
    out = tr.rerank_rows(rows, cands, "q", _stub(["Ann: c", "Ann: b"]), pinned=pinned, order="rank")
    assert _ids(out) == ["m1", "m3"]


def test_graph_vote_turns_keep_their_slots_even_when_the_scorer_ranks_them_last():
    rows = [_row(1, "a", "2023-01-01"), _row(2, "b", "2023-01-02")]
    cands = [_row(3, "c", "2023-01-03"), _row(4, "d", "2023-01-04")]
    pinned = {"https://campy.dev/id/Message/m1"}
    out = tr.rerank_rows(rows, cands, "q", _stub(["Ann: d", "Ann: c", "Ann: b"]), pinned=pinned)
    assert _ids(out) == ["m1", "m4"]


@pytest.mark.asyncio
async def test_flag_off_and_missing_model_leave_rows_unchanged(caplog):
    rows = [_row(1, "a", "2023-01-01")]
    called = []
    stub = lambda q, d: called.append(1) or [1.0] * len(d)
    assert await tr.rerank_conversation(None, rows, "q", QUERY_EMB, {"retrieval": {"turn_rerank": False}},
                                        scorer=stub) is rows
    assert not called
    tr._scorers.clear(); tr._warned.clear()
    cfg = {"retrieval": {"turn_rerank": True, "turn_rerank_path": ""}}
    assert await tr.rerank_conversation(None, rows, "q", QUERY_EMB, cfg) is rows
    cfg = {"retrieval": {"turn_rerank": True, "turn_rerank_path": "/nonexistent/b578-model"}}
    assert await tr.rerank_conversation(None, rows, "q", QUERY_EMB, cfg) is rows
    assert sum("turn_rerank" in r.getMessage() for r in caplog.records) == 2
    tr._scorers.clear(); tr._warned.clear()


# --- the candidates query and the stage, on a real store ---

@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b578.db"), REGISTRY)


async def _add(gw, n, text, when, cos, speaker="Ann", role="user"):
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                 embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text), created_at=when)
    await gw.run("capture.set_message_source", message_id=f"m{n}", speaker=speaker, occurred_at=when)


@pytest.mark.asyncio
async def test_candidates_are_best_first_without_echo_or_assistant(gw):
    await _add(gw, 1, "far turn", "2023-01-01T00:00:00", 0.10)
    await _add(gw, 2, "near turn", "2023-01-02T00:00:00", 0.80)
    await _add(gw, 3, "the question itself", "2023-01-03T00:00:00", 0.999)
    await _add(gw, 4, "assistant turn", "2023-01-04T00:00:00", 0.90, role="assistant")
    rows = await gw.run("thalamus.bundle_conversation_rerank_candidates", query_embedding=QUERY_EMB, limit=10)
    assert _ids(rows) == ["m2", "m1"]
    rows = await gw.run("thalamus.bundle_conversation_rerank_candidates", query_embedding=QUERY_EMB, limit=1)
    assert _ids(rows) == ["m2"]


@pytest.mark.asyncio
async def test_stage_with_flag_on_changes_only_the_conversation_turns(gw, monkeypatch):
    """With the flag on, the conversation section is reranked and every other section is unchanged."""
    from campy.brain.thalamus import bundle_compiler as bc

    for n, (text, cos) in enumerate([("we hiked the ridge trail", 0.9), ("lunch was soup", 0.6),
                                     ("the ridge trail is steep", 0.5), ("my cat sleeps", 0.4)], start=1):
        await _add(gw, n, text, f"2023-01-0{n}T00:00:00", cos)
    monkeypatch.setattr(bc, "get_gateway", lambda db: gw, raising=False)
    import campy.brain.hippocampus.graph.gateway as gmod
    monkeypatch.setattr(gmod, "get_gateway", lambda db: gw)
    monkeypatch.setattr("campy.brain.hippocampus.graph.embeddings.embed", lambda q, model_name=None: QUERY_EMB)
    base = {"retrieval": {"conversation_limit": 2, "conversation_neighbours": 0, "graph_vote": False,
                          "conversation_token_budget": 0}}
    off = await bc._stage_conversation(None, "ridge trail", base)
    stub = _stub(["Ann: my cat sleeps", "Ann: we hiked the ridge trail"])
    monkeypatch.setattr(tr, "load_scorer", lambda cfg: stub)
    on_cfg = {"retrieval": {**base["retrieval"], "turn_rerank": True}}
    on = await bc._stage_conversation(None, "ridge trail", on_cfg)
    assert len(on.content) == len(off.content) == 2
    assert any("cat sleeps" in c["text"] for c in on.content)
    assert not any("cat sleeps" in c["text"] for c in off.content)


@pytest.mark.asyncio
async def test_whole_bundle_other_sections_unchanged_with_flag_on(gw, monkeypatch):
    from campy.brain.thalamus import bundle_compiler as bc

    for n, (text, cos) in enumerate([("we hiked the ridge trail", 0.9), ("lunch was soup", 0.6),
                                     ("the ridge trail is steep", 0.5), ("my cat sleeps", 0.4)], start=1):
        await _add(gw, n, text, f"2023-01-0{n}T00:00:00", cos)
    monkeypatch.setattr("campy.brain.hippocampus.graph.embeddings.embed", lambda q, model_name=None: QUERY_EMB)
    monkeypatch.setattr(tr, "load_scorer", lambda cfg: _stub(["Ann: my cat sleeps"]))
    r = {"conversation_limit": 2, "conversation_neighbours": 0, "conversation_token_budget": 0}
    kw = dict(include_tabular=False, include_summaries=False)
    off = await bc.compile_bundle("ridge trail", gw._client, {"retrieval": {**r, "turn_rerank": False}}, **kw)
    on = await bc.compile_bundle("ridge trail", gw._client, {"retrieval": {**r, "turn_rerank": True}}, **kw)
    other = lambda b: [(s.section_type, s.content) for s in b.sections if s.section_type != "conversation"]
    assert other(on) == other(off)
    conv = lambda b: [c["text"] for s in b.sections if s.section_type == "conversation" for c in s.content]
    assert any("cat sleeps" in t for t in conv(on)) and not any("cat sleeps" in t for t in conv(off))
    assert len(conv(on)) == len(conv(off))
