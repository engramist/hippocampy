"""
campy/brain/temporal_lobe/observations/ownership.py -- B523: ownership decided by a grammar rule.

The extractor (an LLM) files the same fact under whichever predicate it likes: a speaker's dog
shows up under `plans`, `prefers` and `relates_to`, never `owns`. "What does X own" cannot be a
query while the predicate depends on the verb the model chose. This module decides ownership from
the sentence's grammar, the one general English construction **first-person possession of a named
entity**, and writes it through the grounded Observation write API:

    predicate `owns`, subject = the Message's speaker Concept, object = the entity Concept,
    evidence = that Message (quote = the matched span), rule_version `rule:first_person_possession`.

Constructions (spaCy dependency parse; the model is `get_nlp` from the NER step, not a second one).
Each has a short plain-English name, recorded per firing; the verb set is acquiring/having, never
about what is acquired (have, own, adopt, get, buy, rescue):

  possessive   my / our on a noun that IS the entity or is in apposition / compound with it:
               "my dog Toby", "Toby, my pup", "our cat Luna", "Toby is my dog" (predicate nominal).
  acquisition  first-person subject (I / we) of an acquisition verb whose direct object is the entity,
               a noun in apposition with it, or the noun it is "named"/"called":
               "I adopted Buddy", "we got Luna", "I bought a puppy, Buddy", "I rescued a cat named Luna".
  care         `have` as a subjectless infinitive or gerund under a first-person present/past clause
               about a feeling (lucky, grateful, happy ... ; love, enjoy, appreciate ...):
               "we feel so lucky to have Scout", "I love having Pixie around". Wanting, hoping, planning,
               "would like to", "going to" stay irrealis.
  naming       "I/we named|called him/her/it X", "X is what I named him", "his/her name is X", "their
               names are A, B and C", when the pronoun refers to a kind noun the speaker possessed or
               acquired in the same turn or in the speaker's previous turn (FOLLOWED_BY, up to three turns
               back; "my pup", "a new puppy I adopted", "I got a plant"). A kind held only by "my/our"
               must be in the graph's kind vocabulary ("our lives" is not); an acquired one needs no entry.
               No such kind noun, no firing ("I named the project Atlas").
  coordination "X and I <verb>" / "I and X <verb>". It CONFIRMS and never creates ownership alone: X must
               already be the object of one of this speaker's rule-written owns Observations (any other
               construction above), or be INSTANCE_OF a kind that such an object is INSTANCE_OF (person-like
               kinds do not count). Confirmation reads the graph, so the backfill runs it as a second pass
               and the result does not depend on turn order. Its Observations carry
               `rule:first_person_possession:coordination`, which confirms nothing further.

The entity is a proper noun: an existing Concept linked to the Message (MENTIONS, or OBSERVATION_ABOUT of an
Observation it evidences; never a kind), or a Concept of that name the rule reuses or creates because the
turn grounds it (with the head noun as its kind). Coordination never creates one. The rule calls no LLM and
keeps no state outside the graph. It does not fire for a question, a negated verb ("I don't have a car"), a
modal or wish ("I would adopt Buddy", "I wish I had a car"), a possessor that is not first person
("your dog Toby", "my friend's dog Rex"), or a possessed noun that names a person's role ("my friend
Sam": kin and social roles are relations, not ownership). Each skip is counted by reason.
Re-running is idempotent: the Observation write API dedupes on (subject, predicate, object).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.graph.gateway import get_gateway

_logger = logging.getLogger(__name__)

RULE_ID = "rule:first_person_possession"
CONFIDENCE = 0.95            # a rule, not a model estimate

# Acquiring / having. Lemmas; deliberately not about what is acquired.
ACQUISITION_VERBS = frozenset({"have", "own", "adopt", "get", "buy", "rescue"})
_FIRST_PERSON_DETERMINERS = frozenset({"my", "our"})
_FIRST_PERSON_SUBJECTS = frozenset({"i", "we"})
# A verb whose complement is wished for or imagined, not asserted.
_IRREALIS_HEADS = frozenset({"wish", "hope", "imagine", "wonder", "pretend", "dream", "suppose"})
_IRREALIS_MARKS = frozenset({"if", "unless", "whether"})
_NEGATING_ADVERBS = frozenset({"never", "hardly", "barely", "scarcely"})
# Relational nouns for people (kin, partners, social roles): possessing one is a relation, not
# ownership. A closed linguistic class; nothing here names what a person owns.
PERSON_ROLE_NOUNS = frozenset({
    "mother", "mom", "mum", "mama", "father", "dad", "papa", "parent", "sister", "brother", "sibling",
    "son", "daughter", "child", "kid", "baby", "wife", "husband", "spouse", "partner", "fiance",
    "fiancee", "boyfriend", "girlfriend", "ex", "friend", "pal", "mate", "buddy", "cousin", "aunt",
    "uncle", "nephew", "niece", "grandmother", "grandma", "grandfather", "grandpa", "grandparent",
    "grandson", "granddaughter", "boss", "coworker", "colleague", "teammate", "neighbor", "neighbour",
    "teacher", "mentor", "manager", "roommate", "classmate", "client", "student", "employee",
    "gf", "bf", "bff", "hubby", "bro", "sis", "in-law", "stepmother", "stepfather", "godmother", "godfather",
})
# Modifiers that turn "my X" into a preference or an ideal rather than a thing held.
_PREFERENCE_MODIFIERS = frozenset({"favorite", "favourite", "go", "ideal", "dream"})
# Care / naming vocabulary (B523 widening)
_THIRD_PERSON_POSS = frozenset({"his", "her", "their", "its"})
NAMING_VERBS = frozenset({"name", "call"})
# "lucky to have X", "love having X": the main clause is first-person and about a feeling.
EMOTION_ADJECTIVES = frozenset({"lucky", "grateful", "thankful", "blessed", "happy", "glad", "proud", "fortunate", "delighted"})
EMOTION_VERBS = frozenset({"love", "enjoy", "appreciate", "adore", "cherish", "treasure", "like"})
_STATE_VERBS = frozenset({"be", "feel", "seem", "get", "become"})
# Kinds that cannot be what a speaker "possesses", for confirming "X and I" by a shared kind.
NON_POSSESSABLE_KINDS = frozenset({"person", "people", "human", "man", "woman", "adult", "individual", "boy", "girl"})
# What a thing the speaker holds can be: WordNet lexicographer files (first, most frequent sense).
OWNABLE_LEXNAMES = frozenset({"noun.animal", "noun.artifact", "noun.food", "noun.plant", "noun.possession"})
# Lexnames that rule a noun out even when a graph kind of that name exists (an extractor can file
# "people" under a kind "group"); only consulted when WordNet is installed.
NON_OWNABLE_LEXNAMES = frozenset({"noun.group", "noun.person", "noun.act", "noun.event", "noun.state", "noun.feeling",
                                  "noun.cognition", "noun.communication", "noun.attribute", "noun.time"})
_NAME_ENTITY_LABELS = frozenset({"PERSON", "ORG", "GPE", "LOC", "FAC", "WORK_OF_ART", "PRODUCT", "EVENT", "NORP", "LAW"})
COORDINATION_RULE_ID = RULE_ID + ":coordination"
_NAMING_CUE_RE = re.compile(r"(?<!\w)(nam(e|ed|ing)|call(ed|ing)?)(?!\w)", re.IGNORECASE)
_LINK_DEPS = frozenset({"appos", "compound"})

_CUE_RE = re.compile(r"(?<!\w)(i|we|my|our)(?!\w)", re.IGNORECASE)

SKIP_REASONS = ("modifier", "partial_name", "no_concept", "negated", "irrealis", "not_first_person", "question", "not_ownable",
                "no_speaker", "too_long")


@dataclass(frozen=True)
class OwnershipMatch:
    concept_id: str | None    # None: a proper noun with no Concept yet (the writer creates it)
    label: str
    quote: str
    start: int            # char offsets of the quote in the Message text
    end: int
    construction: str     # "possessive" | "acquisition"
    kind: str | None = None   # head noun of the construction ("dog" in "my dog Pixie"); None without one


@dataclass
class OwnershipStats:
    messages: int = 0
    firings: int = 0                  # matches found (rule fired)
    created: int = 0                  # new Observations
    duplicate: int = 0                # the claim already existed (evidence added)
    rejected: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    # Concepts the rule created for a proper noun the turn grounds (names match entities.py counters)
    entity_concepts_created: int = 0
    entities_linked: int = 0
    kinds_created: int = 0
    kinds_reused: int = 0
    kinds_broader: int = 0
    kinds_close_match: int = 0
    kinds_dropped_meta: int = 0   # B525: a proposed kind was a meta-noun (name, thing, ...) and dropped
    kinds_wordnet: int = 0        # B534: kind BROADER links proposed from WordNet hypernyms
    kind_alt_labels: int = 0
    kinds_linked: int = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def as_details(self) -> dict[str, Any]:
        return {"messages": self.messages, "firings": self.firings, "created": self.created,
                "duplicate": self.duplicate, "concepts_created": self.entity_concepts_created,
                "kinds_created": self.kinds_created, "kinds_linked": self.kinds_linked,
                "rejected": dict(self.rejected), "skipped": dict(self.skipped)}


# --- the matcher (pure; spaCy Doc in, matches out) -----------------------------------

def _wordnet_lexname(lemma: str) -> str | None:
    """Lexicographer file of the first (most frequent) noun sense of `lemma`, or None when WordNet is
    not installed (optional extra `wordnet`) or the word is unknown. The loader is shared with B534."""
    from campy.brain.temporal_lobe.lexicon import wordnet

    return wordnet.lexname(lemma)


def make_ownable(instantiated_kinds: set[str]):
    """The test for "can the speaker hold one of these": the noun is a kind already in the graph that
    some entity is INSTANCE_OF (`instantiated_kinds`, norm_key forms), or its WordNet lexname is one of
    OWNABLE_LEXNAMES; a WordNet lexname in NON_OWNABLE_LEXNAMES (group, act, state ...) vetoes both.
    Without WordNet it is the graph kinds alone."""
    from campy.brain.hippocampus.concept_links import norm_key

    def ownable(lemma: str) -> bool:
        lexname = _wordnet_lexname(lemma.lower())
        if lexname in NON_OWNABLE_LEXNAMES:
            return False
        return norm_key(lemma) in instantiated_kinds or lexname in OWNABLE_LEXNAMES

    return ownable


def _full_span(doc, s: int, e: int) -> tuple[int, int]:
    """A proper-noun span grown to the whole name: leading proper-noun compounds ("Iron" of "Iron Man")
    and the named entity spaCy recognises around it, trimmed to proper-noun tokens."""
    lo, hi = s, e
    while lo > 0 and doc[lo - 1].pos_ == "PROPN" and doc[lo - 1].dep_ in ("compound", "amod", "nmod") \
            and lo <= doc[lo - 1].head.i < hi:
        lo -= 1
    for ent in doc.ents:
        if ent.label_ in _NAME_ENTITY_LABELS and ent.start <= lo and hi <= ent.end:
            a, b = ent.start, ent.end
            while a < b and doc[a].pos_ != "PROPN":
                a += 1
            while b > a and doc[b - 1].pos_ != "PROPN":
                b -= 1
            if all(doc[i].pos_ == "PROPN" for i in range(a, b)) and a <= lo and hi <= b:
                lo, hi = a, b
    return lo, hi


def _is_question(sent) -> bool:
    return sent.text.strip().endswith("?")


def _concept_spans(doc, concepts: dict[str, str]) -> list[tuple[int, int, str]]:
    """Token spans of each known entity label (case-insensitive, whole tokens), longest first,
    non-overlapping: [(start_token, end_token, label_key)]."""
    out: list[tuple[int, int, str]] = []
    lowered = [t.lower_ for t in doc]
    for key in sorted(concepts, key=lambda k: -len(k.split())):
        parts = key.split()
        n = len(parts)
        if not n:
            continue
        for i in range(len(lowered) - n + 1):
            if lowered[i:i + n] == parts and not any(i < e and s < i + n for s, e, _ in out):
                out.append((i, i + n, key))
    return sorted(out)


def _propn_spans(doc, taken: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    """Maximal runs of proper-noun tokens that are not a known entity: constructions about them
    are counted as skipped (no Concept), never written."""
    spans, i = [], 0
    while i < len(doc):
        if doc[i].pos_ == "PROPN" and not any(s <= i < e for s, e, _ in taken):
            j = i
            while j + 1 < len(doc) and doc[j + 1].pos_ == "PROPN" and not any(s <= j + 1 < e for s, e, _ in taken):
                j += 1
            spans.append((i, j + 1))
            i = j + 1
        else:
            i += 1
    return spans


def _anchors(e, start: int | None = None) -> list:
    """Tokens that stand for the same noun phrase as entity head `e`, nearest first: `e`, the noun
    it is in apposition / compound with ("my dog Toby", "Toby, my pup"), the noun it is named
    ("a puppy named Max"), the earlier item of a list ("Buddy and Luna"), the subject of a
    predicate nominal ("Toby is my dog"), the noun written right before the name even when the parser attached
    the two as siblings ("my pup Toby")."""
    out: list = []

    def add(t) -> None:
        if t is not None and t not in out:
            out.append(t)

    add(e)
    for c in e.children:          # "Toby, my pup" / "her cat Luna": the noun hangs below the name
        if c.dep_ in _LINK_DEPS:
            add(c)
    t = e
    for _ in range(3):
        if t.dep_ in _LINK_DEPS and t.head.i != t.i:
            t = t.head
            add(t)
        elif t.dep_ in ("oprd", "attr", "dobj", "pobj") and t.head.dep_ == "acl" and t.head.lemma_ in ("name", "call") \
                and t.head.head.i != t.head.i:
            t = t.head.head
            add(t)
        elif t.dep_ == "conj" and t.head.i != t.i:
            t = t.head
            add(t)
        else:
            break
    if start:
        left = e.doc[start - 1]
        if left.pos_ == "NOUN" and left.i + 1 == start and (left.head.i == e.head.i or left.head.i == e.i or e.head.i == left.i):
            add(left)
    # a nominal predicate: "Toby is my dog" -- the entity is the subject, the anchor the attribute
    for a in list(out):
        if a.dep_ in ("nsubj", "nsubjpass"):
            for sib in a.head.children:
                if sib.dep_ == "attr":
                    add(sib)
    return out


def _poss_of(anchor):
    """The possessor children of a noun: possessive determiners and 's-possessor nouns."""
    return [c for c in anchor.children if c.dep_ == "poss"]


