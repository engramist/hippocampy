"""
campy/brain/hippocampus/provenance.py — B312 provenance + explicit supersession,
B313 authority (projected vs earned memory), B320 idempotent writes.

Write-side helpers for the provenance/supersession contract defined in
schema.py (PROVENANCE_TABLES, SUPERSESSION_REASONS, AUTHORITY_VALUES):

    provenance_fields()     — build the provenance kwargs for a CREATE
                               (source, source_version, observed_at,
                               evidence_ref, and — when passed — authority).
    mark_superseded()       — flip a node to "superseded" AND record the
                               DEPRECATED_BY edge, in one call, so the two
                               halves of a supersession cannot drift apart.
                               (B326: writes DEPRECATED_BY, not SUPERSEDES —
                               SUPERSEDES was retired and merged into
                               DEPRECATED_BY. See this function's docstring.)
    authority_of()          — read a row's authority, NULL-safe (B313).
    validate_authority()    — enforce that "projected" rows carry the
                               source/source_version they claim to be
                               rebuildable from (B313).
    find_stale_projections() — drift report: projected facts whose
                               source_version has fallen behind (B313).
    drop_projections()      — safe re-projection: delete only 'projected'
                               rows from one source, never 'earned' ones
                               (B313).
    content_hash()          — stable sha256 identity hash for a fact, over
                               its canonical (table, text, source,
                               workspace_id, extra) tuple (B320).
    resolve_dedupe_key()    — content_hash(), unless the caller supplies an
                               explicit idempotency_key, which wins (B320).
    find_live_by_dedupe_key() — look up a non-superseded row already
                               carrying a given dedupe key, so a retried
                               write can reuse its id instead of forking a
                               second node (B320).

See docs/ARCHITECTURE.md for the full contract this module implements.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from campy.brain.hippocampus.schema import AUTHORITY_VALUES, SUPERSESSION_REASONS

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

# Primary-key column name for every table covered by provenance +
# supersession (mirrors the PRIMARY KEY declared in schema.py's
# NODE_TABLES DDL for each of PROVENANCE_TABLES). Kept here rather than
# derived at runtime so mark_superseded() has no dependency on parsing DDL
# strings.
_PK_COLUMN: dict[str, str] = {
    "Concept": "concept_id",
    "Decision": "decision_id",
    "Constraint": "constraint_id",
    "Requirement": "requirement_id",
    "ActionItem": "action_item_id",
    "GlobalConstraint": "global_constraint_id",
    "GlobalPreference": "global_preference_id",
    "Lesson": "lesson_id",
    "Procedure": "procedure_id",
    "KnowledgeGap": "gap_id",
    "Plan": "plan_id",
    "PlanStep": "step_id",
    "Hypothesis": "id",
    "ActionFact": "fact_id",
    "ActionEffect": "effect_id",
    "VictoryCondition": "condition_id",
    "Rule": "rule_id",
    "Transition": "transition_id",
    "DocumentExtract": "extract_id",
    "WorkSummary": "summary_id",
    "WorkArtifact": "artifact_id",
    "ArcMechanic": "mechanic_id",
    "ArcActionPattern": "pattern_id",
    "ArcEffectPattern": "pattern_id",
    "ArcPrecondition": "precondition_id",
    "ArcFailureMode": "failure_mode_id",
    "ArcRecoveryPolicy": "recovery_policy_id",
    "ArcWorldModelStep": "world_model_step_id",
}


def provenance_fields(
    *,
    source: str,
    source_version: str | None = None,
    observed_at: datetime | None = None,
    evidence_ref: str | None = None,
    authority: str | None = None,
) -> dict:
    """Return the provenance params, defaulting observed_at to now(UTC).

    `observed_at` is returned as an ISO-8601 string, matching how every
    other TIMESTAMP-bearing write in this codebase feeds Kùzu (via
    `timestamp($param)` in Cypher — see capture.py / lessons.py). Callers
    pass the returned dict's values straight through as query params.

    B313: `authority` is optional and, when omitted (the default), is left
    out of the returned dict entirely — existing callers that don't pass it
    see the exact same four-key dict as before B313, and the write leaves
    the column NULL, which `authority_of()` reads back as "earned" (the
    conservative default; see schema.py's AUTHORITY_VALUES comment). Pass
    `authority` explicitly to write a real value; doing so runs it through
    `validate_authority()` first, so a "projected" row can never be created
    here without the `source`/`source_version` that makes it rebuildable.
    """
    if observed_at is None:
        observed_at = datetime.now(timezone.utc)
    fields = {
        "source": source,
        "source_version": source_version,
        "observed_at": observed_at.isoformat(),
        "evidence_ref": evidence_ref,
    }
    if authority is not None:
        validate_authority(authority, source, source_version)
        fields["authority"] = authority
    return fields


async def mark_superseded(
    db: "KuzuClient",
    *,
    table: str,
    node_id: str,
    superseded_by: str,
    reason: str,
    at: datetime | None = None,
) -> None:
    """Set the three node columns AND create the DEPRECATED_BY edge together.

    Both halves happen inside this single call so they cannot drift apart.
    If a caller ever sets `superseded_by` directly (e.g. a raw `SET` in
    some other write path) without going through this function — and thus
    without creating the matching DEPRECATED_BY edge — that is a bug: the
    stored ID becomes a dangling reference instead of traversable lineage.

    Edge direction: `(old)-[:DEPRECATED_BY]->(new)`, i.e. the node
    identified by `node_id` (the one being replaced) points at the node
    identified by `superseded_by` (the replacement). This reads "A is
    DEPRECATED_BY B" as "A is deprecated by B" — the ORIGINAL, pre-existing
    DEPRECATED_BY convention (`(older)-[:DEPRECATED_BY]->(newer)`).

    B326: this function used to write a separate `SUPERSEDES` edge in the
    opposite direction (`(new)-[:SUPERSEDES]->(old)`, "A supersedes B").
    B326 retired SUPERSEDES and merged it into DEPRECATED_BY, keeping
    DEPRECATED_BY's original arrow direction rather than flipping it —
    DEPRECATED_BY already had several independent readers/writers assuming
    `(older)->(newer)` (`apply_contradiction()` in
    `campy/brain/temporal_lobe/loop/step7_pathway.py`, the Lesson-dedup
    archival path in `campy/brain/brainstem/sweep.py`, the graph-view and
    MergeEvent-rollback endpoints in `web/server.py`, and
    `compile_card_context()` in
    `campy/brain/thalamus/tools/context_tools.py`), while SUPERSEDES had
    only this one writer and no external readers. Flipping DEPRECATED_BY
    would have silently broken all of those call sites (a wrong-direction
    Cypher pattern match returns zero rows, not an error); repointing this function
    to DEPRECATED_BY's existing direction was the smaller, safer change. See
    the DEPRECATED_BY DDL comment in schema.py and docs/ARCHITECTURE.md's
    B312 "Explicit supersession" section for the full writeup.

    Raises:
        ValueError: if `reason` is not one of SUPERSESSION_REASONS, or
            `table` is not a provenance-tracked table (see _PK_COLUMN /
            schema.PROVENANCE_TABLES).
    """
    if reason not in SUPERSESSION_REASONS:
        raise ValueError(
            f"Invalid supersession reason {reason!r}; must be one of "
            f"{sorted(SUPERSESSION_REASONS)}"
        )
    if table not in _PK_COLUMN:
        raise ValueError(
            f"{table!r} is not a provenance-tracked table; cannot mark_superseded()"
        )

    pk = _PK_COLUMN[table]
    at_iso = (at or datetime.now(timezone.utc)).isoformat()

    await db.execute_write(
        f"MATCH (n:{table} {{{pk}: $node_id}}) "
        f"SET n.superseded_by = $superseded_by, "
        f"n.superseded_at = timestamp($at), "
        f"n.supersession_reason = $reason",
        {
            "node_id": node_id,
            "superseded_by": superseded_by,
            "at": at_iso,
            "reason": reason,
        },
    )
    await db.execute_write(
        f"MATCH (old:{table} {{{pk}: $node_id}}), (new:{table} {{{pk}: $superseded_by}}) "
        f"MERGE (old)-[:DEPRECATED_BY]->(new)",
        {"superseded_by": superseded_by, "node_id": node_id},
    )


# ---------------------------------------------------------------------------
# B313 — Authority: projected vs earned memory
# ---------------------------------------------------------------------------


def authority_of(row) -> str:
    """NULL/missing authority reads as 'earned' — the safe default.

    `row` may be whatever shape the caller happens to have on hand: a full
    node dict (or any dict/row-mapping carrying an "authority" key), or a
    bare authority value (a string, or None) already pulled out of one.
    Either way, anything that isn't a recognized AUTHORITY_VALUES member —
    including None, missing, or a corrupt/unexpected string — reads back as
    "earned". That's deliberate, not merely permissive: per the card
    rationale, misreading a projected fact as earned costs an unnecessary
    backup, while misreading an earned fact as projected risks deleting
    something unrecoverable during a drop_projections() rebuild. When in
    doubt, treat it as irreplaceable.
    """
    value = row.get("authority") if isinstance(row, dict) else row
    return value if value in AUTHORITY_VALUES else "earned"


def validate_authority(
    authority: str,
    source: str | None,
    source_version: str | None,
) -> None:
    """Enforce the invariant that makes `authority='projected'` meaningful.

    A projected fact claims "you can rebuild me from `source`" — that claim
    is only checkable if both `source` and `source_version` are present, so
    both are required whenever `authority == 'projected'`. `authority ==
    'earned'` carries no such requirement (Campy itself is the only place
    an earned fact lives, so there is nothing external to point at).

    Raises:
        ValueError: if `authority` is not one of schema.AUTHORITY_VALUES,
            or if it is "projected" and `source` or `source_version` is
            NULL/empty.
    """
    if authority not in AUTHORITY_VALUES:
        raise ValueError(
            f"Invalid authority {authority!r}; must be one of {sorted(AUTHORITY_VALUES)}"
        )
    if authority == "projected":
        if not source:
            raise ValueError(
                "authority='projected' requires a non-NULL `source` — "
                "otherwise there is nothing to say this fact is rebuilt from"
            )
        if not source_version:
            raise ValueError(
                "authority='projected' requires a non-NULL `source_version` — "
                "otherwise drift against the source can never be detected"
            )


async def find_stale_projections(
    db: "KuzuClient",
    *,
    source: str,
    current_version: str,
    tables: list[str] | None = None,
) -> list[dict]:
    """Projected facts from `source` whose source_version != current_version.

    Turns projection drift from an invisible risk into a query: every row
    returned is a fact Campy is still presenting as current that the
    upstream `source` has since moved past. Rows with a NULL source_version
    are excluded (Cypher's `<>` never matches NULL) rather than reported as
    stale — `validate_authority()` should have refused to create such a row
    in the first place, so encountering one is a pre-B313 anomaly this
    function doesn't try to diagnose, not a drift signal.

    Returns one dict per stale row: `{"table", "node_id", "source",
    "source_version"}`. Empty list when every projected fact from `source`
    is already current (or none exist).
    """
    target_tables = tables if tables is not None else list(_PK_COLUMN.keys())
    stale: list[dict] = []
    for table in target_tables:
        pk = _PK_COLUMN.get(table)
        if not pk:
            continue
        rows = await db.execute_read(
            f"MATCH (n:{table}) "
            f"WHERE n.authority = 'projected' AND n.source = $source "
            f"AND n.source_version IS NOT NULL AND n.source_version <> $current_version "
            f"RETURN n.{pk} AS node_id, n.source AS source, n.source_version AS source_version",
            {"source": source, "current_version": current_version},
        )
        for row in rows:
            stale.append({"table": table, **row})
    return stale


async def drop_projections(
    db: "KuzuClient",
    *,
    source: str,
    dry_run: bool = True,
    tables: list[str] | None = None,
) -> dict:
    """Delete all projected facts from one source so it can be re-projected.

    This is the operation that makes re-projection safe, and the single
    most dangerous function in this module — a filter mistake here deletes
    irreplaceable earned memory, not a rebuildable mirror. Two safeguards:

      1. The DELETE (and the count that drives it) always filters on
         `authority = 'projected' AND source = $source` together, never on
         `source` alone — an earned row that happens to share a `source`
         string is never a deletion candidate.
      2. `dry_run` defaults to True. Callers must opt in to `dry_run=False`
         to actually delete anything.

    Returns `{"deleted": N, "skipped_earned": M}` — `skipped_earned` is the
    count of rows the filter *excluded* despite sharing `source`, so a
    caller can see the safeguard actually did something rather than just
    trusting it silently.
    """
    target_tables = tables if tables is not None else list(_PK_COLUMN.keys())
    deleted = 0
    skipped_earned = 0
    for table in target_tables:
        counts = await db.execute_read(
            f"MATCH (n:{table}) WHERE n.source = $source "
            f"RETURN n.authority AS authority, count(*) AS c",
            {"source": source},
        )
        for row in counts:
            count = int(row.get("c") or 0)
            if authority_of(row) == "projected":
                deleted += count
            else:
                skipped_earned += count

        if not dry_run:
            await db.execute_write(
                f"MATCH (n:{table}) "
                f"WHERE n.authority = 'projected' AND n.source = $source "
                f"DETACH DELETE n",
                {"source": source},
            )

    return {"deleted": deleted, "skipped_earned": skipped_earned}


# ---------------------------------------------------------------------------
# B320 — Idempotent writes: content-addressed deduplication
# ---------------------------------------------------------------------------

# Bump this if the canonicalization rules below ever change. It is folded
# into the hashed payload itself (see content_hash()), so a version bump
# automatically re-partitions every future dedup decision instead of
# silently colliding old and new hashes for what canonicalization now
# treats as different text. Existing NULL content_hash rows (pre-B320) are
# unaffected either way — they never match anything (see
# find_live_by_dedupe_key()).
CONTENT_HASH_VERSION = 1


def _normalize_text_for_hash(text: str) -> str:
    """Canonicalize text for content_hash() — the exact rules the card
    specifies, and nothing more:

      1. Unicode-normalize to NFC (composed form) so the same visible
         string always hashes the same regardless of how the client's
         input method / OS produced it (precomposed vs. combining-mark
         sequences).
      2. Strip leading/trailing whitespace and collapse internal runs of
         whitespace (any run of \\s, including newlines/tabs) to a single
         ASCII space, via `str.split()` + `" ".join(...)`.

    Deliberately does NOT lowercase: case is semantically load-bearing in
    code, identifiers, and proper nouns, and folding it would merge facts
    that a caller means to keep distinct (the card is explicit on this).
    """
    return " ".join(unicodedata.normalize("NFC", text).split())


def content_hash(
    *,
    table: str,
    text: str,
    source: str,
    workspace_id: str = "local",
    extra: dict | None = None,
) -> str:
    """Stable identity hash for a fact. Same inputs -> same hash, forever.

    This is the floor for retry-safety: a client that does nothing special
    still gets exact-content dedup, because re-issuing the same capture
    (same text, same source, same workspace) always yields the same hash,
    regardless of when the retry happens or what fresh uuid4/timestamp the
    retry would otherwise have minted.

    Included in the hash (these define "the same fact"):
      - `table`     — a Concept and a Lesson with identical text are not
                      the same fact; the table name disambiguates them.
      - `text`      — normalized per `_normalize_text_for_hash()`: NFC,
                      whitespace-collapsed, case-PRESERVED.
      - `source`    — the B312 provenance source string (e.g.
                      "agent:claude-code", "user:direct"). The same text
                      asserted by two different sources is two different
                      facts (one may be wrong, or they may agree — either
                      way that's a fact about the world Campy should not
                      erase by merging).
      - `workspace_id` — the same fact learned in two workspaces stays two
                      distinct facts: different owners, different
                      lifecycles, and (per B316) different databases
                      entirely. Defaults to "local" for the common
                      single-workspace case.
      - `extra`     — caller-supplied discriminators (e.g. a `domain` or
                      `lesson_type` the caller considers identity-bearing
                      for a particular table). Canonicalized as
                      `json.dumps(extra, sort_keys=True, separators=(',',
                      ':'))` so key order never affects the hash. Omit or
                      pass `None`/`{}` when a table has no extra
                      discriminators.
      - `CONTENT_HASH_VERSION` — a version tag, so a future change to these
                      rules cannot silently re-partition old hashes as if
                      nothing changed (bump the constant instead).

    Deliberately EXCLUDED (anything that legitimately varies between a call
    and its retry would make the hash useless — a retry producing a
    *different* hash is precisely the bug this card exists to fix):
    `observed_at`, `created_at`, `session_id`, `message_id`, embeddings,
    `confidence`, and every uuid.

    Returns a 64-character lowercase hex sha256 digest. Stable across
    process restarts and across calls separated in time — this function is
    pure (no clock, no randomness, no I/O), so the same inputs always
    produce the same digest; see
    tests/test_idempotent_writes.py::test_content_hash_hardcoded_digest for
    the frozen-digest regression test the card requires.
    """
    payload = {
        "v": CONTENT_HASH_VERSION,
        "table": table,
        "text": _normalize_text_for_hash(text),
        "source": source,
        "workspace_id": workspace_id,
        "extra": extra or {},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def resolve_dedupe_key(
    *,
    table: str,
    text: str,
    source: str,
    workspace_id: str = "local",
    extra: dict | None = None,
    idempotency_key: str | None = None,
) -> str:
    """B320 Task 4: the actual key a write helper dedupes on.

    When the caller supplies `idempotency_key` (a well-behaved client that
    can guarantee exact-once semantics for a specific logical write, even
    across retries whose text differs slightly — content hashing alone
    cannot catch that), it *replaces* content_hash() entirely as the dedup
    key. Content hashing remains the floor for callers that pass nothing.

    The returned key is prefixed `idemp:` when it comes from an explicit
    idempotency_key, keeping it in a namespace disjoint from
    content_hash()'s raw 64-hex-char sha256 digests — a caller-chosen
    idempotency_key is under no obligation to look like a hash, and this
    guarantees it can never accidentally collide with one computed for
    unrelated content.
    """
    if idempotency_key:
        return f"idemp:{idempotency_key.strip()}"
    return content_hash(
        table=table, text=text, source=source, workspace_id=workspace_id, extra=extra
    )


async def find_live_by_dedupe_key(
    db: "KuzuClient",
    *,
    table: str,
    pk_column: str,
    dedupe_key: str,
    touch_last_accessed: bool = False,
    now_iso: str | None = None,
) -> str | None:
    """Look up a live (non-superseded) row in `table` whose `content_hash`
    column equals `dedupe_key`. Returns its primary key, or `None` if no
    such row exists — the caller should then proceed with a normal insert.

    Two things make this NULL-safe and supersession-safe by construction,
    not by convention:

      - `n.content_hash = $key` — Cypher/Kùzu's `=` against a NULL operand
        is never true, so every pre-B320 row (content_hash NULL) is
        excluded automatically. NULL never matches anything, which is
        exactly this card's "never backfilled, never matched" requirement.
      - `n.superseded_by IS NULL` — a superseded row is explicitly excluded
        so that re-capturing content identical to a fact that has since
        been superseded (B312) creates a fresh live node rather than
        resurrecting the dead one.

    `touch_last_accessed`: B320 Task 3's reinforcement judgement call is to
    default to NOT bumping `pathway_strength` on a dedup hit (under-
    counting reinforcement is recoverable; inflating it from a network
    retry poisons ranking in a way nothing later can undo — see this
    module's module docstring / docs/ARCHITECTURE.md for the full
    reasoning). The one thing this function *will* update on a hit, if the
    caller opts in via `touch_last_accessed=True`, is `last_accessed_at` —
    but only when the table actually has that column (`Concept` does; most
    of the Tier 1 tables this card touches — `Lesson`, `Plan`, `PlanStep`
    — do not, so callers for those tables should leave this False). This
    function does not try to detect the column itself; passing
    `touch_last_accessed=True` for a table without it would raise from
    Kùzu, so the caller must know its own table's schema.
    """
    rows = await db.execute_read(
        f"MATCH (n:{table}) "
        f"WHERE n.content_hash = $key AND n.superseded_by IS NULL "
        f"RETURN n.{pk_column} AS id LIMIT 1",
        {"key": dedupe_key},
    )
    if not rows:
        return None
    existing_id = rows[0].get("id")
    if touch_last_accessed and existing_id:
        await db.execute_write(
            f"MATCH (n:{table} {{{pk_column}: $id}}) "
            f"SET n.last_accessed_at = timestamp($now)",
            {"id": existing_id, "now": now_iso or datetime.now(timezone.utc).isoformat()},
        )
    return existing_id
