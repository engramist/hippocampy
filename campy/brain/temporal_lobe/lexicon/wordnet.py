"""
campy/brain/temporal_lobe/lexicon/wordnet.py -- B534: the one WordNet loader.

WordNet (Princeton WordNet 3.0, a permissive licence; read through NLTK, Apache-2.0) is a standard
lexical resource: which noun is a kind of which. The NLP pipeline asks it two questions:

  * `lexname(word)`: the lexicographer file of the word's first sense ("noun.animal"). B523's ownable
    test uses it.
  * `plan_links(kinds)`: which EXISTING kinds are hypernyms of which (B534). "puppy" is a kind of "dog"
    is a kind of "animal"; when both kinds are in the graph, `puppy BROADER dog` is a link a rule can
    write. The link is a candidate from a lexicon, not a model, and it says so (`link_source`).

Optional dependency (pyproject extra `wordnet`, plus the one-time corpus download
`python -m nltk.downloader wordnet`). Without either, every function here returns nothing; nothing in
the pipeline fails. The module imports NLTK on each call (the import is cached by Python) rather than
holding the corpus in a module global, so "WordNet absent" is a state a test can create.

Sense choice. A word has several noun senses ("bank"); walking the hypernyms of every one would link a
river bank to a financial institution. WordNet lists senses most frequent first and counts each lemma's
occurrences in a sense-tagged corpus. `noun_synsets(word, cutoff)` keeps the first sense, plus any later
sense whose count for this word is at least `cutoff` x the first sense's count (a word whose first sense
has no tagged occurrences keeps the first sense only). The default is the first sense only
(`SENSE_FIRST_ONLY`); `SENSE_FREQUENT` (0.5) also keeps the senses at least half as frequent. Measured on
two stores (PR body): the frequent-sense setting added 9 links on one and 2 on the other, about three of
eleven right ("character" under "concept", "landmark" under "event", "garden" under "group"), so the default
is first sense.
Both ends use it: a parent kind is matched only through a sense of ITS word that passes the same cutoff
("country" is a lemma of the synset "area", but not the dominant sense of "country").

Closed set. This module never decides a kind should exist: `plan_links` only pairs kinds it is handed.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from campy.brain.hippocampus.concept_links import norm_key

_logger = logging.getLogger(__name__)

SENSE_FIRST_ONLY = float("inf")         # walk only the most frequent sense of each word (the default)
SENSE_CUTOFF = SENSE_FIRST_ONLY
SENSE_FREQUENT = 0.5                    # first sense, plus later senses with >= half its tagged count
SOURCE = "wordnet"                      # the `link_source` value of a BROADER link this module proposes

_DETERMINERS = frozenset({"a", "an", "the", "my", "our", "your", "his", "her", "their", "its",
                          "this", "that", "these", "those"})
# A hypernym this high says nothing ("entity", "object", "whole"); a parent kind named by one of these
# is not proposed. Closed and small.
_TOO_GENERAL = frozenset({"entity", "object", "whole", "thing", "physical entity", "abstraction", "matter"})


def _wn() -> Any | None:
    """NLTK's WordNet reader, or None when NLTK or the corpus is not installed."""
    try:
        from nltk.corpus import wordnet as wn

        wn.ensure_loaded()
        return wn
    except Exception:                    # ImportError, LookupError (corpus not downloaded)
        return None


def available() -> bool:
    return _wn() is not None


def lexname(lemma: str) -> str | None:
    """Lexicographer file of the first (most frequent) noun sense of `lemma` ("noun.animal"), or None
    when WordNet is not installed or the word is unknown. A unique beginner (file `noun.Tops`: group,
    animal, food, person ...) takes the file most of its hyponyms are in, the category it heads
    (group.n.01 -> noun.group)."""
    wn = _wn()
    if wn is None:
        return None
    try:
        senses = wn.synsets(lemma, pos="n")
        if not senses:
            return None
        lexname = senses[0].lexname()
        if lexname == "noun.Tops":
            below = Counter(h.lexname() for h in senses[0].hyponyms() if h.lexname() != "noun.Tops")
            lexname = below.most_common(1)[0][0] if below else lexname
        return lexname
    except Exception:
        return None


