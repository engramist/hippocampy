"""B487: `[retrieval] conversation_neighbours` -- neighbour expansion in the
conversation stage.

A matched turn gets up to N same-session turns (either speaker) before and
after it, because evidence turns are often replies that do not repeat the
question's words. 0 (default) is the existing stage, byte-identical.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from tests.test_b463_successor_bridge import QUERY_EMB

DIM = 384


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b487.db"), REGISTRY)


async def _session(gw, sid):
    await gw.run("quests.merge_session_git_locked", sid=sid, now="2023-05-01T00:00:00+00:00")


async def _add(gw, n, text, when, sid="s1", cos=0.0, role="user", speaker="Ann", archived=False):
    """cos = 0 -> orthogonal to the query: never matched by the vector plane."""
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                 embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text),
                 created_at=when)
    await gw.run("capture.set_message_source", message_id=f"m{n}", speaker=speaker, occurred_at=when)
    if sid:
        await gw.run("capture.link_message_sent_in_session", session_id=sid, message_id=f"m{n}")


def _ids(rows):
    return [r["node_id"].rsplit("/", 1)[-1] for r in rows]


async def _win(gw, n=1, cap=18, limit=1, order="time", budget=0, q="zzqx", mode="fit_all"):
    return await gw.run("thalamus.bundle_conversation_windows", query_embedding=QUERY_EMB,
                        query_text=q, limit=limit, order=order, token_budget=budget,
                        budget_mode=mode, neighbours=n, neighbour_cap=cap)


async def _fixed(gw, limit=1, order="time", q="zzqx"):
    return await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                        query_text=q, limit=limit, order=order)


async def _dialogue(gw):
    """s1: a question by Bob, Ann's reply (the evidence), then filler; the
    query matches only m3 ("what's your fave?" is orthogonal to it)."""
    await _session(gw, "s1")
    await _add(gw, 1, "Hi!", "2023-05-01T10:00:00+00:00", speaker="Bob")
    await _add(gw, 2, "Which style do you like best?", "2023-05-01T10:01:00+00:00", speaker="Bob")
    await _add(gw, 3, "I love dance, my top pick is contemporary.", "2023-05-01T10:02:00+00:00",
               cos=0.9, speaker="Ann")
    await _add(gw, 4, "Nice choice.", "2023-05-01T10:03:00+00:00", speaker="Bob")
    await _add(gw, 5, "See you later.", "2023-05-01T10:04:00+00:00", speaker="Ann")


@pytest.mark.asyncio
async def test_zero_neighbours_is_byte_identical(gw):
    await _dialogue(gw)
    for order in ("time", "rank"):
        assert [dict(r) for r in await _win(gw, n=0, order=order)] == \
               [dict(r) for r in await _fixed(gw, order=order)]
    assert _ids(await _win(gw, n=0)) == ["m3"]


@pytest.mark.asyncio
async def test_window_includes_the_other_speaker_and_questions(gw):
    await _dialogue(gw)
    rows = await _win(gw, n=1)
    assert _ids(rows) == ["m2", "m3", "m4"]
    assert [r["speaker"] for r in rows] == ["Bob", "Ann", "Bob"]
    assert rows[1].get("neighbour") is None and rows[0]["neighbour"] and rows[2]["neighbour"]
    assert _ids(await _win(gw, n=2)) == ["m1", "m2", "m3", "m4", "m5"]


@pytest.mark.asyncio
async def test_windows_stay_in_the_matched_turns_session(gw):
    await _dialogue(gw)
    await _session(gw, "s2")
    # same moment as the matched turn's neighbours, but another session
    await _add(gw, 6, "Other session turn.", "2023-05-01T10:02:30+00:00", sid="s2")
    await _add(gw, 7, "Unattached turn.", "2023-05-01T10:02:40+00:00", sid=None)
    assert _ids(await _win(gw, n=2)) == ["m1", "m2", "m3", "m4", "m5"]


@pytest.mark.asyncio
async def test_overlapping_windows_merge_and_dedupe(gw):
    await _session(gw, "s1")
    await _add(gw, 1, "a", "2023-05-01T10:00:00+00:00")
    await _add(gw, 2, "match one", "2023-05-01T10:01:00+00:00", cos=0.9)
    await _add(gw, 3, "b", "2023-05-01T10:02:00+00:00")
    await _add(gw, 4, "match two", "2023-05-01T10:03:00+00:00", cos=0.8)
    await _add(gw, 5, "c", "2023-05-01T10:04:00+00:00")
    assert _ids(await _win(gw, n=1, limit=2)) == ["m1", "m2", "m3", "m4", "m5"]


@pytest.mark.asyncio
async def test_cap_bounds_added_turns_and_prefers_closest_best_ranked(gw):
    await _session(gw, "s1")
    for i, c in zip(range(1, 8), (0, 0, 0.9, 0, 0, 0, 0)):  # one matched turn: m3
        await _add(gw, i, f"turn {i}", f"2023-05-01T10:0{i}:00+00:00", cos=c)
    rows = await _win(gw, n=2, cap=3)
    assert len(rows) == 1 + 3
    # distance 1 both sides first, then one of the distance-2 turns; contiguous
    ids = _ids(rows)
    assert {"m2", "m3", "m4"} <= set(ids)
    assert ids == sorted(ids)
    assert len(await _win(gw, n=2, cap=0)) == 1


@pytest.mark.asyncio
async def test_archived_assistant_and_query_echo_neighbours_are_dropped(gw):
    await _session(gw, "s1")
    await _add(gw, 1, "archived one", "2023-05-01T10:00:00+00:00")
    await _add(gw, 2, "assistant answer", "2023-05-01T10:01:00+00:00", role="assistant")
    await _add(gw, 3, "the match", "2023-05-01T10:02:00+00:00", cos=0.9)
    await _add(gw, 4, "zzqx", "2023-05-01T10:03:00+00:00")  # echo of the query
    await _add(gw, 5, "kept", "2023-05-01T10:04:00+00:00")
    await gw.run("capture.archive_earlier_message_version", marker="archived one")
    ids = _ids(await _win(gw, n=2))
    assert ids == ["m3", "m5"]


@pytest.mark.asyncio
async def test_same_timestamp_turns_keep_capture_order(gw):
    same = "2023-05-01T10:00:00+00:00"
    await _session(gw, "s1")
    await _add(gw, 1, "first", same)
    await _add(gw, 2, "second match", same, cos=0.9)
    await _add(gw, 3, "third", same)
    assert _ids(await _win(gw, n=1)) == ["m1", "m2", "m3"]


@pytest.mark.asyncio
async def test_window_order_time_vs_rank(gw):
    await _session(gw, "s1")
    await _session(gw, "s2")
    await _add(gw, 1, "early match", "2023-05-01T10:00:00+00:00", sid="s1", cos=0.5)
    await _add(gw, 2, "early reply", "2023-05-01T10:01:00+00:00", sid="s1")
    await _add(gw, 3, "late match", "2023-06-01T10:00:00+00:00", sid="s2", cos=0.9)
    await _add(gw, 4, "late reply", "2023-06-01T10:01:00+00:00", sid="s2")
    assert _ids(await _win(gw, n=1, limit=2, order="time")) == ["m1", "m2", "m3", "m4"]
    assert _ids(await _win(gw, n=1, limit=2, order="rank")) == ["m3", "m4", "m1", "m2"]


@pytest.mark.asyncio
async def test_full_history_path_is_untouched(gw):
    await _dialogue(gw)
    rows = await _win(gw, n=2, budget=3500)
    assert all(dict(r).get("full_history") is True for r in rows)
    assert not any("neighbour" in dict(r) for r in rows)
    budget = await gw.run("thalamus.bundle_conversation_budget", query_embedding=QUERY_EMB,
                          query_text="zzqx", limit=1, order="time", token_budget=3500,
                          budget_mode="fit_all")
    assert [dict(r) for r in rows] == [dict(r) for r in budget]


@pytest.mark.asyncio
async def test_over_budget_store_expands_the_fixed_limit_turns(gw):
    await _dialogue(gw)
    # a budget too small for the whole history: fit_all falls back to the top-1
    rows = await _win(gw, n=1, budget=10)
    assert _ids(rows) == ["m2", "m3", "m4"]
    assert not any(dict(r).get("full_history") for r in rows)


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
@pytest.mark.parametrize("cfg", [{"retrieval": {"conversation_neighbours": 0}},
                                 {"retrieval": {"conversation_neighbours": "junk"}},
                                 {"retrieval": {"conversation_neighbours": -2}}])
async def test_stage_neighbours_off_uses_the_existing_queries(recorder, cfg):
    await bundle_compiler._stage_conversation(None, "q", cfg)
    assert recorder.name == "thalamus.bundle_conversation_budget"
    assert "neighbours" not in recorder.params
    await bundle_compiler._stage_conversation(
        None, "q", {"retrieval": {**cfg.get("retrieval", {}), "conversation_token_budget": 0}})
    assert recorder.name == "thalamus.bundle_conversation"


@pytest.mark.asyncio
async def test_stage_neighbours_are_on_by_default(recorder):
    await bundle_compiler._stage_conversation(None, "q", {})
    assert recorder.name == "thalamus.bundle_conversation_windows"
    assert recorder.params["neighbours"] == bundle_compiler.DEFAULT_CONVERSATION_NEIGHBOURS == 1


@pytest.mark.asyncio
async def test_stage_neighbours_on_uses_the_windows_query(recorder):
    await bundle_compiler._stage_conversation(None, "q", {"retrieval": {"conversation_neighbours": 2}})
    assert recorder.name == "thalamus.bundle_conversation_windows"
    assert recorder.params["neighbours"] == 2 and recorder.params["neighbour_cap"] == 18
    await bundle_compiler._stage_conversation(
        None, "q", {"retrieval": {"conversation_neighbours": 1, "conversation_neighbour_cap": 5}})
    assert recorder.params["neighbour_cap"] == 5
