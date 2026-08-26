"""
campy/brain/hippocampus/graph/queries/arc.py — B314 named-query slice.

Currently holds only the query B363 needed to migrate: `arc_queries.py`'s
`VictoryCondition` write grew from a one-line bare `MATCH` into a `MERGE`,
which tripped the Cypher ratchet (scripts/check_cypher_ratchet.py) on line
count. The rest of `arc_queries.py`'s inline Cypher is untouched — this is
not a full migration of that file, just the one query this card's fix
actually changed. See B314's card for the full rationale.

Naming convention: `arc.<verb>_<subject>`.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

ARC_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="arc.merge_victory_condition_confidence",
        cypher="""
            MERGE (vc:VictoryCondition {condition_id: $gid})
            SET vc.task_id = $tid, vc.confidence = $conf,
                vc.created_at = coalesce(vc.created_at, current_timestamp()),
                vc.last_updated = current_timestamp()
            """,
        params=("gid", "tid", "conf"),
        mutating=True,
        description=(
            "B363: create-or-update a VictoryCondition's confidence, keyed on "
            "condition_id. Previously a bare MATCH silently no-op'd against a "
            "condition_id with no existing node."
        ),
    ),
)