def head_words(label: str) -> list[str]:
    """The WordNet lookups for a kind label, most specific first: the whole phrase as a compound
    ("ice cream" -> "ice_cream") when it has more than one word, then the head (last) word."""
    words = [w for w in (label or "").lower().replace("’", "'").split() if w.strip(".,;:!?\"()[]")]
    while len(words) > 1 and words[0] in _DETERMINERS:
        words = words[1:]
    if words and words[-1].endswith("'s") and len(words[-1]) > 2:
        words[-1] = words[-1][:-2]
    if not words:
        return []
    out = []
    if len(words) > 1:
        out.append("_".join(words))
    out.append(words[-1])
    return out


def noun_synsets(word: str, cutoff: float = SENSE_CUTOFF) -> list[Any]:
    """The noun senses of `word` to walk: the first, plus later ones whose lemma count for this word
    is at least `cutoff` x the first sense's count (see the module docstring)."""
    wn = _wn()
    if wn is None:
        return []
    try:
        senses = wn.synsets(word, pos="n")
        if not senses:
            return []
        base = wn.morphy(word, "n") or word.lower()

        def count(s) -> int:
            return sum(l.count() for l in s.lemmas() if l.name().lower() == base)

        top = count(senses[0])
        keep = [senses[0]]
        if top > 0:
            keep += [s for s in senses[1:] if count(s) >= cutoff * top]
        return keep
    except Exception:
        _logger.debug("WordNet sense lookup failed for %r", word, exc_info=True)
        return []


def _parents(syn: Any) -> list[Any]:
    return list(syn.hypernyms()) + list(syn.instance_hypernyms())


@dataclass
class Ancestor:
    synset: str                                   # "dog.n.01"
    keys: set[str]                                # norm_key of each lemma name
    distance: int
    path: list[str] = field(default_factory=list)  # synset names from the start sense up to this one


def hypernym_closure(syns: list[Any]) -> dict[str, Ancestor]:
    """Every hypernym (and instance hypernym) of the senses `syns` up to the root, nearest path kept.
    The start senses themselves are not included."""
    seen: dict[str, Ancestor] = {}
    frontier = [(s, [s.name()]) for s in syns]
    start = {s.name() for s in syns}
    dist = 0
    while frontier:
        dist += 1
        nxt = []
        for syn, path in frontier:
            for p in _parents(syn):
                n = p.name()
                if n in seen or n in start:
                    continue
                keys = {norm_key(l.name().replace("_", " ")) for l in p.lemmas()}
                seen[n] = Ancestor(n, {k for k in keys if k}, dist, path + [n])
                nxt.append((p, path + [n]))
        frontier = nxt
    return seen


def closure_of(synset_name: str) -> set[str]:
    wn = _wn()
    if wn is None:
        return set()
    try:
        return set(hypernym_closure([wn.synset(synset_name)]))
    except Exception:
        return set()


@dataclass
class WordNetLink:
    child: str                  # kind Concept id
    parent: str                 # kind Concept id
    child_label: str
    parent_label: str
    path: list[str]             # synset path from the child's sense to the parent's
    source: str = SOURCE


