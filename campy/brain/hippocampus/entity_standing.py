"""
campy/brain/hippocampus/entity_standing.py -- B549: a named entity's standing is derived by rule; the tagger's
label stays evidence.

spaCy labels chat words as named entities wrongly: Yoga, Art, Congrats, Glad as PERSON, Love, Nature as
WORK_OF_ART, Music as ORG, "Yep Deb" as one PERSON. B544 stores the label as `Concept.ner_label`; readers that
took it as fact kept "art" out of the kind scheme and could anchor a question on a fake person. This module
derives, by rule, from signals independent of the tagger, whether an entity stands as a named entity, and writes
that as `Concept.entity_standing` (`confirmed | doubtful | unverified`). The raw label is untouched (P3).

The rule (pure, over one entity and the user turns of its conversation; spaCy sentence boundaries and POS only,
no word list, no WordNet, no model):

  for each occurrence of the entity's tokens (a leading the/a/an dropped), case-insensitively:
    position  initial  every token before it in its sentence is an interjection or punctuation (or none)
              mid      otherwise
    mid = occurrences written capitalised in a mid position; init = written capitalised in an initial position;
    low = written lowercase.
  a speaker of the conversation                 -> confirmed   (a person, whatever the tagger said)
  mid > 0 and mid >= low                        -> confirmed   (a capital that position does not explain)
  low > 0                                       -> doubtful    (an ordinary word the tagger caught)
  otherwise                                     -> unverified  (capital only at sentence start, or no evidence)

The standing is relative to the label: it withdraws trust from words that are not names, it does not decide
between person, place and organisation. The conversation is the turns by the speakers of the turn's session (the
evidence pool); a store without speakers pools its speakerless user turns.

Span trimming (admission). A span of two or more tokens, in a sentence-initial position, whose leading tokens are
alphabetic words or commas and whose remainder is a known name (a speaker, or a Concept whose standing is
confirmed), is replaced by the remainder: "Yep Deb" -> "Deb", "Oof, Sam" -> "Sam". POS cannot decide it ("Yep" is
tagged a proper noun), so the remainder being a known name does. The backfill moves a wrapper Concept's edges to
its target, archives it and keeps its text as an alt label.

Readers (`can_be_kind`, the kind-label guard, the B547 person lexicon) read the standing inside their own named
queries. Flag `[loop] entity_standing` (env `CAMPY_ENTITY_STANDING`, default off, on under profile "principled");
a no-op without `[loop] entity_admission`. Graph store only; every read and write is a named query.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

_logger = logging.getLogger(__name__)

CONFIRMED, DOUBTFUL, UNVERIFIED = "confirmed", "doubtful", "unverified"
_DETERMINERS = frozenset({"the", "a", "an"})
_DEFAULT_MODEL = "en_core_web_md"


def entity_standing_enabled(config: dict | None) -> bool:
    """`[loop] entity_standing` (default false; env `CAMPY_ENTITY_STANDING=1` turns it on). A config without the
    key reads as off."""
    return bool(((config or {}).get("loop") or {}).get("entity_standing", False))


# ---------------------------------------------------------------------------------------------------
# The rule (pure)
# ---------------------------------------------------------------------------------------------------

def _nlp(model: str = _DEFAULT_MODEL):
    from campy.brain.temporal_lobe.loop.step1_ner import get_nlp
    return get_nlp(model)


@lru_cache(maxsize=8192)
def _parse(text: str, model: str):
    return _nlp(model)(text)


def key_tokens(text: str, model: str = _DEFAULT_MODEL) -> list[str]:
    """The lowercased tokens an entity is matched by: its own tokenisation, a leading the/a/an dropped."""
    toks = [t.lower_ for t in _nlp(model).make_doc(text or "") if not t.is_space]
    while len(toks) > 1 and toks[0] in _DETERMINERS:
        toks = toks[1:]
    return toks


def initial_position(doc, start: int) -> bool:
    """True when the token at `start` opens its sentence, or only interjections and punctuation precede it."""
    sent = doc[start].sent
    return all(t.pos_ in ("INTJ", "PUNCT", "SPACE") or t.tag_ == "UH" for t in doc[sent.start:start])


def occurrences(doc, kt: list[str]) -> list[tuple[int, int]]:
    """Token spans of `doc` whose lowercased texts equal `kt`."""
    n = len(kt)
    if n == 0:
        return []
    low = [t.lower_ for t in doc]
    return [(i, i + n) for i in range(len(doc) - n + 1) if low[i:i + n] == kt]


def case_counts(docs: list, kt: list[str]) -> tuple[int, int, int]:
    """(mid, init, low): occurrences written capitalised mid-sentence, capitalised sentence-initially, lowercase."""
    mid = init = low = 0
    for d in docs:
        for s, _e in occurrences(d, kt):
            first = d[s].text
            if first[:1].isupper():
                if initial_position(d, s):
                    init += 1
                else:
                    mid += 1
            elif first[:1].islower():
                low += 1
    return mid, init, low


def standing_from(kt: list[str], mid: int, low: int, init: int, speakers) -> str:
    """The standing the rule gives an entity with these tokens and counts (see the module docstring)."""
    if " ".join(kt) in {" ".join(s.lower().split()) for s in speakers}:
        return CONFIRMED
    if mid > 0 and mid >= low:
        return CONFIRMED
    if low > 0:
        return DOUBTFUL
    return UNVERIFIED


def assess_text(text: str, docs: list, speakers, model: str = _DEFAULT_MODEL) -> tuple[str, tuple[int, int, int]]:
    """Standing of the entity `text` over the parsed turns `docs` of its conversation. Returns (standing,
    (mid, init, low))."""
    kt = key_tokens(text, model)
    mid, init, low = case_counts(docs, kt)
    return standing_from(kt, mid, low, init, speakers), (mid, init, low)


def trim_span(doc, start: int, end: int, known: set[str]) -> tuple[int, int]:
    """Drop the sentence-initial wrapper tokens (words and commas) in front of a span whose remainder, lowercased,
    is in `known`. Returns the new token span (unchanged when nothing applies)."""
    if end - start < 2 or not initial_position(doc, start):
        return start, end
    for k in range(start + 1, end):
        rest = " ".join(t.lower_ for t in doc[k:end])
        if rest in known and all(t.text == "," or t.is_alpha for t in doc[start:k]):
            return k, end
    return start, end


# ---------------------------------------------------------------------------------------------------
# Graph reads (named queries)
# ---------------------------------------------------------------------------------------------------

async def conversation_speakers(gw: Any, message_id: str, speaker: str | None = None) -> set[str]:
    sp = {str(r["speaker"]) for r in await gw.run("entity_standing.session_speakers", mid=message_id)}
    if speaker and speaker.strip():
        sp.add(speaker)
    return sp


async def known_names(gw: Any, message_id: str, speaker: str | None = None) -> set[str]:
    """Lowercased names a wrapped span may be trimmed to: the conversation's speakers and the texts of the
    Concepts whose standing is confirmed."""
    names = {" ".join(sp.lower().split()) for sp in await conversation_speakers(gw, message_id, speaker)}
    names |= {" ".join(str(r["text_raw"]).lower().split()) for r in await gw.run("entity_standing.confirmed_texts")}
    return {n for n in names if n}


def _prefilter_key(kt: list[str]) -> str | None:
    """The longest alphanumeric token of the entity: the cheap text filter that narrows the pool before parsing."""
    words = [t for t in kt if any(c.isalnum() for c in t)]
    return max(words, key=len) if words else None


async def pool_docs(gw: Any, kt: list[str], speakers: set[str], model: str) -> list:
    """The parsed user turns of the conversation that contain the entity's longest token (a superset of its
    occurrences; `case_counts` is exact)."""
    key = _prefilter_key(kt)
    if key is None:
        return []
    if speakers:
        rows = await gw.run("entity_standing.turns_by_speakers", speakers=sorted(speakers), key=key)
    else:
        rows = await gw.run("entity_standing.turns_unspoken", key=key)
    return [_parse(str(r["text"]), model) for r in rows]


async def assess_entity(gw: Any, cid: str, text: str, speakers: set[str], model: str = _DEFAULT_MODEL,
                        *, write: bool = True) -> str:
    """Assess one Concept and (unless `write` is false) record its standing when it changed. The evidence pool is
    the conversations of the Concept's mentioning turns (`speakers` plus `entity_standing.concept_speakers`), so
    the standing does not depend on which turn is processed last."""
    speakers = set(speakers) | {str(r["speaker"]) for r in await gw.run("entity_standing.concept_speakers", cid=cid)}
    kt = key_tokens(text, model)
    docs = await pool_docs(gw, kt, speakers, model)
    mid, init, low = case_counts(docs, kt)
    standing = standing_from(kt, mid, low, init, speakers)
    if write:
        cur = await gw.run("entity_standing.concept_standing", cid=cid)
        if not cur or cur[0].get("entity_standing") != standing:
            await gw.run("entity_standing.set_standing", cid=cid, standing=standing)
    return standing


async def assess_turn(gw: Any, message_id: str, admitted: list[tuple[str, str]], speaker: str | None,
                      config: dict | None) -> dict[str, str]:
    """Incremental assessment (the admission hook): re-assess every entity this turn admitted or mentions, over
    the evidence the graph holds now. Returns {concept id: standing}. Never raises for one entity."""
    model = ((config or {}).get("nlp") or {}).get("spacy_model", _DEFAULT_MODEL)
    todo: dict[str, str] = {cid: text for cid, text in admitted}
    try:
        for r in await gw.run("entity_standing.turn_entities", mid=message_id):
            todo.setdefault(str(r["concept_id"]), str(r["text_raw"]))
        speakers = await conversation_speakers(gw, message_id, speaker)
    except Exception:
        _logger.warning("[EntityStanding] msg=%s evidence read failed", message_id[:8], exc_info=True)
        return {}
    out: dict[str, str] = {}
    for cid, text in todo.items():
        try:
            out[cid] = await assess_entity(gw, cid, text, speakers, model)
        except Exception:
            _logger.warning("[EntityStanding] msg=%s entity %r failed", message_id[:8], text, exc_info=True)
    return out


async def trim_entities(gw: Any, doc: Any, entities: list[dict], message_id: str, speaker: str | None) -> list[dict]:
    """Step-1 entities with each wrapped span replaced by its remainder (see `trim_span`); a later entity whose
    text repeats an earlier one is dropped. The input is returned unchanged when nothing qualifies."""
    cands = []
    for i, e in enumerate(entities):
        span = doc.char_span(e["start"], e["end"], alignment_mode="expand") if "start" in e else None
        if span is not None and len(span) >= 2 and initial_position(doc, span.start):
            cands.append((i, span))
    if not cands:
        return entities
    known = await known_names(gw, message_id, speaker)
    out = list(entities)
    changed = False
    for i, span in cands:
        s, e_ = trim_span(doc, span.start, span.end, known)
        new = doc[s:e_]
        if (s, e_) != (span.start, span.end) and new.text != out[i]["text"]:
            out[i] = {**out[i], "text": new.text, "surface": entities[i].get("surface", entities[i]["text"]),
                      "start": new.start_char, "end": new.end_char, "trimmed_from": entities[i]["text"]}
            changed = True
    if not changed:
        return entities
    seen: set[str] = set()
    kept = []
    for e in out:
        if e["text"].lower() in seen:
            continue
        seen.add(e["text"].lower())
        kept.append(e)
    return kept


# ---------------------------------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------------------------------

@dataclass
class StandingStats:
    concepts: int = 0
    by_standing: Counter = field(default_factory=Counter)
    wrappers: int = 0            # Concepts whose text is wrapper + known name
    merged: int = 0              # of those, with a live target Concept
    unmerged: int = 0            # no live Concept for the remainder (left as they are)
    mentions_moved: int = 0
    kind_conflicts: list[str] = field(default_factory=list)
    dry_run: bool = True
    merges: list[tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"concepts": self.concepts, "by_standing": dict(self.by_standing), "wrappers": self.wrappers, "merged": self.merged, "unmerged": self.unmerged,
                "mentions_moved": self.mentions_moved, "kind_conflicts": self.kind_conflicts,
                "dry_run": self.dry_run, "merges": self.merges}


async def _concept_by_text(gw: Any, text: str) -> str | None:
    for q in ("orchestrator.find_concept_by_exact_text", "orchestrator.find_concept_by_label_text"):
        rows = await gw.run(q, t=text)
        if rows:
            return str(rows[0]["concept_id"])
    return None


async def _trim_target(gw: Any, cid: str, text: str, known: set[str], model: str) -> str | None:
    """The remainder `text` is trimmed to in some turn that mentions it, or None."""
    for r in await gw.run("entity_standing.concept_turns", cid=cid):
        doc = _parse(str(r["text"]), model)
        for s, e in occurrences(doc, key_tokens(text, model)):
            ns, ne = trim_span(doc, s, e, known)
            if (ns, ne) != (s, e):
                return doc[ns:ne].text
    return None


async def backfill_entity_standing(db: Any, config: dict | None = None, *, dry_run: bool = True,
                                   log_every: int = 0) -> StandingStats:
    """Assess every live labelled Concept, trim-merge the wrapped ones, assess again (the targets' evidence grew).
    Idempotent. `dry_run` (default) computes and counts and writes nothing. The only edges removed are the
    re-pointed edges of a trimmed wrapper; kinds that are confirmed entities are listed, never edited."""
    from campy.brain.hippocampus.graph.gateway import get_gateway

    gw = get_gateway(db)
    model = ((config or {}).get("nlp") or {}).get("spacy_model", _DEFAULT_MODEL)
    stats = StandingStats(dry_run=dry_run)
    concepts = [(str(r["concept_id"]), str(r["text_raw"])) for r in await gw.run("entity_standing.labelled_concepts")]
    stats.concepts = len(concepts)

    async def assess_all() -> dict[str, str]:
        out: dict[str, str] = {}
        for n, (cid, text) in enumerate(concepts):
            out[cid] = await assess_entity(gw, cid, text, set(), model, write=not dry_run)
            if log_every and n % log_every == 0:
                _logger.info("[EntityStanding] %d / %d concepts", n, len(concepts))
        return out

    first = await assess_all()
    # trim-merge: known names are the speakers and the (now) confirmed Concepts
    confirmed = {" ".join(t.lower().split()) for (cid, t) in concepts if first.get(cid) == CONFIRMED}
    speakers = {" ".join(str(r["speaker"]).lower().split()) for r in await gw.run("typed_objects.speakers")}
    known = confirmed | speakers
    for cid, text in concepts:
        target_text = await _trim_target(gw, cid, text, known, model)
        if target_text is None:
            continue
        stats.wrappers += 1
        tid = await _concept_by_text(gw, target_text)
        if tid is None or tid == cid:
            stats.unmerged += 1
            continue
        stats.merged += 1
        stats.merges.append((text, target_text))
        stats.mentions_moved += len(await gw.run("entity_standing.concept_turns", cid=cid))
        if not dry_run:
            for q in ("entity_standing.repoint_mentions", "entity_standing.repoint_about",
                      "entity_standing.repoint_subject", "entity_standing.repoint_object"):
                await gw.run(q, wid=cid, tid=tid)
            lid = str(uuid.uuid4())
            await gw.run("quests.create_alt_label", lid=lid, txt=text, now=datetime.now(timezone.utc).isoformat())
            await gw.run("quests.link_concept_has_alt_label", cid=tid, lid=lid)
            await gw.run("quests.archive_concept", cid=cid)
    merged_ids = {cid for cid, text in concepts if any(text == m[0] for m in stats.merges)} if not dry_run else set()
    if not dry_run:
        concepts = [(cid, t) for cid, t in concepts if cid not in merged_ids]
        second = await assess_all()
    else:
        wrappers = {m[0] for m in stats.merges}
        second = {cid: first[cid] for cid, t in concepts if t not in wrappers}
    for cid, st in second.items():
        stats.by_standing[st] += 1
    stats.kind_conflicts = sorted(str(r["text_raw"]) for r in await gw.run("entity_standing.kind_conflicts"))
    _logger.info("[EntityStanding] %s", stats.as_dict())
    return stats