def _negated(verb) -> bool:
    return any(c.dep_ == "neg" for c in verb.children) or any(
        c.dep_ == "advmod" and c.lower_ in _NEGATING_ADVERBS for c in verb.children)


def _irrealis(verb) -> bool:
    if any(c.dep_ == "aux" and c.tag_ == "MD" for c in verb.children):
        return True
    if any(c.dep_ == "mark" and c.lower_ in _IRREALIS_MARKS for c in verb.children):
        return True
    return verb.dep_ in ("ccomp", "xcomp", "advcl") and verb.head.lemma_ in _IRREALIS_HEADS


def _first_person_subject(verb):
    for c in verb.children:
        if c.dep_ in ("nsubj", "nsubjpass"):
            if c.lower_ in _FIRST_PERSON_SUBJECTS or any(j.lower_ in _FIRST_PERSON_SUBJECTS for j in c.conjuncts):
                return c, True
            return c, False
    return None, False


def _classify(doc, span, ownable=None):
    """Decide one entity head `e` (spaCy token): (construction, quote_start_tok, quote_end_tok)
    when it is first-person possessed, or a skip reason, or None when no ownership construction
    touches it."""
    e, entity_end = span.root, span.end
    if _is_question(e.sent):
        return None if not _touches_ownership(e, span.start) else "question"
    if e.dep_ in ("compound", "amod", "nmod") and e.head.i > e.i and e.head.pos_ in ("NOUN", "PROPN"):
        # "my Rocky Mountains trip", "my Gryffindor scarf": the name modifies the possessed noun
        return "modifier" if _touches_ownership(e, span.start) else None
    anchors = _anchors(e, span.start)
    for a in anchors:
        poss = _poss_of(a)
        if poss:
            # the nearest possessor decides
            p = poss[0]
            if not (p.tag_ == "PRP$" and p.lower_ in _FIRST_PERSON_DETERMINERS):
                return "not_first_person"
            lo_i, hi_i = sorted((p.i, a.i, e.i))[0], sorted((p.i, a.i, e.i))[-1]
            if a.lemma_ in PERSON_ROLE_NOUNS or any(t.pos_ == "NOUN" and t.lemma_.lower() in PERSON_ROLE_NOUNS for t in doc[lo_i:hi_i + 1]):
                return "not_ownable"     # also when the parser hangs "my" on the name: "my gf, Toby"
            if any(t.lower_ in _PREFERENCE_MODIFIERS for t in doc[a.left_edge.i:a.i + 1]):
                return "not_ownable"     # "Garlic is my go-to ingredient": a preference, not a possession
            if _not_ownable(a, span, ownable):
                return "not_ownable"     # "Nature is my haven": the held noun is not a thing one holds
            gov = a.head
            if a.dep_ in ("dobj", "attr") and gov.lemma_ in ACQUISITION_VERBS | {"be"}:
                if _negated(gov):
                    return "negated"
                if gov.lemma_ in ACQUISITION_VERBS and _irrealis(gov):
                    return "irrealis"
            lo = min(p.i, a.i, e.i)
            hi = max(p.i, a.i, entity_end - 1)
            return ("possessive", lo, hi, a)
        if a.dep_ == "dobj" and a.head.pos_ == "VERB" and a.head.lemma_ in ACQUISITION_VERBS:
            verb = a.head
            subj, first = _first_person_subject(verb)
            construction = "acquisition"
            if subj is None:
                # no subject of its own: "lucky to have Scout" is held (a first-person feeling about
                # having it); "I'm going to adopt Buddy", "to get Luna" are planned, not held
                subj = _stative_subject(verb)
                if subj is None:
                    return "irrealis" if verb.dep_ in ("xcomp", "advcl", "ccomp", "acl", "pcomp") else "not_first_person"
                first, construction = True, "care"
            if not first:
                return "not_first_person"
            nxt = doc[entity_end] if entity_end < len(doc) else None
            if any(c.dep_ in ("xcomp", "ccomp") for c in verb.children) or (
                    nxt is not None and nxt.lower_ == "to" and nxt.dep_ == "aux"):
                return "not_ownable"     # "I got Sam to help": the object is an agent, not a possession
            if a.lemma_ in PERSON_ROLE_NOUNS or _not_ownable(a, span, ownable):
                return "not_ownable"
            if _negated(verb):
                return "negated"
            if _irrealis(verb):
                return "irrealis"
            lo = min(subj.i, e.i)
            hi = max(a.i, entity_end - 1)
            return (construction, lo, hi, a)
    return None


