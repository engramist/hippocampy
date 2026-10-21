"""
B504: object entities and kinds for Observations, validated by rule, written to the graph.

Why: B503's retrieval walk needs the evidence entities to exist as Concepts ("Revell
F-15 Eagle") and needs kind Concepts ("model kit") to hang them on. The extractor, when
`[observations] entities` is on, proposes for each claim an `object_entity` and an
`object_kind`. The model only advises (principle 3): this module decides.

Rules (a proposal that fails is dropped and counted; the claim itself is unaffected):
  entity  at most 60 chars / 6 words, has a letter, not a pronoun or a stopword-only
          phrase, and it appears in the source turn (case-insensitive, after
          normalising quotes and whitespace). A name the turn does not contain is a
          hallucination and is dropped.
  kind    only with a valid entity; at most 40 chars / 4 words, not a pronoun or
          stopword-only phrase, not the entity itself. A kind may be inferred (it need
          not be in the turn): "Tamiya Spitfire" -> "model kit".
  value   a `has_attribute` claim's value ("name: value") must appear in the turn.

Writes (graph store only; plain idempotent edges, nothing kept in Python):
  Concept for the entity and the kind: reused when a live Concept has the same
  normalised key (`concept_links.norm_key`), else created like a dictionary Concept.
  Observation -OBSERVATION_ABOUT-> entity;  Message -MENTIONS-> entity;
  entity -IS_A-> kind.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.concept_links import concept_index, norm_key
from campy.brain.hippocampus.graph import embeddings as emb

_logger = logging.getLogger(__name__)

MAX_ENTITY_CHARS = 60
MAX_ENTITY_WORDS = 6
MAX_KIND_CHARS = 40
MAX_KIND_WORDS = 4
_NULLS = frozenset({"null", "none", "n/a", "unknown", "na", "-"})
_PRONOUNS = frozenset({
    "i", "me", "my", "myself", "mine", "we", "us", "our", "you", "your", "he", "him", "his",
    "she", "her", "they", "them", "their", "it", "its", "this", "that", "these", "those",
    "someone", "something", "anyone", "anything", "one", "thing", "things", "stuff", "user",
})


def _norm_text(text: str | None) -> str:
    s = str(text or "").translate(obs._QUOTE_TABLE).lower()
    return " ".join(s.split())


def in_turn(phrase: str | None, turn_text: str | None) -> bool:
    """Case-insensitive substring after quote and whitespace normalisation."""
    p = _norm_text(phrase).strip(" .,;:!?\"'")
    return bool(p) and p in _norm_text(turn_text)


def _clean_name(value: Any) -> str | None:
    if value is None:
        return None
    s = " ".join(str(value).split())
    if not s or s.lower() in _NULLS:
        return None
    return s


def _plausible(name: str, max_chars: int, max_words: int) -> bool:
    if len(name) > max_chars or len(name.split()) > max_words:
        return False
    if not any(ch.isalpha() for ch in name):
        return False
    words = [w.strip(".,;:!?\"'").lower() for w in name.split()]
    if all(w in _PRONOUNS for w in words):
        return False
    return bool(norm_key(name))     # stopword-only phrases have no content key


@dataclass(frozen=True)
class EntityProposal:
    entity: str
    kind: str | None


def validate_entity(proposal: dict, turn_text: str, stats: Any) -> EntityProposal | None:
    """The validated (entity, kind) of one model proposal, or None. Updates
    `stats.entity_rejected` / `stats.kind_rejected` for what it drops."""
    entity = _clean_name(proposal.get("object_entity"))
    kind = _clean_name(proposal.get("object_kind"))
    if entity is None:
        if kind is not None:
            stats.kind_rejected += 1       # a kind with no entity to hang on
        return None
    if not _plausible(entity, MAX_ENTITY_CHARS, MAX_ENTITY_WORDS) or not in_turn(entity, turn_text):
        stats.entity_rejected += 1
        if kind is not None:
            stats.kind_rejected += 1
        return None
    if kind is not None and (not _plausible(kind, MAX_KIND_CHARS, MAX_KIND_WORDS)
                             or norm_key(kind) == norm_key(entity)):
        stats.kind_rejected += 1
        kind = None
    return EntityProposal(entity, kind)


def value_in_turn(predicate: str, object_text: str, turn_text: str) -> bool:
    """A `has_attribute` value ("name: value") must be a span of the turn. Other predicates pass."""
    if predicate != "has_attribute":
        return True
    value = object_text.split(":", 1)[1] if ":" in object_text else object_text
    return in_turn(value, turn_text)


async def _concept_for(gw: Any, name: str, index: dict[str, list[str]], stats: Any, *,
                       embedding_model: str) -> str | None:
    """A live Concept for `name` (same normalised key), or a new one."""
    key = norm_key(name)
    if not key:
        return None
    ids = index.get(key)
    if ids:
        return sorted(ids)[0]
    try:
        vec = emb.embed(name, model_name=embedding_model)
    except Exception:
        _logger.debug("entity embedding failed", exc_info=True)
        return None
    cid = str(uuid.uuid4())
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=name, emb=vec,
                 gist="Entity", stype="Thing", now=datetime.now(timezone.utc))
    index.setdefault(key, []).append(cid)
    stats.entity_concepts_created += 1
    return cid


async def write_entity(gw: Any, proposal: EntityProposal, observation_id: str, message_id: str,
                       stats: Any, *, embedding_model: str = obs.EMBEDDING_MODEL) -> str | None:
    """Create or reuse the entity (and kind) Concepts and write the edges.
    Returns the entity Concept id."""
    index = await concept_index(gw)
    entity_id = await _concept_for(gw, proposal.entity, index, stats, embedding_model=embedding_model)
    if not entity_id:
        return None
    await gw.run("observations.link_about_concept", oid=observation_id, cid=entity_id)
    await gw.run("concept_links.link_message_concept", mid=message_id, cid=entity_id)
    stats.entities_linked += 1
    if proposal.kind:
        kind_id = await _concept_for(gw, proposal.kind, index, stats, embedding_model=embedding_model)
        if kind_id and kind_id != entity_id:
            await gw.run("concept_links.link_is_a", cid=entity_id, pid=kind_id)
            stats.kinds_linked += 1
    return entity_id
