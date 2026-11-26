"""Entity-resolved typed Observation capture (`[observations] entity_resolved_capture`).

Ports the entity-resolved triple capture pipeline into `campy/` behind the
`[observations] entity_resolved_capture` flag (default ``False``, env
``CAMPY_ENTITY_RESOLVED_CAPTURE=1``, in no profile until gated):

- 3-turn coreference context window (`recent_turns`) for pronoun/alias resolution
- Closed entity list (`known_entities`) supplied to the extractor
- Inline image caption stripping (`[shares an image: ...]`)
- P8 person-anchored subject grounding (`subject.lower() == speaker.lower()`
  sets ``is_first_person=True`` so third-person speaker references on
  first-person turns are never dropped; ungrounded non-person subjects are
  rejected)
- Grounded object Concept admission + SKOS ``INSTANCE_OF`` / ``BROADER`` linking
- Speaker alias resolution via ``HAS_ALT_LABEL``
- ``num_ctx=4096`` / ``think=False`` passed when supported by the LLM client

All graph reads and writes go strictly through ``GraphGateway`` NamedQueries and
``observations.record_observation`` (zero ``pyoxigraph``, zero ``execute_raw``,
zero inline Cypher).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from campy.brain.hippocampus import attribute_names, kinds as kinds_mod, observations as obs
from campy.brain.hippocampus.concept_links import norm_key
from campy.brain.hippocampus.graph import embeddings as emb_mod
from campy.brain.hippocampus.graph.gateway import get_gateway
from campy.brain.hippocampus.shapes.validator import is_stopword_only
from campy.brain.temporal_lobe.lexicon.closed_class import is_closed_class
from campy.brain.temporal_lobe.observations.extract import (
    find_existing_concept,
    parse_observations,
    predicate_by_lemma,
    predicate_lemma_key,
    salvage_cut_reply,
)
from campy.brain.temporal_lobe.observations.timeparse import normalize_time

_logger = logging.getLogger(__name__)

RULE_VERSION = "entity-resolved-1"
DEFAULT_NUM_CTX = 4096
DEFAULT_MAX_TOKENS = 2048

CLOSED_PRONOUNS = frozenset(
    "i me my you your it its we us our they them their he she him her this that these those".split()
)
_FIRST_PERSON_SUBJECTS = frozenset({
    "i", "me", "my", "myself", "mine", "i'm", "i've", "i'd", "i'll",
    "we", "us", "our", "ourselves", "we're", "we've", "we'll", "we'd",
})
_WE_WORDS = frozenset({"we", "us", "our", "ourselves", "we're", "we've", "we'll", "we'd"})
_GENERIC_ENTITY_WORDS = frozenset({
    "someone", "something", "anyone", "anything", "one", "thing", "things", "stuff", "user",
})
_NULL_STRINGS = frozenset({"null", "none", "n/a", "na", "unknown", "-", ""})

_IMAGE_CAPTION_RE = re.compile(r"[ \t]*\[shares an image:[^\]]*\]", re.IGNORECASE)
_LEADING_DET_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
_THIRD_PERSON_PRONOUN_RE = re.compile(
    r"(?<!\w)(he|him|his|she|her|hers|they|them|their|theirs|it|its)(?!\w)",
    re.IGNORECASE,
)

SYSTEM_PROMPT = (
    "You extract entity-resolved, source-grounded factual triples from a single target chat turn. "
    "Use the preceding turns ONLY to resolve pronouns or coreferences, never extract facts from them. "
    "Reply with a JSON array and nothing else."
)


def entity_resolved_capture_enabled(config: dict | None) -> bool:
    """`[observations] entity_resolved_capture` (default False; env `CAMPY_ENTITY_RESOLVED_CAPTURE=1`)."""
    return bool(((config or {}).get("observations") or {}).get("entity_resolved_capture", False))


def strip_image_captions(text: str) -> str:
    """Remove `[shares an image: ...]` captions without mangling surrounding prose."""
    if not text:
        return ""
    cleaned = _IMAGE_CAPTION_RE.sub("", text)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def build_entity_resolved_prompt(
    speaker: str,
    turn_text: str,
    *,
    recent_turns: list[tuple[str, str]] = (),
    known_entities: list[str] = (),
    occurred_at: str | None = None,
) -> str:
    """Build the entity-resolved triple extraction prompt with 3-turn coreference window and closed entities."""
    prior_lines: list[str] = []
    for sp, txt in list(recent_turns)[-3:]:
        clean_txt = " ".join(strip_image_captions(txt).split())
        if clean_txt:
            prior_lines.append(f"- [{sp or 'unknown'}]: {clean_txt}")
    prior_block = "\n".join(prior_lines) or "(none — start of session)"

    entity_items = [str(item).strip() for item in known_entities if str(item).strip()]
    concepts_block = ", ".join(entity_items) if entity_items else "(none yet)"

    speaker_str = " ".join((speaker or "").split()) or "unknown"
    date_str = str(occurred_at)[:10] if occurred_at else "unknown"
    body = " ".join(strip_image_captions(turn_text).split()).replace('"""', "'''")

    return f"""Extract the concrete personal facts stated in the TARGET TURN below.

PRECEDING TURNS IN THIS SESSION (read-only coreference context; DO NOT extract facts from these):
{prior_block}

KNOWN ENTITIES IN MEMORY (reuse exact canonical name when referring to an existing entity):
{concepts_block}

TARGET TURN (extract facts ONLY from this turn):
Speaker: {speaker_str}
Date: {date_str}
Message: \"\"\"{body}\"\"\"

Output a JSON array of objects, each with these keys:
- "subject_entity": MUST be a PERSON (or named pet) the fact is about — use "I" when the speaker refers to themselves, or a named person/pet from KNOWN ENTITIES / target turn (resolve "he"/"she"/"they"/"my dog" using preceding turns when clear). NEVER use abstract nouns, hobbies, objects, or photos (like "life", "painting", "art", "pic", "that painting") as "subject_entity"; instead anchor the fact on the person (e.g. subject "I", predicate "prefers", object_entity "painting").
- "predicate": one of:
    did (concrete event or action taken),
    has_attribute (factual property of the person/pet; write "name: value" in "object_text", e.g. "job: nurse"),
    is_a (role, occupation, or identity of a person/pet — NEVER an adjective like "awesome"),
    located_in (where subject lives, works, or visited),
    owns (possession, pet, or item owned),
    relates_to (relationship to another person/entity),
    prefers (like, dislike, hobby, or preference),
    plans (concrete intention, goal, or future event),
    changed_to (stated change of state)
- "object_entity": canonical entity name if the object is a specific person, pet, place, title, organization, product, hobby, activity, or named event — either copied from KNOWN ENTITIES or an exact entity span present in the TARGET TURN (NEVER a full verb phrase); otherwise null
- "object_kind": singular common noun for the kind of "object_entity" (e.g. "dog", "book", "city", "event", "hobby"), or null if "object_entity" is null
- "object_text": concise claim object or attribute "name: value" (required, short)
- "time": exact time phrase from the TARGET TURN (e.g. "yesterday", "last Saturday", "7 May 2023"), or null
- "polarity": "asserted", "negated", "hypothetical", or "planned"
- "quote": exact verbatim substring from the TARGET TURN supporting this fact (copied character-for-character)
- "confidence": number between 0.0 and 1.0

Rules:
- Extract ONLY concrete facts stated in the TARGET TURN. Do not extract facts that appear only in PRECEDING TURNS.
- Every "subject_entity" MUST be a person or named pet ("I" or a named person/pet). Do NOT extract facts whose subject is an abstract concept, artwork, or generic noun.
- Every "quote" MUST be an exact verbatim substring of the TARGET TURN.
- Never invent an "object_entity" name that is neither in KNOWN ENTITIES nor explicitly written in the TARGET TURN.
- Questions, greetings, compliments ("that's cool", "you're killing it"), or generic platitudes ("Life's unpredictable", "Being yourself is great") -> return [].
- Reply with ONLY the JSON array.

JSON array:"""