def _not_ownable(anchor, span, ownable) -> bool:
    """True when the held noun is a common noun other than the entity and fails the ownable test.
    No test given (None): nothing is rejected."""
    if ownable is None or anchor.pos_ != "NOUN" or span.start <= anchor.i < span.end:
        return False
    return not ownable(anchor.lemma_.lower())


def _stative_subject(verb):
    """The first-person subject of the main clause when `verb` ("have") is a subjectless infinitive or
    gerund under a first-person present/past clause about a feeling: "lucky to have X", "grateful to
    have X", "love having X". None otherwise (want / plan / hope / would like / going to stay irrealis)."""
    if verb.dep_ not in ("xcomp", "pcomp", "advcl", "ccomp", "acl"):
        return None
    head, main = verb.head, None
    if head.pos_ == "ADJ" and head.lemma_ in EMOTION_ADJECTIVES and head.dep_ == "acomp":
        main = head.head
    elif head.pos_ == "VERB" and head.lemma_ in EMOTION_VERBS and verb.dep_ in ("xcomp", "pcomp"):
        main = head
    if main is None or main.lemma_ not in EMOTION_VERBS | _STATE_VERBS:
        return None
    subj, first = _first_person_subject(main)
    if not first or _negated(main) or _irrealis(main):
        return None
    return subj


