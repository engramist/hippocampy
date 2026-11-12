"""
B564: the roles of an event fact (flag `[observations] roles`, env `CAMPY_OBSERVATION_ROLES`, default off).

The extraction form gains three fields for a fact: "action" (did / plans only), "with" (a list) and "place", each
copied from the turn. The model only proposes spans. This module is the rule that confirms them and the only
writer of the edges (through the NamedQueries in `graph/queries/roles.py`); the model never names a Concept, a
synset or an IRI (P3).

A span is kept only when:
  1. it occurs in the turn as whole words (exact, then with quotation marks and backticks folded, then ignoring
     case), and
  2. one occurrence lies inside the fact's quote (tier 1), or in the clause of the quote (tier 2, the B554
     `clause_owner`) provided that no OTHER fact of the turn has the occurrence inside its quote and it is not a
     list mate of a word inside the quote. Tier 2 is why the rule runs once per turn, after every fact is written.

What a kept span writes:
  action       predicate did / plans only. `wordnet.action_sense` picks the action kind (the most frequent event
               noun sense of the span's lemma; a light verb has none). Written: Concept `wn:<synset>` (kind_scheme
               "action", no embedding, in no index), its hypernym chain up to `event.n.01` as BROADER with
               link_source "wordnet", and `Observation -HAS_ACTION-> Concept` (first wins). No sense: nothing.
  with         each list member on its own: the conversation's speaker, or a B544-admitted PERSON / ORG / NORP
               Concept inside the member -> `HAS_PARTICIPANT` Concept; else a common noun whose first WordNet sense
               is under person.n.01 / social_group.n.01 -> `HAS_PARTICIPANT` to a nameless `ObjectPhrase`.
  place        an admitted GPE / LOC / FAC Concept -> `HAS_PLACE` Concept; else a head noun under location.n.01,
               structure.n.01, geological_formation.n.01, body_of_water.n.01 or vegetation.n.01 -> `HAS_PLACE`
               to an `ObjectPhrase`. At most one place per fact.
A pronoun, the subject or the speaker is never a participant. Every rejection is counted by reason (stats).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus import observations as obs
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import evidence_entities as evid
from campy.brain.temporal_lobe.observations import typed_objects as T

_logger = logging.getLogger(__name__)

RULE_VERSION = "b564-1"
_PHRASE_NS = uuid.UUID("b5640000-0000-0000-0000-000000000000")
EVENT_PREDICATES = frozenset({"did", "plans"})
PERSON_LABELS = frozenset({"PERSON", "ORG", "NORP"})
MAX_WITH = 4
MAX_SPAN_CHARS = 60
MAX_SPAN_WORDS = 6
_NULLS = frozenset({"null", "none", "n/a", "unknown", "na", "-"})
_FOLD = {**obs._QUOTE_TABLE, 0x60: "'", 0xB4: "'"}      # backtick and acute accent are apostrophes in chat text
SKIP_TOKENS = frozenset({"DET", "PRON", "PUNCT", "SPACE"})


# --- what the model proposes ---------------------------------------------------------------

@dataclass
class RoleProposal:
    action: str | None = None
    with_: list[str] = field(default_factory=list)
    place: str | None = None

    def __bool__(self) -> bool:
        return bool(self.action or self.with_ or self.place)


def _span_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    s = " ".join(value.split())
    if not s or s.lower() in _NULLS or len(s) > MAX_SPAN_CHARS or len(s.split()) > MAX_SPAN_WORDS:
        return None
    return s


def propose(p: dict) -> RoleProposal:
    """The model's three fields of one fact, as clean strings (a list or one string for `with`). Nothing here is
    trusted: the rule confirms every span against the turn."""
    raw_with = p.get("with")
    members = raw_with if isinstance(raw_with, (list, tuple)) else [raw_with]
    with_: list[str] = []
    for m in members:
        t = _span_text(m)
        if t and t.lower() not in {x.lower() for x in with_}:
            with_.append(t)
    return RoleProposal(_span_text(p.get("action")), with_[:MAX_WITH], _span_text(p.get("place")))


@dataclass
class FactIn:
    oid: str
    quote: str
    predicate: str
    proposal: RoleProposal
    subject_text: str = ""


# --- the rule: pure given spaCy and WordNet --------------------------------------------------

@dataclass
class Target:
    kind: str                    # 'concept' | 'phrase'
    cid: str | None
    surface: str                 # the span as written in the turn


@dataclass
class Plan:
    oid: str
    action: wn_mod.ActionSense | None = None
    participants: list[Target] = field(default_factory=list)
    place: Target | None = None


@dataclass
class Turn:
    """What every fact of one turn shares."""
    doc: Any
    text: str
    mentions: list[tuple[str, str, str]]
    speakers: frozenset[str]
    speaker_cids: dict[str, str]           # lower-cased speaker name -> its existing Concept id
    spans: list[tuple[int, int, str, str, str]]
    quotes: dict[str, tuple[int, int]]     # observation id -> its quote placed in the turn


def find_spans(text: str, span: str) -> list[tuple[int, int]]:
    """Every whole-word occurrence of `span` in `text`: exact, else with quotes folded, else ignoring case. The
    fold is one character for one character, so offsets stay valid."""
    if not text or not span:
        return []
    ft, fs = text.translate(_FOLD), span.translate(_FOLD)
    pat = r"(?<!\w)" + re.escape(fs) + r"(?!\w)"
    for flags in (0, re.I):
        found = [(m.start(), m.end()) for m in re.finditer(pat, ft, flags)]
        if found:
            return found
    return []


def _confirm(turn: Turn, oid: str, span: str) -> tuple[tuple[int, int] | None, str | None]:
    """((start, end) of the confirmed occurrence, None) or (None, rejection reason)."""
    occ = find_spans(turn.text, span)
    if not occ:
        return None, "not_in_turn"
    qs, qe = turn.quotes[oid]
    inside = [o for o in occ if o[0] >= qs and o[1] <= qe]
    if inside:
        return inside[0], None
    _toks, owners = evid._quote_clauses(turn.doc, qs, qe)
    others = [q for k, q in turn.quotes.items() if k != oid]
    held = False
    for a, b in occ:
        if any(a >= os_ and b <= oe for os_, oe in others):
            held = True
            continue
        sp = turn.doc.char_span(a, b, alignment_mode="expand")
        if sp is None or evid.clause_owner(sp.root) not in owners:
            continue
        if any(qs <= turn.doc[i].idx < qe for i in evid.list_mates(sp.root)):
            continue
        return (a, b), None
    return None, "held_by_other_fact" if held else "not_in_clause"


def _span(turn: Turn, occ: tuple[int, int]):
    return turn.doc.char_span(occ[0], occ[1], alignment_mode="expand")


def _admitted_in(turn: Turn, occ: tuple[int, int], labels: frozenset[str]) -> str | None:
    for s, e, cid, _surface, label in turn.spans:
        if label in labels and s >= occ[0] and e <= occ[1]:
            return cid
    return None


def _head_lemma(sp) -> str:
    root = sp.root
    return root.lemma_.lower() if root.lemma_.isalpha() else root.text.lower()


def _noun_head(sp) -> str | None:
    """The span's head noun lemma, or None when the span is not headed by a noun."""
    return _head_lemma(sp) if sp.root.pos_ in ("NOUN", "PROPN") else None