def parse_entity_resolved_response(raw: str | None) -> list[dict]:
    """Parse an extraction reply (clean JSON, fenced JSON, or truncated array) into dicts."""
    if not raw or not isinstance(raw, str):
        return []
    parsed = parse_observations(raw)
    if parsed is not None:
        return parsed
    return salvage_cut_reply(raw)


def _whole_word_in_text(phrase: str, text: str) -> str | None:
    cleaned = " ".join((phrase or "").split())
    if not cleaned or not text:
        return None
    m = re.search(r"(?<!\w)" + re.escape(cleaned) + r"(?!\w)", text, re.IGNORECASE)
    return m.group(0) if m else None


def ground_subject_entity(
    subject: str,
    speaker: str,
    turn_text: str,
    known_persons: dict[str, str],
) -> tuple[str | None, bool]:
    """Resolve `subject` to `(concept_id, is_first_person)` with P8 person-anchored grounding.

    First-person pronouns and ``subject.lower() == speaker.lower()`` always set
    ``is_first_person=True`` so third-person speaker references on first-person
    turns are never dropped even when the turn has no literal ``"I"``.
    Non-speaker subjects must resolve in ``known_persons`` and be grounded in
    ``turn_text`` (either by name/alias or a third-person coreference pronoun).
    """
    subj = " ".join((subject or "").split())
    if not subj:
        return None, False

    sp = " ".join((speaker or "").split())
    subj_low = subj.lower()
    sp_low = sp.lower()
    persons_low = {
        " ".join(str(k).split()).lower(): str(v)
        for k, v in (known_persons or {}).items()
        if k and v
    }

    is_first_person = (subj_low in _FIRST_PERSON_SUBJECTS) or (bool(sp_low) and subj_low == sp_low)
    if is_first_person:
        return persons_low.get(sp_low), True

    cid = persons_low.get(subj_low)
    if not cid:
        return None, False

    clean_turn = strip_image_captions(turn_text or "")
    if clean_turn:
        aliases_for_cid = [k for k, v in persons_low.items() if v == cid]
        grounded_in_turn = (
            any(_whole_word_in_text(alias, clean_turn) for alias in aliases_for_cid)
            or bool(_THIRD_PERSON_PRONOUN_RE.search(clean_turn))
        )
        if not grounded_in_turn:
            return None, False

    return cid, False


