"""
campy/brain/hippocampus/provenance.py — B312 provenance + explicit supersession.

Write-side helpers for the provenance/supersession contract defined in
schema.py (PROVENANCE_TABLES, SUPERSESSION_REASONS). Two entry points:

    provenance_fields()  — build the four provenance kwargs for a CREATE.
    mark_superseded()    — flip a node to "superseded" AND record the
                            SUPERSEDES edge, in one call, so the two halves
                            of a supersession cannot drift apart.

See docs/ARCHITECTURE.md for the full contract this module implements.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from campy.brain.hippocampus.schema import SUPERSESSION_REASONS

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
) -> dict:
    """Return the four provenance params, defaulting observed_at to now(UTC).

    `observed_at` is returned as an ISO-8601 string, matching how every
    other TIMESTAMP-bearing write in this codebase feeds Kùzu (via
    `timestamp($param)` in Cypher — see capture.py / lessons.py). Callers
    pass the returned dict's values straight through as query params.
    """
    if observed_at is None:
        observed_at = datetime.now(timezone.utc)
    return {
        "source": source,
        "source_version": source_version,
        "observed_at": observed_at.isoformat(),
        "evidence_ref": evidence_ref,
    }


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
