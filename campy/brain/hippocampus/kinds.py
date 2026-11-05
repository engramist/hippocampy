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

Hygiene (B525, flag `[observations] kind_hygiene`, env `CAMPY_KIND_HYGIENE`, default off).
A kind label is a clean singular noun, so a question can name it: `normalise_kind_label`
drops leading determiners ("my dogs" -> "dogs"), puts the last word into the singular with the
spaCy model the NER step already loads ("dogs" -> "dog", "puppies" -> "puppy", "mice" ->
"mouse"; only a word spaCy tags as a plural noun changes), and returns None for a meta-noun
(`META_NOUNS`: words that describe a category, not a category: "name", "thing", "type" ...).
The surface the model wrote stays as an altLabel, so lookup by the old wording still works.
`plan_hygiene` is the same rule over the kinds already in a store (scripts/consolidate_kinds.py):
kinds that collapse to one label merge into one survivor, meta-noun kinds lose their
INSTANCE_OF edges and are archived; nothing is deleted except those edges.

WordNet (B534, flag `[observations] wordnet_kinds`, env `CAMPY_WORDNET_KINDS`, default off). The
labels of two kinds already in the scheme often stand in a hypernym relation that no suffix rule sees
("puppy" is a kind of "dog" is a kind of "animal"). `temporal_lobe/lexicon/wordnet.plan_links` reads that
from WordNet (first/frequent senses only) and `link_broader_sourced` writes `child BROADER parent` with
`campy:link_source "wordnet"` on the edge's RDF-star reifier, so a later steward can tell these links from
the label rule's (`kinds.broader_links_by_source` reads the property). Closed set: only existing kinds are
linked, no kind is ever created from WordNet. It runs when a kind is created (up, and down to existing
narrower kinds) and as `scripts/backfill_wordnet_kinds.py` over a store.

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

from campy.brain.hippocampus.concept_links import KIND_SCHEME, norm_key

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


def kind_hygiene_enabled(config: dict | None) -> bool:
    """`[observations] kind_hygiene` (default false; env `CAMPY_KIND_HYGIENE=1` turns it on)."""
    return bool(((config or {}).get("observations") or {}).get("kind_hygiene", False))


def wordnet_kinds_enabled(config: dict | None) -> bool:
    """`[observations] wordnet_kinds` (default false; env `CAMPY_WORDNET_KINDS=1` turns it on)."""
    return bool(((config or {}).get("observations") or {}).get("wordnet_kinds", False))


def closematch_threshold(config: dict | None, default: float = DEFAULT_CLOSEMATCH_THRESHOLD) -> float:
    """`[retrieval] skos_closematch_threshold`: cosine at or above which two kinds are
    linked by CLOSE_MATCH. 0 (or anything not a positive number) turns it off."""
    try:
        v = float(((config or {}).get("retrieval") or {}).get("skos_closematch_threshold", default))
    except (TypeError, ValueError):
        return default
    return v if v > 0 else 0.0


# --- B525: clean kind labels ---------------------------------------------------------

# Leading words that say whose or which one, not what kind ("my dogs", "this dish").
LABEL_DETERMINERS = frozenset({
    "a", "an", "the", "my", "our", "your", "his", "her", "their", "its",
    "this", "that", "these", "those",
})
# Words that describe a category rather than name one. "Scout is a name" says nothing about what
# Scout is; as a kind they swallow every named thing. Closed and small on purpose: grow it only from
# a kind a store shows holding unrelated entities.
META_NOUNS = frozenset({
    "name", "thing", "type", "kind", "sort", "stuff", "one", "item", "example", "part", "way", "lot", "bit",
})
# Nouns that are plural in form only; their "singular" is not a word for the thing.
_PLURALE_TANTUM = frozenset({
    "binoculars", "scissors", "glasses", "sunglasses", "pants", "jeans", "trousers", "shorts", "clothes",
    "headphones", "goggles", "pliers", "tweezers", "leggings", "pajamas", "news", "series", "species",
})
_WORD_STRIP = ".,;:!?\"()[]"


