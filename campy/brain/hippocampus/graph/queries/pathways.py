"""campy/brain/hippocampus/graph/queries/pathways.py — Named queries for Step 7 pathway updates and Hebbian learning."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

PATHWAY_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="pathways.get_concept_pathway_state",
        cypher="""
            MATCH (c:Concept {concept_id: $id})
            RETURN c.pathway_strength, c.last_accessed_at, c.created_at
            """,
        params=("id",),
        mutating=False,
        description="Fetch Concept pathway_strength and access timestamps for additive update.",
    ),
    NamedQuery(
        name="pathways.update_concept_pathway_additive",
        cypher="""
            MATCH (c:Concept {concept_id: $id})
            SET c.pathway_strength = c.pathway_strength + $increment,
                c.last_accessed_at = timestamp($now)
            """,
        params=("id", "increment", "now"),
        mutating=True,
        description="Increment Concept pathway_strength and update last_accessed_at.",
    ),
    NamedQuery(
        name="pathways.get_concept_strength",
        cypher="MATCH (c:Concept {concept_id: $id}) RETURN c.pathway_strength",
        params=("id",),
        mutating=False,
        description="Fetch Concept pathway_strength.",
    ),
    NamedQuery(
        name="pathways.apply_contradiction",
        cypher="""
            MATCH (old:Concept {concept_id: $old_id}),
                  (new:Concept {concept_id: $new_id})
            SET old.archived = true
            MERGE (old)-[:DEPRECATED_BY]->(new)
            CREATE (me:MergeEvent {
                merge_event_id:        $merge_event_id,
                pre_pathway_strength:  $pre_strength,
                delta_pathway_strength: 0.0,
                alias_added:           [],
                metadata_patch:        $patch,
                created_at:            timestamp($now)
            })
            MERGE (me)-[:UPDATES_PATHWAY]->(new)
            """,
        params=("old_id", "new_id", "merge_event_id", "pre_strength", "patch", "now"),
        mutating=True,
        description="Apply contradiction resolution: archive old, deprecate, and record MergeEvent.",
    ),
    NamedQuery(
        name="pathways.link_message_merge_event",
        cypher="""
            MATCH (m:Message {message_id: $mid}),
                  (me:MergeEvent {merge_event_id: $meid})
            MERGE (m)-[:TRIGGERED]->(me)
            """,
        params=("mid", "meid"),
        mutating=True,
        description="Link Message to MergeEvent via TRIGGERED.",
    ),
    NamedQuery(
        name="pathways.unwind_co_occurs_with",
        cypher="""
            UNWIND $pairs AS pair
            MATCH (a:Concept {concept_id: pair.a_id}),
                  (b:Concept {concept_id: pair.b_id})
            MERGE (a)-[r:CO_OCCURS_WITH]->(b)
            ON CREATE SET r.count     = 1,
                          r.strength  = $strength
            ON MATCH SET  r.count    = r.count + 1,
                          r.strength = (r.strength + $strength) / 2.0
            """,
        params=("pairs", "strength"),
        mutating=True,
        description="Batch upsert CO_OCCURS_WITH edges for concept pairs.",
    ),
    NamedQuery(
        name="pathways.find_low_confidence_hops",
        cypher="""
            MATCH (anchor:Concept {concept_id: $id})
            MATCH (anchor)-[*1..2]-(neighbor:Concept)
            WHERE neighbor.confidence_low = true
              AND neighbor.archived = false
              AND neighbor.concept_id <> $id
            RETURN DISTINCT neighbor.concept_id,
                   neighbor.confidence,
                   neighbor.pathway_strength
            """,
        params=("id",),
        mutating=False,
        description="Find confidence_low Concepts within 1-2 hops of anchor.",
    ),
    NamedQuery(
        name="pathways.count_high_confidence_neighbors",
        cypher="""
            MATCH (c:Concept {concept_id: $cid})-[]-(n:Concept)
            WHERE n.archived = false AND n.confidence >= 0.60
            RETURN count(n) AS neighbor_count,
                   avg(n.pathway_strength) AS avg_strength
            """,
        params=("cid",),
        mutating=False,
        description="Count active high-confidence neighbors for density boost.",
    ),
    NamedQuery(
        name="pathways.update_concept_confidence",
        cypher="""
            MATCH (c:Concept {concept_id: $cid})
            SET c.confidence = $conf,
                c.confidence_low = $low
            """,
        params=("cid", "conf", "low"),
        mutating=True,
        description="Update Concept confidence and confidence_low flag.",
    ),
    NamedQuery(
        name="pathways.get_previous_decision",
        cypher="""
            MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid})
            WHERE d.decision_id <> $did
            RETURN d.decision_id, d.created_at
            ORDER BY d.created_at DESC LIMIT 1
            """,
        params=("sid", "did"),
        mutating=False,
        description="Find most recent previous Decision in session.",
    ),
    NamedQuery(
        name="pathways.count_prior_decisions",
        cypher="""
            MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid})
            WHERE d.decision_id <> $did RETURN count(d)
            """,
        params=("sid", "did"),
        mutating=False,
        description="Count prior decisions in session to compute step_number.",
    ),
    NamedQuery(
        name="pathways.merge_decision_chain",
        cypher="""
            MATCH (p:Decision {decision_id: $prev}), (c:Decision {decision_id: $curr})
            MERGE (p)-[r:DECISION_CHAIN]->(c)
            ON CREATE SET r.session_id = $sid, r.step_number = $step
            ON MATCH SET r.step_number = $step
            """,
        params=("prev", "curr", "sid", "step"),
        mutating=True,
        description="Link consecutive Decisions via DECISION_CHAIN.",
    ),
)
