"""
campy/brain/hippocampus/observations.py -- B472 Phase 3a: the Observation write API.

An Observation is a typed, source-grounded claim a speaker made in a turn
("my sister is a nurse"). This module is the ONLY writer of Observation
nodes. It enforces the grounding rule in code, not by convention: a draft
whose supporting quote is not a verbatim span of its evidence Message is
rejected, so no row can exist without a quote ("no quote, no row").

Design: backlog/plans/B-472-phase3-observations.md sections 3-4. Phase 3a
ships the table, this API and its queries, and nothing that calls them: no
producer, no worker, no retrieval use. `[observations] enabled` (default
false) is read by `observations_enabled()` for the later phases.

Everything goes through `GraphGateway` NamedQueries
(`graph/queries/observations.py`); there is no direct database access here.
KuzuDB / the graph is the single source of truth: nothing is cached.

Idempotency
-----------
A draft whose (subject, predicate, object, time, polarity) matches a live
Observation does not create a second row. It adds an `EVIDENCED_BY` edge to
the existing row (a no-op when that Message already supports it) and bumps
`last_accessed_at`, and the result is `status="duplicate"`. Re-recording the
same draft against the same Message is therefore a no-op, and a second,
independent supporting turn is recorded as evidence rather than as a
duplicate claim. The create is not atomic with the lookup: the Phase 3b
worker is the single writer, so no lock is taken here. A crash between the
node create and its edges is self-healing, because the retry finds the node
by its content hash and adds the missing edges.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from campy.brain.hippocampus.graph.gateway import get_gateway
from campy.brain.hippocampus.provenance import content_hash

# --- the v1 vocabularies (design section 3.3; a predicate is added by review) ---

PREDICATES = frozenset({
    "did", "has_attribute", "is_a", "located_in", "owns",
    "relates_to", "prefers", "plans", "changed_to",
})
POLARITIES = frozenset({"asserted", "negated", "hypothetical", "planned"})
TIME_PRECISIONS = frozenset({"day", "week", "month", "year", "unknown"})
# 'deterministic' is reserved for Phase 4 rules.
EXTRACTION_METHODS = frozenset({"pattern", "llm"})
# Decision 3: assistant turns are not evidence in Phase 3 (they are capped and
# untrusted, ISSUE-024; B471 covers questions about the assistant's own words).
EVIDENCE_ROLES = frozenset({"user"})

MIN_CONFIDENCE = 0.60          # below this: not written
LOW_CONFIDENCE_CEILING = 0.90  # 0.60-0.90 inclusive -> confidence_low
MAX_EVIDENCE_CHARS = 400
MAX_OBJECT_CHARS = 200
EMBEDDING_DIM = 384
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

REJECT_REASONS = (
    "evidence_message_missing",
    "evidence_message_archived",
    "evidence_not_user_turn",
    "quote_not_found",
    "bad_predicate",
    "bad_polarity",
    "bad_time_precision",
    "bad_extraction_method",
    "low_confidence",
    "subject_not_grounded",
    "empty_object",
    "evidence_too_long",
    "object_too_long",
    "bad_time_range",
    "bad_embedding",
    "subject_concept_missing",
    "object_concept_missing",
)

_FIRST_PERSON = frozenset({"i", "me", "my", "myself", "mine"})
_FIRST_PERSON_RE = re.compile(r"(?<!\w)(i|i'm|i've|i'd|i'll|me|my|mine|myself)(?!\w)", re.IGNORECASE)
_UNKNOWN_SPEAKER_SUBJECT = "the user"

_QUOTE_TABLE = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x2032: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"', 0x2033: '"',
}


def observations_enabled(config: dict | None) -> bool:
    """`[observations] enabled` (default false: Phase 3 ships disabled until a
    reader exists). Nothing in 3a consults this to do work; the 3b worker will."""
    return bool(((config or {}).get("observations") or {}).get("enabled", False))


def observations_retrieval_enabled(config: dict | None) -> bool:
    """`[observations] retrieval` (default false; env `CAMPY_OBSERVATIONS_RETRIEVAL`):
    the bundle's semantic section is fed from Observations (B472 Phase 3c).
    Independent of `enabled`, which gates only the writer: a store built with
    the worker on can be read with this on or off."""
    return bool(((config or {}).get("observations") or {}).get("retrieval", False))


def observation_limit(config: dict | None, default: int = 8) -> int:
    """`[observations] observation_limit`: most Observations the semantic section carries."""
    try:
        return int(((config or {}).get("observations") or {}).get("observation_limit", default))
    except (TypeError, ValueError):
        return default


# --- types ------------------------------------------------------------------------

@dataclass
class ObservationDraft:
    """What a producer proposes. Offsets are not accepted: they are recomputed
    from the quote's position in the Message (never trusted from the producer)."""

    evidence_ref: str                   # id of the supporting Message (required)
    evidence_text: str                  # the verbatim supporting quote (required)
    subject_text: str
    predicate: str
    object_text: str
    extraction_method: str              # 'pattern' | 'llm'
    confidence: float
    rule_version: str | None = None     # e.g. 'pattern-1', 'llm-1'
    polarity: str = "asserted"
    subject_id: str | None = None       # resolved Concept id, if any
    object_id: str | None = None        # resolved Concept id, if the object is an entity
    event_text: str | None = None       # short normalized description, for 'did'
    time_text: str | None = None
    time_start: datetime | None = None
    time_end: datetime | None = None
    time_precision: str | None = None
    speaker: str | None = None          # defaults to the Message's speaker
    observed_at: datetime | None = None  # defaults to the Message's occurred_at / created_at
    text_raw: str | None = None         # defaults to render_observation_text(draft)
    embedding: list[float] | None = None