def _kind_nouns(doc, vocab: set[str] | None = None) -> list[str]:
    """Common nouns the speaker possesses or acquired in `doc` (first-person): "my pup", "a new puppy I
    adopted", "I got a plant". The kind a later pronoun ("I named him X", "his name is X") refers to.
    A noun held only by "my/our" ("our lives", "my little ones") must be a kind already in the graph's
    kind vocabulary (`vocab`, the labels of kind Concepts; None disables the check); a noun the
    speaker acquired by an acquisition verb needs no vocabulary entry."""
    out: list[str] = []
    for t in doc:
        if t.pos_ != "NOUN" or t.lemma_.lower() in PERSON_ROLE_NOUNS or _is_question(t.sent):
            continue
        if any(m.lower_ in _PREFERENCE_MODIFIERS for m in doc[t.left_edge.i:t.i + 1]):
            continue
        held = False
        in_vocab = vocab is None or t.lemma_.lower() in vocab or t.lower_ in vocab
        for p in _poss_of(t):
            held = held or (p.tag_ == "PRP$" and p.lower_ in _FIRST_PERSON_DETERMINERS and in_vocab)
        gov = t.head
        if t.dep_ == "dobj" and gov.pos_ == "VERB" and gov.lemma_ in ACQUISITION_VERBS:
            _, first = _first_person_subject(gov)
            held = held or first
        for c in t.children:
            if c.dep_ in ("relcl", "acl") and c.lemma_ in ACQUISITION_VERBS:
                _, first = _first_person_subject(c)
                held = held or first
        if held and not (gov.lemma_ in ACQUISITION_VERBS | {"be"} and t.dep_ in ("dobj", "attr") and _negated(gov)):
            out.append(t.lemma_.lower())
    return out


