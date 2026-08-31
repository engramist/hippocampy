"""
campy/brain/hippocampus/graph/queries/arc.py — B314 named-query slice.

Holds queries migrated out of `arc_queries.py`'s inline Cypher, one card at
a time (B363's `VictoryCondition` merge, B369's `InvestigationThread`
read/create/link queries) — not a full migration of that file, just what
each card actually touched. New code in `arc_queries.py` is written as a
NamedQuery from the start rather than inline, to stay under the Cypher
ratchet (scripts/check_cypher_ratchet.py). See B314's card for the full
rationale.

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
    # B369 — arc_start_or_resume_thread (investigation-thread durability for
    # ARC_AGI's trajectory Annatar). Written as NamedQuery from the start
    # (new code, not a migration) to stay under the Cypher ratchet.
    NamedQuery(
        name="arc.fetch_investigation_thread_state",
        cypher="MATCH (t:InvestigationThread {thread_id: $tid}) RETURN t.state",
        params=("tid",),
        mutating=False,
        description="B369: O(1) primary-key lookup for arc_start_or_resume_thread's resume check.",
    ),
    NamedQuery(
        name="arc.reopen_investigation_thread",
        cypher="""
            MATCH (t:InvestigationThread {thread_id: $tid})
            SET t.state = 'exploring', t.state_updated_at = current_timestamp()
            """,
        params=("tid",),
        mutating=True,
        description="B369: reset a terminal (satisfied/exhausted) thread to a fresh 'exploring' start.",
    ),
    NamedQuery(
        name="arc.create_investigation_thread",
        cypher="""
            MERGE (t:InvestigationThread {thread_id: $tid})
            SET t.task_id = $task, t.anchor_ref = $aref, t.anchor_type = $atype,
                t.state = 'exploring', t.state_updated_at = current_timestamp(),
                t.created_at = current_timestamp()
            """,
        params=("tid", "task", "aref", "atype"),
        mutating=True,
        description="B369: create a brand-new InvestigationThread in state 'exploring'.",
    ),
    NamedQuery(
        name="arc.link_thread_to_entity_anchor",
        cypher="""
            MATCH (t:InvestigationThread {thread_id: $tid}),
                  (ge:GridEntity {task_id: $task, region_index: $eref})
            WITH t, ge LIMIT 1
            MERGE (t)-[:ANCHORED_ON_ENTITY]->(ge)
            """,
        params=("tid", "task", "eref"),
        mutating=True,
        description=(
            "B369: best-effort ANCHORED_ON_ENTITY edge -- no-ops if the GridEntity "
            "doesn't exist yet."
        ),
    ),
    NamedQuery(
        name="arc.link_thread_to_goal_anchor",
        cypher="""
            MATCH (t:InvestigationThread {thread_id: $tid}), (h:Hypothesis {id: $hid})
            WITH t, h LIMIT 1
            MERGE (t)-[:ANCHORED_ON_GOAL]->(h)
            """,
        params=("tid", "hid"),
        mutating=True,
        description=(
            "B369: best-effort ANCHORED_ON_GOAL edge -- no-ops if the Hypothesis "
            "doesn't exist yet."
        ),
    ),
    # B372 — arc_perceive_state's new disappeared_entities handling (ARC_AGI's
    # A221 Finding 2). Written as NamedQuery from the start to stay under the
    # Cypher ratchet.
    NamedQuery(
        name="arc.record_entity_disappearance",
        cypher="""
            MERGE (d:EntityDisappearance {disappearance_id: $did})
            SET d.task_id = $task, d.entity_id = $eid, d.region_index = $ridx,
                d.color_id = $cid, d.step = $step, d.centroid_row = $cr,
                d.centroid_col = $cc, d.pixel_count = $pc,
                d.created_at = current_timestamp()
            """,
        params=("did", "task", "eid", "ridx", "cid", "step", "cr", "cc", "pc"),
        mutating=True,
        description=(
            "B372: one row per observed disappearance (task_id, entity, step) -- "
            "deliberately event-style, never merged/updated per-entity, so a later "
            "reappearance doesn't overwrite an earlier disappearance's history."
        ),
    ),
    NamedQuery(
        name="arc.link_entity_disappearance",
        cypher="""
            MATCH (e:GridEntity {entity_id: $eid}), (d:EntityDisappearance {disappearance_id: $did})
            WITH e, d LIMIT 1
            MERGE (e)-[:DISAPPEARED]->(d)
            """,
        params=("eid", "did"),
        mutating=True,
        description=(
            "B372: best-effort DISAPPEARED edge -- in practice the GridEntity should "
            "always already exist (disappearance implies a prior frame observed it), "
            "but no-ops rather than errors if it somehow doesn't, matching this file's "
            "existing best-effort-edge convention."
        ),
    ),
)
