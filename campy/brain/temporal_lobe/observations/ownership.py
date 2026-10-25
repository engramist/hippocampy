"""
campy/brain/temporal_lobe/observations/ownership.py -- B523: ownership decided by a grammar rule.

The extractor (an LLM) files the same fact under whichever predicate it likes: a speaker's dog
shows up under `plans`, `prefers` and `relates_to`, never `owns`. "What does X own" cannot be a
query while the predicate depends on the verb the model chose. This module decides ownership from
the sentence's grammar, the one general English construction **first-person possession of a named
entity**, and writes it through the grounded Observation write API:

    predicate `owns`, subject = the Message's speaker Concept, object = the entity Concept,
    evidence = that Message (quote = the matched span), rule_version `rule:first_person_possession`.

Constructions (spaCy dependency parse; the model is `get_nlp` from the NER step, not a second one):

  (a) possessive determiner  my / our on a noun that IS the entity or is in apposition / compound
      with it: "my dog Toby", "Toby, my pup", "our cat Luna", "Toby is my dog" (predicate nominal);
  (b) first-person subject (I / we) of an acquisition verb whose direct object is the entity or a
      noun in apposition with it, or that the object noun is "named"/"called": "I adopted Buddy",
      "we got Luna", "I bought a puppy, Buddy", "I rescued a cat named Luna".

The verb set is acquiring/having, not about any kind of thing: have, own, adopt, get, buy, rescue.

What it never does: create a Concept (the entity must be one already linked to the Message through
MENTIONS, or OBSERVATION_ABOUT of an Observation it evidences, and not a kind), call an LLM, or keep
state outside the graph. It does not fire for a question, a negated verb ("I don't have a car"), a
modal or wish ("I would adopt Buddy", "I wish I had a car"), a possessor that is not first person
("your dog Toby", "my friend's dog Rex"), or a possessed noun that names a person's role ("my friend
Sam": kin and social roles are relations, not ownership). Each skip is counted by reason.
Re-running is idempotent: the Observation write API dedupes on (subject, predicate, object).
"""

from __future__ import annotations

import asyncio
import logging
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
_LINK_DEPS = frozenset({"appos", "compound"})

SKIP_REASONS = ("no_concept", "negated", "irrealis", "not_first_person", "question", "not_ownable",
                "no_speaker", "too_long")


@dataclass(frozen=True)
class OwnershipMatch:
    concept_id: str
    label: str
    quote: str
    start: int            # char offsets of the quote in the Message text
    end: int
    construction: str     # "possessive" | "acquisition"


@dataclass
class OwnershipStats:
    messages: int = 0
    firings: int = 0                  # matches found (rule fired)
    created: int = 0                  # new Observations
    duplicate: int = 0                # the claim already existed (evidence added)
    rejected: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def as_details(self) -> dict[str, Any]:
        return {"messages": self.messages, "firings": self.firings, "created": self.created,
                "duplicate": self.duplicate, "rejected": dict(self.rejected), "skipped": dict(self.skipped)}


# --- the matcher (pure; spaCy Doc in, matches out) -----------------------------------

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


def _classify(doc, span):
    """Decide one entity head `e` (spaCy token): (construction, quote_start_tok, quote_end_tok)
    when it is first-person possessed, or a skip reason, or None when no ownership construction
    touches it."""
    e, entity_end = span.root, span.end
    if _is_question(e.sent):
        return None if not _touches_ownership(e, span.start) else "question"
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
            gov = a.head
            if a.dep_ in ("dobj", "attr") and gov.lemma_ in ACQUISITION_VERBS | {"be"}:
                if _negated(gov):
                    return "negated"
                if gov.lemma_ in ACQUISITION_VERBS and _irrealis(gov):
                    return "irrealis"
            lo = min(p.i, a.i, e.i)
            hi = max(p.i, a.i, entity_end - 1)
            return ("possessive", lo, hi)
        if a.dep_ == "dobj" and a.head.pos_ == "VERB" and a.head.lemma_ in ACQUISITION_VERBS:
            verb = a.head
            subj, first = _first_person_subject(verb)
            if subj is None:
                # no subject of its own: "I'm going to adopt Buddy", "to get Luna" -- planned, not held
                return "irrealis" if verb.dep_ in ("xcomp", "advcl", "ccomp", "acl") else "not_first_person"
            if not first:
                return "not_first_person"
            nxt = doc[entity_end] if entity_end < len(doc) else None
            if any(c.dep_ in ("xcomp", "ccomp") for c in verb.children) or (
                    nxt is not None and nxt.lower_ == "to" and nxt.dep_ == "aux"):
                return "not_ownable"     # "I got Sam to help": the object is an agent, not a possession
            if a.lemma_ in PERSON_ROLE_NOUNS:
                return "not_ownable"
            if _negated(verb):
                return "negated"
            if _irrealis(verb):
                return "irrealis"
            lo = min(subj.i, e.i)
            hi = max(a.i, entity_end - 1)
            return ("acquisition", lo, hi)
    return None