def _naming(doc, span, ctx_kinds: list[str]):
    """Naming ("I named him X", "X is what I named him", "his name is X"): the entity is a possession
    of the speaker when the pronoun refers to a kind noun the speaker possesses (same turn or the
    speaker's previous turn, passed in `ctx_kinds`). Returns a verdict like `_classify`, or None."""
    e = span.root
    if _is_question(e.sent):
        return None
    while e.dep_ == "conj" and e.head.i != e.i:       # "Their names are A, B and C": the list shares the clause
        e = e.head
    verb, target, lo = None, None, None            # target: "pron" | the named noun's lemma
    if e.dep_ in ("oprd", "attr", "xcomp", "dobj") and e.head.lemma_ in NAMING_VERBS and e.head.pos_ == "VERB":
        verb = e.head
        if e.dep_ != "dobj" and any(c.dep_ == "dobj" and c.pos_ == "PRON" for c in verb.children):
            target = "pron"                                           # I named him Buddy
        elif e.dep_ == "dobj" and any(c.dep_ == "poss" and c.lower_ in _THIRD_PERSON_POSS for c in e.children):
            target = "pron"                                           # We named her Luna
    elif e.dep_ == "appos" and e.head.dep_ == "dobj" and e.head.head.lemma_ in NAMING_VERBS:
        noun = e.head
        if any(p.lower_ in _FIRST_PERSON_DETERMINERS for p in _poss_of(noun)):
            return None                                               # "I named my cat Luna": possession
        verb, target = noun.head, noun.lemma_.lower()                 # I named the project Atlas
    elif e.dep_ in ("nsubj", "attr", "nsubjpass") and e.head.lemma_ == "be":
        be = e.head
        for c in be.children:
            if c.dep_ in ("nsubj", "attr") and c.lemma_ == "name":
                poss = [p for p in c.children if p.dep_ == "poss" and p.lower_ in _THIRD_PERSON_POSS]
                if poss:
                    s_ = _first_person_context(ctx_kinds)
                    if s_ is None:
                        return "no_kind_context"
                    return ("naming", min(poss[0].i, e.i), max(e.i, span.end - 1), s_)    # his name is X
            if c.dep_ in ("ccomp", "csubj", "relcl", "advcl") and c.lemma_ in NAMING_VERBS \
                    and any(k.pos_ == "PRON" and k.dep_ in ("dobj", "oprd") for k in c.children):
                verb, target = c, "pron"                                   # X is what I named him
    if verb is None or target is None:
        return None
    subj, first = _first_person_subject(verb)
    if subj is None:
        return "irrealis" if verb.dep_ in ("xcomp", "advcl", "ccomp", "acl") else None
    if not first:
        return "not_first_person"
    if _negated(verb):
        return "negated"
    if _irrealis(verb):
        return "irrealis"
    kind = _first_person_context(ctx_kinds) if target == "pron" else (target if target in ctx_kinds else None)
    if kind is None:
        return "no_kind_context"
    hi = max(span.end - 1, verb.i, *(k.i for k in verb.children if k.dep_ in ("dobj", "oprd")))
    return ("naming", min(subj.i, e.i), hi, kind)


