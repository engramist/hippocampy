"""
campy/brain/hippocampus/entity_admission.py -- B544: a named entity is stored because it is
a named entity, not because its turn sounds like a developer decision.

Why: spaCy labels "The Name of the Wind" WORK_OF_ART, then Loop step 2 (whole-message gist
centroids, noise floor 0.18) and step 4 (decision / constraint / requirement / action-item
gate, floor 0.60) drop it. Both were built for an early developer-decision tracker. On a
LoCoMo store most places, organisations and titles never became Concepts, so a question
about "the books Tim read" had no object entity to reach.

The rule (flag `[loop] entity_admission`, env `CAMPY_ENTITY_ADMISSION`, default off):
every named entity step 1 finds, with a label in `ADMITTED_LABELS`, in a user turn:
  * becomes a Concept, or is linked to the live Concept the existing lookups find
    (exact text, then a recorded label; the same two lookups `_store_concept` uses);
  * carries the NER label in `Concept.ner_label` (first label wins);
  * is linked from the turn by `Message -MENTIONS-> Concept`;
whatever steps 2-7 decide. No kind or INSTANCE_OF edge is written from the label (the B540
audit found NER-label kinds 37% wrong). Steps 2-7 still run for Decisions, Constraints and
the like; their exact-text dedup finds the admitted Concept, so no duplicate is created.

Guard (`can_be_kind`, independent of the flag): a Concept that is a named entity
(`ner_label` set) or a Person is never put in the kind scheme, except a labelled Concept whose derived
standing (B549, `[loop] entity_standing`) is `doubtful`: a common word the tagger caught.

Graph store only; every write is a named query through the gateway.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from campy.brain.hippocampus.graph import embeddings as emb

_logger = logging.getLogger(__name__)

# The closed set of labels that admit an entity. NOT: DATE/TIME/CARDINAL/ORDINAL/QUANTITY/
# MONEY/PERCENT (values, not entities), LANGUAGE/LAW (outside the declared set).
ADMITTED_LABELS = frozenset({
    "PERSON", "WORK_OF_ART", "GPE", "ORG", "PRODUCT", "LOC", "FAC", "EVENT", "NORP",
})


def entity_admission_enabled(config: dict | None) -> bool:
    """`[loop] entity_admission` (default false; env `CAMPY_ENTITY_ADMISSION=1` turns it on).
    A config without the key reads as off."""
    return bool(((config or {}).get("loop") or {}).get("entity_admission", False))


async def admit_entities(gw: Any, message_id: str, entities: list[dict], *,
                         embedding_model: str) -> list[str]:
    """Admit each entity whose label is in `ADMITTED_LABELS`; link the turn to it. Returns
    the Concept ids (one per distinct Concept, in order). Never raises for one bad entity."""
    return [cid for cid, _ in await admit_entities_with_text(gw, message_id, entities, embedding_model=embedding_model)]


async def admit_entities_with_text(gw: Any, message_id: str, entities: list[dict], *,
                                   embedding_model: str) -> list[tuple[str, str]]:
    """`admit_entities`, returning (Concept id, entity text) pairs."""
    ids: list[str] = []
    pairs: list[tuple[str, str]] = []
    for e in entities:
        label, text = e.get("label"), (e.get("text") or "").strip()
        if label not in ADMITTED_LABELS or not text:
            continue
        try:
            cid = await _concept_for(gw, text, embedding_model)
            if not cid:
                continue
            await gw.run("entity_admission.set_ner_label", cid=cid, label=label)
            await gw.run("concept_links.link_message_concept", mid=message_id, cid=cid)
        except Exception:
            _logger.warning("[EntityAdmission] msg=%s entity %r failed", message_id[:8], text, exc_info=True)
            continue
        if cid not in ids:
            ids.append(cid)
            pairs.append((cid, text))
    return pairs


async def trim_wrapped(gw: Any, message_id: str, doc: Any, entities: list[dict], speaker: str | None,
                       config: dict | None) -> list[dict]:
    """With `[loop] entity_standing` on, step 1's entities with each wrapped span replaced by the known name it
    holds ("Yep Deb" -> "Deb"); otherwise the entities as given. Never raises."""
    from campy.brain.hippocampus import entity_standing as es
    if doc is None or not es.entity_standing_enabled(config):
        return entities
    try:
        return await es.trim_entities(gw, doc, entities, message_id, speaker)
    except Exception:
        _logger.warning("[EntityAdmission] msg=%s span trimming failed", message_id[:8], exc_info=True)
        return entities


async def admit_parsed(gw: Any, message_id: str, doc: Any, entities: list[dict], speaker: str | None,
                       config: dict | None, *, embedding_model: str, trimmed: bool = False) -> list[tuple[str, str]]:
    """The one admission entry both workers call (the Loop and the Observation extractor): with `[loop]
    entity_standing` on, a wrapped span is trimmed first (unless the caller already did), the entities are
    admitted, then the standing of every entity the turn admitted or mentions is assessed. With the flag off this
    is exactly `admit_entities_with_text`."""
    from campy.brain.hippocampus import entity_standing as es
    if not trimmed:
        entities = await trim_wrapped(gw, message_id, doc, entities, speaker, config)
    pairs = await admit_entities_with_text(gw, message_id, entities, embedding_model=embedding_model)
    if es.entity_standing_enabled(config):
        await es.assess_turn(gw, message_id, pairs, speaker, config)
    return pairs


async def _concept_for(gw: Any, text: str, embedding_model: str) -> str | None:
    """The live Concept the existing lookups find for `text`, else a new one; None for a closed-class word (B565)."""
    from campy.brain.temporal_lobe.lexicon.closed_class import is_closed_class
    if is_closed_class(text):
        return None
    for query in ("orchestrator.find_concept_by_exact_text", "orchestrator.find_concept_by_label_text"):
        rows = await gw.run(query, t=text)
        if rows:
            row = rows[0]
            cid = row.get("concept_id") or row.get("c.concept_id") if hasattr(row, "get") else row[0]
            if cid:
                return str(cid)
    vec = await asyncio.to_thread(emb.embed, text, model_name=embedding_model)
    cid = str(uuid.uuid4())
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=vec,
                 gist="Entity", stype="Thing", now=datetime.now(timezone.utc))
    return cid


async def can_be_kind(gw: Any, concept_id: str) -> bool:
    """False when the Concept is a Person, or a named entity (`ner_label` set) whose standing is not `doubtful`
    (B549: a labelled common word such as "art" or "music" may be a kind). An unknown id or a plain Concept can be
    one. The query decides (`entity_admission.concept_status`, `can_be_kind`)."""
    rows = await gw.run("entity_admission.concept_status", cid=concept_id)
    if not rows:
        return True
    row = rows[0]
    if row.get("can_be_kind") is not None:
        return bool(row["can_be_kind"])
    if row.get("ner_label") and row.get("entity_standing") != "doubtful":      # a gateway without the column
        return False
    return str(row.get("schema_org_type") or "").rsplit(":", 1)[-1] != "Person"


@dataclass
class ParsedTurn:
    """What `admit_turn_parsed` found: the admitted (Concept id, text) pairs, the spaCy parse of the turn and
    step 1's undeduplicated entities (every occurrence, with character offsets)."""
    pairs: list[tuple[str, str]]
    doc: Any = None
    raw_entities: list[dict] = field(default_factory=list)
    known_names: set[str] = field(default_factory=set)


