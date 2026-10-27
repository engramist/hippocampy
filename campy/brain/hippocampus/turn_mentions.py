"""
B538: relative dates in user turns, resolved by rule and stored in the graph.

Behind `[observations] turn_dates` (default false; env `CAMPY_TURN_DATES=1`).

Write: `write_turn_mentions(gw, message_id, text, anchor)` finds the relative time
expressions of one user turn (`temporal_lobe.observations.turn_dates`), resolves
each against `anchor` (the turn's `occurred_at`, else its `created_at`) and
writes one `TimeMention` per expression, linked `Message -HAS_TIME_MENTION->`.
`backfill_turn_mentions(db)` does the same for every live user turn of a store
written without it; both are idempotent (a mention's id is the turn plus its
character span, and `turn_mentions.upsert` rewrites in place).

Read: `load_mentions(gw, message_uris)` returns the stored mentions of the turns
the bundle is about to show, and `annotate_turn(text, mentions)` writes the
resolved date right after each phrase (`... we went yesterday [= 2023-05-07] ...`).
Rendering only reads; the model never does the date arithmetic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from campy.brain.temporal_lobe.observations.timeparse import format_resolved
from campy.brain.temporal_lobe.observations.turn_dates import annotate, find_time_expressions

_logger = logging.getLogger(__name__)

TURN_DATES_SUFFIX = ("; a bracketed [= date] after a time phrase is that phrase resolved to a calendar date "
                     "by rule, against the date of the turn it is in")


def turn_dates_enabled(config: dict | None) -> bool:
    """`[observations] turn_dates` (default false; env `CAMPY_TURN_DATES=1` turns it on)."""
    return bool(((config or {}).get("observations") or {}).get("turn_dates", False))


def _as_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).strip()
        return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None


async def write_turn_mentions(gw: Any, message_id: str, text: str | None, anchor: Any) -> int:
    """Resolve and store the relative time expressions of one user turn.
    Returns how many were written (0 when there is none or no usable anchor)."""
    anchor_dt = _as_dt(anchor)
    if anchor_dt is None:
        return 0
    now = datetime.now(timezone.utc)
    n = 0
    for sp in find_time_expressions(text, anchor_dt):
        await gw.run(
            "turn_mentions.upsert", mid=message_id, mention_id=f"{message_id}:{sp.start}-{sp.end}",
            time_text=sp.phrase, span_start=sp.start, span_end=sp.end,
            time_start=sp.resolved.start, time_end=sp.resolved.end,
            time_precision=sp.resolved.precision, now=now,
        )
        n += 1
    return n


async def backfill_turn_mentions(db: Any, *, limit: int | None = None) -> dict[str, int]:
    """One pass over a store written without `turn_dates`: every live user turn
    with a usable date gets its mentions, by the same rule as the write path.
    Idempotent. WRITES: run it at ingest or on a copy of a store, never in the
    read path of `ask`. `limit` caps how many turns are written this call."""
    from campy.brain.hippocampus.graph.gateway import get_gateway

    gw = get_gateway(db)
    stats = {"turns": 0, "turns_with_mentions": 0, "mentions": 0, "no_date": 0}
    for row in await gw.run("turn_mentions.list_user_turns"):
        stats["turns"] += 1
        anchor = row.get("occurred_at") or row.get("created_at")
        if _as_dt(anchor) is None:
            stats["no_date"] += 1
            continue
        if limit is not None and stats["turns_with_mentions"] >= limit:
            continue
        n = await write_turn_mentions(gw, row["message_id"], row.get("text_raw"), anchor)
        if n:
            stats["turns_with_mentions"] += 1
            stats["mentions"] += n
    _logger.info("[TurnDates] backfill: %s", stats)
    return stats


async def load_mentions(gw: Any, message_uris: list[str]) -> dict[str, list[dict]]:
    """The stored mentions of the given Messages (instance URIs), by URI, in
    reading order. Empty on any failure: a missing annotation never breaks the bundle."""
    uris = [u for u in dict.fromkeys(message_uris) if u]
    if not uris:
        return {}
    try:
        rows = await gw.run("turn_mentions.for_messages", ms=uris)
    except Exception:
        _logger.warning("[TurnDates] mention read failed", exc_info=True)
        return {}
    out: dict[str, list[dict]] = {}
    for r in rows or []:
        get = r.get
        out.setdefault(str(get("m")), []).append({
            "id": get("mention_id"), "phrase": get("time_text"), "start": get("span_start"), "end": get("span_end"),
            "resolved": format_resolved(get("time_start"), get("time_end"), get("time_precision")),
        })
    return out


def annotate_turn(text: str, mentions: list[dict] | None) -> str:
    """`text` with ` [= <resolved date>]` right after each stored phrase. The
    stored character span is used when it still holds the phrase; otherwise (the
    shown text is a cut of the turn) the phrase is looked up in the shown text,
    and a phrase that is not there is skipped."""
    if not mentions or not text:
        return text
    lowered = text.lower()
    spans: list[tuple[int, int, str]] = []
    taken: set[int] = set()
    for m in mentions:
        phrase, resolved = str(m.get("phrase") or ""), m.get("resolved")
        if not phrase or not resolved:
            continue
        s, e = m.get("start"), m.get("end")
        if isinstance(s, int) and isinstance(e, int) and lowered[s:e] == phrase.lower() and s not in taken:
            pos = s
        else:
            pos, at = -1, 0
            while True:
                at = lowered.find(phrase.lower(), at)
                if at < 0:
                    break
                if at not in taken:
                    pos = at
                    break
                at += 1
            if pos < 0:
                continue
        taken.add(pos)
        spans.append((pos, pos + len(phrase), resolved))
    return annotate(text, spans)