def _singular_by_rule(word: str) -> str:
    """The no-model fallback: -ies -> -y, a plain trailing -s dropped (not -ss/-us/-is)."""
    low = word.lower()
    if len(low) <= 3 or low in _PLURALE_TANTUM:
        return word
    if low.endswith("ies"):
        return word[:-3] + "y"
    if low.endswith(("ss", "us", "is")) or not low.endswith("s"):
        return word
    return word[:-1]


def _singular_by_spacy(words: list[str], nlp: Any) -> str | None:
    """The last word's lemma when spaCy tags it a plural noun, else None (no change)."""
    # inside "The ... ." the tagger reads the phrase as a noun phrase; alone, "gardens" is tagged a proper noun
    doc = nlp("The " + " ".join(words).lower() + ".")
    toks = [t for t in doc if not t.is_space and not t.is_punct]
    if len(toks) < 2 or toks[-1].text.lower() != words[-1].lower():
        return None                                     # the tokeniser split the word differently
    last = toks[-1]
    return last.lemma_ if last.tag_ in ("NNS", "NNPS") and last.lemma_ else None


def _default_nlp() -> Any | None:
    try:
        from campy.brain.temporal_lobe.loop.step1_ner import get_nlp
        return get_nlp()
    except Exception:
        _logger.debug("spaCy unavailable for kind lemmatisation", exc_info=True)
        return None


def normalise_kind_label(label: str | None, nlp: Any | None = None) -> str | None:
    """The clean form of a kind label: determiners dropped, last word singular. None when nothing is
    left, or when the result is a meta-noun (the kind is not written). `nlp` is a loaded spaCy model
    (default: the one the NER step uses; without one, a suffix rule). Case of the surviving words is kept."""
    t = " ".join(str(label or "").replace("\u2019", "'").split())
    t = t.strip(_WORD_STRIP + " ")
    words = t.split(" ") if t else []
    while len(words) > 1 and words[0].lower() in LABEL_DETERMINERS:
        words = words[1:]
    if not words or not any(ch.isalpha() for ch in " ".join(words)):
        return None
    if words[-1].lower().endswith("'s") and len(words[-1]) > 2:
        words[-1] = words[-1][:-2]                       # a possessive is not a kind
    last = words[-1]
    if last.lower() not in _PLURALE_TANTUM:
        model = nlp if nlp is not None else _default_nlp()
        lemma = None
        if model is not None:
            try:
                lemma = _singular_by_spacy(words, model)
            except Exception:
                _logger.debug("spaCy lemmatisation failed", exc_info=True)
        else:
            lemma = _singular_by_rule(last)
        if lemma and lemma.lower() != last.lower():
            words[-1] = lemma.capitalize() if last[:1].isupper() and not last.isupper() else lemma
    out = " ".join(words)
    return None if out.lower() in META_NOUNS else out


@dataclass
class HygienePlan:
    """What `plan_hygiene` decides for a store's kinds. All ids are kind Concept ids."""
    relabel: dict[str, str] = field(default_factory=dict)         # survivor -> new prefLabel
    merge: dict[str, str] = field(default_factory=dict)           # merged kind -> survivor
    drop_meta: list[str] = field(default_factory=list)            # meta-noun kinds
    detach_alts: list[tuple[str, str]] = field(default_factory=list)   # (surviving kind, altLabel) to detach
    unchanged: int = 0


