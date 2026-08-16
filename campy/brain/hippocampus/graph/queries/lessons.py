"""
campy/brain/hippocampus/graph/queries/lessons.py — B314 named-query slice.

Every Cypher string previously inline in
`campy/brain/thalamus/tools/lessons.py` lives here now, as `NamedQuery`
objects. `lessons.py`'s tool functions call `GraphGateway.run(name, ...)`
instead of building/passing Cypher text directly — see B314's card for the
full rationale (engine-portability seam, tenant-visibility injection point
for B316, and a governance-reviewable artifact).

Naming convention: `lessons.<verb>_<subject>`.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

LESSONS_QUERIES: tuple[NamedQuery, ...] = (
    # -- Plan / PlanStep creation (writes) -----------------------------------
    NamedQuery(
        name="lessons.create_plan",
        cypher="""
            CREATE (p:Plan {
                plan_id: $plan_id,
                goal: $goal,
                strategy: $strategy,
                source: $source,
                embedding: $embedding,
                embedding_model: $embedding_model,
                embedding_dim: $embedding_dim,
                step_count: $step_count,
                valence: NULL,
                valence_source: NULL,
                status: 'active',
                confidence: $confidence,
                confidence_low: $confidence_low,
                pathway_strength: $pathway_strength,
                archived: false,
                created_at: timestamp($created_at),
                completed_at: NULL,
                source_version: $prov_source_version,
                observed_at: timestamp($prov_observed_at),
                evidence_ref: $prov_evidence_ref,
                content_hash: $content_hash
            })
            """,
        params=(
            "plan_id", "goal", "strategy", "source", "embedding", "embedding_model",
            "embedding_dim", "step_count", "confidence", "confidence_low",
            "pathway_strength", "created_at", "prov_source_version",
            "prov_observed_at", "prov_evidence_ref", "content_hash",
        ),
        mutating=True,
        description="Create a Plan node (B75 active/passive plan declaration).",
    ),
    NamedQuery(
        name="lessons.create_plan_step",
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
                status: 'pending',
                created_at: timestamp($created_at),
                completed_at: NULL,
                source: $prov_source,
                source_version: $prov_source_version,
                observed_at: timestamp($prov_observed_at),
                evidence_ref: $prov_evidence_ref
            })
            """,
        params=(
            "step_id", "step_number", "description", "embedding", "embedding_model",
            "embedding_dim", "created_at", "prov_source", "prov_source_version",
            "prov_observed_at", "prov_evidence_ref",
        ),
        mutating=True,
        description="Create one PlanStep node, one CREATE per step (B68).",
    ),
    NamedQuery(
        name="lessons.link_step_to_plan",
        cypher="""
            MATCH (p:Plan {plan_id: $plan_id})
            MATCH (ps:PlanStep {step_id: $step_id})
            MERGE (ps)-[:STEP_OF]->(p)
            """,
        params=("plan_id", "step_id"),
        mutating=True,
        description="Link a PlanStep to its parent Plan via STEP_OF.",
    ),
    NamedQuery(
        name="lessons.link_step_acts_on_concepts",
        cypher="""
            UNWIND $cids AS cid
            MATCH (ps:PlanStep {step_id: $sid})
            MATCH (c:Concept {concept_id: cid})
            MERGE (ps)-[:ACTS_ON]->(c)
            """,
        params=("sid", "cids"),
        mutating=True,
        description="Link a PlanStep to the Concepts it acts on (B75 vector-search precalc).",
    ),
    NamedQuery(
        name="lessons.link_plan_to_session",
        cypher="""
            MATCH (p:Plan {plan_id: $plan_id})
            MATCH (s:Session {session_id: $session_id})
            MERGE (p)-[:PLANNED_IN]->(s)
            """,
        params=("plan_id", "session_id"),
        mutating=True,
        description="Link a Plan to the Session it was planned in.",
    ),
    NamedQuery(
        name="lessons.link_plan_to_main_quest",
        cypher="""
            MATCH (p:Plan {plan_id: $plan_id})
            MATCH (q:MainQuest {quest_id: $quest_id})
            MERGE (p)-[:TARGETS]->(q)
            """,
        params=("plan_id", "quest_id"),
        mutating=True,
        description="Link a Plan to the MainQuest it targets.",
    ),
    NamedQuery(
        name="lessons.link_plan_to_side_quest",
        cypher="""
            MATCH (p:Plan {plan_id: $plan_id})
            MATCH (q:SideQuest {quest_id: $quest_id})
            MERGE (p)-[:TARGETS]->(q)
            """,
        params=("plan_id", "quest_id"),
        mutating=True,
        description="Link a Plan to the SideQuest it targets (fallback when MainQuest match fails).",
    ),
    NamedQuery(
        name="lessons.chain_plan_steps",
        cypher="""
            UNWIND $pairs AS pair
            MATCH (x:PlanStep {step_id: pair.a}), (y:PlanStep {step_id: pair.b})
            MERGE (x)-[:NEXT_STEP]->(y)
            """,
        params=("pairs",),
        mutating=True,
        description="Chain consecutive PlanSteps with NEXT_STEP (B75 call 2).",
    ),
    NamedQuery(
        name="lessons.delete_plan_steps",
        cypher="UNWIND $ids AS sid MATCH (ps:PlanStep {step_id: sid}) DETACH DELETE ps",
        params=("ids",),
        mutating=True,
        description="Compensating delete of PlanStep nodes when a Plan write fails partway through.",
    ),
    NamedQuery(
        name="lessons.delete_plan",
        cypher="MATCH (p:Plan {plan_id: $pid}) DETACH DELETE p",
        params=("pid",),
        mutating=True,
        description="Compensating delete of a Plan node when its write fails partway through.",
    ),
    # -- Plan / PlanStep reads ------------------------------------------------
    NamedQuery(
        name="lessons.find_quest_for_session",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q)
            RETURN q.quest_id AS quest_id LIMIT 1
            """,
        params=("sid",),
        mutating=False,
        description="Resolve the quest a Session is currently working on, if any.",
    ),
    NamedQuery(
        name="lessons.list_plan_step_ids",
        cypher="""
            MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
            RETURN ps.step_id AS step_id ORDER BY ps.step_number ASC
            """,
        params=("pid",),
        mutating=False,
        description="List the step_ids of a Plan's PlanSteps, in order (B320 dedup-hit branch).",
    ),
    NamedQuery(
        name="lessons.find_quest_for_plan",
        cypher="""
            MATCH (p:Plan {plan_id: $pid})-[:TARGETS]->(q)
            RETURN q.quest_id AS quest_id LIMIT 1
            """,
        params=("pid",),
        mutating=False,
        description="Resolve the quest a Plan targets, if any (B320 dedup-hit branch).",
    ),
    NamedQuery(
        name="lessons.list_plan_steps_for_feedback",
        cypher="""
            MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
            RETURN ps.step_number AS step_number, ps.description AS description,
                   ps.valence AS valence, ps.status AS status
            ORDER BY ps.step_number ASC
            """,
        params=("pid",),
        mutating=False,
        description="List a similar Plan's steps for the amygdala-reflex warning/suggestion payload.",
    ),
    # -- Plan-outcome Lesson (writes) ------------------------------------------
    NamedQuery(
        name="lessons.create_plan_outcome_lesson",
        cypher="""
            CREATE (l:Lesson {
                lesson_id: $lesson_id,
                text_raw: $text_raw,
                embedding: $embedding,
                embedding_model: $embedding_model,
                embedding_dim: $embedding_dim,
                domain: 'planning',
                lesson_type: 'optimization',
                confidence: 0.85,
                confidence_low: false,
                pathway_strength: 0.85,
                archived: false,
                created_at: timestamp($created_at),
                source: $prov_source,
                source_version: $prov_source_version,
                observed_at: timestamp($prov_observed_at),
                evidence_ref: $prov_evidence_ref,
                content_hash: $content_hash
            })
            """,
        params=(
            "lesson_id", "text_raw", "embedding", "embedding_model", "embedding_dim",
            "created_at", "prov_source", "prov_source_version", "prov_observed_at",
            "prov_evidence_ref", "content_hash",
        ),
        mutating=True,
        description="Create a Lesson synthesized from a strong-valence Plan outcome.",
    ),
    NamedQuery(
        name="lessons.link_plan_to_lesson",
        cypher="""
            MATCH (p:Plan {plan_id: $pid}), (l:Lesson {lesson_id: $lid})
            MERGE (p)-[:PRODUCED_PLAN_LESSON]->(l)
            """,
        params=("pid", "lid"),
        mutating=True,
        description="Link a Plan to the Lesson its outcome produced.",
    ),
    NamedQuery(
        name="lessons.link_session_learned_lesson",
        cypher="""
            MATCH (s:Session {session_id: $sid}), (l:Lesson {lesson_id: $lid})
            MERGE (s)-[:LEARNED]->(l)
            """,
        params=("sid", "lid"),
        mutating=True,
        description="Link a Session to a Lesson it learned (shared by outcome-lesson and upsert_lesson paths).",
    ),
    # -- Quest-synthesis Lesson (writes + per-table artifact reads) -----------
    NamedQuery(
        name="lessons.list_confirmed_decisions",
        cypher="""
            MATCH (a:Decision) WHERE a.archived = false AND a.confidence_low = false
            RETURN a.text_raw AS text_raw, a.confidence AS confidence
            ORDER BY a.pathway_strength DESC LIMIT 5
            """,
        params=(),
        mutating=False,
        description="Top confirmed Decision artifacts for quest-completion lesson synthesis.",
    ),
    NamedQuery(
        name="lessons.list_confirmed_constraints",
        cypher="""
            MATCH (a:Constraint) WHERE a.archived = false AND a.confidence_low = false
            RETURN a.text_raw AS text_raw, a.confidence AS confidence
            ORDER BY a.pathway_strength DESC LIMIT 5
            """,
        params=(),
        mutating=False,
        description="Top confirmed Constraint artifacts for quest-completion lesson synthesis.",
    ),
    NamedQuery(
        name="lessons.list_confirmed_requirements",
        cypher="""
            MATCH (a:Requirement) WHERE a.archived = false AND a.confidence_low = false
            RETURN a.text_raw AS text_raw, a.confidence AS confidence
            ORDER BY a.pathway_strength DESC LIMIT 5
            """,
        params=(),
        mutating=False,
        description="Top confirmed Requirement artifacts for quest-completion lesson synthesis.",
    ),
    NamedQuery(
        name="lessons.create_quest_synthesis_lesson",
        cypher="""
            CREATE (l:Lesson {
                lesson_id:        $lesson_id,
                text_raw:         $text_raw,
                embedding:        $embedding,
                embedding_model:  $embedding_model,
                embedding_dim:    $embedding_dim,
                domain:           'generic',
                lesson_type:      'optimization',
                confidence:       0.70,
                confidence_low:   true,
                pathway_strength: 0.70,
                archived:         false,
                created_at:       timestamp($created_at)
            })
            """,
        params=("lesson_id", "text_raw", "embedding", "embedding_model", "embedding_dim", "created_at"),
        mutating=True,
        description="Create the LLM-synthesized Lesson for a completed quest (B11).",
    ),
    NamedQuery(
        name="lessons.link_quest_to_lesson",
        cypher="""
            MATCH (q:MainQuest {quest_id: $qid}), (l:Lesson {lesson_id: $lid})
            CREATE (q)-[:PRODUCED_LESSON]->(l)
            """,
        params=("qid", "lid"),
        mutating=True,
        description="Link a completed MainQuest to its synthesized Lesson.",
    ),
    # -- upsert_lesson (writes + read) -----------------------------------------
    NamedQuery(
        name="lessons.find_lesson_by_id",
        cypher="MATCH (l:Lesson {lesson_id: $lid}) RETURN l.lesson_id AS lesson_id",
        params=("lid",),
        mutating=False,
        description="Check whether a Lesson with this id already exists (KuzuDB 0.11.3: MERGE incompatible with vector-indexed tables).",
    ),
    NamedQuery(
        name="lessons.create_lesson",
        cypher="""
            CREATE (l:Lesson {
                lesson_id:        $lid,
                text_raw:         $text,
                embedding:        $emb,
                embedding_model:  $model,
                embedding_dim:    $dim,
                domain:           $domain,
                lesson_type:      $type,
                scene_wl_hash:    $scene_wl_hash,
                scene_graph_vector: $scene_graph_vector,
                archetype:        $archetype,
                progress_score:   $progress_score,
                valence:          $valence,
                confidence:       0.90,
                confidence_low:   false,
                pathway_strength: 1.0,
                archived:         false,
                created_at:       timestamp($now),
                trigger_pattern:       $trig_pattern,
                trigger_hook_type:     $trig_hook_type,
                trigger_tool:          $trig_tool,
                trigger_project_scope: $trig_scope,
                source:                $prov_source,
                source_version:        $prov_source_version,
                observed_at:           timestamp($prov_observed_at),
                evidence_ref:          $prov_evidence_ref,
                content_hash:          $content_hash
            })
            """,
        params=(
            "lid", "text", "emb", "model", "dim", "domain", "type", "scene_wl_hash",
            "scene_graph_vector", "archetype", "progress_score", "valence", "now",
            "trig_pattern", "trig_hook_type", "trig_tool", "trig_scope", "prov_source",
            "prov_source_version", "prov_observed_at", "prov_evidence_ref", "content_hash",
        ),
        mutating=True,
        description="Create a Lesson node via the explicit upsert_lesson tool.",
    ),
    NamedQuery(
        name="lessons.update_lesson",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid})
            SET l.text_raw         = $text,
                l.domain           = $domain,
                l.lesson_type      = $type,
                l.scene_wl_hash    = $scene_wl_hash,
                l.scene_graph_vector = $scene_graph_vector,
                l.archetype        = $archetype,
                l.progress_score   = $progress_score,
                l.valence          = $valence,
                l.pathway_strength = l.pathway_strength + 0.1,
                l.trigger_pattern       = $trig_pattern,
                l.trigger_hook_type     = $trig_hook_type,
                l.trigger_tool          = $trig_tool,
                l.trigger_project_scope = $trig_scope,
                l.source                = $prov_source,
                l.source_version        = $prov_source_version,
                l.observed_at           = timestamp($prov_observed_at),
                l.evidence_ref          = $prov_evidence_ref,
                l.content_hash          = $content_hash
            """,
        params=(
            "lid", "text", "domain", "type", "scene_wl_hash", "scene_graph_vector",
            "archetype", "progress_score", "valence", "trig_pattern", "trig_hook_type",
            "trig_tool", "trig_scope", "prov_source", "prov_source_version",
            "prov_observed_at", "prov_evidence_ref", "content_hash",
        ),
        mutating=True,
        description="Update a Lesson's non-embedding fields on a caller-supplied-id re-upsert (bumps pathway_strength).",
    ),
    # -- recall_relevant_lessons -----------------------------------------------
    NamedQuery(
        name="lessons.list_lessons_by_domain",
        cypher="""
            MATCH (l:Lesson) WHERE l.domain = $domain AND l.archived = false
            RETURN l.lesson_id AS lesson_id, l.text_raw AS text_raw, l.lesson_type AS lesson_type
            LIMIT $limit
            """,
        params=("domain", "limit"),
        mutating=False,
        description="List Lessons by domain (recall_relevant_lessons' non-similarity path).",
    ),
    # -- recall_scene_graph_priors -----------------------------------------------
    NamedQuery(
        name="lessons.list_scene_graph_priors",
        cypher="""
            MATCH (l:Lesson)
            WHERE l.archived = false AND l.scene_wl_hash = $wl_hash
            AND l.progress_score IS NOT NULL
            AND (l.valence IS NULL OR l.valence >= $min_valence)
            AND ($archetype = '' OR l.archetype = $archetype)
            RETURN l.lesson_id AS lesson_id, l.progress_score AS progress_score,
                   l.valence AS valence, l.archetype AS archetype, l.text_raw AS text
            ORDER BY l.created_at DESC LIMIT $limit
            """,
        params=("wl_hash", "min_valence", "archetype", "limit"),
        mutating=False,
        description="Evidence-weighted priors for a scene-graph WL-hash signature.",
    ),
)
