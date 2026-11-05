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
(`ner_label` set) or a Person is never put in the kind scheme.

Graph store only; every write is a named query through the gateway.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
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


async def _concept_for(gw: Any, text: str, embedding_model: str) -> str | None:
    """The live Concept the existing lookups find for `text`, else a new one."""
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
    """False when the Concept is a named entity (`ner_label` set) or a Person: such a
    Concept is an instance, never a kind. An unknown id or a plain Concept can be one."""
    rows = await gw.run("entity_admission.concept_status", cid=concept_id)
    if not rows:
        return True
    row = rows[0]
    if row.get("ner_label"):
        return False
    return str(row.get("schema_org_type") or "").rsplit(":", 1)[-1] != "Person"


async def admit_turn(gw: Any, message_id: str, text: str, speaker: str | None, config: dict | None, *,
                     embedding_model: str) -> list[tuple[str, str]]:
    """Admit the named entities of one turn from its text: step 1 (spaCy + surface
    normalisation, as the Loop runs it) then `admit_entities`. Idempotent (the lookups find
    what an earlier call or the Loop wrote), so the Observation extractor calls it before it
    links a claim's words to Concepts and does not depend on whether `run_loop` ran first.
    No-op when the flag is off. Never raises."""
    if not entity_admission_enabled(config):
        return []
    try:
        from campy.brain.temporal_lobe.loop.step1_ner import extract_entities, normalize_entities
        model = ((config or {}).get("nlp") or {}).get("spacy_model", "en_core_web_md")
        _, entities = await asyncio.to_thread(extract_entities, text, model)
        known = {speaker} if speaker and speaker.strip() else set()
        entities = normalize_entities(entities, known)
        return await admit_entities_with_text(gw, message_id, entities, embedding_model=embedding_model)
    except Exception:
        _logger.warning("[EntityAdmission] msg=%s turn admission failed", message_id[:8], exc_info=True)
        return []


def names_in(entity_text: str | None, claim_words: str | None) -> bool:
    """True when `entity_text` occurs in `claim_words` as whole words, case-insensitively
    ("Art" is not in "artist"; "Nike" is in "signed with Nike's team")."""
    e = " ".join((entity_text or "").lower().replace("\u2019", "'").split())
    c = " ".join((claim_words or "").lower().replace("\u2019", "'").split())
    return bool(e) and re.search(r"(?<!\w)" + re.escape(e) + r"(?!\w)", c) is not None
