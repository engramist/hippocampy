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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?p a campy:Plan ;
                 campy:plan_id ?plan_id ;
                 campy:goal ?goal ;
                 campy:strategy ?strategy ;
                 campy:source ?source ;
                 campy:embedding ?embedding ;
                 campy:embedding_model ?embedding_model ;
                 campy:embedding_dim ?embedding_dim ;
                 campy:step_count ?step_count ;
                 campy:status "active" ;
                 campy:confidence ?confidence ;
                 campy:confidence_low ?confidence_low ;
                 campy:pathway_strength ?pathway_strength ;
                 campy:archived false ;
                 campy:created_at ?created_at ;
                 campy:source_version ?prov_source_version ;
                 campy:observed_at ?prov_observed_at ;
                 campy:evidence_ref ?prov_evidence_ref ;
                 campy:content_hash ?content_hash .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Plan/", ENCODE_FOR_URI(STR(?plan_id)))) AS ?p)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?ps a campy:PlanStep ;
                  campy:step_id ?step_id ;
                  campy:step_number ?step_number ;
                  campy:description ?description ;
                  campy:embedding ?embedding ;
                  campy:embedding_model ?embedding_model ;
                  campy:embedding_dim ?embedding_dim ;
                  campy:status "pending" ;
                  campy:created_at ?created_at ;
                  campy:source ?prov_source ;
                  campy:source_version ?prov_source_version ;
                  campy:observed_at ?prov_observed_at ;
                  campy:evidence_ref ?prov_evidence_ref .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/PlanStep/", ENCODE_FOR_URI(STR(?step_id)))) AS ?ps)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?ps campy:STEP_OF ?p .
            }
            WHERE {
              ?ps a campy:PlanStep ; campy:step_id ?step_id .
              ?p a campy:Plan ; campy:plan_id ?plan_id .
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?ps campy:ACTS_ON ?c .
            }
            WHERE {
              VALUES ?cid { }
              ?ps a campy:PlanStep ; campy:step_id ?sid .
              ?c a campy:Concept ; campy:concept_id ?cid .
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?p campy:PLANNED_IN ?s .
            }
            WHERE {
              ?p a campy:Plan ; campy:plan_id ?plan_id .
              ?s a campy:Session ; campy:session_id ?session_id .
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?p campy:TARGETS ?q .
            }
            WHERE {
              ?p a campy:Plan ; campy:plan_id ?plan_id .
              ?q a campy:MainQuest ; campy:quest_id ?quest_id .
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?p campy:TARGETS ?q .
            }
            WHERE {
              ?p a campy:Plan ; campy:plan_id ?plan_id .
              ?q a campy:SideQuest ; campy:quest_id ?quest_id .
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?x campy:NEXT_STEP ?y .
            }
            WHERE {
              VALUES (?pair_a ?pair_b) { }
              ?x a campy:PlanStep ; campy:step_id ?pair_a .
              ?y a campy:PlanStep ; campy:step_id ?pair_b .
            }
        """,
    ),
    NamedQuery(
        name="lessons.delete_plan_steps",
        cypher="UNWIND $ids AS sid MATCH (ps:PlanStep {step_id: sid}) DETACH DELETE ps",
        params=("ids",),
        mutating=True,
        description="Compensating delete of PlanStep nodes when a Plan write fails partway through.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?ps ?p ?o .
              ?s ?p2 ?ps .
            }
            WHERE {
              VALUES ?sid { }
              ?ps a campy:PlanStep ; campy:step_id ?sid .
              OPTIONAL { ?ps ?p ?o }
              OPTIONAL { ?s ?p2 ?ps }
            }
        """,
    ),
    NamedQuery(
        name="lessons.delete_plan",
        cypher="MATCH (p:Plan {plan_id: $pid}) DETACH DELETE p",
        params=("pid",),
        mutating=True,
        description="Compensating delete of a Plan node when its write fails partway through.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?p ?prop ?o .
              ?s ?prop2 ?p .
            }
            WHERE {
              ?p a campy:Plan ; campy:plan_id ?pid .
              OPTIONAL { ?p ?prop ?o }
              OPTIONAL { ?s ?prop2 ?p }
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?quest_id
            WHERE {
              ?s a campy:Session ; campy:session_id ?sid ;
                 campy:WORKING_ON ?q .
              ?q campy:quest_id ?quest_id .
            }
            LIMIT 1
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?step_id
            WHERE {
              ?p a campy:Plan ; campy:plan_id ?pid .
              ?ps a campy:PlanStep ;
                  campy:STEP_OF ?p ;
                  campy:step_id ?step_id ;
                  campy:step_number ?step_number .
            }
            ORDER BY ASC(?step_number)
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?quest_id
            WHERE {
              ?p a campy:Plan ; campy:plan_id ?pid ;
                 campy:TARGETS ?q .
              ?q campy:quest_id ?quest_id .
            }
            LIMIT 1
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?step_number ?description ?valence ?status
            WHERE {
              ?p a campy:Plan ; campy:plan_id ?pid .
              ?ps a campy:PlanStep ;
                  campy:STEP_OF ?p ;
                  campy:step_number ?step_number ;
                  campy:description ?description ;
                  campy:status ?status .
              OPTIONAL { ?ps campy:valence ?valence }
            }
            ORDER BY ASC(?step_number)
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?l a campy:Lesson ;
                 campy:lesson_id ?lesson_id ;
                 campy:text_raw ?text_raw ;
                 campy:embedding ?embedding ;
                 campy:embedding_model ?embedding_model ;
                 campy:embedding_dim ?embedding_dim ;
                 campy:domain "planning" ;
                 campy:lesson_type "optimization" ;
                 campy:confidence "0.85"^^xsd:double ;
                 campy:confidence_low false ;
                 campy:pathway_strength "0.85"^^xsd:double ;
                 campy:archived false ;
                 campy:created_at ?created_at ;
                 campy:source ?prov_source ;
                 campy:source_version ?prov_source_version ;
                 campy:observed_at ?prov_observed_at ;
                 campy:evidence_ref ?prov_evidence_ref ;
                 campy:content_hash ?content_hash .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Lesson/", ENCODE_FOR_URI(STR(?lesson_id)))) AS ?l)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?p campy:PRODUCED_PLAN_LESSON ?l .
            }
            WHERE {
              ?p a campy:Plan ; campy:plan_id ?pid .
              ?l a campy:Lesson ; campy:lesson_id ?lid .
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?s campy:LEARNED ?l .
            }
            WHERE {
              ?s a campy:Session ; campy:session_id ?sid .
              ?l a campy:Lesson ; campy:lesson_id ?lid .
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?text_raw ?confidence
            WHERE {
              ?a a campy:Decision ;
                 campy:text_raw ?text_raw ;
                 campy:confidence ?confidence ;
                 campy:pathway_strength ?pathway_strength .
              OPTIONAL { ?a campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
              OPTIONAL { ?a campy:confidence_low ?confidence_low }
              FILTER(!BOUND(?confidence_low) || ?confidence_low = false)
            }
            ORDER BY DESC(?pathway_strength)
            LIMIT 5
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?text_raw ?confidence
            WHERE {
              ?a a campy:Constraint ;
                 campy:text_raw ?text_raw ;
                 campy:confidence ?confidence ;
                 campy:pathway_strength ?pathway_strength .
              OPTIONAL { ?a campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
              OPTIONAL { ?a campy:confidence_low ?confidence_low }
              FILTER(!BOUND(?confidence_low) || ?confidence_low = false)
            }
            ORDER BY DESC(?pathway_strength)
            LIMIT 5
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?text_raw ?confidence
            WHERE {
              ?a a campy:Requirement ;
                 campy:text_raw ?text_raw ;
                 campy:confidence ?confidence ;
                 campy:pathway_strength ?pathway_strength .
              OPTIONAL { ?a campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
              OPTIONAL { ?a campy:confidence_low ?confidence_low }
              FILTER(!BOUND(?confidence_low) || ?confidence_low = false)
            }
            ORDER BY DESC(?pathway_strength)
            LIMIT 5
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?l a campy:Lesson ;
                 campy:lesson_id ?lesson_id ;
                 campy:text_raw ?text_raw ;
                 campy:embedding ?embedding ;
                 campy:embedding_model ?embedding_model ;
                 campy:embedding_dim ?embedding_dim ;
                 campy:domain "generic" ;
                 campy:lesson_type "optimization" ;
                 campy:confidence "0.70"^^xsd:double ;
                 campy:confidence_low true ;
                 campy:pathway_strength "0.70"^^xsd:double ;
                 campy:archived false ;
                 campy:created_at ?created_at .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Lesson/", ENCODE_FOR_URI(STR(?lesson_id)))) AS ?l)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?q campy:PRODUCED_LESSON ?l .
            }
            WHERE {
              ?q a campy:MainQuest ; campy:quest_id ?qid .
              ?l a campy:Lesson ; campy:lesson_id ?lid .
            }
        """,
    ),
    # -- upsert_lesson (writes + read) -----------------------------------------
    NamedQuery(
        name="lessons.find_lesson_by_id",
        cypher="MATCH (l:Lesson {lesson_id: $lid}) RETURN l.lesson_id AS lesson_id",
        params=("lid",),
        mutating=False,
        description="Check whether a Lesson with this id already exists (KuzuDB 0.11.3: MERGE incompatible with vector-indexed tables).",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?lesson_id
            WHERE {
              ?l a campy:Lesson ; campy:lesson_id ?lid .
              BIND(?lid AS ?lesson_id)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?l a campy:Lesson ;
                 campy:lesson_id ?lid ;
                 campy:text_raw ?text ;
                 campy:embedding ?emb ;
                 campy:embedding_model ?model ;
                 campy:embedding_dim ?dim ;
                 campy:domain ?domain ;
                 campy:lesson_type ?type ;
                 campy:scene_wl_hash ?scene_wl_hash ;
                 campy:scene_graph_vector ?scene_graph_vector ;
                 campy:archetype ?archetype ;
                 campy:progress_score ?progress_score ;
                 campy:valence ?valence ;
                 campy:confidence "0.90"^^xsd:double ;
                 campy:confidence_low false ;
                 campy:pathway_strength "1.0"^^xsd:double ;
                 campy:archived false ;
                 campy:created_at ?now ;
                 campy:trigger_pattern ?trig_pattern ;
                 campy:trigger_hook_type ?trig_hook_type ;
                 campy:trigger_tool ?trig_tool ;
                 campy:trigger_project_scope ?trig_scope ;
                 campy:source ?prov_source ;
                 campy:source_version ?prov_source_version ;
                 campy:observed_at ?prov_observed_at ;
                 campy:evidence_ref ?prov_evidence_ref ;
                 campy:content_hash ?content_hash .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Lesson/", ENCODE_FOR_URI(STR(?lid)))) AS ?l)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            DELETE {
              ?l campy:text_raw ?old_text .
              ?l campy:domain ?old_dom .
              ?l campy:lesson_type ?old_type .
              ?l campy:scene_wl_hash ?old_wl .
              ?l campy:scene_graph_vector ?old_sgv .
              ?l campy:archetype ?old_arch .
              ?l campy:progress_score ?old_prog .
              ?l campy:valence ?old_val .
              ?l campy:pathway_strength ?old_ps .
              ?l campy:trigger_pattern ?old_tp .
              ?l campy:trigger_hook_type ?old_tht .
              ?l campy:trigger_tool ?old_tt .
              ?l campy:trigger_project_scope ?old_tps .
              ?l campy:source ?old_src .
              ?l campy:source_version ?old_sv .
              ?l campy:observed_at ?old_oa .
              ?l campy:evidence_ref ?old_er .
              ?l campy:content_hash ?old_ch .
            }
            INSERT {
              ?l campy:text_raw ?text .
              ?l campy:domain ?domain .
              ?l campy:lesson_type ?type .
              ?l campy:scene_wl_hash ?scene_wl_hash .
              ?l campy:scene_graph_vector ?scene_graph_vector .
              ?l campy:archetype ?archetype .
              ?l campy:progress_score ?progress_score .
              ?l campy:valence ?valence .
              ?l campy:pathway_strength ?new_ps .
              ?l campy:trigger_pattern ?trig_pattern .
              ?l campy:trigger_hook_type ?trig_hook_type .
              ?l campy:trigger_tool ?trig_tool .
              ?l campy:trigger_project_scope ?trig_scope .
              ?l campy:source ?prov_source .
              ?l campy:source_version ?prov_source_version .
              ?l campy:observed_at ?prov_observed_at .
              ?l campy:evidence_ref ?prov_evidence_ref .
              ?l campy:content_hash ?content_hash .
            }
            WHERE {
              ?l a campy:Lesson ; campy:lesson_id ?lid .
              OPTIONAL { ?l campy:text_raw ?old_text }
              OPTIONAL { ?l campy:domain ?old_dom }
              OPTIONAL { ?l campy:lesson_type ?old_type }
              OPTIONAL { ?l campy:scene_wl_hash ?old_wl }
              OPTIONAL { ?l campy:scene_graph_vector ?old_sgv }
              OPTIONAL { ?l campy:archetype ?old_arch }
              OPTIONAL { ?l campy:progress_score ?old_prog }
              OPTIONAL { ?l campy:valence ?old_val }
              OPTIONAL { ?l campy:pathway_strength ?old_ps }
              OPTIONAL { ?l campy:trigger_pattern ?old_tp }
              OPTIONAL { ?l campy:trigger_hook_type ?old_tht }
              OPTIONAL { ?l campy:trigger_tool ?old_tt }
              OPTIONAL { ?l campy:trigger_project_scope ?old_tps }
              OPTIONAL { ?l campy:source ?old_src }
              OPTIONAL { ?l campy:source_version ?old_sv }
              OPTIONAL { ?l campy:observed_at ?old_oa }
              OPTIONAL { ?l campy:evidence_ref ?old_er }
              OPTIONAL { ?l campy:content_hash ?old_ch }
              BIND(COALESCE(?old_ps + "0.1"^^xsd:double, "0.1"^^xsd:double) AS ?new_ps)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?lesson_id ?text_raw ?lesson_type
            WHERE {
              ?l a campy:Lesson ;
                 campy:domain ?domain ;
                 campy:lesson_id ?lesson_id ;
                 campy:text_raw ?text_raw ;
                 campy:lesson_type ?lesson_type .
              OPTIONAL { ?l campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?lesson_id ?progress_score ?valence ?archetype ?text
            WHERE {
              ?l a campy:Lesson ;
                 campy:lesson_id ?lesson_id ;
                 campy:scene_wl_hash ?wl_hash ;
                 campy:progress_score ?progress_score ;
                 campy:created_at ?created_at .
              OPTIONAL { ?l campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
              OPTIONAL { ?l campy:valence ?valence }
              FILTER(!BOUND(?valence) || ?valence >= ?min_valence)
              OPTIONAL { ?l campy:archetype ?archetype }
              FILTER(?archetype_filter = "" || ?archetype = ?archetype_filter)
              OPTIONAL { ?l campy:text_raw ?text }
            }
            ORDER BY DESC(?created_at)
        """,
    ),
)