def _first_person_context(ctx_kinds: list[str]):
    return ctx_kinds[-1] if ctx_kinds else None


def _coordination(doc, span):
    """"X and I <verb>" / "I and X <verb>": X shares a first-person subject with the speaker. Only a
    candidate here; the caller confirms it against what the speaker already owns."""
    e = span.root
    if _is_question(e.sent):
        return None
    top = e
    while top.dep_ == "conj" and top.head.i != top.i:
        top = top.head
    if top.dep_ not in ("nsubj", "nsubjpass"):
        return None
    group = [top, *top.conjuncts]
    speakers = [t for t in group if t.lower_ in ("i", "me") and t.i != e.i]
    if e.i not in {t.i for t in group} or not speakers or _negated(top.head):
        return None
    return ("coordination", min(e.i, *(t.i for t in speakers)), max(e.i, top.head.i, *(t.i for t in speakers)), None)


def _touches_ownership(e, start: int | None = None) -> bool:
    for a in _anchors(e, start):
        if _poss_of(a) or (a.dep_ == "dobj" and a.head.lemma_ in ACQUISITION_VERBS):
            return True
    return False


def _kind_of(extra, span) -> str | None:
    """The kind a verdict carries: a head-noun token (possessive / acquisition / care) or the
    kind lemma (naming). None without a head noun."""
    if isinstance(extra, str):
        return extra
    if extra is not None and extra.pos_ == "NOUN" and extra.i not in range(span.start, span.end):
        return extra.lemma_.lower()
    return None


def find_ownership(doc, concepts: dict[str, str], stats: OwnershipStats | None = None, *,
                   context_kinds: list[str] | None = None, confirmed: set[str] | None = None,
                   mode: str = "all", kind_vocab: set[str] | None = None, ownable=None) -> list[OwnershipMatch]:
    """First-person possession (or care, or naming) of a named entity in `doc`.

    `concepts` maps a lower-cased entity label to its Concept id (the closed set). One match per
    Concept; skips are counted in `stats`. `context_kinds`: kind nouns the speaker possessed in their
    previous turn (naming resolves a pronoun against them and this turn's own). `confirmed`: Concept
    ids the speaker already owns by a rule firing, or that share a possessed kind with one;
    "X and I" counts only for these. `mode`: "all", "no_coordination" (first backfill pass) or
    "coordination_only" (second pass, once every other firing exists)."""
    stats = stats if stats is not None else OwnershipStats()
    text = doc.text
    spans = _concept_spans(doc, concepts)
    ctx = [*(context_kinds or []), *_kind_nouns(doc, kind_vocab)]
    entities = []
    covered: set[int] = set()
    for s, e_, key in spans:
        if doc[s:e_].root.pos_ != "PROPN":
            continue
        fs, fe = _full_span(doc, s, e_)
        covered.update(range(fs, fe))
        if (fs, fe) != (s, e_):
            stats.skip("partial_name")       # the Concept is only part of the name ("Man" in "Iron Man")
            continue
        entities.append((s, e_, key))
    for s, e_ in _propn_spans(doc, spans):
        if all(i in covered for i in range(s, e_)):
            continue
        fs, fe = _full_span(doc, s, e_)
        if any(i in covered for i in range(fs, fe)) and (fs, fe) != (s, e_):
            continue
        entities.append((fs, fe, None))
    out: list[OwnershipMatch] = []
    seen: set[str] = set()
    for s, e_, key in entities:
        cid = concepts[key] if key else None
        name = doc[s:e_].text
        if (cid and cid in seen) or (cid is None and any(m.concept_id is None and m.label.lower() == name.lower() for m in out)):
            continue
        span = doc[s:e_]
        verdict = None
        if mode != "coordination_only":
            verdict = _naming(doc, span, ctx)
            if verdict is None:
                verdict = _classify(doc, span, ownable)
            elif verdict == "no_kind_context":
                held = _classify(doc, span, ownable)          # "I named my cat Luna" is a possession whatever precedes
                verdict = held if isinstance(held, tuple) else verdict
        if verdict is None and mode != "no_coordination" and (mode == "coordination_only" or confirmed is not None):
            verdict = _coordination(doc, span)
            if isinstance(verdict, tuple) and (cid is None or cid not in (confirmed or set())):
                stats.skip("unconfirmed_coordination")
                continue
        if verdict is None:
            continue
        if isinstance(verdict, str):
            stats.skip(verdict)
            continue
        construction, lo, hi, extra = verdict
        a, b = doc[lo].idx, doc[hi].idx + len(doc[hi])
        if b - a > obs.MAX_EVIDENCE_CHARS:
            stats.skip("too_long")
            continue
        if cid:
            seen.add(cid)
            out.append(OwnershipMatch(cid, name, text[a:b], a, b, construction))
        else:
            out.append(OwnershipMatch(None, name, text[a:b], a, b, construction, _kind_of(extra, span)))
    return out