def _target(turn: Turn, occ: tuple[int, int], labels: frozenset[str], roots: tuple[str, ...],
            *, speaker: bool) -> tuple[Target | None, str | None]:
    surface = turn.text[occ[0]:occ[1]]
    low = surface.strip().lower()
    cid = _admitted_in(turn, occ, labels)
    if cid:
        return Target("concept", cid, surface), None
    if speaker and low in turn.speaker_cids:
        return Target("concept", turn.speaker_cids[low], surface), None
    sp = _span(turn, occ)
    head = _noun_head(sp) if sp is not None else None
    if head and head not in T.PRON and wn_mod.first_sense_under(head, roots):
        return Target("phrase", None, surface), None
    return None, "with_not_person" if speaker else "place_not_place"


def plan_fact(turn: Turn, fact: FactIn, counts: Counter, subject_names: frozenset[str]) -> Plan:
    plan = Plan(fact.oid)
    pr = fact.proposal
    if pr.action:
        counts["action_proposed"] += 1
        if fact.predicate not in EVENT_PREDICATES:
            counts["rejected:predicate_not_event"] += 1
        else:
            occ, why = _confirm(turn, fact.oid, pr.action)
            sp = _span(turn, occ) if occ else None
            if occ is None or sp is None:
                counts[f"rejected:{why or 'not_in_turn'}"] += 1
            else:
                words = [t.lemma_.lower() for t in sp if t.pos_ not in SKIP_TOKENS and t.lemma_.isalpha()]
                # a compound noun ("pottery class") is looked up whole first; a phrasal verb ("try out") never is:
                # its noun sense ("try-out": an audition) is another word
                cand = ["_".join(words)] if len(words) > 1 and sp.root.pos_ == "NOUN" else []
                cand.append(_head_lemma(sp))
                sense = wn_mod.action_sense(cand)
                if sense is not None:
                    plan.action = sense
                else:
                    counts["rejected:action_light_verb" if cand[-1] in wn_mod.LIGHT_VERBS
                           else "rejected:action_no_sense"] += 1
    seen: set[tuple] = set()
    for member in pr.with_:
        counts["with_proposed"] += 1
        low = member.lower()
        if low in T.PRON or low in subject_names:
            counts["rejected:with_pronoun_or_subject"] += 1
            continue
        occ, why = _confirm(turn, fact.oid, member)
        if occ is None:
            counts[f"rejected:{why}"] += 1
            continue
        tgt, why = _target(turn, occ, PERSON_LABELS, wn_mod.PERSON_ROOTS, speaker=True)
        if tgt is None:
            counts[f"rejected:{why}"] += 1
            continue
        key = (tgt.kind, tgt.cid or tgt.surface.lower())
        if key not in seen:
            seen.add(key)
            plan.participants.append(tgt)
    if pr.place:
        counts["place_proposed"] += 1
        occ, why = _confirm(turn, fact.oid, pr.place)
        if occ is None:
            counts[f"rejected:{why}"] += 1
        else:
            tgt, why = _target(turn, occ, T.PLACE_LABELS, wn_mod.PLACE_ROOTS, speaker=False)
            if tgt is None:
                counts[f"rejected:{why}"] += 1
            else:
                plan.place = tgt
    return plan