def _clean_str(val: Any) -> str | None:
    if val is None or isinstance(val, (dict, list, tuple, set, bool)):
        return None
    s = " ".join(str(val).split())
    if s.lower() in _NULL_STRINGS:
        return None
    return s


def _span_in_text(span: str, text: str) -> bool:
    norm_span = " ".join(span.translate(obs._QUOTE_TABLE).split()).strip(" .,;:!?\"'")
    norm_text = " ".join(text.translate(obs._QUOTE_TABLE).split())
    if not norm_span or not norm_text:
        return False
    return re.search(r"(?<!\w)" + re.escape(norm_span) + r"(?!\w)", norm_text, re.IGNORECASE) is not None


def _valid_new_entity(name: str) -> bool:
    if not name or len(name) < 2 or len(name) > 60 or len(name.split()) > 6:
        return False
    if not any(ch.isalpha() for ch in name):
        return False
    if is_closed_class(name) or is_stopword_only(name):
        return False
    words = [w.strip(".,;:!?\"'").lower() for w in name.split()]
    if all(w in CLOSED_PRONOUNS or w in _GENERIC_ENTITY_WORDS for w in words):
        return False
    return True


def _safe_embed(text: str, *, model_name: str) -> list[float] | None:
    try:
        return emb_mod.embed(text, model_name=model_name)
    except Exception:
        _logger.debug("Embedding failed for %r", text[:40], exc_info=True)
        return None


