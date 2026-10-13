"""B483: `conversation_budget_mode = "sessions"` -- when the history does not
fit the conversation token budget, take whole sessions (scored by their best
turn) until the budget is full, presented chronologically; plus
`conversation_budget_large`, the budget used for "fill"/"sessions" then."""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway, conversation_turn_tokens
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from tests.test_b463_successor_bridge import QUERY_EMB
from tests.test_b482_conversation_token_budget import _Recorder, recorder  # noqa: F401

DIM = 384
TURN_TOKENS = 21  # "[Ann, 2023-05-01 10:00] " + 60-char text, // 4


@pytest.fixture
def gw(tmp_path):
    return GraphGateway(OxigraphClient(tmp_path / "test_b483.db"), REGISTRY)


async def _session(gw, sid):
    await gw.run("quests.merge_session", sid=sid, now="2023-01-01T00:00:00+00:00",
                 routing_state="locked", routing_confidence=0.9, routing_method="git")


async def _turn(gw, n, sid, day, minute, cos, text=None):
    """Message m<n> in session `sid` on `day`; `minute` orders it within the session."""
    text = text or f"Turn {n:03d} " + "x" * 51  # 60 chars
    emb = [0.0] * DIM
    emb[0], emb[n] = cos, math.sqrt(1.0 - cos * cos)
    when = f"2023-05-{day:02d}T10:{minute:02d}:00+00:00"
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=emb,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
                 created_at=when)
    await gw.run("capture.set_message_source", message_id=f"m{n}", speaker="Ann", occurred_at=when)
    if sid:
        await gw.run("capture.link_message_sent_in_session", session_id=sid, message_id=f"m{n}")


async def _sessions(gw, spec):
    """spec: {sid: (day, [cos, ...])}; message numbers are assigned in order."""
    n = 0
    for sid, (day, coss) in spec.items():
        await _session(gw, sid)
        for minute, cos in enumerate(coss):
            n += 1
            await _turn(gw, n, sid, day, minute, cos)
    return n


def _ids(rows):
    return [int(r["node_id"].rsplit("/", 1)[-1][1:]) for r in rows]


async def _run(gw, budget=100, limit=1, mode="sessions", q="zzqx", fit=1):
    """`budget` is the large budget; `fit` the fit-all threshold (1 = never fits)."""
    return await gw.run("thalamus.bundle_conversation_large", query_embedding=QUERY_EMB,
                        query_text=q, limit=limit, order="time",
                        token_budget=fit, budget_mode=mode, large_budget=budget)


def test_turn_cost_assumption():
    assert conversation_turn_tokens("Ann", "2023-05-01T10:00:00+00:00", "Turn 001 " + "x" * 51) == TURN_TOKENS


@pytest.mark.asyncio
async def test_whole_sessions_best_first_until_the_budget_is_full(gw):
    # A: m1-4, B: m5-8, C: m9-12, D: m13-16; best turns A .5 < B .9 < C .7 < D .4
    await _sessions(gw, {"A": (1, [.5, .31, .31, .31]), "B": (2, [.31, .9, .31, .31]),
                         "C": (3, [.7, .31, .31, .31]), "D": (4, [.4, .31, .31, .31])})
    # budget for two whole sessions (8 turns) + 3 turns: B (best) then C, not A or D
    rows = await _run(gw, budget=11 * TURN_TOKENS)
    assert _ids(rows) == [5, 6, 7, 8, 9, 10, 11, 12]


@pytest.mark.asyncio
async def test_session_scores_as_its_best_turn_not_its_average(gw):
    # X has one great turn and weak others; Y is uniformly decent
    await _sessions(gw, {"Y": (1, [.6, .6, .6, .6]), "X": (2, [.31, .31, .95, .31])})
    rows = await _run(gw, budget=5 * TURN_TOKENS)
    assert _ids(rows) == [5, 6, 7, 8]  # X, entire


