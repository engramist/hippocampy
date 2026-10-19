"""B484 (M4.2): time normalisation at capture.

Anchor used throughout: Sunday 2023-05-07 unless stated.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import backfill_time, format_resolved, normalize_time
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.thalamus import bundle_compiler as bc

SUN = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
EMB = [0.05] * 384


def _res(text, anchor=SUN):
    r = normalize_time(text, anchor)
    return None if r is None else (r.start.date().isoformat(), r.end.date().isoformat(), r.precision)


def _d(s):
    return (s, s, "day")


@pytest.mark.parametrize("text,expected", [
    # today / yesterday / tomorrow
    ("today", _d("2023-05-07")), ("tonight", _d("2023-05-07")), ("this morning", _d("2023-05-07")),
    ("yesterday", _d("2023-05-06")), ("Yesterday morning", _d("2023-05-06")), ("last night", _d("2023-05-06")),
    ("the day before yesterday", _d("2023-05-05")), ("tomorrow", _d("2023-05-08")),
    ("tomorrow night", _d("2023-05-08")), ("the day after tomorrow", _d("2023-05-09")),
    # N units ago / in N units
    ("two days ago", _d("2023-05-05")), ("3 days ago", _d("2023-05-04")), ("a couple of days ago", _d("2023-05-05")),
    ("a week ago", ("2023-04-24", "2023-04-30", "week")),
    ("two weeks ago", ("2023-04-17", "2023-04-23", "week")),
    ("3 months ago", ("2023-02-01", "2023-02-28", "month")),
    ("a year ago", ("2022-01-01", "2022-12-31", "year")),
    ("in 2 weeks", ("2023-05-15", "2023-05-21", "week")),
    ("in three days", _d("2023-05-10")),
    # weekdays: last = most recent strictly before, next = first strictly after, this = same ISO week
    ("last Saturday", _d("2023-05-06")), ("last Sunday", _d("2023-04-30")), ("last Monday", _d("2023-05-01")),
    ("this past Friday", _d("2023-05-05")), ("next Monday", _d("2023-05-08")), ("next Sunday", _d("2023-05-14")),
    ("this Friday", _d("2023-05-05")), ("this Sunday", _d("2023-05-07")), ("on last Saturday", _d("2023-05-06")),
    ("last Saturday at 5pm", _d("2023-05-06")), ("last Saturday evening", _d("2023-05-06")),
    # periods
    ("last week", ("2023-04-24", "2023-04-30", "week")), ("this week", ("2023-05-01", "2023-05-07", "week")),
    ("next week", ("2023-05-08", "2023-05-14", "week")), ("the week before", ("2023-04-24", "2023-04-30", "week")),
    ("earlier this week", ("2023-05-01", "2023-05-07", "week")),
    ("last month", ("2023-04-01", "2023-04-30", "month")), ("next month", ("2023-06-01", "2023-06-30", "month")),
    ("this year", ("2023-01-01", "2023-12-31", "year")), ("last year", ("2022-01-01", "2022-12-31", "year")),
    ("last weekend", ("2023-04-29", "2023-04-30", "day")), ("this weekend", ("2023-05-06", "2023-05-07", "day")),
    ("this past weekend", ("2023-05-06", "2023-05-07", "day")), ("next weekend", ("2023-05-13", "2023-05-14", "day")),
    # absolute
    ("7 May 2023", _d("2023-05-07")), ("May 7, 2023", _d("2023-05-07")), ("May 7th 2023", _d("2023-05-07")),
    ("7th of May, 2023", _d("2023-05-07")), ("Sunday, 7 May 2023", _d("2023-05-07")), ("on 7 May 2023", _d("2023-05-07")),
    ("2023-05-07", _d("2023-05-07")), ("2023-05-07T10:00:00Z", _d("2023-05-07")),
    ("May 2023", ("2023-05-01", "2023-05-31", "month")), ("2023-02", ("2023-02-01", "2023-02-28", "month")),
    ("2024-02", ("2024-02-01", "2024-02-29", "month")), ("2023", ("2023-01-01", "2023-12-31", "year")),
    ("in 2019", ("2019-01-01", "2019-12-31", "year")), ("13/04/2023", _d("2023-04-13")),
    ("04/13/2023", _d("2023-04-13")), ("29 Feb 2024", _d("2024-02-29")),
    # relative to an explicit date
    ("the week before 9 June 2023", ("2023-05-29", "2023-06-04", "week")),
    ("the Sunday before 25 May 2023", _d("2023-05-21")), ("two days before 9 June 2023", _d("2023-06-07")),
    ("the day after 31 December 2023", _d("2024-01-01")), ("the month before June 2023", None),
    ("the weekend after 9 June 2023", ("2023-06-17", "2023-06-18", "day")),
    ("the Monday after 9 June 2023", _d("2023-06-12")),
])
def test_normalize_time_rules(text, expected):
    assert _res(text) == expected


@pytest.mark.parametrize("text", [
    None, "", "  ", "recently", "a few days ago", "several weeks ago", "the other day", "a while ago",
    "last summer", "this Christmas", "in the 90s", "sometime", "at 5pm", "morning",
    "on Saturday", "Saturday", "03/04/2023", "30 Feb 2023", "31 April 2023", "since May", "until June",
    "from May to June", "3 to 5 May", "before the trip", "the next day", "two days later", "99999",
    "x" * 80, 7,
])
def test_unknown_or_ambiguous_is_none(text):
    assert normalize_time(text, SUN) is None


def test_month_and_year_rollover():
    jan = datetime(2023, 1, 15, tzinfo=timezone.utc)
    assert _res("last month", jan) == ("2022-12-01", "2022-12-31", "month")
    assert _res("2 months ago", jan) == ("2022-11-01", "2022-11-30", "month")
    assert _res("last week", datetime(2023, 1, 2, tzinfo=timezone.utc)) == ("2022-12-26", "2023-01-01", "week")
    assert _res("yesterday", datetime(2023, 1, 1, tzinfo=timezone.utc)) == _d("2022-12-31")
    assert _res("tomorrow", datetime(2023, 12, 31, tzinfo=timezone.utc)) == _d("2024-01-01")
    assert _res("next month", datetime(2023, 12, 5, tzinfo=timezone.utc)) == ("2024-01-01", "2024-01-31", "month")
    assert _res("in 3 months", datetime(2023, 11, 30, tzinfo=timezone.utc)) == ("2024-02-01", "2024-02-29", "month")
    assert _res("a month ago", datetime(2023, 3, 31, tzinfo=timezone.utc)) == ("2023-02-01", "2023-02-28", "month")
    assert _res("3 days ago", datetime(2024, 3, 2, tzinfo=timezone.utc)) == _d("2024-02-28")   # leap year


def test_weekday_arithmetic_from_every_anchor_weekday():
    # Mon 2023-05-01 .. Sun 2023-05-07
    for offset in range(7):
        a = datetime(2023, 5, 1 + offset, tzinfo=timezone.utc)
        last_sat = normalize_time("last Saturday", a).start.date()
        assert last_sat.weekday() == 5 and 1 <= (a.date() - last_sat).days <= 7
        next_sat = normalize_time("next Saturday", a).start.date()
        assert next_sat.weekday() == 5 and 1 <= (next_sat - a.date()).days <= 7
        this_sat = normalize_time("this Saturday", a).start.date()
        assert this_sat.isocalendar()[:2] == a.date().isocalendar()[:2]


def test_year_less_dates_pick_the_occurrence_nearest_the_anchor():
    dec = datetime(2023, 12, 20, tzinfo=timezone.utc)
    assert _res("5 January", dec) == _d("2024-01-05")           # nearer than the January that has passed
    assert _res("5 September", dec) == _d("2023-09-05")
    assert _res("March", dec) == ("2024-03-01", "2024-03-31", "month")   # 3 months ahead beats 9 back
    assert _res("January", dec) == ("2024-01-01", "2024-01-31", "month")
    assert _res("May 7", SUN) == _d("2023-05-07")
    assert normalize_time("7 May", None) is None                  # no anchor, no year
    assert _res("7 May 2023") == _d("2023-05-07") and normalize_time("7 May 2023", None) is not None
    assert normalize_time("yesterday", None) is None


def test_anchor_may_be_a_naive_datetime_or_a_date():
    from datetime import date
    assert _res("yesterday", datetime(2023, 5, 7, 23, 59)) == _d("2023-05-06")
    r = normalize_time("yesterday", date(2023, 5, 7))
    assert r.start.date().isoformat() == "2023-05-06"


def test_format_resolved():
    def f(text):
        r = normalize_time(text, SUN)
        return format_resolved(r.start, r.end, r.precision)

    assert f("yesterday") == "2023-05-06"
    assert f("last week") == "week of 2023-04-24"
    assert f("last month") == "2023-04"
    assert f("last year") == "2022"
    assert f("this weekend") == "2023-05-06 to 2023-05-07"
    assert format_resolved(None, None, "day") is None
    assert format_resolved("2023-05-06T00:00:00+00:00", None, "day") == "2023-05-06"


# --- worker --------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_embedder(monkeypatch):
    monkeypatch.setattr(ex.emb, "embed", lambda text, model_name=None: EMB)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b484.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


CFG = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600}}


class _LLM:
    def __init__(self, items):
        self.items = items

    def chat(self, messages, **kw):
        return json.dumps(self.items)


async def _message(gw, mid, text, occurred="2023-05-07T12:00:00+00:00"):
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None, embedding_model="m",
                 embedding_dim=384, role="user", byte_end=len(text), created_at=occurred)
    await gw.run("capture.set_message_source", message_id=mid, speaker="Melanie", occurred_at=occurred)


def _fact(time, quote, obj="went to the support group"):
    return {"subject": "I", "predicate": "did", "object": obj, "time": time, "polarity": "asserted",
            "quote": quote, "confidence": 0.9}


@pytest.mark.asyncio
async def test_worker_fills_time_fields_against_the_turns_date(db, gw):
    text = "I went to the support group yesterday. I got my license on 7 May 2019. I met her sometime back."
    await _message(gw, "m1", text)
    llm = _LLM([
        _fact("yesterday", "I went to the support group yesterday"),
        _fact("7 May 2019", "I got my license on 7 May 2019", "got a driver's license"),
        _fact("sometime back", "I met her sometime back", "met her"),
    ])
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, CFG, llm, "m1", stats)
    rows = {r["time_text"]: r for r in await obs.observations_for_message(db, "m1")}
    y = rows["yesterday"]
    assert str(y["time_start"])[:10] == "2023-05-06" and str(y["time_end"])[:10] == "2023-05-06"
    assert y["time_precision"] == "day"
    assert str(rows["7 May 2019"]["time_start"])[:10] == "2019-05-07"
    vague = rows["sometime back"]
    assert vague["time_start"] is None and vague["time_end"] is None and vague["time_precision"] == "unknown"
    assert stats.time_resolved == 2 and stats.time_unresolved == 1


@pytest.mark.asyncio
async def test_same_phrase_on_different_days_is_two_observations(db, gw):
    q = "I went to the support group yesterday"
    await _message(gw, "m1", q, "2023-05-07T12:00:00+00:00")
    await _message(gw, "m2", q, "2023-05-20T12:00:00+00:00")
    llm = _LLM([_fact("yesterday", q)])
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, CFG, llm, "m1", stats)
    await ex.process_turn(db, CFG, llm, "m2", stats)
    await ex.process_turn(db, CFG, llm, "m2", stats)              # re-run: still idempotent
    assert stats.created == 2 and stats.duplicate == 1
    starts = []
    for m in ("m1", "m2"):
        starts.append(str((await obs.observations_for_message(db, m))[0]["time_start"])[:10])
    starts.sort()
    assert starts == ["2023-05-06", "2023-05-19"]


@pytest.mark.asyncio
async def test_no_time_phrase_leaves_time_null(db, gw):
    await _message(gw, "m1", "I went to the support group")
    await ex.process_turn(db, CFG, _LLM([_fact(None, "I went to the support group")]), "m1", ex.ObservationWorkerStats())
    row = (await obs.observations_for_message(db, "m1"))[0]
    assert row["time_text"] is None and row["time_start"] is None and row["time_precision"] is None


# --- rendering -----------------------------------------------------------------------------

BASE = {"speaker": "Caroline", "observed_at": "2023-05-08T12:00:00+00:00", "subject_text": "I", "predicate": "did",
        "object_text": "went to a support group", "polarity": "asserted", "evidence_text": "I went yesterday"}


def test_render_shows_the_resolved_date_next_to_the_raw_phrase():
    stored = {**BASE, "time_text": "yesterday", "time_start": "2023-05-07T00:00:00+00:00",
              "time_end": "2023-05-07T00:00:00+00:00", "time_precision": "day"}
    assert bc.render_observation(stored) == (
        '[Caroline, 2023-05-08] did: went to a support group (when: yesterday → 2023-05-07) ("I went yesterday")')
    week = {**stored, "time_text": "last week", "time_start": datetime(2023, 4, 24, tzinfo=timezone.utc),
            "time_end": datetime(2023, 4, 30, tzinfo=timezone.utc), "time_precision": "week"}
    assert "(when: last week → week of 2023-04-24)" in bc.render_observation(week)


def test_render_resolves_old_rows_on_the_fly_without_writing():
    old = {**BASE, "time_text": "last Saturday", "time_start": None}      # written before B484
    assert "(when: last Saturday → 2023-05-06)" in bc.render_observation(old)
    assert "(when: sometime back)" in bc.render_observation({**old, "time_text": "sometime back"})
    assert "when:" not in bc.render_observation({**BASE, "time_text": None})
    no_anchor = {**old, "observed_at": None}
    assert "(when: last Saturday)" in bc.render_observation(no_anchor)
    bad_anchor = {**old, "observed_at": "not a date"}
    assert "(when: last Saturday)" in bc.render_observation(bad_anchor)


def test_render_does_not_repeat_an_identical_date():
    row = {**BASE, "time_text": "2023-05-07", "time_start": "2023-05-07T00:00:00+00:00",
           "time_end": "2023-05-07T00:00:00+00:00", "time_precision": "day"}
    assert "(when: 2023-05-07)" in bc.render_observation(row)


# --- backfill ------------------------------------------------------------------------------

async def _legacy(db, oid, time_text, observed="2023-05-07T12:00:00+00:00"):
    """An Observation as written before B484: time_text only."""
    draft = obs.ObservationDraft(
        evidence_ref="m1", evidence_text="I went to the support group", subject_text="I", predicate="did",
        object_text=f"object {oid}", extraction_method="llm", confidence=0.9, time_text=time_text,
        observed_at=obs._as_datetime(observed), embedding=EMB, speaker="Melanie")
    res = await obs.record_observation(db, draft)
    assert res.status == "created", res
    return res.observation_id


@pytest.mark.asyncio
async def test_backfill_fills_old_rows_idempotently_and_touches_nothing_else(db, gw):
    await _message(gw, "m1", "I went to the support group")
    ids = {
        "yesterday": await _legacy(db, "a", "yesterday"),
        "7 May 2019": await _legacy(db, "b", "7 May 2019"),
        "sometime back": await _legacy(db, "c", "sometime back"),
        None: await _legacy(db, "d", None),
    }
    before = {k: await obs.get_observation(db, v) for k, v in ids.items()}
    assert all(r["time_start"] is None for r in before.values())

    s1 = await backfill_time(db)
    assert (s1.candidates, s1.filled, s1.unresolved) == (3, 2, 1)
    after = {k: await obs.get_observation(db, v) for k, v in ids.items()}
    assert str(after["yesterday"]["time_start"])[:10] == "2023-05-06" and after["yesterday"]["time_precision"] == "day"
    assert str(after["7 May 2019"]["time_start"])[:10] == "2019-05-07"
    assert after["sometime back"]["time_start"] is None and after["sometime back"]["time_precision"] == "unknown"
    assert after[None]["time_start"] is None and after[None]["time_precision"] is None
    for k in ids:                       # nothing but the time fields changed
        for col in ("time_text", "text_raw", "content_hash", "evidence_text", "observed_at", "confidence"):
            assert after[k][col] == before[k][col], (k, col)

    s2 = await backfill_time(db)        # second run: only the unresolvable row is looked at; nothing written
    assert (s2.candidates, s2.filled, s2.unresolved) == (1, 0, 1)
    again = {k: await obs.get_observation(db, v) for k, v in ids.items()}
    assert again == after


@pytest.mark.asyncio
async def test_backfill_limit_and_empty_store(db, gw):
    assert (await backfill_time(db)).candidates == 0
    await _message(gw, "m1", "I went to the support group")
    await _legacy(db, "a", "yesterday")
    await _legacy(db, "b", "today")
    s = await backfill_time(db, limit=1)
    assert s.filled == 1
    assert (await backfill_time(db)).filled == 1