async def _admit_object_concept(
    gw: Any,
    object_entity: str,
    object_kind: str | None,
    message_id: str,
    turn_text: str,
    *,
    embedding_model: str,
) -> str | None:
    """Resolve `object_entity` to an existing Concept or admit a turn-grounded one with optional SKOS kind."""
    cid = await find_existing_concept(gw, object_entity)
    if cid is None:
        stripped = _LEADING_DET_RE.sub("", object_entity).strip()
        if stripped and stripped != object_entity:
            cid = await find_existing_concept(gw, stripped)

    if cid is not None:
        if _span_in_text(object_entity, turn_text):
            await gw.run("concept_links.link_message_concept", mid=message_id, cid=cid)
    else:
        if not _valid_new_entity(object_entity) or not _span_in_text(object_entity, turn_text):
            return None
        vec = await asyncio.to_thread(_safe_embed, object_entity, model_name=embedding_model)
        cid = str(uuid.uuid4())
        await gw.run(
            "temporal_lobe.dict_create_concept",
            cid=cid,
            text=object_entity,
            emb=vec,
            gist="Entity",
            stype="Thing",
            now=datetime.now(timezone.utc),
        )
        await gw.run("concept_links.link_message_concept", mid=message_id, cid=cid)

    if object_kind and cid:
        await _link_object_kind(
            gw, cid, object_entity, object_kind, embedding_model=embedding_model
        )
    return cid


async def _link_object_kind(
    gw: Any,
    concept_id: str,
    object_entity: str,
    object_kind: str,
    *,
    embedding_model: str,
) -> None:
    clean_kind = kinds_mod.normalise_kind_label(object_kind)
    if (
        not clean_kind
        or len(clean_kind) > 40
        or len(clean_kind.split()) > 4
        or is_closed_class(clean_kind)
        or is_stopword_only(clean_kind)
        or norm_key(clean_kind) == norm_key(object_entity)
    ):
        return

    known_kinds = await kinds_mod.load_kinds(gw)
    if concept_id in known_kinds:
        return

    plan = kinds_mod.plan_kind(clean_kind, known_kinds)
    kind_id: str | None = None
    if plan.exact:
        kind_id = plan.exact
        await kinds_mod.add_alt_label(gw, known_kinds[kind_id], object_kind)
    else:
        existing_k = await find_existing_concept(gw, clean_kind)
        if existing_k:
            if await kinds_mod.mark_kind(gw, existing_k):
                kind_id = existing_k
        else:
            kvec = await asyncio.to_thread(_safe_embed, clean_kind, model_name=embedding_model)
            cand_kid = str(uuid.uuid4())
            await gw.run(
                "temporal_lobe.dict_create_concept",
                cid=cand_kid,
                text=clean_kind,
                emb=kvec,
                gist="Category",
                stype="Thing",
                now=datetime.now(timezone.utc),
            )
            if await kinds_mod.mark_kind(gw, cand_kid):
                kind_id = cand_kid
                for parent in plan.broader:
                    await kinds_mod.link_broader(gw, kind_id, parent)
                for child in plan.narrower:
                    await kinds_mod.link_broader(gw, child, kind_id)

    if kind_id and kind_id != concept_id:
        await kinds_mod.link_instance_of(gw, concept_id, kind_id)