async def admit_turn_parsed(gw: Any, message_id: str, text: str, speaker: str | None, config: dict | None, *,
                            embedding_model: str) -> ParsedTurn:
    """`admit_turn`, also returning the parse and the raw entities it already computed (B554 reads them, so the
    turn is not parsed twice). No-op (empty) when the flag is off. Never raises."""
    if not entity_admission_enabled(config):
        return ParsedTurn([])
    try:
        from campy.brain.temporal_lobe.loop.step1_ner import extract_entities, normalize_entities
        model = ((config or {}).get("nlp") or {}).get("spacy_model", "en_core_web_md")
        doc, raw = await asyncio.to_thread(extract_entities, text, model)
        known = {speaker} if speaker and speaker.strip() else set()
        entities = normalize_entities(raw, known)
        pairs = await admit_parsed(gw, message_id, doc, entities, speaker, config, embedding_model=embedding_model)
        return ParsedTurn(pairs, doc, raw, known)
    except Exception:
        _logger.warning("[EntityAdmission] msg=%s turn admission failed", message_id[:8], exc_info=True)
        return ParsedTurn([])


async def admit_turn(gw: Any, message_id: str, text: str, speaker: str | None, config: dict | None, *,
                     embedding_model: str) -> list[tuple[str, str]]:
    """Admit the named entities of one turn from its text: step 1 (spaCy + surface
    normalisation, as the Loop runs it) then `admit_entities`. Idempotent (the lookups find
    what an earlier call or the Loop wrote), so the Observation extractor calls it before it
    links a claim's words to Concepts and does not depend on whether `run_loop` ran first.
    No-op when the flag is off. Never raises."""
    return (await admit_turn_parsed(gw, message_id, text, speaker, config, embedding_model=embedding_model)).pairs


def names_in(entity_text: str | None, claim_words: str | None) -> bool:
    """True when `entity_text` occurs in `claim_words` as whole words, case-insensitively
    ("Art" is not in "artist"; "Nike" is in "signed with Nike's team")."""
    e = " ".join((entity_text or "").lower().replace("\u2019", "'").split())
    c = " ".join((claim_words or "").lower().replace("\u2019", "'").split())
    return bool(e) and re.search(r"(?<!\w)" + re.escape(e) + r"(?!\w)", c) is not None