# --- the writer (Observation write API; graph reads for the closed set) -----------------

def _nlp(config: dict):
    from campy.brain.temporal_lobe.loop.step1_ner import get_nlp

    return get_nlp(((config or {}).get("nlp") or {}).get("spacy_model", "en_core_web_md"))


async def apply_to_message(db: Any, config: dict, message_id: str, stats: OwnershipStats, *,
                           embedding_model: str = obs.EMBEDDING_MODEL, record: list | None = None,
                           mode: str = "all") -> int:
    """Run the rule on one user Message and write what it finds. Returns Observations newly created.
    Never raises for a bad parse or a rejected draft. `record` (optional) collects
    (message_id, label, quote, status, construction) per firing for reporting. `mode` as in
    `find_ownership` ("all" at capture; the backfill runs "no_coordination" then "coordination_only")."""
    from campy.brain.temporal_lobe.observations.extract import _is_named, find_existing_concept

    gw = get_gateway(db)
    rows = await gw.run("observations.get_message", mid=message_id)
    if not rows:
        return 0
    msg = rows[0]
    if msg.get("archived") or msg.get("role") not in obs.EVIDENCE_ROLES:
        return 0
    if mode != "coordination_only":
        stats.messages += 1
    speaker = msg.get("speaker")
    text = msg.get("text_raw") or ""
    if not _CUE_RE.search(text):
        return 0                          # no first-person word: no construction to find
    concept_rows = await gw.run("observations.message_concepts", mid=message_id)
    if not _is_named(speaker):
        if mode != "coordination_only":
            stats.skip("no_speaker")
        return 0
    speaker_name = " ".join(speaker.split())
    speaker_id = await find_existing_concept(gw, speaker_name)
    if not speaker_id:
        if mode != "coordination_only":
            stats.skip("no_speaker")
        return 0
    concepts: dict[str, str] = {}
    for r in concept_rows:
        cid, label = r["concept_id"], (r["label"] or "").strip()
        if cid and label and cid != speaker_id:
            concepts.setdefault(" ".join(label.lower().split()), cid)

    nlp = _nlp(config)
    doc = await asyncio.to_thread(nlp, text)
    context_kinds: list[str] = []
    vocab = await _kind_vocabulary(gw) if mode != "coordination_only" else None
    if mode != "coordination_only" and _NAMING_CUE_RE.search(text):
        # a pronoun in a naming sentence refers to a kind the speaker possessed in their previous turn
        for pr in await gw.run("observations.preceding_messages", mid=message_id):
            if " ".join((pr.get("speaker") or "").split()) == speaker_name:
                context_kinds = _kind_nouns(await asyncio.to_thread(nlp, pr.get("text_raw") or ""), vocab)
                break
    confirmed: set[str] | None = None
    if mode != "no_coordination":
        confirmed = await _confirmed_for_coordination(gw, speaker_id)
    ownable = await _ownable_test(gw) if mode != "coordination_only" else None
    matches = find_ownership(doc, concepts, stats, context_kinds=context_kinds, confirmed=confirmed, mode=mode,
                             kind_vocab=vocab, ownable=ownable)
    created = 0
    occurred_at = msg.get("occurred_at") or msg.get("created_at")
    index: dict[str, list[str]] | None = None
    for m in matches:
        if m.concept_id is None:
            # a proper noun the turn grounds as possessed: reuse a Concept of that name or create one
            from campy.brain.hippocampus.concept_links import concept_index
            from campy.brain.hippocampus.kinds import closematch_threshold, kind_hygiene_enabled, skos_vocab_enabled, \
                wordnet_kinds_enabled
            from campy.brain.temporal_lobe.observations import entities as ent

            skos = skos_vocab_enabled(config)
            if index is None:
                index = await concept_index(gw, alt_labels=skos)
            cid = await ent._concept_for(gw, m.label, index, stats, embedding_model=embedding_model)
            if not cid:
                stats.skip("no_concept")
                continue
            if cid == speaker_id:
                continue                  # the speaker's own name is not a possession
            m = OwnershipMatch(cid, m.label, m.quote, m.start, m.end, m.construction, m.kind)
            await gw.run("concept_links.link_message_concept", mid=message_id, cid=cid)
            stats.entities_linked += 1
            if m.kind:
                await _link_kind(gw, cid, m.kind, index, stats, skos=skos, embedding_model=embedding_model,
                                 closematch=closematch_threshold(config), hygiene=kind_hygiene_enabled(config),
                                 wordnet=wordnet_kinds_enabled(config))
        stats.firings += 1
        draft = obs.ObservationDraft(
            evidence_ref=message_id, evidence_text=m.quote, subject_text="I", predicate="owns",
            object_text=m.label, extraction_method="pattern", confidence=CONFIDENCE,
            rule_version=COORDINATION_RULE_ID if m.construction == "coordination" else RULE_ID,
            polarity="asserted", subject_id=speaker_id, object_id=m.concept_id, speaker=speaker_name,
            observed_at=obs._as_datetime(occurred_at))
        draft.text_raw = obs.render_observation_text(obs.ObservationDraft(**{**draft.__dict__, "subject_text": speaker_name}))
        try:
            draft.embedding = await asyncio.to_thread(emb.embed, draft.text_raw, model_name=embedding_model)
        except Exception:
            draft.embedding = None
        res = await obs.record_observation(db, draft, config=config)
        if res.ok and res.observation_id:
            # the rule's own claim is only readable by objects_of_subject through these two edges
            await obs.write_roles(gw, res.observation_id, subject_id=speaker_id, object_id=m.concept_id)
        if res.status == "created":
            stats.created += 1
            created += 1
        elif res.status == "duplicate":
            stats.duplicate += 1
        else:
            stats.rejected[res.reason or "unknown"] = stats.rejected.get(res.reason or "unknown", 0) + 1
        if record is not None:
            record.append((message_id, m.label, m.quote, res.status, m.construction))
    return created