def _call_llm_with_options(llm: Any, messages: list[dict[str, str]]) -> str:
    """Invoke `llm.chat` with `num_ctx=4096` and `think=False` when supported by the client."""
    from campy.brain.llm.provider import LLMClient

    if isinstance(llm, LLMClient):
        if getattr(llm, "_provider", None) == "ollama":
            try:
                return llm.chat(
                    messages,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    extra_body={"options": {"num_ctx": DEFAULT_NUM_CTX}, "think": False},
                )
            except TypeError:
                pass
        return llm.chat(messages, max_tokens=DEFAULT_MAX_TOKENS)

    chat_fn = llm.chat
    try:
        params = inspect.signature(chat_fn).parameters
    except (TypeError, ValueError):
        params = {}
    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    kwargs: dict[str, Any] = {}
    if has_varkw or "max_tokens" in params:
        kwargs["max_tokens"] = DEFAULT_MAX_TOKENS
    if has_varkw or "num_ctx" in params:
        kwargs["num_ctx"] = DEFAULT_NUM_CTX
    if has_varkw or "think" in params:
        kwargs["think"] = False

    try:
        return chat_fn(messages, **kwargs)
    except TypeError:
        fallback = {"max_tokens": DEFAULT_MAX_TOKENS} if (has_varkw or "max_tokens" in params) else {}
        return chat_fn(messages, **fallback)


async def _load_known_context(
    gw: Any,
    *,
    message_id: str,
    speaker: str,
    speaker_id: str,
    recent_turns: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[str], dict[str, str], dict[str, list[str]], str | None]:
    turns = list(recent_turns)
    if not turns:
        prev_rows = await gw.run("observations.preceding_messages", mid=message_id)
        turns = [
            (str(r.get("speaker") or "user"), str(r.get("text_raw") or ""))
            for r in reversed(prev_rows or [])
            if r.get("text_raw")
        ]

    closed_rows = await gw.run("observations.closed_entity_concepts")
    known_entities: list[str] = []
    seen_cids: set[str] = set()
    for r in closed_rows or []:
        cid = str(r.get("concept_id") or "")
        txt = str(r.get("text_raw") or "").strip()
        if not txt or (cid and cid in seen_cids):
            continue
        if cid:
            seen_cids.add(cid)
        kind_lbl = str(r.get("kind_lbl") or "").strip()
        known_entities.append(f"{txt} ({kind_lbl})" if kind_lbl else txt)

    surf_rows = await gw.run("question_analysis.concept_surfaces")
    alt_labels_by_cid: dict[str, list[str]] = {}
    for r in surf_rows or []:
        cid = str(r.get("concept_id") or "")
        surf = str(r.get("surface") or "").strip()
        if cid and surf:
            alt_labels_by_cid.setdefault(cid, []).append(surf)

    lex_rows = await gw.run("question_analysis.concept_lexicon")
    known_persons: dict[str, str] = {}
    for r in lex_rows or []:
        cid = str(r.get("concept_id") or "")
        txt = str(r.get("text_raw") or "").strip()
        is_person = (
            r.get("person_basis") in ("strong", "weak")
            or str(r.get("schema_org_type") or "").endswith("Person")
            or str(r.get("ner_label") or "") == "PERSON"
        )
        if not (cid and is_person):
            continue
        if txt:
            known_persons.setdefault(txt, cid)
        for surf in alt_labels_by_cid.get(cid, ()):
            known_persons.setdefault(surf, cid)

    sp_clean = " ".join((speaker or "").split())
    resolved_speaker_id = speaker_id.strip() if speaker_id else None
    if not resolved_speaker_id and sp_clean:
        resolved_speaker_id = await find_existing_concept(gw, sp_clean)
    if sp_clean and resolved_speaker_id:
        known_persons[sp_clean] = resolved_speaker_id
        for surf in alt_labels_by_cid.get(resolved_speaker_id, ()):
            known_persons.setdefault(surf, resolved_speaker_id)

    return turns, known_entities, known_persons, alt_labels_by_cid, resolved_speaker_id