def plan_hygiene(kinds: dict[str, "Kind"], instance_counts: dict[str, int] | None = None,
                 nlp: Any | None = None) -> HygienePlan:
    """The same rule over existing kinds. Kinds whose clean labels share a key are one kind; the
    survivor is, in order, one whose label is already the clean label, the one with most instances,
    the lowest id (deterministic). Pure: nothing is read or written here."""
    counts = instance_counts or {}
    plan = HygienePlan()
    groups: dict[str, list[tuple[str, str]]] = {}
    for cid in sorted(kinds):
        clean = normalise_kind_label(kinds[cid].pref, nlp)
        if clean is None:
            plan.drop_meta.append(cid)
            continue
        groups.setdefault(norm_key(clean) or clean.lower(), []).append((cid, clean))
    for members in groups.values():
        clean = members[0][1]
        survivor = min(members, key=lambda m: (
            kinds[m[0]].pref.casefold() != clean.casefold(), -counts.get(m[0], 0), m[0]))[0]
        for cid, _ in members:
            if cid != survivor:
                plan.merge[cid] = survivor
        if kinds[survivor].pref != clean:
            plan.relabel[survivor] = clean
        elif len(members) == 1:
            plan.unchanged += 1
    # A prefLabel outranks an altLabel (plan_kind rule (a)). An altLabel whose key is ANOTHER live kind's
    # prefLabel key makes that word name two kinds ("dogs" on "animal" next to "dog"), and one that is
    # exactly its own kind's prefLabel says nothing: detach both. Other wordings stay.
    dropped = set(plan.drop_meta) | set(plan.merge)
    pref_after = {cid: plan.relabel.get(cid, kinds[cid].pref) for cid in kinds if cid not in dropped}
    owner = {norm_key(p) or p.lower(): cid for cid, p in sorted(pref_after.items(), reverse=True)}
    for cid in sorted(kinds):
        if cid in plan.drop_meta:
            continue
        holder = plan.merge.get(cid, cid)
        for alt in kinds[cid].alts:
            hit = owner.get(norm_key(alt) or alt.lower())
            if (hit is not None and hit != holder) or alt.casefold() == pref_after[holder].casefold():
                plan.detach_alts.append((holder, alt))
    return plan


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


async def link_broader_sourced(gw: Any, narrower_id: str, broader_id: str, source: str) -> None:
    """B534: `narrower BROADER broader`, with `campy:link_source` on the edge's reifier. A no-op when the
    pair is already related through BROADER (the query checks), so a re-run adds nothing."""
    if narrower_id != broader_id:
        await gw.run("kinds.link_broader_sourced", cid=narrower_id, pid=broader_id, src=source)


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




async def apply_hygiene(gw: Any, plan: HygienePlan, kinds: dict[str, Kind]) -> dict[str, int]:
    """Carry `plan` out on the graph with set-based updates. Idempotent: a second run over the result
    plans nothing. Merged and meta-noun kinds are archived, never deleted; their old wording is kept
    as an altLabel of the survivor; only INSTANCE_OF edges into a meta-noun kind are removed (plain
    edges have no archive form). Returns counts."""
    done = {"relabelled": 0, "merged": 0, "meta_archived": 0, "alt_labels": 0, "alts_detached": 0}
    for cid in sorted(plan.relabel):                    # first, so a merge compares against the clean label
        k = kinds[cid]
        old, k.pref = k.pref, plan.relabel[cid]
        await gw.run("kinds.set_kind_label", cid=cid, txt=k.pref)
        done["alt_labels"] += await add_alt_label(gw, k, old)
        done["relabelled"] += 1
    for cid in sorted(plan.merge):
        survivor = plan.merge[cid]
        for q in ("merge_instance_of", "merge_broader_up", "merge_broader_down", "merge_alt_labels"):
            await gw.run(f"kinds.{q}", lid=cid, sid=survivor)
        await gw.run("quests.archive_concept", cid=cid)
        done["alt_labels"] += await add_alt_label(gw, kinds[survivor], kinds[cid].pref)
        done["merged"] += 1
    for holder, alt in plan.detach_alts:
        await gw.run("kinds.detach_alt_label", cid=holder, txt=alt)
        done["alts_detached"] += 1
    for cid in sorted(plan.drop_meta):
        await gw.run("kinds.drop_instance_of", kid=cid)
        await gw.run("quests.archive_concept", cid=cid)
        done["meta_archived"] += 1
    return done
