"""
B484 (plan item M4.2): time normalisation for Observations.

`normalize_time(time_text, anchor)` turns the time phrase a speaker used
("yesterday", "last Saturday", "two weeks ago", "7 May 2023") into an ISO date
range against the date the turn was said (`anchor`, the evidence Message's
`occurred_at`). Pure, stdlib-only, rule-based: no LLM, no dependency, no
dataset-specific cases. Anything it does not recognise or that is genuinely
ambiguous returns None, and the caller keeps `time_start`/`time_end` NULL; the
phrase is still stored as written (`time_text`).

Output: `(start, end, precision)`, both datetimes at 00:00 UTC. `end` is the
INCLUSIVE last day of the range (same as `start` for a single day).
`precision` is one of day / week / month / year (a TIME_PRECISIONS member).

Conventions (each is a deliberate choice, stated once here):
- Weeks run Monday..Sunday (ISO). A "weekend" is that week's Saturday..Sunday
  and has precision "day" with a two-day range.
- "last <weekday>" is the most recent such day strictly before the anchor; "next
  <weekday>" the first strictly after it; "this <weekday>" the one in the
  anchor's own ISO week. A bare weekday ("on Saturday") is ambiguous -> None.
- "N weeks/months/years ago" resolves to the week / month / year containing the
  shifted date (precision week / month / year), not to a day: the speaker did
  not say which day. "N days ago" is a day.
- A date with no year ("7 May", "May") resolves to the occurrence nearest the
  anchor (ties go to the past). A numeric date with both parts <= 12 and
  different ("03/04/2023") is ambiguous (US vs day-first) -> None.
- A bare "the week before" / "the previous week" is relative to the anchor
  (same as "last week"); "the <unit> before/after <date>" is relative to that
  date.
- Vague amounts ("a few days ago", "recently", "the other day"), seasons,
  holidays, "since X", "until X", ranges and times of day alone -> None.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

__all__ = ["Resolved", "normalize_time", "format_resolved"]


class Resolved(NamedTuple):
    start: datetime
    end: datetime
    precision: str


_UNITS = ("day", "week", "month", "year")
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "a couple of": 2, "a couple": 2, "couple of": 2,
}
_NUM = r"(?:\d{1,3}|" + "|".join(sorted((re.escape(k) for k in _NUMBER_WORDS), key=len, reverse=True)) + r")"
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD = r"(" + "|".join(_WEEKDAYS) + r")"
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
                "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
_MON = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_FULL_MON = r"(" + "|".join(name.lower() for name in calendar.month_name if name) + r")"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"

_PART_OF_DAY = r"(?:morning|afternoon|evening|night)"
_CLOCK = r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)"

_OPEN_ENDED = ("since ", "until ", "till ", "before ", "after ", "from ", "between ")
_SHIFT_WORDS = {"last": -1, "previous": -1, "past": -1, "prior": -1, "this": 0, "current": 0,
                "next": 1, "coming": 1, "upcoming": 1}


def _utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _day(d: date) -> Resolved:
    return Resolved(_utc(d), _utc(d), "day")


def _week_of(d: date) -> Resolved:
    monday = d - timedelta(days=d.weekday())
    return Resolved(_utc(monday), _utc(monday + timedelta(days=6)), "week")


def _weekend_of(d: date) -> Resolved:
    saturday = d - timedelta(days=d.weekday()) + timedelta(days=5)
    return Resolved(_utc(saturday), _utc(saturday + timedelta(days=1)), "day")


def _add_months(y: int, m: int, n: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + n
    return idx // 12, idx % 12 + 1


def _month_range(y: int, m: int) -> Resolved | None:
    if not (1 <= y <= 9999) or not (1 <= m <= 12):
        return None
    return Resolved(_utc(date(y, m, 1)), _utc(date(y, m, calendar.monthrange(y, m)[1])), "month")


def _year_range(y: int) -> Resolved | None:
    if not (1 <= y <= 9999):
        return None
    return Resolved(_utc(date(y, 1, 1)), _utc(date(y, 12, 31)), "year")


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _shift_unit(anchor: date, unit: str, n: int) -> Resolved | None:
    """The `unit` containing `anchor` shifted by n units (n may be negative)."""
    try:
        if unit == "day":
            return _day(anchor + timedelta(days=n))
        if unit == "week":
            return _week_of(anchor + timedelta(days=7 * n))
        if unit == "month":
            y, m = _add_months(anchor.year, anchor.month, n)
            return _month_range(y, m)
        if unit == "year":
            return _year_range(anchor.year + n)
    except (OverflowError, ValueError):
        return None
    return None


def _number(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        n = int(token)
        return n if 0 < n <= 999 else None
    return _NUMBER_WORDS.get(token)


def _nearest_year(month: int, day: int, anchor: date) -> int | None:
    best_key, best_year = None, None
    for y in (anchor.year - 1, anchor.year, anchor.year + 1):
        d = _safe_date(y, month, day)
        if d is None:
            continue
        key = (abs((d - anchor).days), 0 if d <= anchor else 1)   # tie -> the past
        if best_key is None or key < best_key:
            best_key, best_year = key, y
    return best_year


def _nearest_month(month: int, anchor: date) -> Resolved | None:
    best_key = None
    best_year = None
    for y in (anchor.year - 1, anchor.year, anchor.year + 1):
        diff = (y * 12 + month) - (anchor.year * 12 + anchor.month)
        key = (abs(diff), 0 if diff <= 0 else 1)
        if best_key is None or key < best_key:
            best_key, best_year = key, y
    return _month_range(best_year, month) if best_year else None


# --- absolute dates --------------------------------------------------------------------

def _absolute(t: str, anchor: date | None) -> Resolved | None:
    """An explicit calendar date, month or year. `anchor` is only needed when
    the year is missing."""
    t = re.sub(r"^(?:on|in|at|around|about)\s+", "", t)
    t = re.sub(r"^" + _WD + r",?\s+", "", t)            # "sunday, 7 may 2023"
    t = re.sub(r"^the\s+", "", t)

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[t ].*)?", t)
    if m:
        d = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        return _day(d) if d else None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", t)
    if m:
        return _month_range(int(m[1]), int(m[2]))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12 and b <= 12:
            d = _safe_date(y, b, a)
        elif b > 12 and a <= 12:
            d = _safe_date(y, a, b)
        elif a == b and a <= 12:
            d = _safe_date(y, a, b)
        else:
            return None                                  # 03/04/2023: US or day-first?
        return _day(d) if d else None

    # 7 may 2023 / 7th of may, 2023 / 7 may
    m = re.fullmatch(_DAY + r"\s+(?:of\s+)?" + _MON + r"(?:,?\s+(\d{4}))?", t)
    if m:
        return _month_day(int(m[1]), _MONTHS[m[2]], m[3], anchor)
    # may 7, 2023 / may 7th / may 7
    m = re.fullmatch(_MON + r"\s+" + _DAY + r"(?:,?\s+(\d{4}))?", t)
    if m:
        return _month_day(int(m[2]), _MONTHS[m[1]], m[3], anchor)
    # may 2023 / may of 2023 / may, 2023
    m = re.fullmatch(_MON + r",?\s+(?:of\s+)?(\d{4})", t)
    if m:
        return _month_range(int(m[2]), _MONTHS[m[1]])
    # may  (full month names only: "mar"/"sat"-style abbreviations are too loose alone)
    m = re.fullmatch(_FULL_MON, t)
    if m and anchor is not None:
        return _nearest_month(_MONTHS[m[1]], anchor)
    m = re.fullmatch(r"(\d{4})", t)
    if m and 1900 <= int(m[1]) <= 2100:
        return _year_range(int(m[1]))
    return None


def _month_day(day: int, month: int, year_text: str | None, anchor: date | None) -> Resolved | None:
    if year_text:
        d = _safe_date(int(year_text), month, day)
    else:
        if anchor is None:
            return None
        y = _nearest_year(month, day, anchor)
        d = _safe_date(y, month, day) if y else None
    return _day(d) if d else None


# --- relative phrases ------------------------------------------------------------------

def _relative(t: str, a: date) -> Resolved | None:
    # today / tonight / this morning ...
    if re.fullmatch(r"(?:today|tonight|(?:earlier |later )?today|this (?:morning|afternoon|evening|night)|"
                    r"right now|just now|now)", t):
        return _day(a)
    if re.fullmatch(r"yesterday|last (?:night|evening)", t):
        return _day(a - timedelta(days=1))
    if re.fullmatch(r"(?:the )?day before yesterday", t):
        return _day(a - timedelta(days=2))
    if t == "tomorrow":
        return _day(a + timedelta(days=1))
    if re.fullmatch(r"(?:the )?day after tomorrow", t):
        return _day(a + timedelta(days=2))

    # N units ago / in N units
    m = re.fullmatch(r"(?:about |around |almost |roughly |nearly )?(" + _NUM + r")\s+(day|week|month|year)s?\s+ago", t)
    if m:
        n = _number(m[1])
        return _shift_unit(a, m[2], -n) if n else None
    m = re.fullmatch(r"in\s+(?:about |around )?(" + _NUM + r")\s+(day|week|month|year)s?(?:'? time)?", t)
    if m:
        n = _number(m[1])
        return _shift_unit(a, m[2], n) if n else None

    # last / this / next <weekday>
    m = re.fullmatch(r"(last|past|this|next|coming|this coming|this past)\s+" + _WD, t)
    if m:
        return _weekday(m[1], _WEEKDAYS.index(m[2]), a)

    # last / this / next week | month | year | weekend  (also "the previous week", "earlier this week")
    m = re.fullmatch(r"(?:earlier |later |early |late )?(?:the |this )?(last|past|previous|prior|this|current|next|"
                     r"coming|upcoming|this past|this coming)\s+(week|month|year|weekend)", t)
    if m:
        shift = _SHIFT_WORDS[m[1].split()[-1]]
        if m[2] == "weekend" and m[1] in ("past", "this past"):
            shift = 0 if a.weekday() >= 5 else -1       # the most recent weekend, today's if it is one
        return _period(m[2], shift, a)
    m = re.fullmatch(r"(?:earlier|later|sometime|early|late)\s+this\s+(week|month|year)", t)
    if m:
        return _period(m[1], 0, a)
    if re.fullmatch(r"the week before", t):
        return _period("week", -1, a)
    return None


def _weekday(word: str, wd: int, a: date) -> Resolved | None:
    kind = word.split()[-1]
    if kind in ("last", "past"):
        delta = (a.weekday() - wd) % 7 or 7
        return _day(a - timedelta(days=delta))
    if kind in ("next", "coming"):
        delta = (wd - a.weekday()) % 7 or 7
        return _day(a + timedelta(days=delta))
    if kind == "this":
        monday = a - timedelta(days=a.weekday())
        return _day(monday + timedelta(days=wd))
    return None


def _period(unit: str, shift: int, a: date) -> Resolved | None:
    if unit == "weekend":
        return _weekend_of(a + timedelta(days=7 * shift))
    return _shift_unit(a, unit, shift)


def _relative_to_date(t: str, anchor: date | None) -> Resolved | None:
    """"the week before 9 June 2023", "two days after 7 May 2023", "the Sunday
    before 25 May 2023": relative to an explicit date inside the phrase."""
    m = re.fullmatch(r"(?:the\s+)?(?:(" + _NUM + r")\s+)?(day|week|month|year|weekend|" + "|".join(_WEEKDAYS) +
                     r")s?\s+(before|after)\s+(.+)", t)
    if not m:
        return None
    ref = _absolute(m[4], anchor)
    if ref is None or ref.precision != "day" or ref.start != ref.end:
        return None
    ref_day = ref.start.date()
    sign = -1 if m[3] == "before" else 1
    unit = m[2]
    n = _number(m[1]) if m[1] else 1
    if not n:
        return None
    if unit in _UNITS:
        return _shift_unit(ref_day, unit, sign * n)
    if m[1]:
        return None                                       # "two Sundays before": not supported
    if unit == "weekend":
        return _weekend_of(ref_day + timedelta(days=7 * sign))
    wd = _WEEKDAYS.index(unit)
    if sign < 0:
        return _day(ref_day - timedelta(days=(ref_day.weekday() - wd) % 7 or 7))
    return _day(ref_day + timedelta(days=(wd - ref_day.weekday()) % 7 or 7))