@dataclass(frozen=True)
class WriteResult:
    status: str                         # 'created' | 'duplicate' | 'rejected'
    observation_id: str | None = None
    reason: str | None = None           # one of REJECT_REASONS when rejected

    @property
    def ok(self) -> bool:
        return self.status != "rejected"


@dataclass
class WriteStats:
    """Counts a producer accumulates across drafts (created / duplicate /
    rejected, with rejections broken out by reason)."""

    created: int = 0
    duplicate: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    def record(self, result: WriteResult) -> WriteResult:
        if result.status == "created":
            self.created += 1
        elif result.status == "duplicate":
            self.duplicate += 1
        else:
            self.rejected[result.reason or "unknown"] = self.rejected.get(result.reason or "unknown", 0) + 1
        return result


# --- grounding --------------------------------------------------------------------

def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to one space and unify curly quotes, returning the
    normalized text and, for each normalized char, its index in the original."""
    out: list[str] = []
    index: list[int] = []
    in_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_space:
                out.append(" ")
                index.append(i)
            in_space = True
            continue
        in_space = False
        out.append(_QUOTE_TABLE.get(ord(ch), ch))
        index.append(i)
    return "".join(out), index


def locate_quote(message_text: str, quote: str) -> tuple[int, int] | None:
    """Offsets `(start, end)` such that `message_text[start:end]` is `quote`
    modulo whitespace and quote-mark differences, or None when the quote is not
    a verbatim span. Matching is case-sensitive; the first occurrence wins."""
    norm_msg, index = _normalize_with_map(message_text)
    norm_quote, _ = _normalize_with_map(quote)
    norm_quote = norm_quote.strip()
    if not norm_quote:
        return None
    pos = norm_msg.find(norm_quote)
    if pos < 0:
        return None
    start = index[pos]
    last = index[pos + len(norm_quote) - 1]
    return start, last + 1


def _subject_grounded(subject: str, quote: str, *, user_turn: bool) -> bool:
    subj = " ".join(subject.split())
    if not subj:
        return False
    low = subj.lower()
    if re.search(r"(?<!\w)" + re.escape(subj) + r"(?!\w)", quote, re.IGNORECASE):
        return True
    if user_turn and low in _FIRST_PERSON:
        return True
    # No named speaker: a first-person claim is stored about "the user", which
    # still needs a first-person cue in the quote.
    return user_turn and low == _UNKNOWN_SPEAKER_SUBJECT and bool(_FIRST_PERSON_RE.search(quote))


def render_observation_text(draft: ObservationDraft) -> str:
    """The sentence used for search and embedding:
    'Caroline - did - attended an LGBTQ support group (7 May 2023)'."""
    obj = draft.event_text or draft.object_text
    text = f"{draft.subject_text} - {draft.predicate} - {obj}"
    if draft.time_text:
        text += f" ({draft.time_text})"
    return text


def _as_datetime(value: Any) -> datetime | None:
    """A Message's occurred_at / created_at can come back as an ISO string (the
    capture path writes them as plain literals); Observation timestamps are typed."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        text = str(value)
        return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None