def plan_links(kinds: dict[str, Any], *, involving: set[str] | None = None,
               cutoff: float = SENSE_CUTOFF) -> list[WordNetLink]:
    """`child BROADER parent` for kinds already in `kinds` (id -> Kind with .pref, .alts, .keys(),
    .broader), where the parent's label (or altLabel) names a WordNet hypernym of the child's head noun.

    Nearest parents only: a match is dropped when it is itself a hypernym of another matched kind
    ("dog" is dropped for "puppy" when "canine" is also a kind). Synonyms of the child, the child's own
    wording, kinds already linked directly, and over-general hypernyms ("entity") are not proposed.
    `involving` limits the result to links where the child or the parent is in the set (a kind was just
    created: its upward links and the links of existing kinds that now reach it). Pure given WordNet;
    returns [] when WordNet is absent. Never proposes a kind that is not in `kinds`.
    """
    if not available():
        return []
    by_key: dict[str, list[str]] = {}
    for cid in sorted(kinds):
        for key in kinds[cid].keys():
            if key not in _TOO_GENERAL:
                by_key.setdefault(key, []).append(cid)
    senses_of_key = {key: {s.name() for s in noun_synsets(key.replace(" ", "_"), cutoff)} for key in by_key}
    out: list[WordNetLink] = []
    for cid in sorted(kinds):
        child = kinds[cid]
        syns: list[Any] = []
        for word in head_words(child.pref):
            syns = noun_synsets(word, cutoff)
            if syns:
                break
        if not syns:
            continue
        own = set(child.keys())
        for s in syns:                                           # synonyms are the same kind, not a parent
            own |= {norm_key(l.name().replace("_", " ")) for l in s.lemmas()}
        closure = hypernym_closure(syns)
        matches: dict[str, tuple[str, Ancestor]] = {}            # parent id -> (synset, nearest ancestor)
        for anc in sorted(closure.values(), key=lambda a: (a.distance, a.synset)):
            for key in anc.keys:
                if anc.synset not in senses_of_key.get(key, ()):
                    continue                                     # the parent's word must mean this synset in its dominant sense
                for pid in by_key.get(key, ()):
                    if pid != cid and pid not in matches and not (kinds[pid].keys() & own):
                        matches[pid] = (anc.synset, anc)
        for pid, (syn_name, anc) in matches.items():
            others = [m for q, m in matches.items() if q != pid and m[0] != syn_name]
            if any(syn_name in closure_of(o[0]) for o in others):
                continue                                         # a nearer matched kind sits between
            if pid in child.broader:
                continue
            if involving is not None and cid not in involving and pid not in involving:
                continue
            out.append(WordNetLink(cid, pid, child.pref, kinds[pid].pref, anc.path))
    return out


def hypernym_support(child_label: str, parent_keys: set[str], cutoff: float = SENSE_CUTOFF) -> list[str] | None:
    """B535: the synset path from the child's sense up to a hypernym that one of `parent_keys` (norm_key forms of the
    parent kind's label and altLabels) names, or None. The same sense policy as `plan_links` (the child's first
    sense; the parent's word must mean that synset in its dominant sense), but ANY ancestor counts, not only the
    nearest one: this is the independent check of a proposal someone else made, not a proposal. None without WordNet."""
    if not available() or not parent_keys:
        return None
    syns: list[Any] = []
    for word in head_words(child_label):
        syns = noun_synsets(word, cutoff)
        if syns:
            break
    if not syns:
        return None
    wanted = {k for k in parent_keys if k and k not in _TOO_GENERAL}
    own = {norm_key(l.name().replace("_", " ")) for s in syns for l in s.lemmas()}
    for anc in sorted(hypernym_closure(syns).values(), key=lambda a: (a.distance, a.synset)):
        for key in anc.keys & wanted:
            if key in own:
                continue
            if anc.synset in {s.name() for s in noun_synsets(key.replace(" ", "_"), cutoff)}:
                return anc.path
    return None


# --- B564: action kinds and role heads --------------------------------------------------
#
# An action kind is a WordNet noun synset under `event.n.01` (`act.n.02` is itself under it, so one root
# reaches every action). The model never names the sense: `action_sense` picks it by rule from the verb or
# activity noun the turn contains, and `action_chain` is the hypernym chain written as BROADER with
# `link_source "wordnet"`. The ids are WordNet's synset names, so no id is invented.

ACTION_ROOT = "event.n.01"
# A light verb names no activity ("went", "made"): the activity is in its object. Never given a sense.
LIGHT_VERBS = frozenset({"go", "get", "take", "make", "do", "have", "be", "give", "put", "keep", "let", "come"})
PERSON_ROOTS = ("person.n.01", "social_group.n.01")
PLACE_ROOTS = ("location.n.01", "structure.n.01", "geological_formation.n.01", "body_of_water.n.01",
               "vegetation.n.01")
PHYSICAL_ROOTS = ("physical_entity.n.01",)


