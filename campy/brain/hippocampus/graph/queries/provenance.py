"""campy/brain/hippocampus/graph/queries/provenance.py — Named queries for provenance & supersession."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

PROVENANCE_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="provenance.mark_superseded_concept",
        cypher="""
            MATCH (n:Concept {concept_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Concept node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_concept",
        cypher="""
            MATCH (old:Concept {concept_id: $node_id}), (new:Concept {concept_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Concept to new Concept with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_concept",
        cypher="""
            MATCH (n:Concept)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.concept_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Concept nodes.",
    ),
    NamedQuery(
        name="provenance.counts_concept",
        cypher="""
            MATCH (n:Concept) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Concept nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_concept",
        cypher="""
            MATCH (n:Concept)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Concept nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_concept",
        cypher="""
            MATCH (n:Concept)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.concept_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Concept by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_concept",
        cypher="""
            MATCH (n:Concept {concept_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Concept.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_decision",
        cypher="""
            MATCH (n:Decision {decision_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Decision node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_decision",
        cypher="""
            MATCH (old:Decision {decision_id: $node_id}), (new:Decision {decision_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Decision to new Decision with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_decision",
        cypher="""
            MATCH (n:Decision)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.decision_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Decision nodes.",
    ),
    NamedQuery(
        name="provenance.counts_decision",
        cypher="""
            MATCH (n:Decision) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Decision nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_decision",
        cypher="""
            MATCH (n:Decision)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Decision nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_decision",
        cypher="""
            MATCH (n:Decision)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.decision_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Decision by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_decision",
        cypher="""
            MATCH (n:Decision {decision_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Decision.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_constraint",
        cypher="""
            MATCH (n:Constraint {constraint_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Constraint node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_constraint",
        cypher="""
            MATCH (old:Constraint {constraint_id: $node_id}), (new:Constraint {constraint_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Constraint to new Constraint with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_constraint",
        cypher="""
            MATCH (n:Constraint)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.constraint_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Constraint nodes.",
    ),
    NamedQuery(
        name="provenance.counts_constraint",
        cypher="""
            MATCH (n:Constraint) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Constraint nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_constraint",
        cypher="""
            MATCH (n:Constraint)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Constraint nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_constraint",
        cypher="""
            MATCH (n:Constraint)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.constraint_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Constraint by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_constraint",
        cypher="""
            MATCH (n:Constraint {constraint_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Constraint.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_requirement",
        cypher="""
            MATCH (n:Requirement {requirement_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Requirement node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_requirement",
        cypher="""
            MATCH (old:Requirement {requirement_id: $node_id}), (new:Requirement {requirement_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Requirement to new Requirement with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_requirement",
        cypher="""
            MATCH (n:Requirement)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.requirement_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Requirement nodes.",
    ),
    NamedQuery(
        name="provenance.counts_requirement",
        cypher="""
            MATCH (n:Requirement) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Requirement nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_requirement",
        cypher="""
            MATCH (n:Requirement)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Requirement nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_requirement",
        cypher="""
            MATCH (n:Requirement)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.requirement_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Requirement by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_requirement",
        cypher="""
            MATCH (n:Requirement {requirement_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Requirement.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_actionitem",
        cypher="""
            MATCH (n:ActionItem {action_item_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ActionItem node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_actionitem",
        cypher="""
            MATCH (old:ActionItem {action_item_id: $node_id}), (new:ActionItem {action_item_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ActionItem to new ActionItem with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_actionitem",
        cypher="""
            MATCH (n:ActionItem)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.action_item_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ActionItem nodes.",
    ),
    NamedQuery(
        name="provenance.counts_actionitem",
        cypher="""
            MATCH (n:ActionItem) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ActionItem nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_actionitem",
        cypher="""
            MATCH (n:ActionItem)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ActionItem nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_actionitem",
        cypher="""
            MATCH (n:ActionItem)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.action_item_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ActionItem by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_actionitem",
        cypher="""
            MATCH (n:ActionItem {action_item_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ActionItem.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint {global_constraint_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a GlobalConstraint node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_globalconstraint",
        cypher="""
            MATCH (old:GlobalConstraint {global_constraint_id: $node_id}), (new:GlobalConstraint {global_constraint_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old GlobalConstraint to new GlobalConstraint with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.global_constraint_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected GlobalConstraint nodes.",
    ),
    NamedQuery(
        name="provenance.counts_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned GlobalConstraint nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected GlobalConstraint nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.global_constraint_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live GlobalConstraint by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint {global_constraint_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live GlobalConstraint.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference {global_preference_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a GlobalPreference node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_globalpreference",
        cypher="""
            MATCH (old:GlobalPreference {global_preference_id: $node_id}), (new:GlobalPreference {global_preference_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old GlobalPreference to new GlobalPreference with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.global_preference_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected GlobalPreference nodes.",
    ),
    NamedQuery(
        name="provenance.counts_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned GlobalPreference nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected GlobalPreference nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.global_preference_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live GlobalPreference by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference {global_preference_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live GlobalPreference.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_lesson",
        cypher="""
            MATCH (n:Lesson {lesson_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Lesson node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_lesson",
        cypher="""
            MATCH (old:Lesson {lesson_id: $node_id}), (new:Lesson {lesson_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Lesson to new Lesson with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_lesson",
        cypher="""
            MATCH (n:Lesson)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.lesson_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Lesson nodes.",
    ),
    NamedQuery(
        name="provenance.counts_lesson",
        cypher="""
            MATCH (n:Lesson) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Lesson nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_lesson",
        cypher="""
            MATCH (n:Lesson)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Lesson nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_lesson",
        cypher="""
            MATCH (n:Lesson)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.lesson_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Lesson by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_lesson",
        cypher="""
            MATCH (n:Lesson {lesson_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Lesson.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_procedure",
        cypher="""
            MATCH (n:Procedure {procedure_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Procedure node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_procedure",
        cypher="""
            MATCH (old:Procedure {procedure_id: $node_id}), (new:Procedure {procedure_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Procedure to new Procedure with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_procedure",
        cypher="""
            MATCH (n:Procedure)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.procedure_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Procedure nodes.",
    ),
    NamedQuery(
        name="provenance.counts_procedure",
        cypher="""
            MATCH (n:Procedure) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Procedure nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_procedure",
        cypher="""
            MATCH (n:Procedure)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Procedure nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_procedure",
        cypher="""
            MATCH (n:Procedure)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.procedure_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Procedure by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_procedure",
        cypher="""
            MATCH (n:Procedure {procedure_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Procedure.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_knowledgegap",
        cypher="""
            MATCH (n:KnowledgeGap {gap_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a KnowledgeGap node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_knowledgegap",
        cypher="""
            MATCH (old:KnowledgeGap {gap_id: $node_id}), (new:KnowledgeGap {gap_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old KnowledgeGap to new KnowledgeGap with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_knowledgegap",
        cypher="""
            MATCH (n:KnowledgeGap)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.gap_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected KnowledgeGap nodes.",
    ),
    NamedQuery(
        name="provenance.counts_knowledgegap",
        cypher="""
            MATCH (n:KnowledgeGap) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned KnowledgeGap nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_knowledgegap",
        cypher="""
            MATCH (n:KnowledgeGap)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected KnowledgeGap nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_knowledgegap",
        cypher="""
            MATCH (n:KnowledgeGap)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.gap_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live KnowledgeGap by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_knowledgegap",
        cypher="""
            MATCH (n:KnowledgeGap {gap_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live KnowledgeGap.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_plan",
        cypher="""
            MATCH (n:Plan {plan_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Plan node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_plan",
        cypher="""
            MATCH (old:Plan {plan_id: $node_id}), (new:Plan {plan_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Plan to new Plan with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_plan",
        cypher="""
            MATCH (n:Plan)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.plan_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Plan nodes.",
    ),
    NamedQuery(
        name="provenance.counts_plan",
        cypher="""
            MATCH (n:Plan) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Plan nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_plan",
        cypher="""
            MATCH (n:Plan)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Plan nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_plan",
        cypher="""
            MATCH (n:Plan)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.plan_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Plan by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_plan",
        cypher="""
            MATCH (n:Plan {plan_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Plan.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_planstep",
        cypher="""
            MATCH (n:PlanStep {step_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a PlanStep node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_planstep",
        cypher="""
            MATCH (old:PlanStep {step_id: $node_id}), (new:PlanStep {step_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old PlanStep to new PlanStep with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_planstep",
        cypher="""
            MATCH (n:PlanStep)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.step_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected PlanStep nodes.",
    ),
    NamedQuery(
        name="provenance.counts_planstep",
        cypher="""
            MATCH (n:PlanStep) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned PlanStep nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_planstep",
        cypher="""
            MATCH (n:PlanStep)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected PlanStep nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_planstep",
        cypher="""
            MATCH (n:PlanStep)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.step_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live PlanStep by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_planstep",
        cypher="""
            MATCH (n:PlanStep {step_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live PlanStep.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_hypothesis",
        cypher="""
            MATCH (n:Hypothesis {id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Hypothesis node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_hypothesis",
        cypher="""
            MATCH (old:Hypothesis {id: $node_id}), (new:Hypothesis {id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Hypothesis to new Hypothesis with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_hypothesis",
        cypher="""
            MATCH (n:Hypothesis)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Hypothesis nodes.",
    ),
    NamedQuery(
        name="provenance.counts_hypothesis",
        cypher="""
            MATCH (n:Hypothesis) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Hypothesis nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_hypothesis",
        cypher="""
            MATCH (n:Hypothesis)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Hypothesis nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_hypothesis",
        cypher="""
            MATCH (n:Hypothesis)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Hypothesis by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_hypothesis",
        cypher="""
            MATCH (n:Hypothesis {id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Hypothesis.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_actionfact",
        cypher="""
            MATCH (n:ActionFact {fact_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ActionFact node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_actionfact",
        cypher="""
            MATCH (old:ActionFact {fact_id: $node_id}), (new:ActionFact {fact_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ActionFact to new ActionFact with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_actionfact",
        cypher="""
            MATCH (n:ActionFact)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.fact_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ActionFact nodes.",
    ),
    NamedQuery(
        name="provenance.counts_actionfact",
        cypher="""
            MATCH (n:ActionFact) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ActionFact nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_actionfact",
        cypher="""
            MATCH (n:ActionFact)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ActionFact nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_actionfact",
        cypher="""
            MATCH (n:ActionFact)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.fact_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ActionFact by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_actionfact",
        cypher="""
            MATCH (n:ActionFact {fact_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ActionFact.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_actioneffect",
        cypher="""
            MATCH (n:ActionEffect {effect_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ActionEffect node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_actioneffect",
        cypher="""
            MATCH (old:ActionEffect {effect_id: $node_id}), (new:ActionEffect {effect_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ActionEffect to new ActionEffect with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_actioneffect",
        cypher="""
            MATCH (n:ActionEffect)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.effect_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ActionEffect nodes.",
    ),
    NamedQuery(
        name="provenance.counts_actioneffect",
        cypher="""
            MATCH (n:ActionEffect) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ActionEffect nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_actioneffect",
        cypher="""
            MATCH (n:ActionEffect)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ActionEffect nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_actioneffect",
        cypher="""
            MATCH (n:ActionEffect)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.effect_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ActionEffect by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_actioneffect",
        cypher="""
            MATCH (n:ActionEffect {effect_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ActionEffect.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_victorycondition",
        cypher="""
            MATCH (n:VictoryCondition {condition_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a VictoryCondition node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_victorycondition",
        cypher="""
            MATCH (old:VictoryCondition {condition_id: $node_id}), (new:VictoryCondition {condition_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old VictoryCondition to new VictoryCondition with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_victorycondition",
        cypher="""
            MATCH (n:VictoryCondition)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.condition_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected VictoryCondition nodes.",
    ),
    NamedQuery(
        name="provenance.counts_victorycondition",
        cypher="""
            MATCH (n:VictoryCondition) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned VictoryCondition nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_victorycondition",
        cypher="""
            MATCH (n:VictoryCondition)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected VictoryCondition nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_victorycondition",
        cypher="""
            MATCH (n:VictoryCondition)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.condition_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live VictoryCondition by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_victorycondition",
        cypher="""
            MATCH (n:VictoryCondition {condition_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live VictoryCondition.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_rule",
        cypher="""
            MATCH (n:Rule {rule_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Rule node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_rule",
        cypher="""
            MATCH (old:Rule {rule_id: $node_id}), (new:Rule {rule_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Rule to new Rule with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_rule",
        cypher="""
            MATCH (n:Rule)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.rule_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Rule nodes.",
    ),
    NamedQuery(
        name="provenance.counts_rule",
        cypher="""
            MATCH (n:Rule) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Rule nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_rule",
        cypher="""
            MATCH (n:Rule)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Rule nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_rule",
        cypher="""
            MATCH (n:Rule)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.rule_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Rule by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_rule",
        cypher="""
            MATCH (n:Rule {rule_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Rule.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_transition",
        cypher="""
            MATCH (n:Transition {transition_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a Transition node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_transition",
        cypher="""
            MATCH (old:Transition {transition_id: $node_id}), (new:Transition {transition_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old Transition to new Transition with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_transition",
        cypher="""
            MATCH (n:Transition)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.transition_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected Transition nodes.",
    ),
    NamedQuery(
        name="provenance.counts_transition",
        cypher="""
            MATCH (n:Transition) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned Transition nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_transition",
        cypher="""
            MATCH (n:Transition)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected Transition nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_transition",
        cypher="""
            MATCH (n:Transition)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.transition_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live Transition by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_transition",
        cypher="""
            MATCH (n:Transition {transition_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live Transition.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_documentextract",
        cypher="""
            MATCH (n:DocumentExtract {extract_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a DocumentExtract node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_documentextract",
        cypher="""
            MATCH (old:DocumentExtract {extract_id: $node_id}), (new:DocumentExtract {extract_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old DocumentExtract to new DocumentExtract with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_documentextract",
        cypher="""
            MATCH (n:DocumentExtract)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.extract_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected DocumentExtract nodes.",
    ),
    NamedQuery(
        name="provenance.counts_documentextract",
        cypher="""
            MATCH (n:DocumentExtract) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned DocumentExtract nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_documentextract",
        cypher="""
            MATCH (n:DocumentExtract)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected DocumentExtract nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_documentextract",
        cypher="""
            MATCH (n:DocumentExtract)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.extract_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live DocumentExtract by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_documentextract",
        cypher="""
            MATCH (n:DocumentExtract {extract_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live DocumentExtract.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_worksummary",
        cypher="""
            MATCH (n:WorkSummary {summary_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a WorkSummary node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_worksummary",
        cypher="""
            MATCH (old:WorkSummary {summary_id: $node_id}), (new:WorkSummary {summary_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old WorkSummary to new WorkSummary with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_worksummary",
        cypher="""
            MATCH (n:WorkSummary)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.summary_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected WorkSummary nodes.",
    ),
    NamedQuery(
        name="provenance.counts_worksummary",
        cypher="""
            MATCH (n:WorkSummary) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned WorkSummary nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_worksummary",
        cypher="""
            MATCH (n:WorkSummary)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected WorkSummary nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_worksummary",
        cypher="""
            MATCH (n:WorkSummary)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.summary_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live WorkSummary by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_worksummary",
        cypher="""
            MATCH (n:WorkSummary {summary_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live WorkSummary.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_workartifact",
        cypher="""
            MATCH (n:WorkArtifact {artifact_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a WorkArtifact node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_workartifact",
        cypher="""
            MATCH (old:WorkArtifact {artifact_id: $node_id}), (new:WorkArtifact {artifact_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old WorkArtifact to new WorkArtifact with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_workartifact",
        cypher="""
            MATCH (n:WorkArtifact)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.artifact_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected WorkArtifact nodes.",
    ),
    NamedQuery(
        name="provenance.counts_workartifact",
        cypher="""
            MATCH (n:WorkArtifact) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned WorkArtifact nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_workartifact",
        cypher="""
            MATCH (n:WorkArtifact)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected WorkArtifact nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_workartifact",
        cypher="""
            MATCH (n:WorkArtifact)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.artifact_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live WorkArtifact by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_workartifact",
        cypher="""
            MATCH (n:WorkArtifact {artifact_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live WorkArtifact.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_arcmechanic",
        cypher="""
            MATCH (n:ArcMechanic {mechanic_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ArcMechanic node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_arcmechanic",
        cypher="""
            MATCH (old:ArcMechanic {mechanic_id: $node_id}), (new:ArcMechanic {mechanic_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ArcMechanic to new ArcMechanic with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_arcmechanic",
        cypher="""
            MATCH (n:ArcMechanic)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.mechanic_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ArcMechanic nodes.",
    ),
    NamedQuery(
        name="provenance.counts_arcmechanic",
        cypher="""
            MATCH (n:ArcMechanic) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ArcMechanic nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_arcmechanic",
        cypher="""
            MATCH (n:ArcMechanic)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ArcMechanic nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_arcmechanic",
        cypher="""
            MATCH (n:ArcMechanic)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.mechanic_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ArcMechanic by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_arcmechanic",
        cypher="""
            MATCH (n:ArcMechanic {mechanic_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ArcMechanic.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_arcactionpattern",
        cypher="""
            MATCH (n:ArcActionPattern {pattern_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ArcActionPattern node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_arcactionpattern",
        cypher="""
            MATCH (old:ArcActionPattern {pattern_id: $node_id}), (new:ArcActionPattern {pattern_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ArcActionPattern to new ArcActionPattern with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_arcactionpattern",
        cypher="""
            MATCH (n:ArcActionPattern)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.pattern_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ArcActionPattern nodes.",
    ),
    NamedQuery(
        name="provenance.counts_arcactionpattern",
        cypher="""
            MATCH (n:ArcActionPattern) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ArcActionPattern nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_arcactionpattern",
        cypher="""
            MATCH (n:ArcActionPattern)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ArcActionPattern nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_arcactionpattern",
        cypher="""
            MATCH (n:ArcActionPattern)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.pattern_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ArcActionPattern by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_arcactionpattern",
        cypher="""
            MATCH (n:ArcActionPattern {pattern_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ArcActionPattern.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_arceffectpattern",
        cypher="""
            MATCH (n:ArcEffectPattern {pattern_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ArcEffectPattern node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_arceffectpattern",
        cypher="""
            MATCH (old:ArcEffectPattern {pattern_id: $node_id}), (new:ArcEffectPattern {pattern_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ArcEffectPattern to new ArcEffectPattern with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_arceffectpattern",
        cypher="""
            MATCH (n:ArcEffectPattern)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.pattern_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ArcEffectPattern nodes.",
    ),
    NamedQuery(
        name="provenance.counts_arceffectpattern",
        cypher="""
            MATCH (n:ArcEffectPattern) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ArcEffectPattern nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_arceffectpattern",
        cypher="""
            MATCH (n:ArcEffectPattern)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ArcEffectPattern nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_arceffectpattern",
        cypher="""
            MATCH (n:ArcEffectPattern)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.pattern_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ArcEffectPattern by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_arceffectpattern",
        cypher="""
            MATCH (n:ArcEffectPattern {pattern_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ArcEffectPattern.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_arcprecondition",
        cypher="""
            MATCH (n:ArcPrecondition {precondition_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ArcPrecondition node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_arcprecondition",
        cypher="""
            MATCH (old:ArcPrecondition {precondition_id: $node_id}), (new:ArcPrecondition {precondition_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ArcPrecondition to new ArcPrecondition with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_arcprecondition",
        cypher="""
            MATCH (n:ArcPrecondition)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.precondition_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ArcPrecondition nodes.",
    ),
    NamedQuery(
        name="provenance.counts_arcprecondition",
        cypher="""
            MATCH (n:ArcPrecondition) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ArcPrecondition nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_arcprecondition",
        cypher="""
            MATCH (n:ArcPrecondition)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ArcPrecondition nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_arcprecondition",
        cypher="""
            MATCH (n:ArcPrecondition)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.precondition_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ArcPrecondition by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_arcprecondition",
        cypher="""
            MATCH (n:ArcPrecondition {precondition_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ArcPrecondition.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_arcfailuremode",
        cypher="""
            MATCH (n:ArcFailureMode {failure_mode_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ArcFailureMode node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_arcfailuremode",
        cypher="""
            MATCH (old:ArcFailureMode {failure_mode_id: $node_id}), (new:ArcFailureMode {failure_mode_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ArcFailureMode to new ArcFailureMode with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_arcfailuremode",
        cypher="""
            MATCH (n:ArcFailureMode)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.failure_mode_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ArcFailureMode nodes.",
    ),
    NamedQuery(
        name="provenance.counts_arcfailuremode",
        cypher="""
            MATCH (n:ArcFailureMode) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ArcFailureMode nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_arcfailuremode",
        cypher="""
            MATCH (n:ArcFailureMode)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ArcFailureMode nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_arcfailuremode",
        cypher="""
            MATCH (n:ArcFailureMode)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.failure_mode_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ArcFailureMode by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_arcfailuremode",
        cypher="""
            MATCH (n:ArcFailureMode {failure_mode_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ArcFailureMode.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_arcrecoverypolicy",
        cypher="""
            MATCH (n:ArcRecoveryPolicy {recovery_policy_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ArcRecoveryPolicy node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_arcrecoverypolicy",
        cypher="""
            MATCH (old:ArcRecoveryPolicy {recovery_policy_id: $node_id}), (new:ArcRecoveryPolicy {recovery_policy_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ArcRecoveryPolicy to new ArcRecoveryPolicy with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_arcrecoverypolicy",
        cypher="""
            MATCH (n:ArcRecoveryPolicy)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.recovery_policy_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ArcRecoveryPolicy nodes.",
    ),
    NamedQuery(
        name="provenance.counts_arcrecoverypolicy",
        cypher="""
            MATCH (n:ArcRecoveryPolicy) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ArcRecoveryPolicy nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_arcrecoverypolicy",
        cypher="""
            MATCH (n:ArcRecoveryPolicy)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ArcRecoveryPolicy nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_arcrecoverypolicy",
        cypher="""
            MATCH (n:ArcRecoveryPolicy)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.recovery_policy_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ArcRecoveryPolicy by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_arcrecoverypolicy",
        cypher="""
            MATCH (n:ArcRecoveryPolicy {recovery_policy_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ArcRecoveryPolicy.",
    ),
    NamedQuery(
        name="provenance.mark_superseded_arcworldmodelstep",
        cypher="""
            MATCH (n:ArcWorldModelStep {world_model_step_id: $node_id})
            SET n.superseded_by = $superseded_by,
                n.superseded_at = timestamp($at),
                n.supersession_reason = $reason
            """,
        params=("node_id", "superseded_by", "at", "reason"),
        mutating=True,
        description="Mark a ArcWorldModelStep node as superseded.",
    ),
    NamedQuery(
        name="provenance.deprecated_by_arcworldmodelstep",
        cypher="""
            MATCH (old:ArcWorldModelStep {world_model_step_id: $node_id}), (new:ArcWorldModelStep {world_model_step_id: $superseded_by})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("node_id", "superseded_by"),
        mutating=True,
        description="Link old ArcWorldModelStep to new ArcWorldModelStep with DEPRECATED_BY.",
    ),
    NamedQuery(
        name="provenance.find_stale_arcworldmodelstep",
        cypher="""
            MATCH (n:ArcWorldModelStep)
            WHERE n.authority = 'projected' AND n.source = $source
              AND n.source_version IS NOT NULL AND n.source_version <> $current_version
            RETURN n.world_model_step_id AS node_id, n.source AS source, n.source_version AS source_version
            """,
        params=("source", "current_version"),
        mutating=False,
        description="Find stale projected ArcWorldModelStep nodes.",
    ),
    NamedQuery(
        name="provenance.counts_arcworldmodelstep",
        cypher="""
            MATCH (n:ArcWorldModelStep) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned ArcWorldModelStep nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_arcworldmodelstep",
        cypher="""
            MATCH (n:ArcWorldModelStep)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected ArcWorldModelStep nodes for a source.",
    ),
    NamedQuery(
        name="provenance.find_live_arcworldmodelstep",
        cypher="""
            MATCH (n:ArcWorldModelStep)
            WHERE n.content_hash = $key AND n.superseded_by IS NULL
            RETURN n.world_model_step_id AS id LIMIT 1
            """,
        params=("key",),
        mutating=False,
        description="Find live ArcWorldModelStep by dedupe key (content hash).",
    ),
    NamedQuery(
        name="provenance.touch_last_accessed_arcworldmodelstep",
        cypher="""
            MATCH (n:ArcWorldModelStep {world_model_step_id: $id})
            SET n.last_accessed_at = timestamp($now)
            """,
        params=("id", "now"),
        mutating=True,
        description="Update last_accessed_at for live ArcWorldModelStep.",
    ),

    # B399: FactEntity (schema.py's B317 capability-graph subgraph) carries
    # the same source/authority/superseded_* columns as every table above
    # (see the "DELIBERATELY SEPARATE subgraph" comment on its DDL in
    # schema.py — separate from PROVENANCE_TABLES, not from this contract)
    # and drop_projections() is written generically enough to already
    # accept it via an explicit `tables=["FactEntity"]` argument. But
    # provenance.py's pre-B386 drop_projections() built
    # `f"MATCH (n:{table}) WHERE n.source = $source ..."` dynamically per
    # call, so it worked for any table name without prior registration;
    # this migration's per-table NamedQuery registration only ever
    # enumerated provenance.py's _PK_COLUMN keys, which never included
    # FactEntity (it doesn't need a pk column for drop_projections's own
    # count/delete queries), so `provenance.counts_factentity` /
    # `provenance.drop_projected_factentity` were simply never generated —
    # a silent capability loss (KeyError from QueryRegistry.get(), not a
    # wrong-answer bug) caught by
    # tests/test_fact_ingest.py::test_drop_projections_removes_fact_graph_leaves_earned_memory_untouched.
    # Scoped to only these two queries because they're the only
    # FactEntity-provenance operation actually reachable today
    # (mark_superseded()/find_live_by_dedupe_key() index _PK_COLUMN
    # first and raise before ever reaching the registry for a table not
    # listed there — no caller passes "FactEntity" to those).
    NamedQuery(
        name="provenance.counts_factentity",
        cypher="""
            MATCH (n:FactEntity) WHERE n.source = $source
            RETURN n.authority AS authority, count(*) AS c
            """,
        params=("source",),
        mutating=False,
        description="Count projected vs earned FactEntity nodes for a source.",
    ),
    NamedQuery(
        name="provenance.drop_projected_factentity",
        cypher="""
            MATCH (n:FactEntity)
            WHERE n.authority = 'projected' AND n.source = $source
            DETACH DELETE n
            """,
        params=("source",),
        mutating=True,
        description="Drop projected FactEntity nodes for a source.",
    ),
)
