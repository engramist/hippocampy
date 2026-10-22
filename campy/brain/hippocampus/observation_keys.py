"""
campy/brain/hippocampus/observation_keys.py -- B499: matching keys for attribute supersession.

Pure rules, no model, no I/O. Decides whether two `has_attribute` Observations
are "the same subject, the same attribute, a different value", which is when the
older one is superseded.

Why this is tolerant (measured on 40 LongMemEval knowledge-update stores, B499
follow-up): the extractor's `object_text` is not reliably "name: value".
It arrives as (a) "name: value", (b) a stringified JSON object
("{'name': 'tripod options', 'value': '...'}", keys name/attribute/key vary),
(c) a quantity phrase with the attribute inside it ("600 followers",
"completed 30 videos", "on page 220"), or (d) a bare value. Keying on the text
before the first colon matched none of (b)-(d), and for (b) it was worse than
useless: every object collapsed to the key "{'name'", so unrelated attributes of
one subject superseded each other.

An attribute is reduced to `AttrKey(tokens, value, kind)`:
- tokens: content tokens of the attribute name, lightly stemmed, stopwords and
  fillers dropped;
- value / kind: the normalised value and its type (number, duration, money,
  date, text); a quantity's unit words move into `tokens`.
Two keys match when their token sets are equal, or one is a subset of the other
with at least two shared tokens, AND the value kinds agree. Bare time/length
units alone ("5-6 hours") are not an attribute name, so such an object has no key.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass

_FIRST_PERSON = frozenset({"i", "me", "my", "myself", "mine", "we", "our", "ours", "us"})
_UNKNOWN_SPEAKER_SUBJECT = "the user"
_DETERMINERS = frozenset({"my", "our", "your", "his", "her", "their", "its", "the", "a", "an", "this", "that"})

_STOPWORDS = frozenset({
    "a", "an", "the", "my", "our", "your", "his", "her", "their", "its", "of", "in", "on", "at", "to", "for",
    "with", "and", "or", "is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "i", "me",
    "currently", "current", "now", "so", "far", "just", "really", "about", "approximately", "around",
    "name", "attribute", "key", "value", "time", "total", "number", "count", "level",
})
_SPELLING = {"favourite": "favorite", "colour": "color", "neighbour": "neighbor", "grey": "gray"}

# Units that, alone, say nothing about WHAT is measured ("5-6 hours", "$300").
_BARE_UNITS = frozenset({
    "second", "minute", "hour", "day", "week", "month", "year", "decade", "mile", "kilometer", "km", "meter",
    "foot", "feet", "inch", "pound", "lb", "kg", "kilogram", "gram", "dollar", "euro", "percent", "time",
})
_DURATION_UNITS = frozenset({"second", "minute", "hour", "day", "week", "month", "year", "decade"})

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "hundred": 100,
}
_NUM = r"(?:\d[\d,]*(?:\.\d+)?|" + "|".join(_NUMBER_WORDS) + r")"
_QUANTITY_RE = re.compile(rf"(?<![\w:]){_NUM}(?:\s*(?:-|to)\s*{_NUM})?(?![\w:])", re.IGNORECASE)
_CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_MONEY_RE = re.compile(r"[$€£]|\b(dollars?|euros?|usd|eur|gbp|bucks)\b", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(/\d{2,4})?|jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|"
    r"july?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)\b", re.IGNORECASE)

_NAME_KEYS = ("name", "attribute", "key", "field", "property", "label")
_VALUE_KEYS = ("value", "val", "amount", "answer")


@dataclass(frozen=True)
class AttrKey:
    tokens: frozenset[str]
    value: str
    kind: str          # number | duration | money | date | clock | text


def norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def stem(word: str) -> str:
    w = _SPELLING.get(word, word)
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def content_tokens(text: str | None) -> frozenset[str]:
    out = set()
    for raw in re.findall(r"[a-z0-9][a-z0-9'\-]*", norm(text).replace("’", "'")):
        w = raw.removesuffix("'s").strip("'-")
        if not w or w in _STOPWORDS:
            continue
        out.add(stem(w))
    return frozenset(t for t in out if t not in _STOPWORDS)


def _value_kind(value: str) -> str:
    v = norm(value)
    if _CLOCK_RE.match(v):
        return "clock"
    if _MONEY_RE.search(v):
        return "money"
    words = set(re.findall(r"[a-z]+", v))
    if any(stem(w) in _DURATION_UNITS for w in words) and _QUANTITY_RE.search(v):
        return "duration"
    if _DATE_RE.search(v) and re.search(r"\d", v):
        return "date"
    stripped = _QUANTITY_RE.sub(" ", v)
    if _QUANTITY_RE.search(v) and len(re.findall(r"[a-z]+", stripped)) <= 3:
        return "number"
    return "text"


def _quantity_key(phrase: str) -> AttrKey | None:
    """`"600 followers"` -> tokens {follower}, value "600". Exactly one quantity
    in the phrase; its trailing unit words and the rest of the phrase name the attribute."""
    p = norm(phrase)
    found = list(_QUANTITY_RE.finditer(p))
    if len(found) != 1 or _MONEY_RE.search(p):
        return None
    m = found[0]
    value = m.group(0).strip()
    tokens = content_tokens((p[:m.start()] + " " + p[m.end():]))
    if not tokens or tokens <= _BARE_UNITS:
        return None            # "5-6 hours": a value with no attribute name
    kind = "duration" if any(t in _DURATION_UNITS for t in tokens) else "number"
    return AttrKey(tokens, value, kind)


def _parse_mapping(text: str) -> tuple[str, str | None] | None:
    """A stringified/JSON mapping -> (name, value). `{'name': n, 'value': v}`
    (key names vary) or a single-pair `{n: v}`; None when it is not a mapping."""
    t = (text or "").strip()
    if not (t.startswith("{") and t.endswith("}")):
        return None
    data = None
    for loader in (json.loads, ast.literal_eval):
        try:
            data = loader(t)
            break
        except Exception:
            continue
    if not isinstance(data, dict) or not data:
        return None
    lowered = {str(k).strip().lower(): v for k, v in data.items()}
    name = next((lowered[k] for k in _NAME_KEYS if lowered.get(k) is not None), None)
    value = next((lowered[k] for k in _VALUE_KEYS if lowered.get(k) is not None), None)
    if name is not None:
        return str(name), None if value is None else str(value)
    if len(data) == 1:
        (k, v), = data.items()
        return str(k), None if v is None else str(v)
    return None


def parse_attribute(object_text: str | None) -> AttrKey | None:
    """The comparison key of one attribute object, or None when it has no attribute name
    and a value to compare (such an Observation neither supersedes nor is superseded)."""
    text = (object_text or "").strip()
    if not text:
        return None
    mapping = _parse_mapping(text)
    if mapping is not None:
        name, value = mapping
    elif ":" in text and not _CLOCK_RE.match(text):
        name, value = text.split(":", 1)
    else:
        return _quantity_key(text)
    name, value = name.strip(), (value or "").strip()
    if not value:
        return _quantity_key(name)          # {'watched 5 MCU films': None}
    tokens = content_tokens(name)
    # A quantity with its unit in the value ("20 videos") names more of the attribute.
    lead = _QUANTITY_RE.match(norm(value))
    if lead and not _MONEY_RE.search(value) and "," not in value \
            and len(re.findall(r"[a-z]+", norm(value)[lead.end():])) <= 3:
        vq = _quantity_key(f"{name} {value}")
        if vq is not None:
            return vq
    if not tokens:
        return None
    return AttrKey(tokens, norm(value), _value_kind(value))


def attribute_names_match(a: frozenset[str], b: frozenset[str]) -> bool:
    """Equal token sets, or one a subset of the other sharing at least two tokens."""
    if not a or not b:
        return False
    if a == b:
        return True
    shared = a & b
    return len(shared) >= 2 and (shared == a or shared == b)


def same_attribute_new_value(a: AttrKey | None, b: AttrKey | None) -> bool:
    """True when `a` and `b` name the same attribute, hold the same kind of value,
    and the values differ."""
    if a is None or b is None or a.value == b.value:
        return False
    return a.kind == b.kind and attribute_names_match(a.tokens, b.tokens)


# --- subject ------------------------------------------------------------------------

def subject_text_key(subject_text: str | None, speaker: str | None) -> str:
    """Who the claim is about, from the text. First-person forms and "the user" are
    keyed by speaker so two speakers' "I" never collide; a leading determiner
    ("my sister" / "the sister") is dropped; other words stay (a "new" lens is not an "old" one)."""
    text = norm(subject_text)
    if text in _FIRST_PERSON or text == _UNKNOWN_SPEAKER_SUBJECT:
        return f"self:{norm(speaker)}"
    words = text.split()
    while len(words) > 1 and words[0] in _DETERMINERS:
        words = words[1:]
    return "text:" + " ".join(words)


def same_subject(a: tuple[str | None, str | None, str | None], b: tuple[str | None, str | None, str | None]) -> bool:
    """Each argument is (subject_id, subject_text, speaker). Two resolved ids decide
    on their own; otherwise the text keys decide, so an id-resolved Observation
    and a text-only one about the same thing still match."""
    if a[0] and b[0]:
        return a[0] == b[0]
    return subject_text_key(a[1], a[2]) == subject_text_key(b[1], b[2])


def subject_text_variants(subject_text: str | None) -> list[str]:
    """The exact stored `subject_text` spellings that `same_subject` can treat as this
    subject, for the exact-match candidate lookup (case differs per row, so each
    spelling is tried as written and lower-cased)."""
    raw = " ".join((subject_text or "").split())
    key = subject_text_key(raw, "")
    spellings: list[str] = []
    if key.startswith("self:"):
        spellings += ["I", "me", "my", "myself", "the user", "We", "we", "our", "us"]
    else:
        core = key[len("text:"):]
        spellings += [raw, core] + [f"{d} {core}" for d in ("my", "our", "the", "your", "his", "her", "their")]
    seen: dict[str, None] = {}
    for s in spellings:
        for v in (s, s.lower(), s.capitalize()):
            if v:
                seen.setdefault(v)
    return list(seen)
