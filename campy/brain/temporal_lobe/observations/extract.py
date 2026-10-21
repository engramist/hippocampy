"""
B472 Phase 3b: per-turn Observation extraction.

For one USER turn, a short LLM prompt proposes (subject, predicate, object,
time text, polarity, quote); each proposal becomes an `ObservationDraft` and goes
through `hippocampus.observations.record_observation`, the only writer, which
rejects any draft whose quote is not a verbatim span of the turn ("no quote,
no row"). The model never writes anything and never sets a Concept id.

Concept linking (design section 6): subject and object resolve to EXISTING
Concepts only, by exact text then by label (the B472 Phase 2 lookups). This
module never creates a Concept; an unmatched name is stored as text with a NULL
id. That is the B473 rule for LLM relations ("LLM relations need existing
endpoints") applied here, so the extractor cannot refill the graph with the
bare Concepts B473 removed.

The LLM call is synchronous (`client.chat`), so it runs via `asyncio.to_thread`
exactly as the Loop's LLM steps do since B468; the event loop is never blocked.

Time (B484, M4.2): the phrase is stored as written in `time_text`, and
`timeparse.normalize_time` resolves it against the turn's date into
`time_start`/`time_end`/`time_precision` (NULL when it cannot be resolved).

Not here: pronoun resolution beyond the
speaker (Phase 4), the pattern route and batching (design 5a/2; 3b is per turn).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.concept_links import concept_index, graph_linking_enabled, link_observation_concepts
from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.graph.gateway import get_gateway
from campy.brain.temporal_lobe.observations import entities as ent
from campy.brain.temporal_lobe.observations.timeparse import normalize_time

_logger = logging.getLogger(__name__)

RULE_VERSION = "llm-1"
MAX_TOKENS = 512            # a JSON array of a handful of short objects
MAX_PER_TURN = 8            # proposals beyond this are dropped and counted
MIN_WORDS = 3               # shorter turns carry no claim worth an LLM call
DEFAULT_CONFIDENCE = 0.75   # when the model gives none
_FIRST_PERSON = frozenset({"i", "me", "my", "myself", "mine", "i'm", "i've", "i'd", "i'll"})

SYSTEM_PROMPT = (
    "You extract facts that a speaker states in one chat message. "
    "Reply with a JSON array and nothing else."
)

PROMPT_TEMPLATE = """Extract the facts the speaker states about themselves or about a named person in this message.

Speaker: {speaker}
Date of message: {date}
Message: \"\"\"{text}\"\"\"

Each fact is a JSON object with these keys:
- "subject": who or what the fact is about, copied exactly as written in the message ("I", "my sister", "Caroline"). Never replace a pronoun or "I" with a name.
- "predicate": one of
    did (an event the subject took part in), has_attribute (a property; put "name: value" in object, e.g. "job: nurse"),
    is_a (a type or role), located_in (where the subject lives or is based), owns (possession),
    relates_to (a relationship to another person; put "relation: person" in object, e.g. "friend: Melanie"),
    prefers (a like or dislike), plans (an intention or a future event), changed_to (a stated change of state)
- "object": the value, as short as possible
- "time": the time phrase exactly as written ("last Saturday", "7 May 2023"), or null
- "polarity": "asserted", "negated", "hypothetical" or "planned"
- "quote": the exact words from the message that state the fact, copied character for character
- "confidence": a number from 0 to 1

Rules:
- Only facts stated in the message. No inference, no outside knowledge.
- Opinions about the world, questions and requests are not facts: skip them.
- A future event or intention uses predicate "plans", never "did".
- Keep relative times as written; do not convert them to dates.
- If the message states no such fact, reply with [].

