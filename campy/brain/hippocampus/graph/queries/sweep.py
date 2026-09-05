"""campy/brain/hippocampus/graph/queries/sweep.py — Named queries for background sweep engine."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

SWEEP_QUERIES: tuple[NamedQuery, ...] = (
    # -----------------------------------------------------------------------
    # Step 5: Retrospective plans
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.get_retrospective_action_items",
        cypher="""
            MATCH (a:ActionItem)-[:ESTABLISHED_IN]->(s:Session)
            WHERE a.archived = false AND a.text_raw IS NOT NULL
            RETURN s.session_id, a.action_item_id, a.text_raw, a.created_at
            ORDER BY s.session_id, a.created_at ASC
            """,
        params=(),
        mutating=False,
        description="Fetch sequential ActionItems by session for retrospective plan inference.",
    ),
    NamedQuery(
        name="sweep.create_retrospective_plan",
        cypher="""
            CREATE (p:Plan {
                plan_id: $plan_id,
                goal: $goal,
                strategy: NULL,
                source: 'retrospective',
                embedding: $embedding,
                embedding_model: $embedding_model,
                embedding_dim: $embedding_dim,
                step_count: $step_count,
                valence: NULL,
                valence_source: NULL,
                status: 'completed',
                confidence: 0.65,
                confidence_low: true,
                pathway_strength: 0.65,
                archived: false,
                created_at: timestamp($created_at),
                completed_at: timestamp($completed_at)
            })
            """,
        params=(
            "plan_id", "goal", "embedding", "embedding_model", "embedding_dim",
            "step_count", "created_at", "completed_at",
        ),
        mutating=True,
        description="Create retrospective Plan node.",
    ),
    NamedQuery(
        name="sweep.link_plan_session",
        cypher="""
            MATCH (p:Plan {plan_id: $pid}), (s:Session {session_id: $sid})
            MERGE (p)-[:PLANNED_IN]->(s)
            """,
        params=("pid", "sid"),
        mutating=True,
        description="Link retrospective Plan to Session via PLANNED_IN.",
    ),
    NamedQuery(
        name="sweep.create_plan_step",
        cypher="""
            CREATE (ps:PlanStep {
                step_id: $step_id,
                step_number: $step_number,
                description: $description,
                embedding: $embedding,
                embedding_model: $embedding_model,
                embedding_dim: $embedding_dim,
                expected_outcome: NULL,
                actual_outcome: NULL,
                valence: NULL,
                status: 'succeeded',
                created_at: timestamp($created_at),
                completed_at: timestamp($completed_at)
            })
            """,
        params=(
            "step_id", "step_number", "description", "embedding", "embedding_model",
            "embedding_dim", "created_at", "completed_at",
        ),
        mutating=True,
        description="Create PlanStep node.",
    ),
    NamedQuery(
        name="sweep.link_step_of_plan",
        cypher="""
            MATCH (ps:PlanStep {step_id: $sid}), (p:Plan {plan_id: $pid})
            MERGE (ps)-[:STEP_OF]->(p)
            """,
        params=("sid", "pid"),
        mutating=True,
        description="Link PlanStep to Plan via STEP_OF.",
    ),
    NamedQuery(
        name="sweep.link_next_step",
        cypher="""
            MATCH (x:PlanStep {step_id: $a}), (y:PlanStep {step_id: $b})
            MERGE (x)-[:NEXT_STEP]->(y)
            """,
        params=("a", "b"),
        mutating=True,
        description="Link sequential PlanSteps via NEXT_STEP.",
    ),

    # -----------------------------------------------------------------------
    # Step 6: Knowledge gap detection
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.count_lessons_by_domain",
        cypher="""
            MATCH (l:Lesson) WHERE l.archived = false AND l.domain IS NOT NULL
            RETURN l.domain, count(l) AS lesson_count, avg(l.confidence) AS avg_conf
            """,
        params=(),
        mutating=False,
        description="Aggregate lesson count and avg confidence by domain.",
    ),
    NamedQuery(
        name="sweep.count_messages_by_domain",
        cypher="""
            MATCH (m:Message)-[:ESTABLISHED]->(c:Concept)
            WHERE c.gist_class IS NOT NULL
            RETURN c.gist_class, count(m) AS msg_count
            """,
        params=(),
        mutating=False,
        description="Count messages mentioning concepts by gist_class domain.",
    ),
    NamedQuery(
        name="sweep.count_solved_plans",
        cypher="""
            MATCH (p:Plan) WHERE p.status = 'completed' AND p.strategy IS NOT NULL
            RETURN p.strategy, count(p) AS solved_count
            """,
        params=(),
        mutating=False,
        description="Count completed plans by strategy/archetype.",
    ),
    NamedQuery(
        name="sweep.find_unresolved_gap",
        cypher="MATCH (g:KnowledgeGap {domain: $d, resolved: false}) RETURN g.gap_id LIMIT 1",
        params=("d",),
        mutating=False,
        description="Find unresolved KnowledgeGap by domain.",
    ),
    NamedQuery(
        name="sweep.resolve_gap",
        cypher="MATCH (g:KnowledgeGap {gap_id: $gid}) SET g.resolved = true, g.resolved_at = timestamp($now)",
        params=("gid", "now"),
        mutating=True,
        description="Mark KnowledgeGap as resolved.",
    ),
    NamedQuery(
        name="sweep.update_gap_severity",
        cypher="""
            MATCH (g:KnowledgeGap {gap_id: $gid})
            SET g.gap_type = $gap_type, g.description = $desc, g.severity = $severity,
                g.message_count = $msg_count, g.lesson_count = $lesson_count
            """,
        params=("gid", "gap_type", "desc", "severity", "msg_count", "lesson_count"),
        mutating=True,
        description="Update KnowledgeGap severity and counts.",
    ),
    NamedQuery(
        name="sweep.create_knowledge_gap",
        cypher="""
            CREATE (g:KnowledgeGap {
                gap_id: $gid, domain: $domain, gap_type: $gap_type, description: $desc,
                severity: $severity, message_count: $msg_count, lesson_count: $lesson_count,
                resolved: false, created_at: timestamp($now)
            })
            """,
        params=("gid", "domain", "gap_type", "desc", "severity", "msg_count", "lesson_count", "now"),
        mutating=True,
        description="Create new KnowledgeGap node.",
    ),
    NamedQuery(
        name="sweep.find_concept_by_domain",
        cypher="MATCH (c:Concept {gist_class: $domain}) RETURN c.concept_id LIMIT 1",
        params=("domain",),
        mutating=False,
        description="Find concept by gist_class domain.",
    ),
    NamedQuery(
        name="sweep.link_gap_concept",
        cypher="""
            MATCH (g:KnowledgeGap {gap_id: $gid}), (c:Concept {concept_id: $cid})
            MERGE (g)-[:IDENTIFIED_GAP_IN]->(c)
            """,
        params=("gid", "cid"),
        mutating=True,
        description="Link KnowledgeGap to Concept via IDENTIFIED_GAP_IN.",
    ),
    NamedQuery(
        name="sweep.find_quest_by_domain",
        cypher="MATCH (q:MainQuest) WHERE lower(q.name) CONTAINS lower($domain) RETURN q.quest_id LIMIT 1",
        params=("domain",),
        mutating=False,
        description="Find quest containing domain string.",
    ),
    NamedQuery(
        name="sweep.link_gap_quest",
        cypher="""
            MATCH (g:KnowledgeGap {gap_id: $gid}), (q:MainQuest {quest_id: $qid})
            MERGE (g)-[:IDENTIFIED_GAP_IN]->(q)
            """,
        params=("gid", "qid"),
        mutating=True,
        description="Link KnowledgeGap to MainQuest via IDENTIFIED_GAP_IN.",
    ),

    # -----------------------------------------------------------------------
    # Step 1.5: Valence-aware decay
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.get_outcome_signals",
        cypher="""
            MATCH (ps:PlanStep)-[o:OUTCOME_SIGNAL]->(c:Concept)
            WHERE c.archived = false
            RETURN c.concept_id, avg(o.valence) AS avg_v
            """,
        params=(),
        mutating=False,
        description="Fetch Concepts with average OUTCOME_SIGNAL valence.",
    ),
    NamedQuery(
        name="sweep.strengthen_concept_pathway",
        cypher="""
            MATCH (c:Concept {concept_id: $cid})
            SET c.pathway_strength = CASE
              WHEN c.pathway_strength * $factor > 1.0 THEN 1.0
              WHEN c.pathway_strength * $factor < 0.0 THEN 0.0
              ELSE c.pathway_strength * $factor END
            """,
        params=("cid", "factor"),
        mutating=True,
        description="Adjust Concept pathway_strength with factor clamped to [0, 1].",
    ),

    # -----------------------------------------------------------------------
    # Step 1 / Supernode: Session edge pruning
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.find_stale_sessions",
        cypher="""
            MATCH (s:Session)
            WHERE coalesce(s.last_active_at, s.started_at) < timestamp($cutoff)
            RETURN s.session_id
            """,
        params=("cutoff",),
        mutating=False,
        description="Find sessions inactive past cutoff timestamp.",
    ),
    NamedQuery(
        name="sweep.unwind_delete_session_loaded",
        cypher="""
            UNWIND $ids AS sid
            MATCH (s:Session)-[r:LOADED]->() WHERE s.session_id = sid
            DELETE r
            """,
        params=("ids",),
        mutating=True,
        description="Batch delete LOADED cache edges for stale sessions.",
    ),
    NamedQuery(
        name="sweep.unwind_delete_session_warm_node",
        cypher="""
            UNWIND $ids AS sid
            MATCH (s:Session)-[r:WARM_NODE]->() WHERE s.session_id = sid
            DELETE r
            """,
        params=("ids",),
        mutating=True,
        description="Batch delete WARM_NODE cache edges for stale sessions.",
    ),

    # -----------------------------------------------------------------------
    # Step 3: Hebbian auto-promotion
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.get_co_occurring_concepts",
        cypher="""
            MATCH (a:Concept)-[r:CO_OCCURS_WITH]->(b:Concept)
            WHERE r.count >= $threshold
              AND NOT (a)-[:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]->(b)
              AND NOT (b)-[:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]->(a)
            RETURN a.concept_id, a.text_raw, b.concept_id, b.text_raw, r.count
            """,
        params=("threshold",),
        mutating=False,
        description="Find high-count co-occurring concept pairs eligible for semantic edge promotion.",
    ),

    # -----------------------------------------------------------------------
    # Step 4: Centroid recomputation
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.get_distinct_gist_classes",
        cypher="MATCH (e:GistExample) RETURN DISTINCT e.gist_class",
        params=(),
        mutating=False,
        description="Fetch distinct gist_classes with examples.",
    ),
    NamedQuery(
        name="sweep.get_gist_examples_by_class",
        cypher="""
            MATCH (e:GistExample {gist_class: $cls})
            WHERE e.embedding IS NOT NULL
            RETURN e.embedding
            """,
        params=("cls",),
        mutating=False,
        description="Fetch embeddings for a gist_class.",
    ),
    NamedQuery(
        name="sweep.update_gist_class_centroid",
        cypher="MATCH (g:GistClass {name: $name}) SET g.centroid = $centroid",
        params=("name", "centroid"),
        mutating=True,
        description="Update GistClass centroid vector.",
    ),

    # -----------------------------------------------------------------------
    # Step 3.5: Dream consolidation / synthesis
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.get_dream_lesson_domains",
        cypher="MATCH (l:Lesson) WHERE l.archived = false AND (l.lesson_type IS NULL OR l.lesson_type != 'synthesis') RETURN DISTINCT l.domain",
        params=(),
        mutating=False,
        description="Fetch distinct active non-synthesis lesson domains.",
    ),
    NamedQuery(
        name="sweep.get_lessons_for_synthesis",
        cypher="""
            MATCH (l:Lesson) WHERE l.archived = false AND l.domain = $domain
            AND (l.lesson_type IS NULL OR l.lesson_type != 'synthesis')
            AND NOT EXISTS { MATCH (l)<-[:GENERALIZES_LESSON]-(:Lesson) }
            RETURN l.lesson_id, l.embedding, l.text_raw, l.pathway_strength, l.confidence
            """,
        params=("domain",),
        mutating=False,
        description="Fetch un-generalized lessons in domain for synthesis.",
    ),
    NamedQuery(
        name="sweep.create_synthesized_lesson",
        cypher="""
            CREATE (m:Lesson {
                lesson_id: $lid,
                text_raw: $text_raw,
                embedding: $embedding,
                embedding_model: $embedding_model,
                embedding_dim: $embedding_dim,
                domain: $domain,
                lesson_type: 'synthesis',
                confidence: $confidence,
                confidence_low: false,
                pathway_strength: $pathway_strength,
                archived: false,
                created_at: timestamp($now)
            })
            """,
        params=(
            "lid", "text_raw", "embedding", "embedding_model", "embedding_dim",
            "domain", "confidence", "pathway_strength", "now",
        ),
        mutating=True,
        description="Create synthesized meta-lesson.",
    ),
    NamedQuery(
        name="sweep.link_generalizes_lesson",
        cypher="""
            MATCH (m:Lesson {lesson_id: $mid}), (c:Lesson {lesson_id: $cid})
            MERGE (m)-[r:GENERALIZES_LESSON]->(c)
            ON CREATE SET r.synthesized_at = timestamp($now), r.cluster_size = $cluster_size
            ON MATCH SET r.cluster_size = $cluster_size
            """,
        params=("mid", "cid", "now", "cluster_size"),
        mutating=True,
        description="Link meta-lesson to constituent lesson via GENERALIZES_LESSON.",
    ),
    NamedQuery(
        name="sweep.touch_subsumed_lesson",
        cypher="""
            MATCH (c:Lesson {lesson_id: $cid})
            SET c.synthesized_at = timestamp($now),
                c.synthesis_cluster_size = $cluster_size,
                c.pathway_strength = c.pathway_strength / $decay_boost
            """,
        params=("cid", "now", "cluster_size", "decay_boost"),
        mutating=True,
        description="Accelerate decay on constituent lesson subsumed into synthesis.",
    ),

    # -----------------------------------------------------------------------
    # Basal Ganglia: Procedure maturity lifecycle
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.promote_procedure_maturity",
        cypher="""
            MATCH (p:Procedure) WHERE p.archived = false
            AND coalesce(p.maturity_stage, 'nascent') <> 'degraded'
            SET p.maturity_stage = CASE
              WHEN p.application_count >= 5 AND p.success_rate >= 0.75 THEN 'mature'
              WHEN p.application_count >= 3 AND p.success_rate >= 0.50 THEN 'developing'
              ELSE 'nascent' END
            """,
        params=(),
        mutating=True,
        description="Promote Procedure maturity stages based on stats.",
    ),
    NamedQuery(
        name="sweep.degrade_procedure_maturity",
        cypher="""
            MATCH (p:Procedure) WHERE p.archived = false
            AND p.application_count >= 3 AND p.success_rate < 0.30
            AND coalesce(p.maturity_stage, 'nascent') <> 'degraded'
            SET p.maturity_stage = 'degraded',
                p.pathway_strength = p.pathway_strength * 0.5
            """,
        params=(),
        mutating=True,
        description="Degrade failing Procedures and halve pathway strength.",
    ),
    NamedQuery(
        name="sweep.archive_degraded_procedure",
        cypher="""
            MATCH (p:Procedure) WHERE p.archived = false
            AND p.maturity_stage = 'degraded'
            AND p.success_rate < 0.20
            SET p.archived = true
            """,
        params=(),
        mutating=True,
        description="Archive deeply degraded Procedures.",
    ),

    # -----------------------------------------------------------------------
    # Consistency Audit
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.get_all_lesson_domains",
        cypher="MATCH (l:Lesson) WHERE l.archived = false RETURN DISTINCT l.domain",
        params=(),
        mutating=False,
        description="Fetch all distinct active lesson domains for consistency audit.",
    ),
    NamedQuery(
        name="sweep.get_lessons_in_domain_embeddings",
        cypher="""
            MATCH (l:Lesson) WHERE l.domain = $domain AND l.archived = false
            AND l.pathway_strength > $min_path ORDER BY l.pathway_strength DESC LIMIT $limit
            RETURN l.lesson_id, l.embedding, l.text_raw, l.confidence, l.pathway_strength, l.created_at, l.last_audited_at
            """,
        params=("domain", "min_path", "limit"),
        mutating=False,
        description="Fetch top active lessons in domain for pairwise consistency check.",
    ),
    NamedQuery(
        name="sweep.create_disambiguation_event",
        cypher="""
            CREATE (e:DisambiguationEvent {
                event_id: $eid,
                concept_id_a: $a,
                concept_id_b: $b,
                similarity: $sim,
                status: 'pending',
                resolved_at: NULL,
                resolved_by: NULL,
                created_at: timestamp($now)
            })
            """,
        params=("eid", "a", "b", "sim", "now"),
        mutating=True,
        description="Create DisambiguationEvent for contradiction review.",
    ),
    NamedQuery(
        name="sweep.archive_lesson",
        cypher="MATCH (l:Lesson {lesson_id: $lid}) SET l.archived = true",
        params=("lid",),
        mutating=True,
        description="Archive superseded lesson.",
    ),
    NamedQuery(
        name="sweep.link_lesson_deprecated_by",
        cypher="""
            MATCH (old:Lesson {lesson_id: $old}), (new:Lesson {lesson_id: $new})
            MERGE (old)-[:DEPRECATED_BY]->(new)
            """,
        params=("old", "new"),
        mutating=True,
        description="Link superseded lesson to winner via DEPRECATED_BY.",
    ),
    NamedQuery(
        name="sweep.touch_audited_lesson",
        cypher="MATCH (l:Lesson {lesson_id: $lid}) SET l.last_audited_at = timestamp($now)",
        params=("lid", "now"),
        mutating=True,
        description="Touch last_audited_at timestamp on lesson.",
    ),
    NamedQuery(
        name="sweep.get_stale_lessons",
        cypher="""
            MATCH (l:Lesson) WHERE l.archived = false AND l.lesson_type <> 'synthesis' AND l.created_at < timestamp($cutoff)
            AND NOT EXISTS { MATCH (l)-[:APPLIES_TO|RELATED_TO|GENERALIZES_LESSON]->() }
            RETURN l.lesson_id, l.text_raw
            """,
        params=("cutoff",),
        mutating=False,
        description="Find stale lessons older than cutoff with no outgoing rels.",
    ),
    NamedQuery(
        name="sweep.flag_stale_lesson",
        cypher="MATCH (l:Lesson {lesson_id: $lid}) SET l.stale_flagged = true, l.stale_flagged_at = timestamp($now)",
        params=("lid", "now"),
        mutating=True,
        description="Flag lesson as stale.",
    ),
    NamedQuery(
        name="sweep.get_orphan_lessons",
        cypher="""
            MATCH (l:Lesson) WHERE l.archived = false
            AND NOT EXISTS { MATCH ()-[:CONTAINS_LESSON|PRODUCED_LESSON|PRODUCED_PLAN_LESSON|LEARNED]->(l) }
            RETURN l.lesson_id, l.text_raw
            """,
        params=(),
        mutating=False,
        description="Find orphan lessons with no inbound source rels.",
    ),
    NamedQuery(
        name="sweep.flag_orphan_lesson",
        cypher="MATCH (l:Lesson {lesson_id: $lid}) SET l.orphan_flagged = true, l.orphan_flagged_at = timestamp($now)",
        params=("lid", "now"),
        mutating=True,
        description="Flag lesson as orphan.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_concept",
        cypher="""
            MATCH (n:Concept) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active Concept nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_concept",
        cypher="""
            MATCH (n:Concept) WHERE n.archived = false
            RETURN n.concept_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active Concept nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_concept",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Concept) WHERE n.concept_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive Concept nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_concept",
        cypher="""
            MATCH (n:Concept)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived Concept nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_concept",
        cypher="""
            MATCH (n:Concept)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.concept_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived Concept nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_concept",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Concept) WHERE n.concept_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived Concept nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active GlobalConstraint nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint) WHERE n.archived = false
            RETURN n.constraint_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active GlobalConstraint nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_globalconstraint",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:GlobalConstraint) WHERE n.constraint_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive GlobalConstraint nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived GlobalConstraint nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_globalconstraint",
        cypher="""
            MATCH (n:GlobalConstraint)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.constraint_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived GlobalConstraint nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_globalconstraint",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:GlobalConstraint) WHERE n.constraint_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived GlobalConstraint nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active GlobalPreference nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference) WHERE n.archived = false
            RETURN n.pref_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active GlobalPreference nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_globalpreference",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:GlobalPreference) WHERE n.pref_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive GlobalPreference nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived GlobalPreference nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_globalpreference",
        cypher="""
            MATCH (n:GlobalPreference)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.pref_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived GlobalPreference nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_globalpreference",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:GlobalPreference) WHERE n.pref_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived GlobalPreference nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_decision",
        cypher="""
            MATCH (n:Decision) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active Decision nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_decision",
        cypher="""
            MATCH (n:Decision) WHERE n.archived = false
            RETURN n.decision_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active Decision nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_decision",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Decision) WHERE n.decision_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive Decision nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_decision",
        cypher="""
            MATCH (n:Decision)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived Decision nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_decision",
        cypher="""
            MATCH (n:Decision)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.decision_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived Decision nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_decision",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Decision) WHERE n.decision_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived Decision nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_constraint",
        cypher="""
            MATCH (n:Constraint) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active Constraint nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_constraint",
        cypher="""
            MATCH (n:Constraint) WHERE n.archived = false
            RETURN n.constraint_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active Constraint nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_constraint",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Constraint) WHERE n.constraint_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive Constraint nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_constraint",
        cypher="""
            MATCH (n:Constraint)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived Constraint nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_constraint",
        cypher="""
            MATCH (n:Constraint)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.constraint_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived Constraint nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_constraint",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Constraint) WHERE n.constraint_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived Constraint nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_requirement",
        cypher="""
            MATCH (n:Requirement) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active Requirement nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_requirement",
        cypher="""
            MATCH (n:Requirement) WHERE n.archived = false
            RETURN n.req_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active Requirement nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_requirement",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Requirement) WHERE n.req_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive Requirement nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_requirement",
        cypher="""
            MATCH (n:Requirement)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived Requirement nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_requirement",
        cypher="""
            MATCH (n:Requirement)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.req_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived Requirement nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_requirement",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Requirement) WHERE n.req_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived Requirement nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_actionitem",
        cypher="""
            MATCH (n:ActionItem) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active ActionItem nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_actionitem",
        cypher="""
            MATCH (n:ActionItem) WHERE n.archived = false
            RETURN n.action_item_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active ActionItem nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_actionitem",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:ActionItem) WHERE n.action_item_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive ActionItem nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_actionitem",
        cypher="""
            MATCH (n:ActionItem)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived ActionItem nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_actionitem",
        cypher="""
            MATCH (n:ActionItem)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.action_item_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived ActionItem nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_actionitem",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:ActionItem) WHERE n.action_item_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived ActionItem nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_message",
        cypher="""
            MATCH (n:Message) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active Message nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_message",
        cypher="""
            MATCH (n:Message) WHERE n.archived = false
            RETURN n.message_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active Message nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_message",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Message) WHERE n.message_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive Message nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_message",
        cypher="""
            MATCH (n:Message)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived Message nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_message",
        cypher="""
            MATCH (n:Message)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.message_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived Message nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_message",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:Message) WHERE n.message_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived Message nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.decay_pathway_documentextract",
        cypher="""
            MATCH (n:DocumentExtract) WHERE n.archived = false
            SET n.pathway_strength = n.pathway_strength * $factor
            """,
        params=("factor",),
        mutating=True,
        description="Decay pathway_strength for active DocumentExtract nodes.",
    ),
    NamedQuery(
        name="sweep.get_active_pathway_documentextract",
        cypher="""
            MATCH (n:DocumentExtract) WHERE n.archived = false
            RETURN n.extract_id, n.pathway_strength
            """,
        params=(),
        mutating=False,
        description="Fetch active DocumentExtract nodes with pathway_strength.",
    ),
    NamedQuery(
        name="sweep.unwind_archive_documentextract",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:DocumentExtract) WHERE n.extract_id = nid
            SET n.archived = true
            """,
        params=("ids",),
        mutating=True,
        description="Batch archive DocumentExtract nodes by id.",
    ),
    NamedQuery(
        name="sweep.index_hygiene_documentextract",
        cypher="""
            MATCH (n:DocumentExtract)
            RETURN n.archived AS archived, count(n) AS c
            """,
        params=(),
        mutating=False,
        description="Count active and archived DocumentExtract nodes for index hygiene.",
    ),
    NamedQuery(
        name="sweep.resurrect_active_embeddings_documentextract",
        cypher="""
            MATCH (n:DocumentExtract)
            WHERE n.archived = true AND n.embedding IS NOT NULL
            RETURN n.extract_id, n.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch archived DocumentExtract nodes with embeddings for resurrection scan.",
    ),
    NamedQuery(
        name="sweep.resurrect_node_documentextract",
        cypher="""
            UNWIND $ids AS nid
            MATCH (n:DocumentExtract) WHERE n.extract_id = nid
            SET n.archived = false,
                n.pathway_strength = $strength
            """,
        params=("ids", "strength"),
        mutating=True,
        description="Resurrect archived DocumentExtract nodes and set pathway strength.",
    ),

    NamedQuery(
        name="sweep.degree_out_co_occurs_with",
        cypher="""
            MATCH (a)-[r:CO_OCCURS_WITH]->()
            RETURN a, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top out-degree nodes on CO_OCCURS_WITH.",
    ),
    NamedQuery(
        name="sweep.degree_in_co_occurs_with",
        cypher="""
            MATCH ()-[r:CO_OCCURS_WITH]->(b)
            RETURN b, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top in-degree nodes on CO_OCCURS_WITH.",
    ),

    NamedQuery(
        name="sweep.degree_out_established_in",
        cypher="""
            MATCH (a)-[r:ESTABLISHED_IN]->()
            RETURN a, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top out-degree nodes on ESTABLISHED_IN.",
    ),
    NamedQuery(
        name="sweep.degree_in_established_in",
        cypher="""
            MATCH ()-[r:ESTABLISHED_IN]->(b)
            RETURN b, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top in-degree nodes on ESTABLISHED_IN.",
    ),

    NamedQuery(
        name="sweep.degree_out_loaded",
        cypher="""
            MATCH (a)-[r:LOADED]->()
            RETURN a, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top out-degree nodes on LOADED.",
    ),
    NamedQuery(
        name="sweep.degree_in_loaded",
        cypher="""
            MATCH ()-[r:LOADED]->(b)
            RETURN b, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top in-degree nodes on LOADED.",
    ),

    NamedQuery(
        name="sweep.degree_out_warm_node",
        cypher="""
            MATCH (a)-[r:WARM_NODE]->()
            RETURN a, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top out-degree nodes on WARM_NODE.",
    ),
    NamedQuery(
        name="sweep.degree_in_warm_node",
        cypher="""
            MATCH ()-[r:WARM_NODE]->(b)
            RETURN b, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top in-degree nodes on WARM_NODE.",
    ),

    NamedQuery(
        name="sweep.degree_out_belongs_to",
        cypher="""
            MATCH (a)-[r:BELONGS_TO]->()
            RETURN a, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top out-degree nodes on BELONGS_TO.",
    ),
    NamedQuery(
        name="sweep.degree_in_belongs_to",
        cypher="""
            MATCH ()-[r:BELONGS_TO]->(b)
            RETURN b, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top in-degree nodes on BELONGS_TO.",
    ),

    NamedQuery(
        name="sweep.degree_out_working_on",
        cypher="""
            MATCH (a)-[r:WORKING_ON]->()
            RETURN a, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top out-degree nodes on WORKING_ON.",
    ),
    NamedQuery(
        name="sweep.degree_in_working_on",
        cypher="""
            MATCH ()-[r:WORKING_ON]->(b)
            RETURN b, count(r) AS deg ORDER BY deg DESC LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Top in-degree nodes on WORKING_ON.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_requires",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:REQUIRES]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic REQUIRES relationship between concepts.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_enables",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:ENABLES]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic ENABLES relationship between concepts.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_replaces",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:REPLACES]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic REPLACES relationship between concepts.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_contradicts",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:CONTRADICTS]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic CONTRADICTS relationship between concepts.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_part_of",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:PART_OF]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic PART_OF relationship between concepts.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_chosen_over",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:CHOSEN_OVER]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic CHOSEN_OVER relationship between concepts.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_implements",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:IMPLEMENTS]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic IMPLEMENTS relationship between concepts.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_extends",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:EXTENDS]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic EXTENDS relationship between concepts.",
    ),

    NamedQuery(
        name="sweep.merge_concept_rel_alternative_to",
        cypher="""
            MATCH (a:Concept {concept_id: $a_id}),
                  (b:Concept {concept_id: $b_id})
            MERGE (a)-[r:ALTERNATIVE_TO]->(b)
            ON CREATE SET r.confidence  = $conf,
                          r.inferred_by = 'LLM',
                          r.inferred_at = timestamp($now)
            ON MATCH SET  r.confidence  = $conf
            """,
        params=("a_id", "b_id", "conf", "now"),
        mutating=True,
        description="Merge semantic ALTERNATIVE_TO relationship between concepts.",
    ),

    # -----------------------------------------------------------------------
    # Pattern Discovery (sweep_patterns.py)
    # -----------------------------------------------------------------------
    NamedQuery(
        name="sweep.patterns_temporal_lessons",
        cypher="""
            MATCH (m:Message)-[:CONTAINS_LESSON]->(l:Lesson)
            WHERE l.archived = false
              AND l.trigger_pattern IS NULL
              AND m.created_at IS NOT NULL
            RETURN l.lesson_id, l.text_raw, m.created_at
            ORDER BY l.lesson_id, m.created_at ASC
            """,
        params=(),
        mutating=False,
        description="Fetch lessons and message timestamps for temporal pattern discovery.",
    ),
    NamedQuery(
        name="sweep.patterns_sequence_failures",
        cypher="""
            MATCH (ps1:PlanStep)-[:NEXT_STEP]->(ps2:PlanStep)-[:NEXT_STEP]->(ps_fail:PlanStep)
            WHERE ps_fail.valence IS NOT NULL AND ps_fail.valence < 0
              AND ps_fail.status = 'failed'
            RETURN ps1.description, ps2.description, ps_fail.description,
                   ps_fail.step_id, ps_fail.valence
            ORDER BY ps_fail.valence ASC
            """,
        params=(),
        mutating=False,
        description="Fetch action chains preceding failed plan steps.",
    ),
    NamedQuery(
        name="sweep.patterns_frequency_lessons",
        cypher="""
            MATCH (m:Message)-[:CONTAINS_LESSON]->(l:Lesson),
                  (m)-[:SENT_IN]->(s:Session)
            WHERE l.archived = false
              AND l.trigger_pattern IS NULL
              AND s.started_at IS NOT NULL
            RETURN l.lesson_id, l.text_raw, s.session_id, s.started_at, count(m) AS msg_count
            ORDER BY l.lesson_id, s.started_at ASC
            """,
        params=(),
        mutating=False,
        description="Fetch lesson occurrences across sessions for frequency pattern discovery.",
    ),
    NamedQuery(
        name="sweep.patterns_existing_lesson_triggers",
        cypher="""
            MATCH (l:Lesson) WHERE l.archived = false
            AND l.trigger_pattern IS NOT NULL AND l.trigger_pattern <> ''
            RETURN l.trigger_pattern
            """,
        params=(),
        mutating=False,
        description="Fetch existing trigger patterns on active lessons.",
    ),
    NamedQuery(
        name="sweep.patterns_existing_procedure_triggers",
        cypher="""
            MATCH (p:Procedure) WHERE p.archived = false
            AND p.trigger_pattern IS NOT NULL AND p.trigger_pattern <> ''
            RETURN p.trigger_pattern
            """,
        params=(),
        mutating=False,
        description="Fetch existing trigger patterns on active procedures.",
    ),
    NamedQuery(
        name="sweep.patterns_update_lesson_trigger",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid})
            SET l.trigger_pattern = $pattern,
                l.trigger_hook_type = $hook_type,
                l.trigger_tool = $tool,
                l.trigger_project_scope = $scope
            """,
        params=("lid", "pattern", "hook_type", "tool", "scope"),
        mutating=True,
        description="Update trigger metadata on a lesson.",
    ),
    NamedQuery(
        name="sweep.patterns_create_procedure",
        cypher="""
            CREATE (pr:Procedure {
                procedure_id: $pid, name: $name,
                domain: 'auto-discovered', archetype: 'failure-sequence',
                description: $description, steps_json: $steps_json,
                embedding: $embedding, embedding_model: $embedding_model,
                embedding_dim: $embedding_dim,
                success_count: 0, application_count: 0, success_rate: 0.0,
                confidence: $confidence, pathway_strength: $pathway_strength,
                archived: false, created_at: timestamp($now),
                trigger_pattern: $trigger_pattern,
                trigger_hook_type: $trigger_hook_type,
                trigger_tool: $trigger_tool,
                trigger_project_scope: $trigger_scope
            })
            """,
        params=(
            "pid", "name", "description", "steps_json", "embedding",
            "embedding_model", "embedding_dim", "confidence", "pathway_strength",
            "now", "trigger_pattern", "trigger_hook_type", "trigger_tool", "trigger_scope",
        ),
        mutating=True,
        description="Create auto-discovered failure sequence Procedure node.",
    ),
    NamedQuery(
        name="sweep.patterns_update_procedure_trigger",
        cypher="""
            MATCH (p:Procedure {procedure_id: $pid})
            SET p.trigger_pattern = $pattern,
                p.trigger_hook_type = $hook_type,
                p.trigger_tool = $tool,
                p.trigger_project_scope = $scope
            """,
        params=("pid", "pattern", "hook_type", "tool", "scope"),
        mutating=True,
        description="Update trigger metadata on a procedure.",
    ),
)