def _norm_key(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def observation_content_hash(draft: ObservationDraft) -> str:
    """Identity of the claim, independent of which Message or extractor asserts
    it. Polarity is part of it: 'I like hiking' and 'I don't like hiking' are two
    claims, not one."""
    subject = draft.subject_id or _norm_key(draft.subject_text)
    obj = draft.object_id or _norm_key(draft.object_text)
    text = "|".join([subject, draft.predicate, obj, _norm_key(draft.time_text), draft.polarity])
    return content_hash(table="Observation", text=text, source="observation")


# --- the write API ----------------------------------------------------------------

def _reject(reason: str) -> WriteResult:
    return WriteResult("rejected", None, reason)


def _validate_shape(draft: ObservationDraft) -> str | None:
    if draft.predicate not in PREDICATES:
        return "bad_predicate"
    if draft.polarity not in POLARITIES:
        return "bad_polarity"
    if draft.time_precision is not None and draft.time_precision not in TIME_PRECISIONS:
        return "bad_time_precision"
    if draft.extraction_method not in EXTRACTION_METHODS:
        return "bad_extraction_method"
    if draft.confidence is None or draft.confidence < MIN_CONFIDENCE:
        return "low_confidence"
    if not (draft.object_text or "").strip():
        return "empty_object"
    if len(draft.object_text) > MAX_OBJECT_CHARS:
        return "object_too_long"
    if len((draft.evidence_text or "").strip()) > MAX_EVIDENCE_CHARS:
        return "evidence_too_long"
    if draft.time_start and draft.time_end and draft.time_end < draft.time_start:
        return "bad_time_range"
    if draft.embedding is not None and len(draft.embedding) != EMBEDDING_DIM:
        return "bad_embedding"
    return None


async def _concept_exists(gw: Any, concept_id: str) -> bool:
    rows = await gw.run("observations.get_concept", cid=concept_id)
    return bool(rows)


async def record_observation(
    db: Any,
    draft: ObservationDraft,
    *,
    allowed_roles: frozenset[str] = EVIDENCE_ROLES,
) -> WriteResult:
    """Validate `draft` against its evidence Message and write it.

    Rejections (a `WriteResult` with `status="rejected"` and a reason from
    `REJECT_REASONS`; nothing is written):
      - the draft's shape: predicate / polarity / time precision / method not in
        their sets, confidence below 0.60, empty or over-long object, over-long
        quote, time_end before time_start, an embedding that is not 384 floats;
      - the evidence Message is missing, archived, or not a user turn;
      - the quote is not a verbatim span of the Message (whitespace and quote
        marks aside);
      - the subject is neither in the quote nor a first-person word on a user turn;
      - subject_id / object_id name a Concept that does not exist.

    A draft matching a live Observation adds evidence to it instead (see the
    module docstring) and returns `status="duplicate"`.
    """
    reason = _validate_shape(draft)
    if reason:
        return _reject(reason)

    gw = get_gateway(db)
    rows = await gw.run("observations.get_message", mid=draft.evidence_ref)
    if not rows:
        return _reject("evidence_message_missing")
    msg = rows[0]
    if msg.get("archived"):
        return _reject("evidence_message_archived")
    role = msg.get("role")
    if role not in allowed_roles:
        return _reject("evidence_not_user_turn")

    span = locate_quote(msg.get("text_raw") or "", draft.evidence_text or "")
    if span is None:
        return _reject("quote_not_found")
    start, end = span
    quote = (msg.get("text_raw") or "")[start:end]
    if len(quote) > MAX_EVIDENCE_CHARS:
        return _reject("evidence_too_long")
    if not _subject_grounded(draft.subject_text, quote, user_turn=(role == "user")):
        return _reject("subject_not_grounded")

    if draft.subject_id and not await _concept_exists(gw, draft.subject_id):
        return _reject("subject_concept_missing")
    if draft.object_id and not await _concept_exists(gw, draft.object_id):
        return _reject("object_concept_missing")

    now = datetime.now(timezone.utc)
    key = observation_content_hash(draft)
    existing = await gw.run("observations.find_live_by_hash", key=key)
    if existing:
        oid = existing[0]["observation_id"]
        await gw.run("observations.link_evidenced_by", oid=oid, mid=draft.evidence_ref)
        await gw.run("observations.touch_observation", oid=oid, now=now)
        await _link_concepts(gw, oid, draft)
        return WriteResult("duplicate", oid)

    oid = str(uuid.uuid4())
    text_raw = draft.text_raw or render_observation_text(draft)
    await gw.run(
        "observations.create_observation",
        observation_id=oid,
        subject_text=draft.subject_text.strip(),
        subject_id=draft.subject_id,
        predicate=draft.predicate,
        object_text=draft.object_text.strip(),
        object_id=draft.object_id,
        event_text=draft.event_text,
        time_text=draft.time_text,
        time_start=draft.time_start,
        time_end=draft.time_end,
        time_precision=draft.time_precision or ("unknown" if draft.time_text else None),
        speaker=draft.speaker or msg.get("speaker"),
        polarity=draft.polarity,
        confidence=float(draft.confidence),
        confidence_low=draft.confidence <= LOW_CONFIDENCE_CEILING,
        extraction_method=draft.extraction_method,
        rule_version=draft.rule_version,
        evidence_start=start,
        evidence_end=end,
        evidence_text=quote,
        text_raw=text_raw,
        embedding=draft.embedding,
        embedding_model=EMBEDDING_MODEL if draft.embedding is not None else None,
        embedding_dim=EMBEDDING_DIM if draft.embedding is not None else None,
        source=f"loop:observation:{draft.extraction_method}",
        observed_at=_as_datetime(draft.observed_at or msg.get("occurred_at") or msg.get("created_at")),
        evidence_ref=draft.evidence_ref,
        content_hash=key,
        now=now,
    )
    await gw.run("observations.link_evidenced_by", oid=oid, mid=draft.evidence_ref)
    await _link_concepts(gw, oid, draft)
    return WriteResult("created", oid)


async def _link_concepts(gw: Any, oid: str, draft: ObservationDraft) -> None:
    for cid in dict.fromkeys(c for c in (draft.subject_id, draft.object_id) if c):
        await gw.run("observations.link_about_concept", oid=oid, cid=cid)


# --- reads --------------------------------------------------------------------------

async def get_observation(db: Any, observation_id: str) -> dict | None:
    rows = await get_gateway(db).run("observations.get_observation", oid=observation_id)
    return dict(rows[0]) if rows else None


async def observations_for_message(db: Any, message_id: str) -> list[dict]:
    """Live Observations a Message supports, in turn order."""
    rows = await get_gateway(db).run("observations.for_message", mid=message_id)
    return [dict(r) for r in rows]


async def observations_for_concept(db: Any, concept_id: str) -> list[dict]:
    """Live Observations linked to a Concept as subject or entity object."""
    rows = await get_gateway(db).run("observations.for_concept", cid=concept_id)
    return [dict(r) for r in rows]


async def evidence_message_ids(db: Any, observation_id: str) -> list[str]:
    """Every Message that supports an Observation (the first is its evidence_ref)."""
    rows = await get_gateway(db).run("observations.evidence_messages", oid=observation_id)
    return [r["message_id"] for r in rows]
