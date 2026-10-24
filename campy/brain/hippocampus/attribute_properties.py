"""
campy/brain/hippocampus/attribute_properties.py -- B509: attribute names as an OWL vocabulary.

Why: B499 superseded `has_attribute` Observations by matching free strings ("the text before
the first colon, token sets"). That rarely fires (attribute names are free-form and often
JSON reprs) and fires wrongly when it does: "hobby: tennis" then "hobby: chess" are both true,
yet matching strings replaced one with the other. Whether a newer value REPLACES an older one
is a property of the attribute, not of the strings: your age has one current value, your
hobbies do not. This module makes the attribute a first-class node so that fact can be stated
once, in the vocabulary, and supersession follows from it.

Flag `[observations] owl_properties` (env `CAMPY_OWL_PROPERTIES`, default off). Off = the
writer is exactly the base one (B499's string rule still runs when ITS flag is on).

The model (graph store only; nothing is kept in Python):

  * `AttributeProperty` node per attribute name: an owl:DatatypeProperty (the value is a
    literal) or owl:ObjectProperty (the value is a Concept), and a skos:Concept in
    campy:PropertyScheme: `text_raw` is the prefLabel, other wordings are altLabels (Label
    nodes via HAS_ALT_LABEL, the B472 mechanism).
  * Observation -HAS_PROPERTY-> AttributeProperty (at most one: owl:FunctionalProperty).
  * The value is stored apart from the name on the Observation: `attr_value` (text as
    written), `attr_value_kind` (number, duration, money, date, clock, text), and the parsed
    typed literal `attr_value_num` + `attr_value_unit` (number / money / duration in seconds)
    or `attr_value_time` (date). An object-valued attribute stores the Concept in
    `attr_value_ref`. `shapes/validator.owl_project` turns these into the OWL assertion
    <subject> <property> <value> for the SHACL and reasoning checks.

Consolidation of attribute names, pure rules, no model call (same style as kinds.py). The
comparison key of a name is its set of stemmed content tokens, order and filler words
("time", "total", "count", articles, "current") ignored (observation_keys.content_tokens):

  (a) same token set as an existing property's prefLabel or altLabel, or a seed property in
      campy_vocab.ttl: the SAME property; a differently worded surface becomes an altLabel.
      "personal best 5K" and "5K personal best time" are one property, "5k personal best".
  (b) the tokens of an existing property are a proper subset of the new name's ("5k personal
      best" over "personal best"): NOT merged (an unqualified "personal best" is not
      interchangeable with the 5K one) but recorded: new BROADER old (skos:broader). Order
      independent: a broader property arriving later gets the existing narrower ones linked up.
  (c) optional: an embedding of the two labels at or above `[retrieval]
      skos_closematch_threshold`: CLOSE_MATCH only, advisory, never merged.

Functional properties (single current value per subject). Rules decide, the model advises:

  1. A seed property of campy_vocab.ttl declared owl:FunctionalProperty (age, occupation,
     employer, residence, ...): functional by IRI identity, nothing stored on the node.
  2. A name containing a campy:SingleValuedModifier from the same file ("favorite food",
     "personal best 5K"): functional_basis = 'modifier'. Such a name picks out one thing.
  3. Rule-confirmed (functional_basis = 'confirmed'): the extractor advised cardinality "one"
     for this property more often than "many" AND a newer value arrives for the same subject
     with a different value AND that turn uses replacement language ("now", "moved to",
     "no longer", "switched", ...). All three are needed. Advice alone never confirms: the
     model said "one" for "hobby: chess" in the same breath as it was wrong; replacement
     language alone never confirms: "I switched to chess" is a statement about chess.
     Advice is stored only as counts (advised_one / advised_many), a candidate.
  Why not (3) only on evidence of repeated replacement: one confirmed replacement is exactly
  the evidence a person gives ("I moved to Denver"), and waiting for a second would leave
  the commonest case (one update) unfixed. A wrong confirmation costs one superseded row
  that is kept, marked, and rendered, never deleted.

Where the name comes from (B511): the extractor's validated structured `attribute`, B499's
parse of "name: value", then shape rules (quantity, copula, count, age) in attribute_names.py.
No rule, no property: the Observation stays unlinked rather than carry an invented name.

Supersession. A functional property's newer value (by `observed_at`, ties `created_at`)
supersedes the older one for the same subject: the older gets `superseded_by` /
`superseded_at` (the newer one's event time) and a DEPRECATED_BY edge to the newer one, and
renders as "(superseded <date>)" (B499's writer and rendering). Out-of-order arrival marks
the incoming row instead. A non-functional property never supersedes.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from campy.brain.hippocampus import observation_keys as ok

_logger = logging.getLogger(__name__)

PROPERTY_BASE = "https://campy.dev/id/AttributeProperty/"
MAX_LABEL_CHARS = 80
PROPERTY_SCHEME = "property"

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800,
                 "month": 2629800, "year": 31557600, "decade": 315576000}
_CURRENCY = (("$", "USD"), ("€", "EUR"), ("£", "GBP"))
_CURRENCY_WORDS = {"dollar": "USD", "usd": "USD", "buck": "USD", "euro": "EUR", "eur": "EUR", "gbp": "GBP"}
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_REPLACEMENT_RE = re.compile(
    r"\b(now|no longer|anymore|any more|used to|moved|moving|switched|switch(?:ing)? to|changed|"
    r"instead|replaced|quit|left|became|these days|upgraded|promoted|updated?|turned)\b", re.IGNORECASE)


def owl_properties_enabled(config: dict | None) -> bool:
    """`[observations] owl_properties` (default false; env `CAMPY_OWL_PROPERTIES=1` turns it on)."""
    return bool(((config or {}).get("observations") or {}).get("owl_properties", False))


def replacement_language(text: str | None) -> bool:
    """The turn says a value changed ("I now live in", "moved to", "no longer")."""
    return bool(_REPLACEMENT_RE.search(text or ""))


# --- the vocabulary file ---------------------------------------------------------------

@dataclass(frozen=True)
class Seed:
    property_id: str
    pref: str
    alts: tuple[str, ...]
    prop_type: str            # 'datatype' | 'object'
    functional: bool


@dataclass(frozen=True)
class Vocab:
    seeds: dict[str, Seed]
    modifiers: tuple[frozenset[str], ...]      # token sets of campy:SingleValuedModifier labels

    def functional_ids(self) -> frozenset[str]:
        return frozenset(i for i, s in self.seeds.items() if s.functional)

    def modifier_hit(self, tokens: frozenset[str]) -> bool:
        return any(m and m <= tokens for m in self.modifiers)


@lru_cache(maxsize=1)
def vocab() -> Vocab:
    """The seed properties and single-valued modifiers declared in campy_vocab.ttl."""
    from rdflib import Namespace
    from rdflib.namespace import OWL, RDF

    from campy.brain.hippocampus.shapes import validator

    g = validator.load_vocab()
    skos, campy = Namespace(validator.SKOS_NS), Namespace(validator.NS)
    seeds: dict[str, Seed] = {}
    for s in set(g.subjects(RDF.type, OWL.DatatypeProperty)) | set(g.subjects(RDF.type, OWL.ObjectProperty)):
        if not str(s).startswith(PROPERTY_BASE):
            continue
        pid = str(s)[len(PROPERTY_BASE):]
        pref = next(iter(g.objects(s, skos.prefLabel)), None)
        if pref is None:
            continue
        seeds[pid] = Seed(
            pid, str(pref), tuple(sorted(str(a) for a in g.objects(s, skos.altLabel))),
            "object" if (s, RDF.type, OWL.ObjectProperty) in g else "datatype",
            (s, RDF.type, OWL.FunctionalProperty) in g)
    mods = tuple(ok.content_tokens(str(g.value(m, skos.prefLabel) or ""))
                 for m in g.subjects(RDF.type, campy.SingleValuedModifier))
    return Vocab(seeds, mods)


# --- typed values ------------------------------------------------------------------------

@dataclass(frozen=True)
class Typed:
    value: str                       # as written
    kind: str                        # number | duration | money | date | clock | text
    num: float | None = None
    unit: str | None = None
    time: datetime | None = None


def _number(text: str) -> float | None:
    m = ok._QUANTITY_RE.search(text or "")
    if not m:
        return None
    q = m.group(0).strip().lower()
    if re.search(r"\d\s*(?:-|to)\s*\S|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+to\b", q) \
            or " to " in q or re.search(r"\w-\w", q):
        return None                  # a range ("5-6") is not one number
    q = q.replace(",", "")
    try:
        return float(q)
    except ValueError:
        w = ok._NUMBER_WORDS.get(q)
        return float(w) if w is not None else None


def typed_value(key: ok.AttrKey, observed_at: datetime | None = None) -> Typed:
    """The value of a parsed attribute as a typed literal where one can be read, else text."""
    raw = (key.raw or key.value or "").strip()
    kind = key.kind
    if kind == "number":
        return Typed(raw, kind, _number(raw))
    if kind == "duration":
        words = set(re.findall(r"[a-z]+", ok.norm(raw))) | set(key.tokens)
        unit = next((u for u in _UNIT_SECONDS if u in {ok.stem(w) for w in words}), None)
        n = _number(raw)
        if n is None or unit is None:
            return Typed(raw, kind)
        return Typed(raw, kind, n * _UNIT_SECONDS[unit], "second")
    if kind == "money":
        cur = next((c for sym, c in _CURRENCY if sym in raw), None) \
            or next((c for w, c in _CURRENCY_WORDS.items()
                     if w in {ok.stem(x) for x in re.findall(r"[a-z]+", ok.norm(raw))}), None)
        return Typed(raw, kind, _number(raw), cur)
    if kind == "clock":
        parts = raw.split(":")
        if len(parts) == 3:
            try:
                h, m, s = (int(p) for p in parts)
                return Typed(raw, kind, float(h * 3600 + m * 60 + s), "second")
            except ValueError:
                pass
        return Typed(raw, kind)      # "25:50" is minutes:seconds or hours:minutes; not guessed
    if kind == "date":
        m = _ISO_DATE_RE.search(raw)
        try:
            if m:
                return Typed(raw, kind, time=datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc))
            from campy.brain.temporal_lobe.observations.timeparse import normalize_time
            r = normalize_time(raw, observed_at)
            if r is not None and r.precision in ("day", "date", "exact"):
                return Typed(raw, kind, time=r.start)
        except Exception:
            _logger.debug("date value not parsed: %r", raw, exc_info=True)
    return Typed(raw, kind)


def same_value(a: dict, b: dict) -> bool:
    """Two stored attribute values are the same value: equal typed literals, else equal text."""
    for n, u in (("attr_value_num", "attr_value_unit"),):
        if a.get(n) is not None and b.get(n) is not None:
            return float(a[n]) == float(b[n]) and (a.get(u) or None) == (b.get(u) or None)
    ta, tb = obs_time(a.get("attr_value_time")), obs_time(b.get("attr_value_time"))
    if ta is not None and tb is not None:
        return ta == tb
    return ok.norm(a.get("attr_value")) == ok.norm(b.get("attr_value"))


def obs_time(v: Any) -> datetime | None:
    from campy.brain.hippocampus import observations as obs

    d = obs._as_datetime(v)
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


# --- the properties already in the store ---------------------------------------------------

def name_key(tokens: frozenset[str]) -> str:
    return " ".join(sorted(tokens))


@dataclass
class Prop:
    property_id: str
    pref: str
    prop_type: str = "datatype"
    functional_basis: str | None = None
    advised_one: int = 0
    advised_many: int = 0
    alts: list[str] = field(default_factory=list)
    broader: set[str] = field(default_factory=set)
    seed: bool = False                     # known from the vocabulary file, not (yet) stored

    @property
    def tokens(self) -> frozenset[str]:
        return ok.content_tokens(self.pref)

    def keys(self) -> set[str]:
        return {k for k in [name_key(self.tokens), *(name_key(ok.content_tokens(a)) for a in self.alts)] if k}

    @property
    def functional(self) -> bool:
        return bool(self.functional_basis) or self.property_id in vocab().functional_ids()


async def load_properties(gw: Any) -> dict[str, Prop]:
    """Every live stored property with altLabels and BROADER targets, read fresh (a read-through view)."""
    props: dict[str, Prop] = {}
    for r in await gw.run("properties.live_properties"):
        props[str(r["property_id"])] = Prop(
            str(r["property_id"]), str(r.get("text_raw") or ""), str(r.get("prop_type") or "datatype"),
            r.get("functional_basis") or None, int(r.get("advised_one") or 0), int(r.get("advised_many") or 0))
    if props:
        for r in await gw.run("properties.alt_labels"):
            p = props.get(str(r["property_id"]))
            if p is not None and r.get("alt") and r["alt"] not in p.alts:
                p.alts.append(str(r["alt"]))
        for r in await gw.run("properties.broader_edges"):
            p = props.get(str(r["child"]))
            if p is not None:
                p.broader.add(str(r["parent"]))
    return props


# --- consolidation (pure) ------------------------------------------------------------------

@dataclass
class PropertyPlan:
    key: str
    exact: str | None = None                                  # (a) the existing / seed property this is
    broader: list[str] = field(default_factory=list)          # (b) stored properties this one narrows
    narrower: list[str] = field(default_factory=list)         # (b) stored properties that now narrow this one


def plan_property(tokens: frozenset[str], stored: dict[str, Prop], seeds: dict[str, Seed]) -> PropertyPlan:
    key = name_key(tokens)
    plan = PropertyPlan(key)
    if not key:
        return plan
    owner: dict[str, str] = {}
    for pid in sorted(stored):
        for k in sorted(stored[pid].keys()):
            owner.setdefault(k, pid)
    for pid in sorted(seeds):
        s = seeds[pid]
        for label in (s.pref, *s.alts):
            k = name_key(ok.content_tokens(label))
            if k:
                owner.setdefault(k, pid)
    if key in owner:
        plan.exact = owner[key]
        return plan
    best: tuple[int, str] | None = None
    for pid in sorted(stored):
        t = stored[pid].tokens
        if t and t < tokens and (best is None or len(t) > best[0]):
            best = (len(t), pid)
    if best:
        plan.broader = [best[1]]
    for pid in sorted(stored):
        t = stored[pid].tokens
        if t and tokens < t:
            more_specific = any(stored[b].tokens > tokens for b in stored[pid].broader if b in stored)
            if not more_specific:
                plan.narrower.append(pid)
    return plan


async def _add_alt_label(gw: Any, prop: Prop, surface: str) -> bool:
    s = " ".join((surface or "").split())
    if not s or len(s) > MAX_LABEL_CHARS:
        return False
    if s.casefold() == prop.pref.casefold() or s.casefold() in {a.casefold() for a in prop.alts}:
        return False
    lid = str(uuid.uuid4())
    await gw.run("quests.create_alt_label", lid=lid, txt=s, now=datetime.now(timezone.utc).isoformat())
    await gw.run("properties.link_alt_label", pid=prop.property_id, lid=lid)
    prop.alts.append(s)
    return True


async def _create(gw: Any, pid: str, pref: str, tokens: frozenset[str], ptype: str, basis: str | None) -> Prop:
    await gw.run("properties.create_property", pid=pid, txt=pref[:MAX_LABEL_CHARS], mkey=name_key(tokens),
                 ptype=ptype, basis=basis, now=datetime.now(timezone.utc))
    return Prop(pid, pref[:MAX_LABEL_CHARS], ptype, basis)


async def resolve(gw: Any, key: ok.AttrKey, *, closematch: float = 0.0, embed: Any = None,
                  stats: dict | None = None) -> Prop | None:
    """The AttributeProperty for a parsed attribute name, created if new (rules a, b, c above)."""
    bump = (lambda n: stats.__setitem__(n, stats.get(n, 0) + 1)) if stats is not None else (lambda n: None)
    tokens = key.name_tokens or key.tokens
    stored = await load_properties(gw)
    v = vocab()
    plan = plan_property(tokens, stored, v.seeds)
    if not plan.key:
        return None
    surface = (key.name or " ".join(sorted(tokens))).strip()
    if plan.exact:
        prop = stored.get(plan.exact)
        if prop is None:                         # a seed seen for the first time: materialise it
            seed = v.seeds[plan.exact]
            prop = await _create(gw, seed.property_id, seed.pref, ok.content_tokens(seed.pref), seed.prop_type, None)
            prop.seed = True
            bump("properties_created")
        else:
            bump("properties_reused")
        if await _add_alt_label(gw, prop, surface):
            bump("property_alt_labels")
        return prop
    basis = "modifier" if v.modifier_hit(tokens) else None
    prop = await _create(gw, str(uuid.uuid4()), surface or name_key(tokens), tokens, "datatype", basis)
    bump("properties_created")
    for parent in plan.broader:
        await gw.run("properties.link_broader", cid=prop.property_id, pid=parent)
        bump("properties_broader")
    for child in plan.narrower:
        await gw.run("properties.link_broader", cid=child, pid=prop.property_id)
        bump("properties_broader")
    if closematch > 0 and embed is not None and stored:
        try:
            from campy.brain.hippocampus import kinds as kinds_mod

            vec = embed(prop.pref)
            pool = {pid: SimpleNamespace(pref=p.pref) for pid, p in stored.items()}
            for other in kinds_mod.close_matches(vec, pool, embed, closematch,
                                                 exclude={prop.property_id, *plan.broader, *plan.narrower}):
                await gw.run("properties.link_close_match", cid=prop.property_id, oid=other)
                bump("properties_close_match")
        except Exception:
            _logger.debug("property close-match search failed", exc_info=True)
    return prop


# --- applying it to one Observation ----------------------------------------------------------

def attribute_key(draft: Any, msg: dict, *, rules: bool = True, stats: dict | None = None) -> ok.AttrKey | None:
    """The attribute name and value of a `has_attribute` draft (B511), or None when no rule can
    name it. In order: the extractor's validated structured `attribute` (draft.attr_name/attr_value),
    then B499's parse of "name: value", then the shape rules of attribute_names (quantity, copula,
    count, age). `rules=False` is the B509 behaviour (the parse of the written object only)."""
    from campy.brain.hippocampus import attribute_names as an

    def bump(n: str) -> None:
        if stats is not None:
            stats[n] = stats.get(n, 0) + 1

    if not rules:
        return ok.parse_attribute(draft.object_text)
    name, value = getattr(draft, "attr_name", None), getattr(draft, "attr_value", None)
    if name and value:
        key = an.key_from_pair(name, value)
        if key is not None:
            bump("attr_named_structured")
            return key
    speaker = draft.speaker or msg.get("speaker")
    key, source = an.derive_key(draft.object_text, quote=getattr(draft, "evidence_text", None),
                                turn=msg.get("text_raw"), subject_text=draft.subject_text, speaker=speaker)
    if key is not None:
        bump(f"attr_named_{source}")
    return key


async def apply(gw: Any, oid: str, draft: Any, msg: dict, now: datetime, *, closematch: float = 0.0,
                embed: Any = None, stats: dict | None = None, rules: bool = True) -> str | None:
    """Link a freshly written `has_attribute` Observation to its property, store its value apart
    from its name, and apply the functional-property supersession. Returns the property id, or
    None when no attribute name/value pair can be read or derived (it is then left as written)."""
    from campy.brain.hippocampus import observations as obs

    key = attribute_key(draft, msg, rules=rules, stats=stats)
    if key is None:
        return None
    me = await gw.run("observations.get_observation", oid=oid)
    if not me:
        return None
    mine = dict(me[0])
    typed = typed_value(key, obs._as_datetime(mine.get("observed_at")))
    prop = await resolve(gw, key, closematch=closematch, embed=embed, stats=stats)
    if prop is None:
        return None
    await gw.run("properties.link_property", oid=oid, pid=prop.property_id)
    await gw.run("properties.set_attribute_value", oid=oid, value=typed.value, kind=typed.kind,
                 num=typed.num, unit=typed.unit, time=typed.time)
    mine.update(attr_value=typed.value, attr_value_kind=typed.kind, attr_value_num=typed.num,
                attr_value_unit=typed.unit, attr_value_time=typed.time)
    advice = (getattr(draft, "attr_cardinality", None) or "").lower()
    if advice in ("one", "many"):
        await gw.run("properties.add_advice", pid=prop.property_id,
                     d1=int(advice == "one"), d2=int(advice == "many"))
        if advice == "one":
            prop.advised_one += 1
        else:
            prop.advised_many += 1
    if draft.polarity == "asserted":
        await supersede_by_property(gw, oid, prop, draft, mine, msg, now, stats=stats)
    return prop.property_id


async def supersede_by_property(gw: Any, oid: str, prop: Prop, draft: Any, mine: dict, msg: dict,
                                now: datetime, *, stats: dict | None = None) -> None:
    """For a functional property, mark the older of each (this, other live value of the same
    subject) pair superseded. A non-functional property does nothing."""
    from campy.brain.hippocampus import observations as obs

    speaker = draft.speaker or msg.get("speaker")
    me_subject = (draft.subject_id, draft.subject_text, speaker)
    rows = [dict(r) for r in await gw.run("properties.live_values", pid=prop.property_id)]
    rivals = []
    for row in rows:
        if row.get("observation_id") == oid:
            continue
        if not ok.same_subject(me_subject, (row.get("subject_id"), row.get("subject_text"), row.get("speaker"))):
            continue
        if same_value(row, mine):
            continue
        rivals.append(row)
    if not rivals:
        return
    functional = prop.functional
    if not functional and prop.advised_one > prop.advised_many and replacement_language(msg.get("text_raw")):
        if any(obs._when(r) < obs._when(mine) for r in rivals):       # this value is the newer one
            await gw.run("properties.set_functional", pid=prop.property_id, basis="confirmed", by=oid)
            prop.functional_basis = "confirmed"
            functional = True
            if stats is not None:
                stats["properties_confirmed"] = stats.get("properties_confirmed", 0) + 1
    if not functional:
        return
    for row in sorted(rivals, key=obs._when):
        old, new = (row, mine) if obs._when(row) <= obs._when(mine) else (mine, row)
        if old is mine and mine.get("superseded_by"):
            continue
        at = obs._as_datetime(new.get("observed_at")) or now
        await gw.run("observations.mark_superseded", oid=old["observation_id"], by=new["observation_id"],
                     at=at, reason="replaced")
        await gw.run("observations.link_deprecated_by", oid=old["observation_id"], by=new["observation_id"])
        if stats is not None:
            stats["superseded"] = stats.get("superseded", 0) + 1
        if old is mine:
            mine["superseded_by"] = new["observation_id"]


async def bind_object(gw: Any, oid: str, entity_id: str) -> str:
    """An attribute whose value was validated as an entity (B504): point the Observation at the
    Concept and make the property an owl:ObjectProperty. OWL keeps datatype and object
    properties apart, so the type is fixed by the first value: a property that already holds
    literal values stays a datatype property and this value stays text ('mismatch')."""
    rows = await gw.run("properties.property_of", oid=oid)
    if not rows:
        return "unlinked"
    r = dict(rows[0])
    pid = str(r["property_id"])
    if r.get("prop_type") == "object":
        await gw.run("properties.set_value_ref", oid=oid, ref=entity_id)
        return "object"
    n = await gw.run("properties.value_count", pid=pid)
    if int(dict(n[0]).get("n", 0)) == 1:
        await gw.run("properties.set_type", pid=pid, ptype="object")
        await gw.run("properties.set_value_ref", oid=oid, ref=entity_id)
        return "promoted"
    return "mismatch"


async def backfill(gw: Any, *, closematch: float = 0.0, embed: Any = None, limit: int | None = None,
                   rules: bool = True) -> dict:
    """Resolve the `has_attribute` Observations that have no property yet, oldest first (so
    supersession sees them in event order). Idempotent. Returns the counts."""
    from campy.brain.hippocampus import observations as obs

    stats: dict = {"linked": 0, "skipped": 0}
    rows = await gw.run("properties.unlinked_attributes")
    for r in (rows[:limit] if limit else rows):
        oid = r["observation_id"]
        row = await gw.run("observations.get_observation", oid=oid)
        if not row:
            continue
        row = dict(row[0])
        draft = obs.ObservationDraft(
            evidence_ref=row.get("evidence_ref") or "", evidence_text=row.get("evidence_text") or "",
            subject_text=row.get("subject_text") or "", predicate="has_attribute",
            object_text=row.get("object_text") or "", extraction_method=row.get("extraction_method") or "llm",
            confidence=float(row.get("confidence") or 0.0), polarity=row.get("polarity") or "asserted",
            subject_id=row.get("subject_id"), speaker=row.get("speaker"))
        msg = await gw.run("observations.get_message", mid=draft.evidence_ref)
        pid = await apply(gw, oid, draft, dict(msg[0]) if msg else {}, datetime.now(timezone.utc),
                          closematch=closematch, embed=embed, stats=stats, rules=rules)
        stats["linked" if pid else "skipped"] += 1
    return stats