# --- graph side ------------------------------------------------------------------------------

@dataclass
class RolesStats:
    counts: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in sorted(self.counts.items()) if v}


async def _write_action(gw: Any, oid: str, sense: wn_mod.ActionSense, ensured: set[str], counts: Counter) -> None:
    now = datetime.now(timezone.utc)
    for synset, label in sense.labels:
        cid = wn_mod.concept_id_of(synset)
        if cid not in ensured:
            await gw.run("roles.ensure_action_concept", cid=cid, text=label, now=now)
            ensured.add(cid)
    for child, parent in sense.chain:
        await kinds_mod.link_broader_sourced(gw, wn_mod.concept_id_of(child), wn_mod.concept_id_of(parent),
                                             wn_mod.SOURCE)
    await gw.run("roles.link_action", oid=oid, cid=sense.concept_id)
    counts["action_written"] += 1


async def _write_target(gw: Any, oid: str, role: str, tgt: Target, counts: Counter) -> None:
    if tgt.kind == "concept":
        await gw.run(f"roles.link_{role}", oid=oid, cid=tgt.cid)
        counts[f"{role}_concept_written"] += 1
        return
    pid = str(uuid.uuid5(_PHRASE_NS, f"{oid}|{role}|{tgt.surface.lower()}"))
    await gw.run(f"roles.link_{role}_phrase", oid=oid, pid=pid, text=tgt.surface, rv=RULE_VERSION,
                 now=datetime.now(timezone.utc))
    counts[f"{role}_phrase_written"] += 1


async def link_turn(gw: Any, tctx: Any, facts: list[FactIn], find_concept: Any) -> RolesStats:
    """The write-time entry. `tctx` is the turn's `typed_objects.TurnContext` (text, speaker, admitted mentions,
    speakers, spaCy); `facts` the facts just written for the turn; `find_concept(gw, text)` the existing-Concept
    lookup (extract.find_existing_concept; it never creates). Never raises for one bad fact."""
    stats = RolesStats()
    counts = stats.counts
    text = tctx.text
    quotes: dict[str, tuple[int, int]] = {}
    for f in facts:
        span = T.locate_quote(text, f.quote)
        if span is None:
            counts["quote_not_located"] += 1
        else:
            quotes[f.oid] = span
    facts = [f for f in facts if f.oid in quotes and f.proposal]
    if not facts:
        return stats
    doc = tctx.docs.get(tctx.message_id)
    if doc is None:
        doc = tctx.docs[tctx.message_id] = tctx.nlp(text)
    speaker_cids: dict[str, str] = {}
    for member in {m.lower() for f in facts for m in f.proposal.with_}:
        if member in tctx.speakers:
            cid = await find_concept(gw, member)
            if cid:
                speaker_cids[member] = cid
    turn = Turn(doc, text, tctx.mentions, tctx.speakers, speaker_cids,
                T.mention_spans(doc, tctx.mentions, 0, len(text)), quotes)
    ensured: set[str] = set()
    speaker = (tctx.speaker or "").strip().lower()
    for f in facts:
        try:
            subj = frozenset(x for x in (speaker, f.subject_text.strip().lower()) if x)
            plan = plan_fact(turn, f, counts, subj)
            if plan.action is not None:
                await _write_action(gw, f.oid, plan.action, ensured, counts)
            for tgt in plan.participants:
                await _write_target(gw, f.oid, "participant", tgt, counts)
            if plan.place is not None:
                await _write_target(gw, f.oid, "place", plan.place, counts)
        except Exception:
            counts["errors"] += 1
            _logger.warning("[Roles] failed oid=%s", f.oid[:8], exc_info=True)
    return stats
