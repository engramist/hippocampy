"""
campy/brain/thalamus/aggregation.py -- B505: counts and sums computed by rule.

Why: on a "how many model kits have I worked on or bought?" or "how many days did
I spend on camping trips?" question, retrieval can find every piece of evidence
and a small answer model still miscounts or mis-sums it. Counting is not a
language task. So when the question asks for a count or a total and names a
kind of thing the graph knows, the items are gathered, deduplicated and
counted here, by rule, and handed to the answer model as a labelled section
(principle 3: the model advises, rules decide).

Detection is structural, never topical:

  * the interrogative form: "how many ...", "how much ...", "how long ... in total",
    "total number / amount of ...";
  * the thing counted is the noun phrase right after it (up to the first auxiliary
    or pronoun: "how many model kits | have I worked on"), or, when that word is a
    unit of measure (days, nights, hours, money, ...), the kind named in the rest
    of the question ("how many days | did I spend on camping trips ...").
  * the kind must then resolve, through B503's normalised matching (plural to
    singular, articles dropped), to a Concept that has members (`entity IS_A kind`,
    B504; with `[retrieval] skos_vocab`, B508: `entity INSTANCE_OF kind` where the kind is
    the asked one or any narrower kind through `BROADER`). No resolvable kind, no
    section: the model answers as before.

No word of any benchmark appears here; the vocabulary is English question
grammar (interrogatives, auxiliaries, units).

Sums are computed only where an amount can be read safely: a number (digits or
a number word up to twelve) followed by a unit of time, or a dollar figure, in the
claim the user made about the item. An item whose evidence holds two different
amounts of the asked unit is skipped and named as skipped. Units are never
converted into one another.

With `[observations] owl_properties` (B509) an item's amount is read first from the typed
literal stored on its attribute Observation (`attr_value_num` / `attr_value_unit`: durations
in seconds, money with a currency code), converted only into the unit the question asked
for; where no typed literal exists the number+unit reading above is used unchanged.

The section is flag-gated (`[retrieval] answer_aggregate` / `CAMPY_ANSWER_AGGREGATE`),
read by the caller; this module never reads global state.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from campy.brain.hippocampus.concept_links import match_concepts, norm_key
from campy.brain.hippocampus.graph.gateway import get_gateway
from campy.brain.hippocampus.kinds import skos_vocab_enabled
from campy.brain.hippocampus.observations import owl_properties_enabled

_logger = logging.getLogger(__name__)

MAX_ITEMS = 40            # items listed; the count is still the full count
QUOTE_CHARS = 110

DURATION_UNITS = frozenset({"minute", "hour", "day", "night", "week", "month", "year"})
_MONEY = "dollar"

# words that end the noun phrase after "how many": auxiliaries, pronoun subjects,
# prepositions that open the clause
_BOUNDARY = frozenset({
    "did", "do", "does", "have", "has", "had", "am", "are", "is", "was", "were", "will", "would",
    "can", "could", "should", "might", "must", "i", "we", "you", "they", "he", "she", "it", "my",
    "our", "there", "that", "which", "who", "in", "on", "at", "during", "since", "this", "last",
    "so", "far", "ever", "total", "altogether",
})
_MODIFIERS = frozenset({
    "different", "distinct", "separate", "unique", "total", "more", "new", "other", "various", "individual",
})
_MONEY_VERBS = frozenset({"spend", "spent", "pay", "paid", "cost", "earn", "earned", "raise", "raised",
                          "donate", "donated"})
_NUMBER_WORDS = {w: i + 1 for i, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve".split())}

_AMOUNT_RE = re.compile(
    r"(?<![\w.$])(?P<num>\d+(?:\.\d+)?|" + "|".join(_NUMBER_WORDS) + r")[\s-]+"
    r"(?P<unit>minute|hour|day|night|week|month|year|dollar)s?\b|"
    r"\$\s?(?P<usd>\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE)


@dataclass(frozen=True)
class Aggregation:
    """What the question asks for: a `count` of a kind, or a `sum` of an amount over it."""
    mode: str                         # "count" | "sum"
    kind_source: str                  # words the kind is looked up in
    units: frozenset[str] = frozenset()   # sum mode: the units to add (never converted)


# --- detection ------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$][a-z0-9$'-]*", text)


def _unit_of(word: str) -> frozenset[str]:
    """The amount units a measure word stands for ('days' -> {day}); empty if it is none."""
    if word == "time":                       # "how much time"; "times" is a repetition count, not a unit
        return DURATION_UNITS
    w = word[:-1] if word.endswith("s") and len(word) > 3 else word
    if w in DURATION_UNITS:
        return frozenset({w})
    if w in ("money", "dollar", "dollars"):
        return frozenset({_MONEY})
    return frozenset()


def _from_phrase(tokens: list[str]) -> Optional[Aggregation]:
    while tokens and tokens[0] in _MODIFIERS:
        tokens = tokens[1:]
    if not tokens:
        return None
    units = _unit_of(tokens[0])
    if units:
        return Aggregation("sum", " ".join(tokens[1:]), units)
    head: list[str] = []
    for t in tokens:
        if t in _BOUNDARY and head:
            break
        head.append(t)
    return Aggregation("count", " ".join(head)) if head else None


def parse_aggregation(question: str | None) -> Optional[Aggregation]:
    """The aggregation `question` asks for, or None (not an aggregation question)."""
    q = " ".join(str(question or "").lower().replace("’", "'").split())
    if not q:
        return None
    m = re.search(r"\bhow many\s+(.+)", q)
    if m:
        return _from_phrase(_tokens(m.group(1)))
    m = re.search(r"\btotal\s+(?:number|count|amount)\s+of\s+(.+)", q)
    if m:
        return _from_phrase(_tokens(m.group(1)))
    m = re.search(r"\bhow much\s+(.+)", q)
    if m:
        toks = _tokens(m.group(1))
        if toks and _unit_of(toks[0]):
            return _from_phrase(toks)
        if toks and toks[0] in _BOUNDARY and any(t in _MONEY_VERBS for t in toks):
            return Aggregation("sum", " ".join(toks[1:]), frozenset({_MONEY}))
        return None
    m = re.search(r"\bhow long\b(.*)", q)
    if m and re.search(r"\b(in total|total|altogether|combined|all together|in all)\b", q):
        return Aggregation("sum", " ".join(_tokens(m.group(1))), DURATION_UNITS)
    return None


# --- amounts --------------------------------------------------------------------------

def parse_amounts(text: str | None) -> list[tuple[float, str]]:
    """Every (value, unit) in `text`: 'a 3-day trip' -> (3, day); '$1,200' -> (1200, dollar)."""
    out: list[tuple[float, str]] = []
    for m in _AMOUNT_RE.finditer(text or ""):
        if m.group("usd"):
            out.append((float(m.group("usd").replace(",", "")), _MONEY))
            continue
        raw = m.group("num").lower()
        value = float(_NUMBER_WORDS[raw]) if raw in _NUMBER_WORDS else float(raw)
        out.append((value, m.group("unit").lower()))
    return out


_SECONDS = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2629800, "year": 31557600}


def typed_amount(ev: dict, units: frozenset[str]) -> Optional[tuple[float, str]]:
    """B509: the amount in an Observation's typed attribute literal, in the asked unit, or None.

    Durations are stored in seconds. One asked unit: converted to it. Several (a bare
    "how long in total"): only an exact number of weeks, days or hours is used (the largest
    that divides evenly); anything else, months and years included, is left to the text
    reading rather than guessed. Money counts only in USD (the dollar unit)."""
    kind, num, unit = ev.get("attr_kind"), ev.get("attr_num"), str(ev.get("attr_unit") or "")
    if num is None:
        return None
    if kind == "money":
        return (float(num), _MONEY) if _MONEY in units and unit == "USD" else None
    if kind != "duration" or unit != "second":
        return None
    asked = sorted(u for u in units if u in _SECONDS)
    if len(asked) == 1:
        value = float(num) / _SECONDS[asked[0]]
        return (round(value, 4), asked[0])
    for u in ("week", "day", "hour"):
        if u in asked and float(num) % _SECONDS[u] == 0:
            return (float(num) / _SECONDS[u], u)
    return None


def _item_amount(evidence: list[dict], units: frozenset[str]) -> tuple[Optional[tuple[float, str]], str]:
    """(amount, why-not): the item's single amount in the asked units, read from the
    claims the user made (the claim's own words first, the quoted turn words if the
    claim holds none). Two different amounts, or none, give no amount and a reason."""
    found: set[tuple[float, str]] = set()
    for ev in evidence:
        if ev.get("kind") != "Observation":
            continue
        typed = typed_amount(ev, units)
        if typed:
            found.add(typed)
            continue
        claim = f"{ev.get('event_text') or ''} {ev.get('object_text') or ''}"
        got = [a for a in parse_amounts(claim) if a[1] in units] or \
              [a for a in parse_amounts(ev.get("quote")) if a[1] in units]
        found.update(got)
    if len(found) == 1:
        return next(iter(found)), ""
    return None, ("two different amounts" if found else "no amount stated")


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def _amount_text(value: float, unit: str) -> str:
    if unit == _MONEY:
        return f"${_fmt(value)}"
    return f"{_fmt(value)} {unit}" + ("" if value == 1 else "s")


# --- items and rendering ----------------------------------------------------------------

def merge_items(rows: list[Any]) -> list[dict]:
    """One item per normalised name, evidence merged, oldest first."""
    by_key: dict[str, dict] = {}
    for r in rows:
        key = norm_key(r.get("name")) or str(r.get("name") or "").lower()
        item = by_key.setdefault(key, {"name": r.get("name"), "evidence": [], "seen": set()})
        for ev in r.get("evidence") or []:
            ident = (ev.get("kind"), ev.get("id"))
            if ident not in item["seen"]:
                item["seen"].add(ident)
                item["evidence"].append(ev)
    items = []
    for item in by_key.values():
        item["evidence"].sort(key=lambda e: (str(e.get("when") or ""), str(e.get("id"))))
        item["when"] = str(item["evidence"][0].get("when") or "")
        items.append(item)
    items.sort(key=lambda i: (i["when"], str(i["name"]).lower()))
    return items


def _quote(item: dict) -> str:
    ev = next((e for e in item["evidence"] if e.get("kind") == "Observation" and e.get("quote")),
              item["evidence"][0])
    q = " ".join(str(ev.get("quote") or "").split())
    return q if len(q) <= QUOTE_CHARS else q[:QUOTE_CHARS].rstrip() + "..."


def render_section(kind_text: str, items: list[dict], agg: Aggregation) -> str:
    """The bundle text: the numbered items with date and quote, the count, and for a
    sum the parts. States that it is computed from memory and may be incomplete."""
    n = len(items)
    lines = [f'Items of kind "{kind_text}" found in memory ({n}):']
    for i, item in enumerate(items[:MAX_ITEMS], 1):
        when = item["when"][:10]
        lines.append(f'{i}. {item["name"]}' + (f" [{when}]" if when else "") + f' "{_quote(item)}"')
    if n > MAX_ITEMS:
        lines.append(f"... and {n - MAX_ITEMS} more (all {n} are counted).")
    lines.append(f"Count: {n}.")
    if agg.mode == "sum":
        parts, skipped = [], []
        for item in items:
            amount, why = _item_amount(item["evidence"], agg.units)
            if amount:
                parts.append((item["name"], amount))
            else:
                skipped.append(f'{item["name"]} ({why})')
        if parts:
            totals: dict[str, float] = {}
            for _, (value, unit) in parts:
                totals[unit] = totals.get(unit, 0.0) + value
            total_text = "; ".join(_amount_text(v, u) for u, v in sorted(totals.items()))
            listed = ", ".join(f"{name}: {_amount_text(v, u)}" for name, (v, u) in parts)
            lines.append(f"Sum (added by rule, units not converted): {total_text}. Parts: {listed}.")
        else:
            lines.append("Sum: no item states an amount in the asked unit, so none is computed.")
        if skipped:
            lines.append("Not in the sum (not safely parsable): " + "; ".join(skipped) + ".")
        lines.append("Limits in the question (place, date range) are not applied to the sum.")
    lines.append("This list and these numbers are computed from memory by rule and may be incomplete: "
                 "an item the user never described, or that was not extracted, is absent.")
    return "\n".join(lines)


async def build_aggregate_section(db: Any, query: str, config: dict | None = None):
    """The `aggregate` BundleSection for `query`, or None: not an aggregation
    question, no kind resolves, no item has user evidence, or anything fails."""
    agg = parse_aggregation(query)
    if agg is None or not agg.kind_source.strip():
        return None
    try:
        from campy.brain.thalamus.bundle_compiler import BundleSection

        gw = get_gateway(db)
        candidates = await match_concepts(gw, agg.kind_source, limit=24,
                                          **({"alt_labels": True} if skos_vocab_enabled(config) else {}))
        if not candidates:
            return None
        extra: dict[str, Any] = {}
        if skos_vocab_enabled(config):
            extra["skos"] = True
        if owl_properties_enabled(config):
            extra["typed"] = True
        rows = await gw.run("thalamus.bundle_aggregate_items", concept_ids=candidates, **extra)
        if not rows:
            return None
        items = merge_items(list(rows))
        if not items:
            return None
        text = render_section(str(rows[0].get("kind_text") or agg.kind_source), items, agg)
        return BundleSection(
            section_type="aggregate",
            content=[{"text": text, "type": "Aggregate", "confidence": 1.0, "pathway_strength": 1.0}],
            source_node_ids=[str(e.get("id")) for i in items for e in i["evidence"]],
            token_estimate=max(1, len(text) // 4),
        )
    except Exception as e:  # fail-soft: the answer proceeds without the section
        _logger.warning("Error in build_aggregate_section: %s", e)
        return None