async def extract_entity_resolved_observations(
    db: Any,
    llm: Any,
    *,
    message_id: str,
    speaker: str,
    speaker_id: str,
    text: str,
    recent_turns: list[tuple[str, str]] = (),
    config: dict | None = None,
    occurred_at: Any = None,
    embedding_model: str = obs.EMBEDDING_MODEL,
    stats: Any = None,
) -> int:
    """Extract and record entity-resolved typed Observations for one turn.

    Returns the number of newly created Observations (``0`` when the
    ``[observations] entity_resolved_capture`` flag is off).
    """
    if not entity_resolved_capture_enabled(config):
        return 0
    if llm is None or not (text or "").strip():
        return 0

    gw = get_gateway(db)
    if occurred_at is None:
        msg_rows = await gw.run("observations.get_message", mid=message_id)
        if not msg_rows:
            return 0
        occurred_at = msg_rows[0].get("occurred_at") or msg_rows[0].get("created_at")

    turns, known_entities, known_persons, alt_labels_by_cid, resolved_speaker_id = await _load_known_context(
        gw, message_id=message_id, speaker=speaker, speaker_id=speaker_id, recent_turns=recent_turns
    )

    prompt = build_entity_resolved_prompt(
        speaker,
        text,
        recent_turns=turns,
        known_entities=known_entities,
        occurred_at=str(occurred_at)[:10] if occurred_at else None,
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]

    if stats is not None and hasattr(stats, "llm_calls"):
        stats.llm_calls += 1
    try:
        raw = await asyncio.to_thread(_call_llm_with_options, llm, messages)
    except Exception:
        if stats is not None and hasattr(stats, "llm_failed"):
            stats.llm_failed += 1
        _logger.warning("[EntityResolved] LLM call failed for msg=%s", message_id[:8], exc_info=True)
        return 0

    proposals = parse_entity_resolved_response(raw)
    if not proposals:
        return 0
    if stats is not None and hasattr(stats, "proposed"):
        stats.proposed += len(proposals)

    observed_at = obs._as_datetime(occurred_at)
    effective_config = {
        **(config or {}),
        "observations": {**((config or {}).get("observations") or {}), "object_roles": True},
    }

    writes = obs.WriteStats()
    for p in proposals:
        draft = await _proposal_to_draft(
            gw,
            p,
            message_id=message_id,
            speaker=speaker,
            resolved_speaker_id=resolved_speaker_id,
            text=text,
            known_persons=known_persons,
            alt_labels_by_cid=alt_labels_by_cid,
            observed_at=observed_at,
            embedding_model=embedding_model,
            stats=stats,
        )
        if draft is None:
            writes.record(obs.WriteResult("rejected", None, "malformed_proposal"))
            continue

        result = await obs.record_observation(
            db,
            draft,
            config=effective_config,
            supersede=obs.observations_supersede_enabled(effective_config),
        )
        writes.record(result)
        if result.ok and result.observation_id and draft.object_id:
            await gw.run("observations.link_about_concept", oid=result.observation_id, cid=draft.object_id)

    if stats is not None and hasattr(stats, "merge_write"):
        stats.merge_write(writes)
    return writes.created


