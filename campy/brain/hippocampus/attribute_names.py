"""
campy/brain/hippocampus/attribute_names.py -- B511: where an attribute's name comes from.

B509 links a `has_attribute` Observation to an AttributeProperty only when its object parses
as an attribute name plus a value (observation_keys.parse_attribute). Measured on a fresh
LoCoMo ingest (R95): 4% of the objects are written "name: value"; the rest are free phrases
or a bare value, so 92% of attribute Observations had no property and nothing could supersede.

This module supplies the name by structure, never by guess. Pure rules, no model, no I/O.
Two sources, in this order (the first that yields a name wins):

  1. The extractor's structured `attribute` field {"name", "value"} (flag `owl_properties`):
     advice, accepted only when `validate_structured` passes: the name is a short noun phrase
     and the value appears in the turn as written.
  2. Rules over what was written, each requiring the value to appear in the turn:
       quantity   "500 followers" -> followers = 500; "currently on page 200" -> page = 200
                  (B499's `_quantity_key`; a quantity that is the head of "N of ..." is not one)
       copula     "my favorite color is blue" / "Max's age is 3": the noun phrase before
                  "is" names the attribute, the object is the value; the possessor must be
                  the claim's subject
       count      the object is only a number ("four"); the noun after it in the turn
                  names it ("my four dogs" -> dogs = four)
       age        "3-year-old" / "30 years old" -> age = 3 years
       name       "name: Scout" (the colon form with the literal word "name")

Anything else (a verb phrase such as "loves hiking", a bare value such as "park") gets NO name:
the Observation stays unlinked rather than carrying an invented property.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from campy.brain.hippocampus import observation_keys as ok

MAX_NAME_WORDS = 3
MAX_NAME_CHARS = 40
MAX_VALUE_CHARS = 80

_NAME_RE = re.compile(r"^[a-z][a-z'\-]*(?: [a-z][a-z'\-]*){0,2}$")
_POSSESSIVE_LEAD = frozenset({"my", "our", "your", "his", "her", "their", "the"})
_NOT_NAME_WORDS = frozenset({
    "is", "are", "was", "were", "be", "am", "has", "have", "had", "do", "does", "did", "to", "and", "or", "that",
    "which", "who", "it", "they", "he", "she", "we", "you", "i", "this", "there",
})
_PLACEHOLDER = frozenset({"attribute", "value", "property", "thing", "stuff", "something", "info", "information",
                          "fact", "detail", "item", "one", "other"})
_PARTITIVE_RE = re.compile(rf"\b{ok._NUM}\s+of\b", re.IGNORECASE)
_AGE_RE = re.compile(r"^(\d{1,3})[- ]years?[- ]old$", re.IGNORECASE)
_COPULA_RE = re.compile(
    r"\b(my|our|[a-z][a-z\-]+'s)\s+((?:[a-z][a-z\-]*\s+){0,2}[a-z][a-z\-]*)\s+(?:is|are|was|were)\s+"
    r"(?:now\s+|currently\s+|about\s+|around\s+|at\s+|only\s+)?([^.,;!?]+)", re.IGNORECASE)


def _squash(text: str | None) -> str:
    return ok.norm((text or "").replace("’", "'"))


def value_in_turn(value: str, turn: str | None) -> bool:
    """The value appears in the turn as written (case, spacing and thousands commas aside)."""
    v, t = _squash(value), _squash(turn)
    if not v or not t:
        return False
    return v in t or v.replace(",", "") in t.replace(",", "")


def name_is_valid(name: str | None) -> str | None:
    """The cleaned attribute name when it is a short noun phrase, else None."""
    n = _squash(name)
    if not n or len(n) > MAX_NAME_CHARS or not _NAME_RE.match(n):
        return None
    words = n.split()
    while len(words) > 1 and words[0] in _POSSESSIVE_LEAD:
        words = words[1:]
    if len(words) > MAX_NAME_WORDS or any(w in _NOT_NAME_WORDS for w in words):
        return None
    if words == ["name"]:
        return "name"
    tokens = ok.content_tokens(" ".join(words))
    if not tokens or tokens <= _PLACEHOLDER or tokens <= ok._BARE_UNITS:
        return None
    return " ".join(words)


def _as_text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return " ".join(value.split()) or None
    return None


def validate_structured(attribute: Any, turn: str | None) -> tuple[tuple[str, str] | None, str | None]:
    """The extractor's `attribute` field -> ((name, value), None) when it passes the rules,
    else (None, reason). `None` input is not a rejection: the model had nothing to say."""
    if attribute is None:
        return None, None
    if not isinstance(attribute, dict):
        return None, "attribute_malformed"
    name = name_is_valid(_as_text(attribute.get("name")))
    if name is None:
        return None, "attribute_name_invalid"
    value = _as_text(attribute.get("value"))
    if not value or len(value) > MAX_VALUE_CHARS or value.startswith(("{", "[")):
        return None, "attribute_value_invalid"
    if not value_in_turn(value, turn):
        return None, "attribute_value_not_in_turn"
    return (name, value), None


def key_from_pair(name: str, value: str) -> ok.AttrKey | None:
    return ok.parse_attribute(f"{name}: {value}")


# --- rules over what was written ----------------------------------------------------------------

def _quantity(obj: str) -> ok.AttrKey | None:
    p = ok.norm(obj)
    if _PARTITIVE_RE.search(p) or len(p.split()) > 5:
        return None
    key = ok._quantity_key(obj)
    if key is None or len(key.tokens) > 2:
        return None
    # the name as the content words of the phrase, in order ("currently on page" -> "page")
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9'\-]*", key.name) if ok.stem(w.removesuffix("'s")) in key.tokens]
    return dataclasses.replace(key, name=" ".join(words)) if words else key


def _copula(obj: str, subject_text: str | None, speaker: str | None, texts: list[str]) -> ok.AttrKey | None:
    o = _squash(obj)
    if not o:
        return None
    subj = ok.subject_text_key(subject_text, speaker)
    for text in texts:
        for m in _COPULA_RE.finditer(text or ""):
            possessor = _squash(m.group(1))
            if possessor in ("my", "our"):
                if not subj.startswith("self:"):
                    continue
            elif subj != ok.subject_text_key(possessor[:-2], speaker):
                continue
            name = name_is_valid(m.group(2))
            if name is None or o not in _squash(m.group(3)):
                continue
            key = key_from_pair(name, obj)
            if key is not None:
                return key
    return None


def _count(obj: str, texts: list[str]) -> ok.AttrKey | None:
    o = ok.norm(obj)
    if not re.fullmatch(ok._QUANTITY_RE, o):
        return None
    for text in texts:
        m = re.search(rf"(?<![\w]){re.escape(o)}\s+([a-z][a-z\-]+)", _squash(text))
        if m and m.group(1) not in ok._STOPWORDS and ok.stem(m.group(1)) not in ok._BARE_UNITS:
            name = name_is_valid(m.group(1))
            if name:
                return ok._quantity_key(f"{obj} {name}")
    return None


def derive_key(object_text: str | None, *, quote: str | None = None, turn: str | None = None,
               subject_text: str | None = None, speaker: str | None = None) -> tuple[ok.AttrKey | None, str]:
    """(key, source) for a has_attribute object, or (None, 'none') when the rules cannot name it."""
    obj = " ".join((object_text or "").split())
    if not obj:
        return None, "none"
    texts = [t for t in (quote, turn) if t]
    if ok._parse_mapping(obj) is not None:
        key = ok.parse_attribute(obj)
        return (key, "stated") if key is not None else (None, "none")
    if ":" in obj and not ok._CLOCK_RE.match(obj):
        key = ok.parse_attribute(obj)
        if key is not None:
            return key, "stated"
        head, _, value = obj.partition(":")
        if ok.norm(head) == "name" and value.strip() and len(value.split()) <= 4 \
                and any(value_in_turn(value, t) for t in texts):
            tokens = frozenset({"name"})
            return ok.AttrKey(tokens, ok.norm(value), "text", "name", value.strip(), tokens), "name"
        return None, "none"
    def seen(key: ok.AttrKey | None) -> ok.AttrKey | None:
        # the value must be in the turn as written
        if key is None:
            return None
        v = key.raw or key.value
        return key if any(value_in_turn(v, t) for t in texts) else None

    age = _AGE_RE.match(obj)
    if age and any(value_in_turn(obj, t) for t in texts):
        key = key_from_pair("age", f"{age.group(1)} years")
        if key is not None:
            return key, "age"
    for source, make in (("quantity", lambda: _quantity(obj)),
                         ("copula", lambda: _copula(obj, subject_text, speaker, texts)),
                         ("count", lambda: _count(obj, texts))):
        key = seen(make())
        if key is not None:
            return key, source
    return None, "none"