# --- public ------------------------------------------------------------------------------

def normalize_time(time_text: str | None, anchor: datetime | date | None) -> Resolved | None:
    """Resolve a time phrase to `(start, end, precision)` or None.

    `anchor` is when the phrase was said (the Message's occurred_at); only its
    calendar date is used. With `anchor=None`, only phrases that carry their own
    year (e.g. "7 May 2023", "2023-05", "2019") resolve."""
    if not time_text or not isinstance(time_text, str):
        return None
    t = " ".join(time_text.lower().replace("’", "'").split()).strip(" .,;:!?\"'()")
    if not t or len(t) > 60:
        return None
    if t.startswith(_OPEN_ENDED) or re.search(r"\b(?:to|until|through)\b", t):
        return None                                       # open-ended or a range, not one date

    a = anchor.date() if isinstance(anchor, datetime) else anchor

    # An hour of the day or a part of the day adds nothing at day granularity.
    if t not in ("last night", "last evening", "tonight", "this evening", "this morning", "this afternoon", "this night"):
        t = re.sub(_CLOCK + "$", "", t)
        t = re.sub(r"\s+(?:in the\s+)?" + _PART_OF_DAY + r"$", "", t) if t != _PART_OF_DAY else t
    t = re.sub(r"^(?:on|at|around|about|approximately|roughly)\s+", "", t)

    result = _relative_to_date(t, a)
    if result is None and a is not None:
        result = _relative(t, a)
    if result is None:
        result = _absolute(t, a)
    return result


def format_resolved(start: datetime | date | str | None, end: datetime | date | str | None,
                    precision: str | None) -> str | None:
    """Human/LLM-readable form of a stored range: day -> `2023-05-07`;
    multi-day -> `2023-05-06 to 2023-05-07`; week -> `week of 2023-04-24`;
    month -> `2023-05`; year -> `2023`. None when `start` is unset."""
    s = _to_date(start)
    if s is None:
        return None
    e = _to_date(end) or s
    if precision == "week":
        return f"week of {s.isoformat()}"
    if precision == "month":
        return f"{s.year:04d}-{s.month:02d}"
    if precision == "year":
        return f"{s.year:04d}"
    if e != s:
        return f"{s.isoformat()} to {e.isoformat()}"
    return s.isoformat()


def _to_date(value: datetime | date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
