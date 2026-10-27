"""B538: relative dates in user turns are resolved by rule at capture and shown inline.

Pure resolver tests (each expression kind, ranges, year rollover, no expression),
the graph write/read (TimeMention nodes, idempotent upsert and backfill), and the
bundle rendering (flag on shows `phrase [= date]`; flag off is unchanged).
Embeddings are hand-built so nothing depends on the embedding model.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pytest

from campy.brain.brainstem.config import load_config
from campy.brain.hippocampus import turn_mentions as tm
from campy.brain.hippocampus.graph import embeddings
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations.turn_dates import (
    annotate, find_time_expressions, resolved_text)
from campy.brain.thalamus import bundle_compiler

DIM = 384
QUERY_EMB = [1.0] + [0.0] * (DIM - 1)
MON = date(2023, 5, 8)           # a Monday


def _resolve(text: str, anchor=MON) -> list[tuple[str, str]]:
    return [(s.phrase, resolved_text(s.resolved)) for s in find_time_expressions(text, anchor)]


# --- the resolver: each expression kind ----------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("I went to the group yesterday.", [("yesterday", "2023-05-07")]),
    ("We leave tomorrow", [("tomorrow", "2023-05-09")]),
    ("It was the day before yesterday", [("the day before yesterday", "2023-05-06")]),
    ("I saw him last night.", [("last night", "2023-05-07")]),
    ("I adopted him three days ago", [("three days ago", "2023-05-05")]),
    ("It started 2 weeks ago", [("2 weeks ago", "week of 2023-04-24")]),
    ("We met about two months ago", [("about two months ago", "2023-03")]),
    ("I graduated a year ago", [("a year ago", "2022")]),
    ("We go in two weeks", [("in two weeks", "week of 2023-05-22")]),
    ("I joined last week", [("last week", "week of 2023-05-01")]),
    ("The trip is next month", [("next month", "2023-06")]),
    ("I moved last year", [("last year", "2022")]),
    ("See you next week", [("next week", "week of 2023-05-15")]),
    ("We hiked last Friday", [("last Friday", "2023-05-05")]),
    ("The show is next Saturday", [("next Saturday", "2023-05-13")]),
    ("I am free this weekend", [("this weekend", "2023-05-13 to 2023-05-14")]),
    ("We camped last weekend", [("last weekend", "2023-05-06 to 2023-05-07")]),
])
def test_each_expression_kind_resolves_against_the_turns_date(text, expected):
    assert _resolve(text) == expected


def test_ranges_carry_their_precision():
    by_phrase = {s.phrase: s.resolved for s in find_time_expressions(
        "last week, next month, last year and yesterday", MON)}
    assert by_phrase["last week"].precision == "week"
    assert by_phrase["next month"].precision == "month"
    assert by_phrase["last year"].precision == "year"
    assert by_phrase["yesterday"].precision == "day"
    assert by_phrase["last week"].end.date() == date(2023, 5, 7)     # inclusive Sunday


def test_year_and_month_rollover():
    assert _resolve("I started last month", date(2023, 1, 3)) == [("last month", "2022-12")]
    assert _resolve("I started last week", date(2023, 1, 3)) == [("last week", "week of 2022-12-26")]
    assert _resolve("We go next month", date(2023, 12, 15)) == [("next month", "2024-01")]
    assert _resolve("It happened yesterday", date(2023, 1, 1)) == [("yesterday", "2022-12-31")]
    assert _resolve("We got married last year", date(2024, 1, 2)) == [("last year", "2023")]
    assert _resolve("I leave in 3 days", date(2023, 12, 30)) == [("in 3 days", "2024-01-02")]
    assert _resolve("three days ago", date(2023, 1, 2)) == [("three days ago", "2022-12-30")]


def test_reading_order_spans_and_case():
    text = "Yesterday I called; Last week I wrote; next month we meet."
    spans = find_time_expressions(text, MON)
    assert [s.phrase for s in spans] == ["Yesterday", "Last week", "next month"]
    for s in spans:
        assert text[s.start:s.end] == s.phrase
    assert [s.start for s in spans] == sorted(s.start for s in spans)


# --- no expression, not annotated ----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "I love hiking and reading.",
    "I am going today, tonight and now.",
    "See you on Saturday.",
    "We chatted the other day, and recently, and a few days ago.",
    "I have been running over the last year.",
    "We will see in the next month.",
    "She was born on 7 May 2019.",
    "",
])
def test_no_expression_or_a_vague_one_finds_nothing(text):
    assert find_time_expressions(text, MON) == []


def test_without_a_usable_anchor_nothing_is_resolved():
    assert find_time_expressions("I went yesterday", None) == []
    assert find_time_expressions("I went yesterday", "not a date") == []
    assert [s.phrase for s in find_time_expressions("I went yesterday", "2023-05-08T13:56:00+00:00")] == ["yesterday"]
    assert [s.phrase for s in find_time_expressions("I went yesterday", datetime(2023, 5, 8, 13, 56))] == ["yesterday"]


def test_annotate_inserts_the_resolved_date_right_after_the_phrase():
    text = "we went yesterday and again last week."
    spans = [(s.start, s.end, resolved_text(s.resolved)) for s in find_time_expressions(text, MON)]
    assert annotate(text, spans) == "we went yesterday [= 2023-05-07] and again last week [= week of 2023-05-01]."
    assert annotate(text, []) == text
    assert annotate(text, [(0, 999, "x")]) == text           # a span that does not fit is skipped


# --- annotate_turn: stored mentions onto shown text ----------------------------------------

def test_annotate_turn_uses_the_phrase_when_the_shown_text_is_a_cut():
    mentions = [{"phrase": "last week", "start": 40, "end": 49, "resolved": "week of 2023-05-01"}]
    assert tm.annotate_turn("I joined last week, finally.", mentions) == "I joined last week [= week of 2023-05-01], finally."
    assert tm.annotate_turn("nothing here", mentions) == "nothing here"
    assert tm.annotate_turn("nothing here", None) == "nothing here"


def test_annotate_turn_handles_a_repeated_phrase_twice():
    mentions = [{"phrase": "yesterday", "start": 0, "end": 9, "resolved": "2023-05-07"},
                {"phrase": "yesterday", "start": 14, "end": 23, "resolved": "2023-05-07"}]
    assert tm.annotate_turn("yesterday, and yesterday!", mentions) == "yesterday [= 2023-05-07], and yesterday [= 2023-05-07]!"


# --- the graph -----------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "test_b538.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def _emb(n: int, cos: float) -> list[float]:
    v = [0.0] * DIM
    v[0], v[n] = cos, math.sqrt(1.0 - cos * cos)
    return v


async def _add(gw, n, text, *, role="user", occurred="2023-05-08T13:56:00+00:00", cos=0.6):
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=_emb(n, cos),
                 embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text),
                 created_at="2026-10-09T10:00:00+00:00")
    if occurred:
        await gw.run("capture.set_message_source", message_id=f"m{n}", speaker="Caroline", occurred_at=occurred)


def _count(db, pred):
    rows = db._execute_and_collect(f"SELECT (COUNT(*) AS ?n) WHERE {{ ?s {pred} ?o }}")
    return int(rows[0]["n"])


MSG = "https://campy.dev/id/Message/"


@pytest.mark.asyncio
async def test_write_then_read_back_the_resolved_mentions(gw, db):
    await _add(gw, 1, "I went to the group yesterday and joined last week.")
    n = await tm.write_turn_mentions(gw, "m1", "I went to the group yesterday and joined last week.",
                                     "2023-05-08T13:56:00+00:00")
    assert n == 2
    got = await tm.load_mentions(gw, [MSG + "m1", MSG + "nope"])
    assert [(m["phrase"], m["resolved"]) for m in got[MSG + "m1"]] == [
        ("yesterday", "2023-05-07"), ("last week", "week of 2023-05-01")]
    assert MSG + "nope" not in got
    assert _count(db, "<https://campy.dev/ns#HAS_TIME_MENTION>") == 2


@pytest.mark.asyncio
async def test_rewriting_is_idempotent_and_replaces_values_in_place(gw, db):
    text = "I went yesterday."
    await _add(gw, 1, text)
    await tm.write_turn_mentions(gw, "m1", text, "2023-05-08T13:56:00+00:00")
    await tm.write_turn_mentions(gw, "m1", text, "2023-05-08T13:56:00+00:00")
    assert _count(db, "<https://campy.dev/ns#HAS_TIME_MENTION>") == 1
    assert _count(db, "<https://campy.dev/ns#time_start>") == 1
    # the turn is re-dated: the one mention moves, it does not gain a second value
    await tm.write_turn_mentions(gw, "m1", text, "2023-06-20T09:00:00+00:00")
    assert _count(db, "<https://campy.dev/ns#time_start>") == 1
    assert _count(db, "<https://campy.dev/ns#created_at>") >= 1
    got = await tm.load_mentions(gw, [MSG + "m1"])
    assert got[MSG + "m1"][0]["resolved"] == "2023-06-19"


@pytest.mark.asyncio
async def test_a_turn_without_an_expression_or_a_date_writes_nothing(gw, db):
    await _add(gw, 1, "I love hiking.")
    assert await tm.write_turn_mentions(gw, "m1", "I love hiking.", "2023-05-08T13:56:00+00:00") == 0
    assert await tm.write_turn_mentions(gw, "m1", "I went yesterday.", None) == 0
    assert _count(db, "<https://campy.dev/ns#HAS_TIME_MENTION>") == 0


@pytest.mark.asyncio
async def test_backfill_covers_user_turns_only_and_is_idempotent(gw, db):
    await _add(gw, 1, "I went to the group yesterday.")
    await _add(gw, 2, "You should go last week.", role="assistant")
    await _add(gw, 3, "I love hiking.")
    await _add(gw, 4, "We start next month.", occurred=None)        # falls back to created_at
    s1 = await tm.backfill_turn_mentions(db)
    assert s1 == {"turns": 3, "turns_with_mentions": 2, "mentions": 2, "no_date": 0}
    got = await tm.load_mentions(gw, [MSG + f"m{i}" for i in (1, 2, 3, 4)])
    assert set(got) == {MSG + "m1", MSG + "m4"}
    assert got[MSG + "m4"][0]["resolved"] == "2026-11"
    before = _count(db, "?p")
    s2 = await tm.backfill_turn_mentions(db)
    assert s2["mentions"] == 2 and _count(db, "?p") == before          # re-run changes nothing
    assert (await tm.backfill_turn_mentions(db, limit=0))["mentions"] == 0


# --- the bundle ----------------------------------------------------------------------------

CFG_ON = {"observations": {"turn_dates": True}}
CFG_OFF = {"observations": {"turn_dates": False}}


@pytest.fixture
def q_embed(monkeypatch):
    monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)


async def _conv_texts(db, cfg):
    sec = await bundle_compiler._stage_conversation(db, "When did Caroline go to the group?", cfg)
    return [c["text"] for c in sec.content]


@pytest.mark.asyncio
async def test_conversation_turn_shows_the_resolved_date_after_the_phrase(gw, db, q_embed):
    await _add(gw, 1, "I went to the group yesterday, it was great.")
    await tm.backfill_turn_mentions(db)
    texts = await _conv_texts(db, CFG_ON)
    assert texts == ["[Caroline, 2023-05-08 13:56] I went to the group yesterday [= 2023-05-07], it was great."]


@pytest.mark.asyncio
async def test_flag_off_or_nothing_stored_leaves_the_turn_unchanged(gw, db, q_embed):
    await _add(gw, 1, "I went to the group yesterday, it was great.")
    plain = "[Caroline, 2023-05-08 13:56] I went to the group yesterday, it was great."
    # flag on but nothing stored (no backfill, no capture-time write): unchanged
    assert await _conv_texts(db, CFG_ON) == [plain]
    # mentions stored, flag off: the render is still the old one
    await tm.backfill_turn_mentions(db)
    assert await _conv_texts(db, CFG_OFF) == [plain]


@pytest.mark.asyncio
async def test_a_turn_with_no_expression_is_unchanged_with_the_flag_on(gw, db, q_embed):
    await _add(gw, 1, "I love hiking with my dog.")
    await tm.backfill_turn_mentions(db)
    assert await _conv_texts(db, CFG_ON) == ["[Caroline, 2023-05-08 13:56] I love hiking with my dog."]


def test_observation_when_and_quote_use_the_same_bracket_form():
    row = {"speaker": "Caroline", "observed_at": "2023-05-08T13:56:00+00:00", "predicate": "did",
           "event_text": "went to the group", "time_text": "yesterday",
           "time_start": datetime(2023, 5, 7, tzinfo=timezone.utc), "time_end": datetime(2023, 5, 7, tzinfo=timezone.utc),
           "time_precision": "day", "evidence_text": "I went to the group yesterday"}
    old = bundle_compiler.render_observation(row)
    assert "(when: yesterday → 2023-05-07)" in old and "[=" not in old
    mentions = [{"phrase": "yesterday", "start": 21, "end": 30, "resolved": "2023-05-07"}]
    new = bundle_compiler.render_observation(row, inline=True, mentions=mentions)
    assert "(when: yesterday [= 2023-05-07])" in new
    assert '("I went to the group yesterday [= 2023-05-07]")' in new


def test_the_flag_defaults_off_and_has_an_env_switch(monkeypatch):
    monkeypatch.delenv("CAMPY_TURN_DATES", raising=False)
    assert tm.turn_dates_enabled(load_config()) is False
    monkeypatch.setenv("CAMPY_TURN_DATES", "1")
    assert tm.turn_dates_enabled(load_config()) is True
    assert tm.turn_dates_enabled(None) is False


def test_ask_prompt_gains_one_line_only_with_the_flag(monkeypatch):
    from campy.brain.thalamus import ask
    from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle

    sec = BundleSection(section_type="conversation", content=[{"text": "[Caroline, 2023-05-08] hi"}],
                        token_estimate=5, source_node_ids=["x"])
    bundle = ContextBundle(query="q", sections=[sec], total_token_estimate=5, token_budget=100, truncated=False)
    off = ask._bundle_to_prompt(bundle, "q", CFG_OFF)
    on = ask._bundle_to_prompt(bundle, "q", CFG_ON)
    assert tm.TURN_DATES_SUFFIX not in off
    assert on.replace(tm.TURN_DATES_SUFFIX, "") == off