@dataclass(frozen=True)
class ActionSense:
    synset: str                                   # "hike.n.01"
    lemma: str                                    # first lemma of the synset ("hike")
    chain: tuple[tuple[str, str], ...]            # (child synset, parent synset) up to ACTION_ROOT
    labels: tuple[tuple[str, str], ...]           # (synset, first lemma) of the sense and every ancestor

    @property
    def concept_id(self) -> str:
        return "wn:" + self.synset


def concept_id_of(synset_name: str) -> str:
    return "wn:" + synset_name


def _under(syn: Any, root: Any) -> bool:
    return syn == root or root in syn.closure(lambda x: x.hypernyms())


def first_sense_under(word: str, roots: tuple[str, ...] | list[str]) -> bool:
    """True when the first (most frequent) noun sense of `word` is under one of the synsets `roots` (names)."""
    wn = _wn()
    if wn is None or not word:
        return False
    try:
        senses = wn.synsets(word.lower().replace(" ", "_"), pos="n")
        if not senses:
            return False
        return any(_under(senses[0], wn.synset(r)) for r in roots)
    except Exception:
        return False


def _action_candidates(wn: Any, lemma: str, root: Any) -> list[tuple[int, int, int, Any]]:
    """(-count, direct 0 / derived 1, order, synset) for the event senses `lemma` has as a noun, or that a verb
    `lemma` is nominalised to (WordNet's derivationally related nouns)."""
    out: list[tuple[int, int, int, Any]] = []
    order = 0
    for s in wn.synsets(lemma, pos="n"):
        if _under(s, root):
            n = sum(x.count() for x in s.lemmas() if x.name().lower() == lemma)
            out.append((-n, 0, order, s))
        order += 1
    for vs in wn.synsets(lemma, pos="v"):
        for vl in vs.lemmas():
            if vl.name().lower() != lemma:
                continue
            for d in vl.derivationally_related_forms():
                ds = d.synset()
                if ds.pos() == "n" and _under(ds, root):
                    n = sum(x.count() for x in ds.lemmas() if x.name().lower() == d.name().lower())
                    out.append((-n, 1, order, ds))
                order += 1
    return out


def action_chain(syn: Any, root: Any) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    """((child, parent) names, (synset, first lemma) labels): every hypernym edge from `syn` up to `root`
    inclusive, over all hypernym paths; a parent outside the root's subtree is not followed."""
    edges: list[tuple[str, str]] = []
    seen = {syn.name()}
    labels = {syn.name(): syn.lemmas()[0].name()}
    todo = [syn]
    while todo:
        cur = todo.pop()
        if cur == root:
            continue
        for p in cur.hypernyms():
            if not _under(p, root):
                continue
            edges.append((cur.name(), p.name()))
            if p.name() not in seen:
                seen.add(p.name())
                labels[p.name()] = p.lemmas()[0].name()
                todo.append(p)
    return tuple(sorted(set(edges))), tuple(sorted(labels.items()))


def action_sense(words: list[str]) -> ActionSense | None:
    """The action kind of the first of `words` (lemmas, most specific first: the whole phrase with `_`, then its
    head) that has one: the most frequent event noun sense (lemma counts), direct before derived on a tie, then
    WordNet's sense order. A light verb has none (and stops the search); no WordNet or no sense gives None."""
    wn = _wn()
    if wn is None:
        return None
    try:
        root = wn.synset(ACTION_ROOT)
        for w in words:
            lemma = (w or "").lower().replace(" ", "_")
            if not lemma or lemma in LIGHT_VERBS:
                if lemma in LIGHT_VERBS:
                    return None
                continue
            cands = _action_candidates(wn, lemma, root)
            if not cands:
                continue
            best = min(cands, key=lambda c: c[:3])[3]
            chain, labels = action_chain(best, root)
            return ActionSense(best.name(), best.lemmas()[0].name().replace("_", " "), chain,
                               tuple((k, v.replace("_", " ")) for k, v in labels))
    except Exception:
        _logger.debug("action sense lookup failed for %r", words, exc_info=True)
    return None