JSON array:"""

# B504 (flag `[observations] entities`). Applied by string replacement so that with the flag
# off the prompt is byte-identical to PROMPT_TEMPLATE. Structural, not rewording: it changes
# WHAT is captured (an entity and its kind per claim; facts inside requests and plans) and
# adds two output fields that rules then validate against the turn.
_ENTITY_FIELDS = """- "object_entity": the named thing the fact is about (a product, place, title, person, event), copied exactly as written in the message, or null
- "object_kind": the kind of that thing in one to three lower-case words ("model kit", "national park", "video editing software"), or null
- "confidence": a number from 0 to 1
"""
_REQUEST_RULE_OLD = "- Opinions about the world, questions and requests are not facts: skip them.\n"
_REQUEST_RULE_NEW = (
    "- Opinions about the world are not facts. A question or request is not itself a fact, "
    "but facts the speaker states about themselves inside it are.\n"
    "- A value stated in passing inside a plan or request (\"to beat my personal best of 25:50\") "
    "is also a has_attribute fact.\n"
)
ENTITY_PROMPT_TEMPLATE = (
    PROMPT_TEMPLATE
    .replace('- "confidence": a number from 0 to 1\n', _ENTITY_FIELDS, 1)
    .replace(_REQUEST_RULE_OLD, _REQUEST_RULE_NEW, 1)
)
assert ENTITY_PROMPT_TEMPLATE != PROMPT_TEMPLATE
ENTITY_MAX_TOKENS = 768     # two more short fields per fact


@dataclass
class ObservationWorkerStats:
    """Counts the worker accumulates (redacted metadata only: no content)."""

    turns: int = 0
    skipped_not_user: int = 0
    skipped_no_message: int = 0
    skipped_short: int = 0
    llm_calls: int = 0
    llm_failed: int = 0
    malformed: int = 0           # reply was not a JSON array of objects
    proposed: int = 0
    truncated_proposals: int = 0
    created: int = 0
    duplicate: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    linked_subject: int = 0
    linked_object: int = 0
    time_resolved: int = 0       # drafts whose time phrase resolved to a date range
    time_unresolved: int = 0     # drafts with a time phrase that did not
    entity_rejected: int = 0     # B504: proposed entity failed the rules (not in turn, pronoun, too long)
    kind_rejected: int = 0       # B504: proposed kind failed the rules
    entities_linked: int = 0     # B504: claims linked to a validated entity Concept
    kinds_linked: int = 0        # B504: entity -IS_A-> kind edges written
    entity_concepts_created: int = 0   # B504: new Concepts (entity or kind)
    queue_dropped: int = 0       # set by the daemon when the queue is full
    errors: int = 0              # a turn that raised (logged, skipped)

    def as_details(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "rejected" and v}
        if self.rejected:
            d["rejected"] = dict(self.rejected)
        return d

    def merge_write(self, ws: obs.WriteStats) -> None:
        self.created += ws.created
        self.duplicate += ws.duplicate
        for reason, n in ws.rejected.items():
            self.rejected[reason] = self.rejected.get(reason, 0) + n


# --- prompt and parsing -----------------------------------------------------------

def build_messages(text: str, speaker: str | None, occurred_at: Any, max_chars: int = 600,
                   *, entities: bool = False) -> list[dict]:
    """The chat messages for one turn. The speaker and the turn's date go in so
    "I"/"my" attach to the speaker and relative time can be kept as written."""
    body = " ".join((text or "").split())[:max_chars]
    date = str(occurred_at)[:10] if occurred_at else "unknown"
    prompt = (ENTITY_PROMPT_TEMPLATE if entities else PROMPT_TEMPLATE).format(
        speaker=(speaker or "unknown"), date=date, text=body.replace('"""', "'''"),
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]


