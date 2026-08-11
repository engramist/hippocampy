"""
campy/brain/hippocampus/provenance.py — B312 provenance + explicit supersession,
B313 authority (projected vs earned memory).

Write-side helpers for the provenance/supersession contract defined in
schema.py (PROVENANCE_TABLES, SUPERSESSION_REASONS, AUTHORITY_VALUES):

    provenance_fields()     — build the provenance kwargs for a CREATE
                               (source, source_version, observed_at,
                               evidence_ref, and — when passed — authority).
    mark_superseded()       — flip a node to "superseded" AND record the
                               SUPERSEDES edge, in one call, so the two
                               halves of a supersession cannot drift apart.
    authority_of()          — read a row's authority, NULL-safe (B313).
    validate_authority()    — enforce that "projected" rows carry the
                               source/source_version they claim to be
                               rebuildable from (B313).
    find_stale_projections() — drift report: projected facts whose
                               source_version has fallen behind (B313).
    drop_projections()      — safe re-projection: delete only 'projected'
                               rows from one source, never 'earned' ones
                               (B313).

See docs/ARCHITECTURE.md for the full contract this module implements.
"""

from __future__ import annotations

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
    """Set the three node columns AND create the SUPERSEDES edge together.

    Both halves happen inside this single call so they cannot drift apart.
    If a caller ever sets `superseded_by` directly (e.g. a raw `SET` in
    some other write path) without going through this function — and thus
    without creating the matching SUPERSEDES edge — that is a bug: the
    stored ID becomes a dangling reference instead of traversable lineage.

    Edge direction: `(new)-[:SUPERSEDES]->(old)`, i.e. the node identified
    by `superseded_by` (the replacement) points at the node identified by
    `node_id` (the one being replaced). This reads "A SUPERSEDES B" as "A
    replaces B", which is the mirror image of the pre-existing
    DEPRECATED_BY table's convention (`(older)-[:DEPRECATED_BY]->(newer)`
    — "A is deprecated by B"). See the SUPERSEDES comment in schema.py;
    B323 is expected to reconcile the two mechanisms.

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
        f"MATCH (new:{table} {{{pk}: $superseded_by}}), (old:{table} {{{pk}: $node_id}}) "
        f"MERGE (new)-[:SUPERSEDES]->(old)",
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