def _touches_ownership(e, start: int | None = None) -> bool:
    for a in _anchors(e, start):
        if _poss_of(a) or (a.dep_ == "dobj" and a.head.lemma_ in ACQUISITION_VERBS):
            return True
    return False


def find_ownership(doc, concepts: dict[str, str], stats: OwnershipStats | None = None) -> list[OwnershipMatch]:
    """First-person possession of a known entity in `doc`. `concepts` maps a lower-cased entity
    label to its Concept id (the closed set). One match per Concept; skips are counted in `stats`."""
    stats = stats if stats is not None else OwnershipStats()
    text = doc.text
    spans = _concept_spans(doc, concepts)
    out: list[OwnershipMatch] = []
    seen: set[str] = set()
    for s, e_, key in spans:
        cid = concepts[key]
        if cid in seen:
            continue
        if doc[s:e_].root.pos_ != "PROPN":
            continue        # a common noun that is also a Concept ("my store", "our dreams") is not a named entity
        verdict = _classify(doc, doc[s:e_])
        if verdict is None:
            continue
        if isinstance(verdict, str):
            stats.skip(verdict)
            continue
        _, lo, hi = verdict
        a, b = doc[lo].idx, doc[hi].idx + len(doc[hi])
        if b - a > obs.MAX_EVIDENCE_CHARS:
            stats.skip("too_long")
            continue
        seen.add(cid)
        out.append(OwnershipMatch(cid, doc[s:e_].text, text[a:b], a, b, verdict[0]))
    for s, e_ in _propn_spans(doc, spans):
        verdict = _classify(doc, doc[s:e_])
        if isinstance(verdict, tuple):
            stats.skip("no_concept")
    return out


# --- the writer (Observation write API; graph reads for the closed set) -----------------

def _nlp(config: dict):
    from campy.brain.temporal_lobe.loop.step1_ner import get_nlp

    return get_nlp(((config or {}).get("nlp") or {}).get("spacy_model", "en_core_web_md"))


async def apply_to_message(db: Any, config: dict, message_id: str, stats: OwnershipStats, *,
                           embedding_model: str = obs.EMBEDDING_MODEL, record: list | None = None) -> int:
    """Run the rule on one user Message and write what it finds. Returns Observations newly created.
    Never raises for a bad parse or a rejected draft. `record` (optional) collects
    (message_id, label, quote, status) per firing for reporting."""
    from campy.brain.temporal_lobe.observations.extract import _is_named, find_existing_concept

    gw = get_gateway(db)
    rows = await gw.run("observations.get_message", mid=message_id)
    if not rows:
        return 0
    msg = rows[0]
    if msg.get("archived") or msg.get("role") not in obs.EVIDENCE_ROLES:
        return 0
    stats.messages += 1
    speaker = msg.get("speaker")
    text = msg.get("text_raw") or ""
    concept_rows = await gw.run("observations.message_concepts", mid=message_id)
    if not concept_rows:
        stats.skip("no_concept")
        return 0
    if not _is_named(speaker):
        stats.skip("no_speaker")
        return 0
    speaker_name = " ".join(speaker.split())
    speaker_id = await find_existing_concept(gw, speaker_name)
    if not speaker_id:
        stats.skip("no_speaker")
        return 0
    concepts: dict[str, str] = {}
    for r in concept_rows:
        cid, label = r["concept_id"], (r["label"] or "").strip()
        if cid and label and cid != speaker_id:
            concepts.setdefault(" ".join(label.lower().split()), cid)
    if not concepts:
        stats.skip("no_concept")
        return 0

    nlp = _nlp(config)
    doc = await asyncio.to_thread(nlp, text)
    matches = find_ownership(doc, concepts, stats)
    created = 0
    occurred_at = msg.get("occurred_at") or msg.get("created_at")
    for m in matches:
        stats.firings += 1
        draft = obs.ObservationDraft(
            evidence_ref=message_id, evidence_text=m.quote, subject_text="I", predicate="owns",
            object_text=m.label, extraction_method="pattern", confidence=CONFIDENCE, rule_version=RULE_ID,
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
            record.append((message_id, m.label, m.quote, res.status))
    return created


async def backfill_ownership(db: Any, config: dict, *, embedding_model: str = obs.EMBEDDING_MODEL,
                             record: list | None = None) -> OwnershipStats:
    """Run the rule over every live user Message that is linked to an entity Concept. WRITES: run it
    on a copy of a store or as a maintenance step. Idempotent."""
    gw = get_gateway(db)
    stats = OwnershipStats()
    for r in await gw.run("observations.messages_with_concepts"):
        try:
            await apply_to_message(db, config, r["message_id"], stats, embedding_model=embedding_model, record=record)
        except Exception:
            stats.rejected["error"] = stats.rejected.get("error", 0) + 1
            _logger.warning("[Ownership] backfill failed msg=%s", str(r["message_id"])[:8], exc_info=True)
    _logger.info("[Ownership] backfill: %s", stats.as_details())
    return stats