def parse_observations(raw: str | None) -> list[dict] | None:
    """Parse the model's reply into a list of dicts. None means the reply was
    malformed (not JSON, or not a list of objects); an empty list means "no
    facts". Defensive: strips code fences and prose around the array."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    candidates = [text]
    lo, hi = text.find("["), text.rfind("]")
    if 0 <= lo < hi:
        candidates.append(text[lo:hi + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            inner = data.get("observations", data.get("facts"))
            data = inner if isinstance(inner, list) else None
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)] if all(isinstance(x, dict) for x in data) else None
    return None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = " ".join(str(value).split())
    return s or None


def _confidence(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE
    return c if 0.0 <= c <= 1.0 else DEFAULT_CONFIDENCE


# --- concept linking (existing Concepts only) -------------------------------------

def _row_concept_id(row: Any) -> str | None:
    for key in ("concept_id", "c.concept_id"):
        try:
            v = row.get(key)
        except AttributeError:
            v = None
        if v:
            return v
    try:
        return row[0]
    except (KeyError, IndexError, TypeError):
        return None


async def find_existing_concept(gw: Any, text: str | None) -> str | None:
    """A live Concept by exact text (case-insensitive), else by one of its
    labels. Never creates one."""
    if not text or len(text) > 80:
        return None
    for q in ("orchestrator.find_endpoint_concept", "orchestrator.find_concept_by_label_text"):
        try:
            rows = await gw.run(q, t=text)
        except Exception:
            _logger.debug("concept lookup %s failed", q, exc_info=True)
            continue
        if rows:
            cid = _row_concept_id(rows[0])
            if cid:
                return cid
    return None


def _object_candidates(predicate: str, object_text: str) -> list[str]:
    """Strings to try as an entity object: the value, and the part after
    "relation:" for relates_to / changed_to. Attributes are literals."""
    if predicate == "has_attribute":
        return []
    out = [object_text]
    if ":" in object_text:
        out.append(object_text.split(":", 1)[1].strip())
    return [c for c in out if c]


def _is_named(speaker: str | None) -> bool:
    s = (speaker or "").strip()
    return bool(s) and any(ch.isalpha() for ch in s) and s.lower() not in {"user", "assistant", "unknown"} \
        and not re.fullmatch(r"speaker[\s_-]*\d+", s, re.IGNORECASE)


# --- one turn ---------------------------------------------------------------------

async def process_turn(
    db: Any,
    config: dict,
    llm_client: Any,
    message_id: str,
    stats: ObservationWorkerStats,
    *,
    embedding_model: str = obs.EMBEDDING_MODEL,
) -> int:
    """Extract and write the Observations of one Message. Returns how many were
    newly created. Never raises for a bad model reply or a rejected draft; a
    storage error propagates to the worker, which logs and skips the turn.
    Idempotent: a re-run finds the same claims and only adds evidence edges."""
    cfg = (config or {}).get("observations") or {}
    stats.turns += 1
    gw = get_gateway(db)

    rows = await gw.run("observations.get_message", mid=message_id)
    if not rows:
        stats.skipped_no_message += 1
        return 0
    msg = rows[0]
    if msg.get("archived") or msg.get("role") not in obs.EVIDENCE_ROLES:
        stats.skipped_not_user += 1
        return 0
    text = msg.get("text_raw") or ""
    if len(text.split()) < MIN_WORDS or llm_client is None or not cfg.get("llm_enabled", True):
        stats.skipped_short += 1
        return 0

    speaker = msg.get("speaker")
    occurred_at = msg.get("occurred_at") or msg.get("created_at")
    entities_on = obs.observations_entities_enabled(config)
    messages = build_messages(text, speaker, occurred_at, int(cfg.get("max_turn_chars", 600)), entities=entities_on)

    stats.llm_calls += 1
    try:
        raw = await asyncio.to_thread(llm_client.chat, messages,
                                     max_tokens=ENTITY_MAX_TOKENS if entities_on else MAX_TOKENS)  # B468: off the loop
    except Exception:
        stats.llm_failed += 1
        _logger.warning("[Observations] LLM call failed for msg=%s", message_id[:8], exc_info=True)
        return 0

    proposals = parse_observations(raw)
    if proposals is None:
        stats.malformed += 1
        return 0
    if len(proposals) > MAX_PER_TURN:
        stats.truncated_proposals += len(proposals) - MAX_PER_TURN
        proposals = proposals[:MAX_PER_TURN]
    stats.proposed += len(proposals)

    named = _is_named(speaker)
    speaker_id: str | None = None
    if named:
        speaker_id = await find_existing_concept(gw, " ".join(speaker.split()))

    linking = graph_linking_enabled(config)
    link_index: dict[str, list[str]] | None = None
    writes = obs.WriteStats()
    for p in proposals:
        draft = await _draft_from_proposal(gw, p, message_id, text, speaker, named, speaker_id, occurred_at, stats)
        if draft is None:
            writes.record(obs.WriteResult("rejected", None, "malformed_proposal"))
            continue
        proposed_entity = None
        if entities_on:
            if not ent.value_in_turn(draft.predicate, draft.object_text, text):
                writes.record(obs.WriteResult("rejected", None, "value_not_in_turn"))
                continue
            proposed_entity = ent.validate_entity(p, text, stats)
        try:
            draft.embedding = await asyncio.to_thread(emb.embed, draft.text_raw, model_name=embedding_model)
        except Exception:
            draft.embedding = None   # still a valid Observation; just not vector-indexed
        result = await obs.record_observation(db, draft)
        writes.record(result)
        if proposed_entity and result.ok and result.observation_id:
            # B504: the validated entity (and kind) become Concepts before B503 links by text,
            # so the linker's index already holds them
            try:
                await ent.write_entity(gw, proposed_entity, result.observation_id, message_id, stats,
                                       embedding_model=embedding_model)
                link_index = None
            except Exception:
                _logger.warning("[ObservationEntities] entity write failed msg=%s", message_id[:8], exc_info=True)
        if linking and result.ok and result.observation_id:
            # B503: link the claim (and its turn) to the Concepts its words name
            try:
                if link_index is None:
                    link_index = await concept_index(gw)
                await link_observation_concepts(
                    gw, result.observation_id, message_id,
                    subject_text=draft.subject_text, predicate=draft.predicate,
                    object_text=draft.object_text, event_text=draft.event_text,
                    subject_id=draft.subject_id, object_id=draft.object_id, index=link_index)
            except Exception:
                _logger.warning("[GraphLinking] observation link failed msg=%s", message_id[:8], exc_info=True)

    stats.merge_write(writes)
    return writes.created


async def _draft_from_proposal(
    gw: Any, p: dict, message_id: str, text: str, speaker: str | None,
    named: bool, speaker_id: str | None, occurred_at: Any, stats: ObservationWorkerStats,
) -> obs.ObservationDraft | None:
    subject = _clean(p.get("subject"))
    predicate = (_clean(p.get("predicate")) or "").lower()
    object_text = _clean(p.get("object"))
    quote = _clean(p.get("quote"))
    if not (subject and predicate and object_text and quote):
        return None

    first_person = subject.lower() in _FIRST_PERSON
    if not first_person and named and subject.lower() == speaker.strip().lower() \
            and subject.lower() not in quote.lower() and obs._FIRST_PERSON_RE.search(quote):
        first_person = True          # the model wrote the speaker's name for "I"
    display_subject = subject
    subject_id: str | None = None
    if first_person:
        if named:
            if subject.lower() not in _FIRST_PERSON:
                subject = "I"        # keep the words as written; the id carries who
            display_subject, subject_id = speaker.strip(), speaker_id
        else:
            subject = display_subject = obs._UNKNOWN_SPEAKER_SUBJECT
    else:
        subject_id = await find_existing_concept(gw, subject)
    if subject_id:
        stats.linked_subject += 1

    object_id = None
    for cand in _object_candidates(predicate, object_text):
        object_id = await find_existing_concept(gw, cand)
        if object_id:
            stats.linked_object += 1
            break

    time_text = _clean(p.get("time"))
    if time_text and time_text.lower() in {"null", "none", "n/a", "unknown"}:
        time_text = None

    observed_at = obs._as_datetime(occurred_at)
    resolved = normalize_time(time_text, observed_at) if time_text else None
    if time_text:
        if resolved:
            stats.time_resolved += 1
        else:
            stats.time_unresolved += 1

    draft = obs.ObservationDraft(
        evidence_ref=message_id,
        evidence_text=quote,
        subject_text=subject,
        predicate=predicate,
        object_text=object_text,
        extraction_method="llm",
        confidence=_confidence(p.get("confidence")),
        rule_version=RULE_VERSION,
        polarity=(_clean(p.get("polarity")) or "asserted").lower(),
        subject_id=subject_id,
        object_id=object_id,
        time_text=time_text,
        time_start=resolved.start if resolved else None,
        time_end=resolved.end if resolved else None,
        time_precision=resolved.precision if resolved else None,
        speaker=speaker if named else None,
        observed_at=observed_at,
    )
    # Searchable sentence names the speaker, not "I".
    shown = obs.ObservationDraft(**{**draft.__dict__, "subject_text": display_subject})
    draft.text_raw = obs.render_observation_text(shown)
    return draft