async def _proposal_to_draft(
    gw: Any,
    p: dict,
    *,
    message_id: str,
    speaker: str,
    resolved_speaker_id: str | None,
    text: str,
    known_persons: dict[str, str],
    alt_labels_by_cid: dict[str, list[str]],
    observed_at: datetime | None,
    embedding_model: str,
    stats: Any,
) -> obs.ObservationDraft | None:
    subj_raw = _clean_str(p.get("subject_entity") or p.get("subject"))
    pred_raw = (_clean_str(p.get("predicate")) or "").lower().replace(" ", "_")
    obj_entity = _clean_str(p.get("object_entity"))
    obj_kind = _clean_str(p.get("object_kind"))
    obj_text = _clean_str(p.get("object_text") or p.get("object"))
    if not obj_text and obj_entity:
        obj_text = obj_entity
    quote_raw = _clean_str(p.get("quote"))
    polarity = (_clean_str(p.get("polarity")) or "asserted").lower()
    time_text = _clean_str(p.get("time"))

    try:
        conf = float(p.get("confidence")) if p.get("confidence") is not None else 0.75
    except (TypeError, ValueError):
        conf = 0.75

    if not (subj_raw and pred_raw and obj_text and quote_raw):
        return None

    if pred_raw not in obs.PREDICATES:
        mapped = predicate_by_lemma().get(predicate_lemma_key(pred_raw))
        if not mapped:
            return None
        pred_raw = mapped
        if stats is not None and hasattr(stats, "predicate_normalised"):
            stats.predicate_normalised += 1

    if polarity not in obs.POLARITIES or conf < obs.MIN_CONFIDENCE or conf > 1.0:
        return None

    span = obs.locate_quote(text, quote_raw)
    if span is None:
        return None
    matched_quote = text[span[0]:span[1]]
    if len(matched_quote) > obs.MAX_EVIDENCE_CHARS or len(obj_text) > obs.MAX_OBJECT_CHARS:
        return None
    if is_stopword_only(obj_text) or obj_text.startswith(("{", "[")):
        return None

    subject_id, is_first_person = ground_subject_entity(subj_raw, speaker, text, known_persons)
    if is_first_person:
        if not subject_id:
            subject_id = resolved_speaker_id
        if not subject_id:
            return None
        display_subject = " ".join((speaker or "").split()) or subj_raw
        if subj_raw.lower() in _WE_WORDS:
            we_match = _whole_word_in_text(subj_raw, matched_quote) or _whole_word_in_text("we", matched_quote)
            draft_subject_text = we_match or subj_raw
        else:
            draft_subject_text = "I"
    else:
        if not subject_id:
            return None
        display_subject = subj_raw
        if _whole_word_in_text(subj_raw, matched_quote):
            draft_subject_text = subj_raw
        else:
            alt_hit = next(
                (a for a in alt_labels_by_cid.get(subject_id, ()) if _whole_word_in_text(a, matched_quote)),
                None,
            )
            if alt_hit:
                draft_subject_text = alt_hit
            else:
                pron_m = _THIRD_PERSON_PRONOUN_RE.search(matched_quote)
                draft_subject_text = pron_m.group(1) if pron_m else subj_raw

    object_id: str | None = None
    if obj_entity:
        object_id = await _admit_object_concept(
            gw,
            obj_entity,
            obj_kind,
            message_id,
            text,
            embedding_model=embedding_model,
        )
        if object_id == subject_id:
            object_id = None

    resolved_time = normalize_time(time_text, observed_at) if time_text else None
    attr_name: str | None = None
    attr_value: str | None = None
    if pred_raw == "has_attribute" and ":" in obj_text:
        k_part, v_part = obj_text.split(":", 1)
        pair, _ = attribute_names.validate_structured(
            {"name": k_part.strip(), "value": v_part.strip()}, text
        )
        if pair:
            attr_name, attr_value = pair

    draft = obs.ObservationDraft(
        evidence_ref=message_id,
        evidence_text=matched_quote,
        subject_text=draft_subject_text,
        predicate=pred_raw,
        object_text=obj_text,
        extraction_method="llm",
        confidence=conf,
        rule_version=RULE_VERSION,
        polarity=polarity,
        subject_id=subject_id,
        object_id=object_id,
        time_text=time_text,
        time_start=resolved_time.start if resolved_time else None,
        time_end=resolved_time.end if resolved_time else None,
        time_precision=resolved_time.precision if resolved_time else None,
        speaker=speaker or None,
        observed_at=observed_at,
        attr_name=attr_name,
        attr_value=attr_value,
    )
    shown = obs.ObservationDraft(**{**draft.__dict__, "subject_text": display_subject})
    draft.text_raw = obs.render_observation_text(shown)
    draft.embedding = await asyncio.to_thread(_safe_embed, draft.text_raw, model_name=embedding_model)
    return draft