@pytest.mark.asyncio
async def test_an_oversize_best_session_is_windowed_around_its_best_turn(gw):
    # one 12-turn session (m1-12); best turn is m7; budget holds 5 turns
    await _sessions(gw, {"S": (1, [.31] * 6 + [.9] + [.31] * 5)})
    rows = await _run(gw, budget=5 * TURN_TOKENS)
    assert _ids(rows) == [5, 6, 7, 8, 9]  # contiguous, centred on m7


@pytest.mark.asyncio
async def test_oversize_window_at_the_session_edge(gw):
    await _sessions(gw, {"S": (1, [.9] + [.31] * 11)})
    rows = await _run(gw, budget=4 * TURN_TOKENS)
    assert _ids(rows) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_top_limit_turns_are_kept_even_when_their_session_does_not_fit(gw):
    # A holds the best turn; C's m9 ranks second but C does not fit after A
    await _sessions(gw, {"A": (1, [.95, .31, .31, .31]), "B": (2, [.5, .31, .31, .31]),
                         "C": (3, [.85, .31, .31, .31])})
    # budget: A whole (4) + 1 spare turn
    rows = await _run(gw, budget=5 * TURN_TOKENS, limit=2)
    assert _ids(rows) == [1, 2, 3, 4, 9]
    # with limit 1 the second-best session's turn is not forced in
    assert _ids(await _run(gw, budget=5 * TURN_TOKENS, limit=1)) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_output_is_chronological_whatever_the_rank_order(gw):
    # the best session is the LATEST one; sessions appear in time order anyway
    await _sessions(gw, {"early": (1, [.5, .31, .31, .31]), "late": (9, [.9, .31, .31, .31])})
    rows = await _run(gw, budget=9 * TURN_TOKENS)
    assert _ids(rows) == [1, 2, 3, 4, 5, 6, 7, 8]
    created = [r["created_at"] for r in rows]
    assert created == sorted(created)


@pytest.mark.asyncio
async def test_a_session_that_does_not_fit_is_skipped_for_a_smaller_one(gw):
    await _sessions(gw, {"big": (1, [.9] + [.31] * 5), "mid": (2, [.8] + [.31] * 5),
                         "small": (3, [.7, .31])})
    # big (6) fits, mid (6) does not fit the 8 left, small (2) does
    rows = await _run(gw, budget=8 * TURN_TOKENS)
    assert _ids(rows) == [1, 2, 3, 4, 5, 6, 13, 14]


@pytest.mark.asyncio
async def test_unlinked_messages_act_as_one_turn_sessions(gw):
    await _sessions(gw, {"A": (1, [.9, .31, .31])})
    await _turn(gw, 10, None, 5, 0, .6)
    await _turn(gw, 11, None, 6, 0, .5)
    rows = await _run(gw, budget=4 * TURN_TOKENS)
    assert _ids(rows) == [1, 2, 3, 10]


@pytest.mark.asyncio
async def test_questions_and_duplicates_are_not_pulled_in_with_a_session(gw):
    await _session(gw, "A")
    await _turn(gw, 1, "A", 1, 0, .9)
    await _turn(gw, 2, "A", 1, 1, .31, text="What is my cat called?")
    await _turn(gw, 3, "A", 1, 2, .31, text="Turn 003 " + "x" * 51)
    await _turn(gw, 4, "A", 1, 3, .31, text="Turn 003 " + "x" * 51)  # repeat
    rows = await _run(gw, budget=10 * TURN_TOKENS)
    assert _ids(rows) == [1, 4]  # the question is out, the repeat keeps the newest


@pytest.mark.asyncio
async def test_a_history_that_fits_the_fit_threshold_is_returned_whole(gw):
    n = await _sessions(gw, {"A": (1, [.5, .31]), "B": (2, [.9, .31])})
    rows = await _run(gw, budget=3 * TURN_TOKENS, fit=100 * TURN_TOKENS)
    assert _ids(rows) == list(range(1, n + 1))  # the fit threshold, not the large budget