async def _kind_vocabulary(gw: Any) -> set[str]:
    """Lower-cased labels of the graph's kind Concepts (prefLabel and altLabels)."""
    from campy.brain.hippocampus import kinds as kinds_mod

    out: set[str] = set()
    for k in (await kinds_mod.load_kinds(gw)).values():
        out.add(" ".join(k.pref.lower().split()))
        out.update(" ".join(a.lower().split()) for a in k.alts)
    return out


async def _ownable_test(gw: Any):
    """The ownable test (`make_ownable`) over the kinds that currently have instances in the graph."""
    from campy.brain.hippocampus import kinds as kinds_mod
    from campy.brain.hippocampus.concept_links import norm_key

    ids = {str(r["concept_id"]) for r in await gw.run("observations.instantiated_kinds")}
    keys: set[str] = set()
    if ids:
        for kid, k in (await kinds_mod.load_kinds(gw)).items():
            if kid in ids:
                keys.update(norm_key(x) for x in (k.pref, *k.alts))
    return make_ownable(keys)


async def _confirmed_for_coordination(gw: Any, speaker_id: str) -> set[str]:
    """Concept ids "X and I" may be confirmed against: objects of this speaker's rule-written owns
    Observations, and Concepts INSTANCE_OF a possessable kind one of those objects is INSTANCE_OF.
    (The query returns the kind label; person-like kinds are dropped here.)"""
    out: set[str] = set()
    for r in await gw.run("observations.ownership_confirmations", sid=speaker_id, rule=RULE_ID):
        kind = (r.get("kind_label") or "").strip().lower()
        if kind and (kind in NON_POSSESSABLE_KINDS or kind in PERSON_ROLE_NOUNS):
            continue
        out.add(r["concept_id"])
    return out


async def _link_kind(gw: Any, entity_id: str, kind: str, index: dict, stats: OwnershipStats, *,
                     skos: bool, embedding_model: str, closematch: float,
                     hygiene: bool = False, wordnet: bool = False) -> None:
    """The kind of a created entity, through the same path entities.write_entity uses."""
    from campy.brain.hippocampus import kinds as kinds_mod
    from campy.brain.temporal_lobe.observations import entities as ent

    if skos:
        kind_id = await ent.resolve_kind(gw, kind, index, stats, embedding_model=embedding_model,
                                         closematch=closematch, hygiene=hygiene, wordnet=wordnet)
        if kind_id and kind_id != entity_id:
            await kinds_mod.link_instance_of(gw, entity_id, kind_id)
            stats.kinds_linked += 1
    else:
        kind_id = await ent._concept_for(gw, kind, index, stats, embedding_model=embedding_model)
        if kind_id and kind_id != entity_id:
            await gw.run("concept_links.link_is_a", cid=entity_id, pid=kind_id)
            stats.kinds_linked += 1


async def backfill_ownership(db: Any, config: dict, *, embedding_model: str = obs.EMBEDDING_MODEL,
                             record: list | None = None) -> OwnershipStats:
    """Run the rule over every live user Message. Two passes, so the result does not depend on turn
    order: every construction except "X and I" first, then "X and I", which only confirms (it reads
    what the first pass wrote). WRITES: run it on a copy of a store or as a maintenance step.
    Idempotent."""
    gw = get_gateway(db)
    stats = OwnershipStats()
    messages = [r["message_id"] for r in await gw.run("concept_links.list_user_messages")]
    for mode in ("no_coordination", "coordination_only"):
        for mid in messages:
            try:
                await apply_to_message(db, config, mid, stats, embedding_model=embedding_model, record=record, mode=mode)
            except Exception:
                stats.rejected["error"] = stats.rejected.get("error", 0) + 1
                _logger.warning("[Ownership] backfill failed msg=%s", str(mid)[:8], exc_info=True)
    _logger.info("[Ownership] backfill: %s", stats.as_details())
    return stats
