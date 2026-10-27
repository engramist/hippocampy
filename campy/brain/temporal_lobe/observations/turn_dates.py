"""
B538: relative dates in a turn, resolved by rule.

`find_time_expressions(text, anchor)` finds the relative time expressions in a
turn ("yesterday", "last week", "three days ago", "next month", "last Friday")
and resolves each against the date the turn was said (`anchor`, the Message's
`occurred_at`) with `timeparse.normalize_time`. The model never does that
arithmetic (PRINCIPLES 3): the rule does, once, at capture, and the bundle shows
the answer next to the words.

Same rule set as B484: this module only FINDS the spans (a closed list of
relative forms); `normalize_time` decides what each one means and stays the one
place the calendar conventions live. Anything it cannot resolve is dropped, so
a span is never annotated with a guess.

Deliberately not annotated:
- `today`, `tonight`, `this morning`, `now`: they are the turn's own date, which
  the stamp already shows. Any expression that resolves to the anchor day is dropped.
- a bare weekday ("on Saturday"), `the past year`, `the other day`, `recently`,
  `a few days ago`: ambiguous or vague; `normalize_time` returns None for them or
  they are not candidates. `the last year` / `the next month` (a rolling window,
  not the calendar period) is skipped too.
- absolute dates ("7 May 2023"): nothing to compute.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import NamedTuple

from campy.brain.temporal_lobe.observations.timeparse import (
    _NUM, _WD, Resolved, format_resolved, normalize_time,
)

__all__ = ["TimeSpan", "find_time_expressions", "annotate", "resolved_text"]


class TimeSpan(NamedTuple):
    start: int            # character offset of the phrase in the turn text
    end: int              # one past its last character
    phrase: str           # the words as written
    resolved: Resolved


_UNIT = r"(?:day|week|month|year)"
_ROLLING = re.compile(r"(?:last|next|this)\s+(?:week|month|year|weekend)$", re.IGNORECASE)
_CANDIDATE = re.compile(
    r"(?<![\w-])(?:"
    r"(?:the\s+)?day\s+(?:before\s+yesterday|after\s+tomorrow)"
    r"|yesterday|tomorrow"
    r"|last\s+(?:night|evening)"
    r"|(?:about\s+|around\s+|almost\s+|roughly\s+|nearly\s+)?" + _NUM + r"\s+" + _UNIT + r"s?\s+ago"
    r"|in\s+(?:about\s+|around\s+)?" + _NUM + r"\s+" + _UNIT + r"s?(?:'?\s*time)?"
    r"|(?:last|next|this\s+past|this\s+coming|this|coming)\s+" + _WD +
    r"|(?:last|next|this)\s+(?:week|month|year|weekend)"
    r")(?![\w-])",
    re.IGNORECASE,
)


def _as_date(anchor: datetime | date | str | None) -> date | None:
    if anchor is None or anchor == "":
        return None
    if isinstance(anchor, datetime):
        return anchor.date()
    if isinstance(anchor, date):
        return anchor
    try:
        return date.fromisoformat(str(anchor)[:10])
    except ValueError:
        return None


def find_time_expressions(text: str | None, anchor: datetime | date | str | None) -> list[TimeSpan]:
    """The relative time expressions in `text`, each resolved against `anchor`,
    in reading order. Empty when there is no anchor, no expression, or none that
    resolves to something other than the anchor day."""
    a = _as_date(anchor)
    if not text or a is None:
        return []
    out: list[TimeSpan] = []
    for m in _CANDIDATE.finditer(text):
        phrase = m.group(0)
        if _ROLLING.fullmatch(phrase) and text[:m.start()].lower().endswith(("the ", "of ")):
            continue                      # "over the last year", "in the next month": a window, not a period
        r = normalize_time(phrase, a)
        if r is None:
            continue
        if r.precision == "day" and r.start == r.end and r.start.date() == a:
            continue                      # the turn's own day: the stamp already says it
        out.append(TimeSpan(m.start(), m.end(), phrase, r))
    return out


def annotate(text: str, spans: list[tuple[int, int, str]]) -> str:
    """`text` with ` [= <resolved>]` inserted right after each span, so the
    reader sees the resolved date where it reads the words. `spans` is
    (start, end, resolved_text); spans that do not fit `text`, or that overlap an
    earlier one, are skipped."""
    out: list[str] = []
    pos = 0
    for start, end, resolved in sorted(spans):
        if start < pos or end > len(text) or start >= end or not resolved:
            continue
        out.append(text[pos:end])
        out.append(f" [= {resolved}]")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def resolved_text(r: Resolved) -> str | None:
    """The date a Resolved range reads as (`2023-05-07`, `week of 2023-04-24`, ...)."""
    return format_resolved(r.start, r.end, r.precision)