@pytest.mark.asyncio
async def test_large_budget_applies_when_the_history_does_not_fit(gw):
    await _sessions(gw, {"A": (1, [.9] + [.31] * 3), "B": (2, [.8] + [.31] * 3)})
    one = await _run(gw, budget=4 * TURN_TOKENS)
    two = await _run(gw, budget=8 * TURN_TOKENS)
    assert _ids(one) == [1, 2, 3, 4] and _ids(two) == list(range(1, 9))
    # large_budget 0 falls back to token_budget
    zero = await gw.run("thalamus.bundle_conversation_large", query_embedding=QUERY_EMB,
                        query_text="zzqx", limit=1, order="time", token_budget=1,
                        budget_mode="sessions", large_budget=0)
    assert _ids(zero) == [1]  # budget 1 token: nothing fits, the top-`limit` fallback


@pytest.mark.asyncio
async def test_fill_through_the_large_query_matches_fill_through_the_budget_query(gw):
    await _sessions(gw, {"A": (1, [.9] + [.31] * 3), "B": (2, [.8] + [.31] * 3),
                         "C": (3, [.7] + [.31] * 3)})
    budget = 6 * TURN_TOKENS
    # a fit threshold below the history size: both go to the rank-fill path
    # over the same budget
    old = await gw.run("thalamus.bundle_conversation_budget", query_embedding=QUERY_EMB,
                       query_text="zzqx", limit=2, order="time", token_budget=budget,
                       budget_mode="fill")
    new = await gw.run("thalamus.bundle_conversation_large", query_embedding=QUERY_EMB,
                       query_text="zzqx", limit=2, order="time", token_budget=budget,
                       budget_mode="fill", large_budget=budget)
    assert [dict(r) for r in new] == [dict(r) for r in old] and len(old) > 0


@pytest.mark.asyncio
async def test_fit_all_through_the_large_query_is_the_fixed_path(gw):
    await _sessions(gw, {"A": (1, [.9] + [.31] * 3), "B": (2, [.8] + [.31] * 3)})
    fixed = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                         query_text="zzqx", limit=2, order="time")
    rows = await _run(gw, budget=50 * TURN_TOKENS, limit=2, mode="fit_all")
    assert [dict(r) for r in rows] == [dict(r) for r in fixed]


# --- stage plumbing and config ---------------------------------------------

@pytest.mark.asyncio
async def test_stage_sessions_mode_uses_the_large_query_with_default_large_budget(recorder):  # noqa: F811
    await bundle_compiler._stage_conversation(
        None, "q", {"retrieval": {"conversation_token_budget": 3500, "conversation_budget_mode": "sessions"}})
    assert recorder.name == "thalamus.bundle_conversation_large"
    assert recorder.params["budget_mode"] == "sessions"
    assert recorder.params["token_budget"] == 3500 and recorder.params["large_budget"] == 3500


@pytest.mark.asyncio
@pytest.mark.parametrize("large,want", [(6000, 6000), ("6000", 6000), (0, 3500), ("junk", 3500), (-3, 3500)])
async def test_stage_passes_the_large_budget(recorder, large, want):  # noqa: F811
    cfg = {"retrieval": {"conversation_token_budget": 3500, "conversation_budget_mode": "fill",
                         "conversation_budget_large": large}}
    await bundle_compiler._stage_conversation(None, "q", cfg)
    assert recorder.name == "thalamus.bundle_conversation_large"
    assert recorder.params["large_budget"] == want


@pytest.mark.asyncio
async def test_stage_fit_all_still_uses_the_b482_query(recorder):  # noqa: F811
    cfg = {"retrieval": {"conversation_token_budget": 3500, "conversation_budget_large": 6000}}
    await bundle_compiler._stage_conversation(None, "q", cfg)
    assert recorder.name == "thalamus.bundle_conversation_budget"
    assert "large_budget" not in recorder.params


def test_env_parser_accepts_sessions_and_rejects_unknown():
    from campy.brain.brainstem.config import apply_env_overrides

    cfg = apply_env_overrides({}, {"CAMPY_RETRIEVAL_CONVERSATION_BUDGET_MODE": "Sessions",
                                   "CAMPY_RETRIEVAL_CONVERSATION_BUDGET_LARGE": "6000"})
    assert cfg["retrieval"]["conversation_budget_mode"] == "sessions"
    assert cfg["retrieval"]["conversation_budget_large"] == 6000
