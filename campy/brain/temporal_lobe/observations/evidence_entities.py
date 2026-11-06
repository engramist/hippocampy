"""
campy/brain/temporal_lobe/observations/evidence_entities.py -- B554: an Observation is about the entities
its evidence names.

Why: B544 links an Observation to an admitted entity only when the entity's name occurs in the model's claim
words (subject / object / event text). The model often paraphrases the name away, so an entity the turn
named has no fact hanging off it (R105: 80 of 156 admitted entities, 43 of them not people). The model's
wording must play no part (P3, P8); the source turn decides.

The rule (flag `[observations] evidence_entity_links`, env `CAMPY_EVIDENCE_ENTITY_LINKS`, default off).
Inputs: the turn text, its spaCy parse, the entities B544 admitted for the turn, the Observation's quote.
  1. The quote is placed in the turn text by `typed_objects.locate_quote` (stored offsets are not trusted, B552).
  2. Each admitted entity's occurrences in the turn: the spaCy spans step 1 found, plus every other occurrence
     of the entity's text exactly as written (case-sensitive, whole words).
  3. Tier 1: an occurrence lying inside the quote links the Observation to the entity.
  4. Tier 2: an occurrence outside the quote but in the same clause as the quote links it. A clause is the set
     of tokens owned by one clause head of the dependency parse (see `clause_owner`). Nothing crosses a clause
     boundary; nothing links at sentence or turn level.
       - an entity in the same list (coordination or apposition) as another entity lying inside the quote does
         not link at tier 2: the quote selected one member of a list, not the list ("places like Paradise Rock, House of Blues");
       - an entity found inside some Observation's quote of the turn links, through tier 2, to no Observation
         whose quote does not hold it (tier 2 is the fallback for an entity no quote holds).
  5. A form of address ("Thanks, Caroline!") is not evidence and links nothing. A speaker of the conversation
     links at tier 1 only (its own facts are anchored by the first-person subject path).

Nothing the model wrote enters the rule. It writes only `Observation -OBSERVATION_ABOUT-> Concept` (existing,
plain, idempotent edge) to Concepts a rule admitted; it creates no Concept.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from campy.brain.hippocampus.entity_admission import ADMITTED_LABELS
from campy.brain.hippocampus.graph.gateway import get_gateway

_logger = logging.getLogger(__name__)

# Heads of a clause in the dependency parse (a verb or auxiliary `conj` of a clause head also is one).
CLAUSE_DEPS = frozenset({"ROOT", "parataxis", "ccomp", "csubj", "advcl", "relcl", "acl"})
_PUNCT = frozenset({",", "!", "?", "."})


def evidence_entity_links_enabled(config: dict | None) -> bool:
    """`[observations] evidence_entity_links` (default FALSE; env `CAMPY_EVIDENCE_ENTITY_LINKS=1` turns it on)
    (B554). A no-op without `[loop] entity_admission` (there are no admitted entities to link). On under the
    `principled` profile."""
    return bool(((config or {}).get("observations") or {}).get("evidence_entity_links", False))


# --- the rule: pure given a spaCy Doc ----------------------------------------------------

def _is_clause_head(tok) -> bool:
    if tok.dep_ in CLAUSE_DEPS:
        return True
    return tok.dep_ == "conj" and tok.pos_ in ("VERB", "AUX") and _is_clause_head(tok.head)


def clause_owner(tok) -> int:
    """Index of the clause head that owns `tok` (its nearest ancestor-or-self clause head)."""
    while not (_is_clause_head(tok) or tok.head is tok):
        tok = tok.head
    return tok.i


def list_mates(tok) -> set[int]:
    """Indices of the tokens in the same list as `tok`: connected to it by coordination (`conj`) or apposition
    (`appos`) edges, in either direction ("Paradise Rock, House of Blues, and Fenway Park" parses as an
    apposition followed by a conjunction)."""
    seen = {tok.i}
    todo = [tok]
    while todo:
        t = todo.pop()
        near = [c for c in t.children if c.dep_ in ("conj", "appos")]
        if t.dep_ in ("conj", "appos") and t.head is not t:
            near.append(t.head)
        for n in near:
            if n.i not in seen:
                seen.add(n.i)
                todo.append(n)
    return seen - {tok.i}


def is_address(span) -> bool:
    """A PERSON span used as a form of address ("Thanks, Caroline!", "Wow, Mel, glad you ...", "Hey Dave!"):
    root `npadvmod` / `intj` set off by punctuation or at a sentence edge, or a sentence-initial name followed
    by a comma that is not an apposition ("Oscar, my guinea pig"), or a sentence made only of a greeting and the name."""
    doc = span.doc
    if not any(t.ent_type_ == "PERSON" for t in span):
        return False
    nxt = doc[span.end] if span.end < len(doc) else None
    prv = doc[span.start - 1] if span.start > 0 else None
    set_off = ((nxt is not None and nxt.text in _PUNCT) or (prv is not None and prv.text == ",")
               or span.start == span.sent.start or span.end == span.sent.end)
    root = span.root
    if root.dep_ in ("npadvmod", "intj", "vocative") and set_off:
        return True
    # a sentence that is only a greeting and the name ("Hey Dave!")
    if root.dep_ in ("ROOT", "dep") and all(t.dep_ == "intj" or t.is_punct for t in span.sent if t not in span):
        return True
    if (root.dep_ in ("ROOT", "dep") and span.start == span.sent.start and nxt is not None
            and nxt.text in (",", "!") and len(doc) > span.end + 1 and doc[span.end + 1].tag_ not in ("PRP$", "DT")):
        return True
    return False


def turn_spans(raw_entities: list[dict], admitted: list[tuple[str, str]],
               known_names: set[str] | None = None) -> dict[str, set[tuple[int, int]]]:
    """Occurrence spans (char start, end) of each admitted entity from step 1's UNDEDUPED entities: each span is
    surface-normalised as admission does and matched to the admitted Concept of the same text. `admitted` is
    [(concept_id, text)]."""
    from campy.brain.temporal_lobe.loop.step1_ner import normalize_surface

    by_text = {" ".join(t.split()).lower(): c for c, t in admitted}
    out: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for e in raw_entities:
        if e.get("label") not in ADMITTED_LABELS:
            continue
        key = " ".join(normalize_surface(e["text"], e.get("label", ""), known_names).split()).lower()
        cid = by_text.get(key)
        if cid:
            out[cid].add((int(e["start"]), int(e["end"])))
    return out


def entity_occurrences(text: str, admitted: list[tuple[str, str]],
                       spans: dict[str, set[tuple[int, int]]]) -> dict[str, set[tuple[int, int]]]:
    """`spans` plus every other occurrence of each admitted entity's text exactly as written (case-sensitive,
    whole words)."""
    occ: dict[str, set[tuple[int, int]]] = {c: set(s) for c, s in spans.items()}
    for cid, etext in admitted:
        etext = " ".join((etext or "").split())
        if not etext:
            continue
        for m in re.finditer(r"(?<!\w)" + re.escape(etext) + r"(?!\w)", text):
            occ.setdefault(cid, set()).add((m.start(), m.end()))
    return occ


def _quote_clauses(doc, qs: int, qe: int):
    toks = [t for t in doc if t.idx >= qs and t.idx + len(t) <= qe and not t.is_punct and not t.is_space]
    return toks, {clause_owner(t) for t in toks}


def entities_in_evidence(doc, occ: dict[str, set[tuple[int, int]]], quote: tuple[int, int],
                         speaker_cids: frozenset[str] = frozenset()) -> dict[str, int]:
    """{concept_id: tier} for one quote: 1 = an occurrence inside the quote, 2 = an occurrence in the same
    clause (outside the quote)."""
    qs, qe = quote
    _, owners = _quote_clauses(doc, qs, qe)
    located: list[tuple[str, int, int, Any, bool]] = []     # (cid, a, b, span, inside quote)
    for cid, ss in occ.items():
        for a, b in sorted(ss):
            sp = doc.char_span(a, b, alignment_mode="expand")
            if sp is None:
                continue
            located.append((cid, a, b, sp, a >= qs and b <= qe))
    inside_roots = {sp.root.i: cid for cid, _a, _b, sp, ins in located if ins}
    result: dict[str, int] = {}
    for cid, a, b, sp, ins in located:
        if is_address(sp):
            continue
        if ins:
            result[cid] = 1
            continue
        if cid in speaker_cids or result.get(cid) == 1:
            continue
        if clause_owner(sp.root) not in owners:
            continue
        # a list mate of an entity inside the quote: the quote selected one member of a list, not the list
        if any(inside_roots.get(i, cid) != cid for i in list_mates(sp.root)):
            continue
        result.setdefault(cid, 2)
    return result


def plan_turn(doc, occ: dict[str, set[tuple[int, int]]], quotes: list[tuple[str, tuple[int, int]]],
              speaker_cids: frozenset[str] = frozenset()) -> list[tuple[str, str]]:
    """[(observation_id, concept_id)] for every Observation of one turn. `quotes` is [(observation_id,
    (start, end))], each quote already placed in the turn text. An entity inside any quote of the turn is
    linked only to the Observations whose quote holds it; tier 2 serves only an entity no quote holds."""
    per = [(oid, entities_in_evidence(doc, occ, span, speaker_cids)) for oid, span in quotes]
    held = {cid for _oid, found in per for cid, tier in found.items() if tier == 1}
    pairs: list[tuple[str, str]] = []
    for oid, found in per:
        for cid, tier in found.items():
            if tier == 1 or cid not in held:
                pairs.append((oid, cid))
    return pairs


# --- graph side ---------------------------------------------------------------------------

@dataclass
class EvidenceLinkStats:
    observations: int = 0
    quote_located: int = 0
    quote_not_located: int = 0
    planned: int = 0
    new_links: int = 0
    unlinked_before: int = 0
    unlinked_after: int = 0
    gained_entities: int = 0
    dry_run: bool = True
    by_label: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "by_label"}
        d["gained_by_label"] = dict(self.by_label)
        return d


async def _existing_about(gw: Any) -> set[tuple[str, str]]:
    return {(str(r["observation_id"]), str(r["concept_id"])) for r in await gw.run("entity_admission.entity_links")}


async def link_turn(gw: Any, doc, text: str, admitted: list[tuple[str, str]],
                    spans: dict[str, set[tuple[int, int]]], written: list[tuple[str, str]],
                    speakers: frozenset[str]) -> int:
    """The write-time entry. `written` is [(observation_id, quote)] of the Observations just written for the
    turn. Returns the number of links written. Never raises for one bad link."""
    from campy.brain.temporal_lobe.observations.typed_objects import locate_quote

    quotes = []
    for oid, quote in written:
        span = locate_quote(text, quote)
        if span is not None:
            quotes.append((oid, span))
    if not quotes:
        return 0
    occ = entity_occurrences(text, admitted, spans)
    spk = frozenset(c for c, t in admitted if " ".join(t.split()).lower() in speakers)
    n = 0
    for oid, cid in plan_turn(doc, occ, quotes, spk):
        try:
            await gw.run("observations.link_about_concept", oid=oid, cid=cid)
            n += 1
        except Exception:
            _logger.warning("[EvidenceLinks] link failed oid=%s", oid[:8], exc_info=True)
    return n


async def backfill_evidence_links(db: Any, config: dict | None = None, *, dry_run: bool = True,
                                  limit: int | None = None, log_every: int = 0) -> EvidenceLinkStats:
    """Run the rule over every live Observation of a store (the rows the B546 backfill walks). Idempotent
    (set-semantics edge, a second run writes nothing), additive (never removes an edge). `dry_run` (default)
    plans and counts and writes nothing. Needs B544's admitted entities (Concepts with `ner_label` and
    MENTIONS); on a store without them nothing is planned."""
    from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
    from campy.brain.temporal_lobe.observations.typed_objects import (
        _nlp, load_speakers, locate_quote)

    gw = get_gateway(db)
    stats = EvidenceLinkStats(dry_run=dry_run)
    model = ((config or {}).get("nlp") or {}).get("spacy_model", "en_core_web_md")
    _nlp(config)                       # fail early if spaCy is missing
    unl_before = {str(r["concept_id"]): str(r["ner_label"]) for r in await gw.run("entity_admission.unlinked_entities")}
    stats.unlinked_before = len(unl_before)
    speakers = await load_speakers(gw)
    rows = sorted(await gw.run("typed_objects.live_observations"), key=lambda r: str(r["observation_id"]))
    if limit:
        rows = rows[:limit]
    by_msg: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        stats.observations += 1
        by_msg[str(r["message_id"])].append(r)
    existing = await _existing_about(gw)
    gained: set[str] = set()
    for n, (mid, group) in enumerate(sorted(by_msg.items())):
        text = str(group[0]["message_text"] or "")
        admitted = [(str(x["concept_id"]), str(x["text_raw"]))
                    for x in await gw.run("typed_objects.message_entities", mid=mid) if x.get("ner_label")]
        quotes = []
        for r in group:
            span = locate_quote(text, str(r["evidence_text"]), int(r["evidence_start"]), int(r["evidence_end"]))
            if span is None:
                stats.quote_not_located += 1
            else:
                stats.quote_located += 1
                quotes.append((str(r["observation_id"]), span))
        if not admitted or not quotes:
            continue
        speaker = group[0].get("speaker")
        known = {str(speaker)} if speaker and str(speaker).strip() else set()
        doc, raw = extract_entities(text, model)
        spans = turn_spans(raw, admitted, known)
        occ = entity_occurrences(text, admitted, spans)
        spk = frozenset(c for c, t in admitted if " ".join(t.split()).lower() in speakers)
        for oid, cid in plan_turn(doc, occ, quotes, spk):
            stats.planned += 1
            if (oid, cid) in existing:
                continue
            existing.add((oid, cid))
            stats.new_links += 1
            if cid in unl_before:
                gained.add(cid)
            if not dry_run:
                await gw.run("observations.link_about_concept", oid=oid, cid=cid)
        if log_every and n % log_every == 0:
            _logger.info("[EvidenceLinks] %d / %d turns", n, len(by_msg))
    stats.gained_entities = len(gained)
    stats.by_label = Counter(unl_before[c] for c in gained)
    if dry_run:
        stats.unlinked_after = stats.unlinked_before - len(gained)       # what the write would leave
    else:
        stats.unlinked_after = len(await gw.run("entity_admission.unlinked_entities"))
    _logger.info("[EvidenceLinks] %s", stats.as_dict())
    return stats
