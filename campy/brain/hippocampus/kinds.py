"""
campy/brain/hippocampus/kinds.py -- B508: a SKOS vocabulary for kinds.

Why: B504 writes a "kind" Concept ("model kit") under each entity with one `IS_A`
edge, and the kind is whatever string the model invented. So "kit", "model kit"
and "model kits" become three unrelated Concepts, and one edge means both
"this is an instance of" and "this is a subtype of". A question about "model kits"
then reaches only the entities hung on that exact string.

What this module defines (flag `[retrieval] skos_vocab`, env `CAMPY_SKOS_VOCAB`,
default off; off = B504's IS_A behaviour exactly):

  * every kind is a `skos:Concept` in the `campy:KindScheme` concept scheme. Stored
    as `Concept.kind_scheme = 'kind'`; the SKOS view (`skos:inScheme`,
    `skos:prefLabel`, `skos:altLabel`, `skos:broader`, `skos:closeMatch`) is
    projected from the store by `shapes/validator.skos_project`, so nothing is
    written twice (principle 2, no shadow stores).
  * two different relations instead of one:
      entity -INSTANCE_OF-> kind      "Revell F-15 is an instance of model kit"
      kind   -BROADER->     kind      "model kit is narrower than hobby item" (skos:broader)
    plus `CLOSE_MATCH` (skos:closeMatch) between kinds that merely look alike.
  * labels: the kept Concept's text is its prefLabel; other wordings accumulate as
    altLabels (Label nodes via HAS_ALT_LABEL, the B472 mechanism).

Consolidation (`plan_kind`), pure and rule-based, no model call. A new kind's label
is compared with the kinds already in the scheme, in this order:

  (a) same normalised key (lower case, article/possessive dropped, plural "s"
      dropped, see `concept_links.norm_key`) as an existing prefLabel or altLabel:
      the same kind. Reuse it; a differently worded surface becomes an altLabel.
  (b) head-noun containment: the existing kind's key is a proper word-suffix of the
      new one ("kit" < "model kit" < "plastic model kit"). English noun compounds
      are headed by their last word, so "model kit" is a KIND OF "kit": the longer
      one is `skos:broader`-linked to the shorter one. NOT an altLabel (an altLabel
      says "same thing"; "model kit" and "kit" are not interchangeable: a question
      about kits should reach model kits, a question about model kits must not
      reach every kit) and NOT a merge. The rule is order independent: when "kit"
      arrives after "model kit", the existing longer kinds are linked up to it.
      Known limit: lexicalised compounds ("ice cream" is not a kind of "cream");
      the cost is a wider walk, never a lost fact, and the edge is removable
      without touching evidence.
  (c) optional, embedding similarity above a strict threshold
      (`[retrieval] skos_closematch_threshold`, default 0.90, 0 = off): only a
      `CLOSE_MATCH` edge, never a merge and never followed by the walk. A model-free
      vector comparison advises; the two rules above decide.

Retrieval (B503's walk, and B505's counts) follow `INSTANCE_OF` and `BROADER` in
both directions and descend the `BROADER` closure, so "model kit" reaches every
instance of every narrower kind. `RELATION_PATH_*` below are the SPARQL fragments
those readers share.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from campy.brain.hippocampus.concept_links import KIND_SCHEME, alt_label_index, norm_key  # noqa: F401 (alt_label_index re-exported)

_logger = logging.getLogger(__name__)

NS = "https://campy.dev/ns#"
KIND_SCHEME_IRI = NS + "KindScheme"
DEFAULT_CLOSEMATCH_THRESHOLD = 0.90
MAX_CLOSEMATCH_COMPARISONS = 300          # kinds compared per new kind (bounded work)

# SPARQL fragments for readers (walk, counts). `<ns...>` full IRIs, ready to inline.
_B, _I, _L = f"<{NS}BROADER>", f"<{NS}INSTANCE_OF>", f"<{NS}IS_A>"
RELATION_PATH_UP = f"({_L}|{_I}|{_B})"            # one step from a thing to its kind / broader kind
RELATION_PATH_NARROWER_CLOSURE = f"({_B}|{_L})+"  # x ... transitively narrower than a kind


def skos_vocab_enabled(config: dict | None) -> bool:
    """`[retrieval] skos_vocab` (default false; env `CAMPY_SKOS_VOCAB=1` turns it on)."""
    return bool(((config or {}).get("retrieval") or {}).get("skos_vocab", False))


def closematch_threshold(config: dict | None, default: float = DEFAULT_CLOSEMATCH_THRESHOLD) -> float:
    """`[retrieval] skos_closematch_threshold`: cosine at or above which two kinds are
    linked by CLOSE_MATCH. 0 (or anything not a positive number) turns it off."""
    try:
        v = float(((config or {}).get("retrieval") or {}).get("skos_closematch_threshold", default))
    except (TypeError, ValueError):
        return default
    return v if v > 0 else 0.0


# --- the kinds already in the scheme -------------------------------------------------

@dataclass
class Kind:
    concept_id: str
    pref: str
    alts: list[str] = field(default_factory=list)
    broader: set[str] = field(default_factory=set)

    @property
    def pref_key(self) -> str:
        return norm_key(self.pref)

    def keys(self) -> set[str]:
        return {k for k in [self.pref_key, *(norm_key(a) for a in self.alts)] if k}


async def load_kinds(gw: Any) -> dict[str, Kind]:
    """Every live kind with its altLabels and BROADER targets, read fresh from the
    graph (a read-through view, never kept)."""
    kinds: dict[str, Kind] = {}
    for r in await gw.run("kinds.live_kinds"):
        kinds[str(r["concept_id"])] = Kind(str(r["concept_id"]), str(r.get("text_raw") or ""))
    if not kinds:
        return kinds
    for r in await gw.run("kinds.kind_alt_labels"):
        k = kinds.get(str(r["concept_id"]))
        if k is not None and r.get("alt") and r["alt"] not in k.alts:
            k.alts.append(str(r["alt"]))
    for r in await gw.run("kinds.kind_broader_edges"):
        k = kinds.get(str(r["child"]))
        if k is not None:
            k.broader.add(str(r["parent"]))
    return kinds


# --- the rule (pure) -----------------------------------------------------------------

@dataclass
class KindPlan:
    key: str
    exact: str | None = None                       # (a) the existing kind this one is
    exact_via: str | None = None                   # 'pref' | 'alt'
    broader: list[str] = field(default_factory=list)    # (b) existing kinds this one is narrower than
    narrower: list[str] = field(default_factory=list)   # (b) existing kinds that become narrower than this one


def _suffixes(words: list[str]) -> list[str]:
    """Proper word-suffixes, longest first: "plastic model kit" -> ["model kit", "kit"]."""
    return [" ".join(words[i:]) for i in range(1, len(words))]


def plan_kind(name: str, kinds: dict[str, Kind]) -> KindPlan:
    """Rules (a) and (b) for one incoming kind label. Deterministic (ids sorted)."""
    key = norm_key(name)
    plan = KindPlan(key=key)
    if not key:
        return plan
    pref_of: dict[str, str] = {}
    alt_of: dict[str, str] = {}
    for cid in sorted(kinds):
        k = kinds[cid]
        pref_of.setdefault(k.pref_key, cid)
        for a in k.alts:
            alt_of.setdefault(norm_key(a), cid)
    if key in pref_of:
        plan.exact, plan.exact_via = pref_of[key], "pref"
        return plan
    if key in alt_of:
        plan.exact, plan.exact_via = alt_of[key], "alt"
        return plan
    words = key.split()
    for suffix in _suffixes(words):                       # longest proper suffix that is a kind
        hit = pref_of.get(suffix) or alt_of.get(suffix)
        if hit:
            plan.broader = [hit]
            break
    for cid in sorted(kinds):
        other = kinds[cid].pref_key.split()
        if len(other) > len(words) and other[-len(words):] == words:
            # skip when it already hangs under a more specific kind than the new one
            more_specific = any(
                len(kinds[b].pref_key.split()) > len(words)
                and other[-len(kinds[b].pref_key.split()):] == kinds[b].pref_key.split()
                for b in kinds[cid].broader if b in kinds)
            if not more_specific:
                plan.narrower.append(cid)
    return plan


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def close_matches(vec: list[float], kinds: dict[str, Kind], embed_label, threshold: float,
                  exclude: set[str]) -> list[str]:
    """Ids of kinds whose prefLabel embedding is at or above `threshold` to `vec`
    (strict; at most the best three), excluding `exclude`. Advisory only."""
    if threshold <= 0:
        return []
    scored: list[tuple[float, str]] = []
    for cid in sorted(kinds)[:MAX_CLOSEMATCH_COMPARISONS]:
        if cid in exclude:
            continue
        try:
            s = cosine(vec, embed_label(kinds[cid].pref))
        except Exception:
            _logger.debug("close-match embedding failed", exc_info=True)
            continue
        if s >= threshold:
            scored.append((s, cid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [cid for _, cid in scored[:3]]


# --- graph writes (plain edges, idempotent) --------------------------------------------

async def mark_kind(gw: Any, concept_id: str) -> None:
    await gw.run("kinds.mark_kind", cid=concept_id, scheme=KIND_SCHEME)


async def link_instance_of(gw: Any, entity_id: str, kind_id: str) -> None:
    await gw.run("kinds.link_instance_of", cid=entity_id, kid=kind_id)


async def link_broader(gw: Any, narrower_id: str, broader_id: str) -> None:
    if narrower_id != broader_id:
        await gw.run("kinds.link_broader", cid=narrower_id, pid=broader_id)


async def link_close_match(gw: Any, a: str, b: str) -> None:
    if a != b:
        await gw.run("kinds.link_close_match", cid=a, oid=b)


async def add_alt_label(gw: Any, kind: Kind, surface: str) -> bool:
    """Accumulate `surface` as an altLabel of `kind` when it is a new wording (case-only
    differences are not wordings). Returns True when one was written."""
    s = " ".join((surface or "").split())
    if not s or len(s) > 80:
        return False
    if s.casefold() == kind.pref.casefold() or s.casefold() in {a.casefold() for a in kind.alts}:
        return False
    lid = str(uuid.uuid4())
    await gw.run("quests.create_alt_label", lid=lid, txt=s, now=datetime.now(timezone.utc).isoformat())
    await gw.run("quests.link_concept_has_alt_label", cid=kind.concept_id, lid=lid)
    kind.alts.append(s)
    return True


