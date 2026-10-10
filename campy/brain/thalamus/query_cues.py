"""B479: what a question says about WHO and WHEN, parsed with rules (no LLM).

A conversation question often names the speaker whose turn holds the answer
("What did Speaker 1 say about...", "Where has Melanie camped?") and
sometimes an explicit time ("in May 2023"). The conversation stage can use
both to BOOST (never filter) the candidates that match. This module only
parses; `GraphGateway._apply_query_cues` applies the boost.

Rules (each a statement about conversations, not about any dataset):

* Speaker. A "Speaker N" label, or any name in `known_speakers` (the
  speakers actually present among the retrieval candidates), is a mention.
  A name is matched whole-word and case-sensitively ("Will" the speaker, not
  "will" the modal); "Speaker N" is case-insensitive.
* Which mention is the evidence speaker. The turn sought is the one by the
  speaker the question says SAID something:
    - a mention followed by a statement verb ("Speaker 1 said", "did Melanie
      mention", "Speaker 1 also told") or preceded by "according to" is the
      evidence speaker: weight 1.0;
    - a mention that is the ADDRESSEE ("asks Speaker 1", "told Speaker 1",
      "to Speaker 1") and not otherwise marked is not evidence;
    - so "Speaker 2 asks Speaker 1 what Speaker 1 said" boosts Speaker 1 only,
      and "What did Speaker 2 ask Speaker 1 about" boosts Speaker 2 only
      (the one asking is the subject; the addressee is dropped);
    - if no mention is marked, the non-addressee mentions share the weight:
      a single one gets 1.0, several get 0.5 each ("lightly, both");
    - if every mention is an addressee, all are used at 0.5 each.
* Time. Only absolute expressions resolve: ISO dates (2023-05-08), "May 8,
  2023" / "8 May 2023" / "8th of May 2023", "May 2023", and a bare year after
  in/during/throughout ("in 2023"). A month with no year ("in May") and
  relative phrases ("last week", "yesterday") are NOT resolvable and yield no
  range. Ranges are half-open ISO dates [start, end); several expressions give
  several ranges, and a turn inside any of them matches.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR = r"((?:19|20)\d{2})"

_ISO = re.compile(rf"\b{_YEAR}-(\d{{2}})-(\d{{2}})\b")
_DAY_MON_YEAR = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?,?\s+{_YEAR}\b", re.I)
_MON_DAY_YEAR = re.compile(
    rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+{_YEAR}\b", re.I)
_MON_YEAR = re.compile(rf"\b({_MON})\.?,?\s+{_YEAR}\b", re.I)
_IN_YEAR = re.compile(rf"\b(?:in|during|throughout)\s+(?:the\s+year\s+)?{_YEAR}\b", re.I)

_SPEAKER_N = re.compile(r"\bspeaker\s*(\d+)\b", re.I)
_STATEMENT = (
    r"\s+(?:also\s+|ever\s+|previously\s+|once\s+|had\s+|has\s+|have\s+)?"
    r"(?:said|say|says|saying|mention(?:ed|s)?|told|tell|tells|stated|state|states|shared|share|"
    r"shares|explained|replied|answered|described|noted|claimed|recalled|talked|spoke|speak|"
    r"revealed|admitted|reported)\b"
)
_AFTER_EVIDENCE = re.compile(r"(?:'s)?" + _STATEMENT, re.I)
_BEFORE_EVIDENCE = re.compile(r"\baccording\s+to\s+$", re.I)
_BEFORE_ADDRESSEE = re.compile(r"\b(?:ask|asks|asked|asking|to|tell|tells|told)\s+$", re.I)


@dataclass(frozen=True)
class QueryCues:
    """`speakers`: ((casefolded speaker, weight), ...); `time_ranges`: ((start,
    end), ...) ISO dates, end exclusive. Both empty when the question names none."""
    speakers: tuple[tuple[str, float], ...] = ()
    time_ranges: tuple[tuple[str, str], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.speakers or self.time_ranges)


def _span(start: date, end: date) -> tuple[str, str]:
    return start.isoformat(), end.isoformat()


def _month_span(year: int, month: int) -> tuple[str, str]:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return _span(start, end)


def _parse_times(question: str) -> tuple[tuple[str, str], ...]:
    text, out = question, []

    def take(rx: re.Pattern, build) -> None:
        nonlocal text
        for m in rx.finditer(text):
            try:
                out.append(build(m))
            except ValueError:  # 31 February
                pass
        text = rx.sub(" ", text)  # consume, so "May 8, 2023" is not also "May 2023"

    def day(y: int, mo: int, d: int) -> tuple[str, str]:
        start = date(y, mo, d)
        return _span(start, start + timedelta(days=1))

    take(_ISO, lambda m: day(int(m[1]), int(m[2]), int(m[3])))
    take(_DAY_MON_YEAR, lambda m: day(int(m[3]), _MONTHS[m[2].lower()], int(m[1])))
    take(_MON_DAY_YEAR, lambda m: day(int(m[3]), _MONTHS[m[1].lower()], int(m[2])))
    take(_MON_YEAR, lambda m: _month_span(int(m[2]), _MONTHS[m[1].lower()]))
    take(_IN_YEAR, lambda m: _span(date(int(m[1]), 1, 1), date(int(m[1]) + 1, 1, 1)))
    return tuple(dict.fromkeys(out))


def _parse_speakers(question: str, known_speakers) -> tuple[tuple[str, float], ...]:
    mentions: list[tuple[int, int, str]] = []  # (start, end, casefolded name)
    for m in _SPEAKER_N.finditer(question):
        mentions.append((m.start(), m.end(), f"speaker {int(m[1])}"))
    taken = [(s, e) for s, e, _ in mentions]
    for name in sorted({str(k).strip() for k in known_speakers or () if k}, key=len, reverse=True):
        if len(name) < 2:
            continue
        for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", question):
            if not any(s < m.end() and m.start() < e for s, e in taken):
                mentions.append((m.start(), m.end(), name.casefold()))
                taken.append((m.start(), m.end()))
    if not mentions:
        return ()
    mentions.sort()
    evidence, neutral, addressee = {}, {}, {}
    for start, end, name in mentions:
        before, after = question[:start], question[end:]
        if _AFTER_EVIDENCE.match(after) or _BEFORE_EVIDENCE.search(before):
            evidence[name] = 1.0
        elif _BEFORE_ADDRESSEE.search(before):
            addressee[name] = 0.5
        else:
            neutral[name] = 1.0
    for name in evidence:
        neutral.pop(name, None)
        addressee.pop(name, None)
    if evidence:
        return tuple(evidence.items())
    for name in neutral:
        addressee.pop(name, None)
    if neutral:
        w = 1.0 if len(neutral) == 1 else 0.5
        return tuple((n, w) for n in neutral)
    return tuple(addressee.items())


def parse_query_cues(question: str, known_speakers=()) -> QueryCues:
    """Pure: the speaker(s) and explicit time range(s) a question names."""
    question = str(question or "")
    if not question.strip():
        return QueryCues()
    return QueryCues(_parse_speakers(question, known_speakers), _parse_times(question))
