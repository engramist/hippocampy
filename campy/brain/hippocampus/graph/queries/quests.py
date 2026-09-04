"""campy/brain/hippocampus/graph/queries/quests.py — Named queries for quest and session management."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

QUEST_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="quests.get_main_quest_by_id",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) RETURN q.quest_id",
        params=("qid",),
        mutating=False,
        description="Check if MainQuest exists by quest_id.",
    ),
    NamedQuery(
        name="quests.touch_main_quest",
        cypher="MATCH (q:MainQuest {quest_id: $quest_id}) SET q.last_active_at = timestamp($now)",
        params=("quest_id", "now"),
        mutating=True,
        description="Update last_active_at timestamp on MainQuest.",
    ),
    NamedQuery(
        name="quests.create_main_quest",
        cypher="""
            CREATE (q:MainQuest {
                quest_id:           $quest_id,
                name:               $name,
                status:             $status,
                completed_at:       null,
                purpose:            $purpose,
                text_raw:           $name,
                embedding:          $embedding,
                embedding_model:    $embedding_model,
                embedding_dim:      $embedding_dim,
                confidence:         1.0,
                confidence_low:     false,
                pathway_strength:   1.0,
                archived:           false,
                created_at:         timestamp($created_at),
                last_active_at:     timestamp($last_active_at),
                git_repo_root:      $git_repo_root,
                purpose_embedding:  $purpose_embedding,
                routing_method:     $routing_method
            })
            """,
        params=(
            "quest_id", "name", "status", "purpose", "embedding", "embedding_model",
            "embedding_dim", "created_at", "last_active_at", "git_repo_root",
            "purpose_embedding", "routing_method",
        ),
        mutating=True,
        description="Create a new MainQuest node.",
    ),
    NamedQuery(
        name="quests.merge_session_git_locked",
        cypher="""
            MERGE (s:Session {session_id: $sid})
            ON CREATE SET s.started_at          = timestamp($now),
                          s.last_active_at      = timestamp($now),
                          s.onboarded           = false,
                          s.purpose             = '',
                          s.routing_state       = 'locked',
                          s.routing_confidence  = 0.95,
                          s.routing_method      = 'git'
            ON MATCH SET  s.last_active_at      = timestamp($now),
                          s.routing_state       = 'locked',
                          s.routing_confidence  = 0.95,
                          s.routing_method      = 'git'
            """,
        params=("sid", "now"),
        mutating=True,
        description="Merge Session node and set git-locked routing metadata.",
    ),
    NamedQuery(
        name="quests.merge_session",
        cypher="""
            MERGE (s:Session {session_id: $sid})
            ON CREATE SET s.started_at          = timestamp($now),
                          s.last_active_at      = timestamp($now),
                          s.onboarded           = false,
                          s.purpose             = '',
                          s.routing_state       = $routing_state,
                          s.routing_confidence  = $routing_confidence,
                          s.routing_method      = $routing_method
            ON MATCH SET  s.last_active_at      = timestamp($now),
                          s.routing_state       = $routing_state,
                          s.routing_confidence  = $routing_confidence,
                          s.routing_method      = $routing_method
            """,
        params=("sid", "now", "routing_state", "routing_confidence", "routing_method"),
        mutating=True,
        description="Merge Session node and update routing metadata.",
    ),
    NamedQuery(
        name="quests.link_session_quest",
        cypher="""
            MATCH (s:Session {session_id: $sid}),
                  (q:MainQuest {quest_id: $qid})
            MERGE (s)-[:WORKING_ON]->(q)
            """,
        params=("sid", "qid"),
        mutating=True,
        description="Link Session to MainQuest via WORKING_ON.",
    ),
    NamedQuery(
        name="quests.create_side_quest",
        cypher="""
            CREATE (sq:SideQuest {
                quest_id:         $quest_id,
                name:             $name,
                status:           'active',
                completed_at:     null,
                purpose:          $purpose,
                text_raw:         $text_raw,
                embedding:        $embedding,
                embedding_model:  $embedding_model,
                embedding_dim:    $embedding_dim,
                confidence:       1.0,
                confidence_low:   false,
                pathway_strength: 1.0,
                archived:         false,
                created_at:       timestamp($created_at)
            })
            """,
        params=(
            "quest_id", "name", "purpose", "text_raw", "embedding",
            "embedding_model", "embedding_dim", "created_at",
        ),
        mutating=True,
        description="Create a new SideQuest node.",
    ),
    NamedQuery(
        name="quests.link_side_quest",
        cypher="""
            MATCH (sq:SideQuest {quest_id: $sqid}),
                  (mq:MainQuest {quest_id: $mqid})
            CREATE (sq)-[:BELONGS_TO]->(mq)
            """,
        params=("sqid", "mqid"),
        mutating=True,
        description="Link SideQuest to MainQuest via BELONGS_TO.",
    ),
    NamedQuery(
        name="quests.get_quest_name_and_status",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) RETURN q.name, q.status",
        params=("qid",),
        mutating=False,
        description="Fetch MainQuest name and status.",
    ),
    NamedQuery(
        name="quests.get_open_loop_concepts",
        cypher="""
            MATCH (c:Concept {confidence_low: true, archived: false})
            WHERE c.created_at IS NOT NULL
            RETURN c.concept_id, c.text_raw, c.gist_class, c.confidence
            ORDER BY c.created_at DESC
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch confidence_low Concepts as open loops.",
    ),
    NamedQuery(
        name="quests.get_active_side_quests",
        cypher="""
            MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest {quest_id: $qid})
            WHERE sq.status = 'active'
            RETURN sq.quest_id, sq.name, sq.purpose
            LIMIT $limit
            """,
        params=("qid", "limit"),
        mutating=False,
        description="Fetch active SideQuests belonging to a MainQuest.",
    ),
    NamedQuery(
        name="quests.get_quest_decisions",
        cypher="""
            MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
            MATCH (m:Message)-[:SENT_IN]->(s)
            MATCH (m)-[:ESTABLISHED]->(a:Decision {archived: false})
            RETURN a.decision_id, a.text_raw, a.confidence_low, a.pathway_strength
            ORDER BY a.pathway_strength DESC
            LIMIT $limit
            """,
        params=("qid", "limit"),
        mutating=False,
        description="Fetch recent Decisions for a MainQuest.",
    ),
    NamedQuery(
        name="quests.get_quest_constraints",
        cypher="""
            MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
            MATCH (m:Message)-[:SENT_IN]->(s)
            MATCH (m)-[:ESTABLISHED]->(a:Constraint {archived: false})
            RETURN a.constraint_id, a.text_raw, a.confidence_low, a.pathway_strength
            ORDER BY a.pathway_strength DESC
            LIMIT $limit
            """,
        params=("qid", "limit"),
        mutating=False,
        description="Fetch recent Constraints for a MainQuest.",
    ),
    NamedQuery(
        name="quests.get_quest_concepts",
        cypher="""
            MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
            MATCH (m:Message)-[:SENT_IN]->(s)
            MATCH (m)-[:ESTABLISHED]->(a:Concept {archived: false})
            RETURN a.concept_id, a.text_raw, a.confidence_low, a.pathway_strength
            ORDER BY a.pathway_strength DESC
            LIMIT $limit
            """,
        params=("qid", "limit"),
        mutating=False,
        description="Fetch recent Concepts for a MainQuest.",
    ),
    NamedQuery(
        name="quests.get_session_by_message",
        cypher="""
            MATCH (m:Message {message_id: $mid})-[:SENT_IN]->(s:Session)
            RETURN s.session_id, s.purpose
            """,
        params=("mid",),
        mutating=False,
        description="Fetch Session id and purpose for a Message.",
    ),
    NamedQuery(
        name="quests.get_quest_by_session",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest)
            RETURN q.quest_id, q.name
            """,
        params=("sid",),
        mutating=False,
        description="Fetch MainQuest working on by a Session.",
    ),
    NamedQuery(
        name="quests.get_session_messages",
        cypher="""
            MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})
            RETURN m.text_raw, m.role
            ORDER BY m.created_at ASC
            LIMIT $limit
            """,
        params=("sid", "limit"),
        mutating=False,
        description="Fetch recent messages for a session.",
    ),
    NamedQuery(
        name="quests.set_session_purpose",
        cypher="MATCH (s:Session {session_id: $sid}) SET s.purpose = $purpose",
        params=("sid", "purpose"),
        mutating=True,
        description="Set Session purpose.",
    ),
    NamedQuery(
        name="quests.set_main_quest_purpose",
        cypher="""
            MATCH (q:MainQuest {quest_id: $qid})
            WHERE q.purpose = $default OR q.purpose IS NULL
            SET q.purpose = $purpose
            """,
        params=("qid", "default", "purpose"),
        mutating=True,
        description="Set MainQuest purpose if not already set.",
    ),
    NamedQuery(
        name="quests.check_session_binding",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest)
            RETURN q.quest_id, s.routing_confidence, s.routing_method, s.routing_state
            """,
        params=("sid",),
        mutating=False,
        description="Check existing session binding to a MainQuest.",
    ),
    NamedQuery(
        name="quests.find_active_by_git_root",
        cypher="""
            MATCH (q:MainQuest)
            WHERE q.git_repo_root = $root AND q.status = 'active'
            RETURN q.quest_id LIMIT 1
            """,
        params=("root",),
        mutating=False,
        description="Find active MainQuest by git_repo_root.",
    ),
    NamedQuery(
        name="quests.find_active_by_id",
        cypher="""
            MATCH (q:MainQuest {quest_id: $qid})
            WHERE q.status = 'active'
            RETURN q.quest_id LIMIT 1
            """,
        params=("qid",),
        mutating=False,
        description="Find active MainQuest by quest_id.",
    ),
    NamedQuery(
        name="quests.get_active_with_embeddings",
        cypher="""
            MATCH (q:MainQuest)
            WHERE q.status = 'active' AND q.archived = false
            RETURN q.quest_id, q.purpose_embedding, q.name, q.purpose, q.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch active MainQuests with embeddings.",
    ),
    NamedQuery(
        name="quests.find_active_by_workspace_path",
        cypher="""
            MATCH (q:MainQuest)-[:ANCHORED_TO]->(w:Workspace {path: $path})
            WHERE q.status = 'active'
            RETURN q.quest_id
            """,
        params=("path",),
        mutating=False,
        description="Find active MainQuests anchored to a workspace path.",
    ),
    NamedQuery(
        name="quests.get_quest_name_purpose",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) RETURN q.name, q.purpose",
        params=("qid",),
        mutating=False,
        description="Fetch MainQuest name and purpose.",
    ),
    NamedQuery(
        name="quests.set_git_repo_root",
        cypher="""
            MATCH (q:MainQuest {quest_id: $qid})
            WHERE q.git_repo_root IS NULL OR q.git_repo_root = ''
            SET q.git_repo_root = $root
            """,
        params=("qid", "root"),
        mutating=True,
        description="Set git_repo_root on MainQuest if empty.",
    ),
    NamedQuery(
        name="quests.get_session_routing",
        cypher="""
            MATCH (s:Session {session_id: $sid})
            RETURN s.routing_confidence, s.routing_state
            """,
        params=("sid",),
        mutating=False,
        description="Fetch Session routing confidence and state.",
    ),
    NamedQuery(
        name="quests.update_session_routing",
        cypher="""
            MATCH (s:Session {session_id: $sid})
            SET s.routing_confidence = $conf, s.routing_state = $state
            """,
        params=("sid", "conf", "state"),
        mutating=True,
        description="Update Session routing confidence and state.",
    ),
    NamedQuery(
        name="quests.get_session_working_quest_id",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest)
            RETURN q.quest_id
            """,
        params=("sid",),
        mutating=False,
        description="Fetch MainQuest quest_id that Session is working on.",
    ),
    NamedQuery(
        name="quests.delete_session_working_on",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[w:WORKING_ON]->(q:MainQuest {quest_id: $qid})
            DELETE w
            """,
        params=("sid", "qid"),
        mutating=True,
        description="Delete WORKING_ON edge between Session and MainQuest.",
    ),
    NamedQuery(
        name="quests.create_rerouted_from",
        cypher="""
            MATCH (s:Session {session_id: $sid}), (q:MainQuest {quest_id: $qid})
            CREATE (s)-[:REROUTED_FROM {rerouted_at: timestamp($now), reason: $reason}]->(q)
            """,
        params=("sid", "qid", "now", "reason"),
        mutating=True,
        description="Create REROUTED_FROM audit edge between Session and MainQuest.",
    ),

    NamedQuery(
        name="quests.find_active_main_quest_by_name",
        cypher="MATCH (q:MainQuest) WHERE q.name = $name AND q.status = 'active' RETURN q.quest_id LIMIT 1",
        params=("name",),
        mutating=False,
        description="Find active MainQuest by exact name",
    ),
    NamedQuery(
        name="quests.complete_main_quest",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) SET q.status = 'completed', q.completed_at = timestamp($now)",
        params=("qid", "now"),
        mutating=True,
        description="Mark MainQuest completed",
    ),
    NamedQuery(
        name="quests.complete_side_quest",
        cypher="MATCH (q:SideQuest {quest_id: $qid}) SET q.status = 'completed', q.completed_at = timestamp($now)",
        params=("qid", "now"),
        mutating=True,
        description="Mark SideQuest completed",
    ),
    NamedQuery(
        name="quests.set_plan_step_outcome",
        cypher="""
        MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
        WHERE ps.step_number = $step_number
        SET ps.actual_outcome = $outcome,
            ps.valence = $valence,
            ps.status = $status,
            ps.completed_at = timestamp($now)
        """,
        params=("pid", "step_number", "outcome", "valence", "status", "now"),
        mutating=True,
        description="Update PlanStep outcome and status",
    ),
    NamedQuery(
        name="quests.link_plan_step_outcome_signal",
        cypher="""
        MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
        WHERE ps.step_number = $step_number
        MATCH (ps)-[:ACTS_ON]->(c:Concept)
        MERGE (ps)-[o:OUTCOME_SIGNAL]->(c)
        SET o.valence = $valence, o.plan_id = $pid, o.observed_at = timestamp($now)
        """,
        params=("pid", "step_number", "valence", "now"),
        mutating=True,
        description="Merge OUTCOME_SIGNAL from PlanStep to Concept",
    ),
    NamedQuery(
        name="quests.set_plan_valence",
        cypher="""
        MATCH (p:Plan {plan_id: $pid})
        SET p.valence = $valence,
            p.valence_source = $valence_source,
            p.status = 'completed',
            p.completed_at = timestamp($now)
        """,
        params=("pid", "valence", "valence_source", "now"),
        mutating=True,
        description="Update Plan valence and mark completed",
    ),
    NamedQuery(
        name="quests.link_plan_applied_procedure",
        cypher="""
        MATCH (p:Plan {plan_id: $pid}), (pr:Procedure {procedure_id: $proc_id})
        MERGE (p)-[r:APPLIED_PROCEDURE]->(pr)
        SET r.success = $success, r.applied_at = timestamp($now)
        """,
        params=("pid", "proc_id", "success", "now"),
        mutating=True,
        description="Link Plan to applied Procedure with APPLIED_PROCEDURE",
    ),
    NamedQuery(
        name="quests.increment_procedure_counts",
        cypher="""
        MATCH (pr:Procedure {procedure_id: $proc_id})
        SET pr.application_count = coalesce(pr.application_count, 0) + 1,
            pr.success_count = coalesce(pr.success_count, 0) + CASE WHEN $success THEN 1 ELSE 0 END,
            pr.last_applied_at = timestamp($now)
        """,
        params=("proc_id", "success", "now"),
        mutating=True,
        description="Increment Procedure application and success counts",
    ),
    NamedQuery(
        name="quests.update_procedure_success_rate",
        cypher="""
        MATCH (pr:Procedure {procedure_id: $proc_id})
        SET pr.success_rate = CASE WHEN coalesce(pr.application_count,0) > 0
        THEN toFloat(coalesce(pr.success_count,0)) / toFloat(pr.application_count) ELSE 0.0 END
        """,
        params=("proc_id",),
        mutating=True,
        description="Recalculate Procedure success rate",
    ),
    NamedQuery(
        name="quests.get_plan_steps_by_plan_id",
        cypher="""
        MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
        RETURN ps.step_number, ps.description, ps.valence, ps.status
        ORDER BY ps.step_number ASC
        """,
        params=("pid",),
        mutating=False,
        description="Fetch steps for a plan",
    ),
    NamedQuery(
        name="quests.get_all_plans_summary",
        cypher="""
        MATCH (p:Plan) WHERE p.archived = false
        RETURN p.plan_id, p.goal, p.status, p.valence, p.pathway_strength, p.confidence
        """,
        params=(),
        mutating=False,
        description="Fetch all active plans for lexical scan",
    ),
    NamedQuery(
        name="quests.get_procedures_by_archetype",
        cypher="""
        MATCH (p:Procedure) WHERE p.archived = false AND p.archetype = $arch
        RETURN p.procedure_id, p.name, p.description, p.steps_json, p.success_count, p.success_rate
        ORDER BY p.success_rate DESC, p.success_count DESC LIMIT $lim
        """,
        params=("arch", "lim"),
        mutating=False,
        description="Fetch procedures by archetype ordered by success rate",
    ),
    NamedQuery(
        name="quests.get_pending_disambiguation_events",
        cypher="""
        MATCH (e:DisambiguationEvent)
        WHERE e.status = 'pending'
        RETURN e.event_id, e.concept_id_a, e.concept_id_b, e.similarity, e.created_at
        ORDER BY e.created_at DESC LIMIT $lim
        """,
        params=("lim",),
        mutating=False,
        description="Fetch pending disambiguation events",
    ),
    NamedQuery(
        name="quests.get_concept_with_alt_labels",
        cypher="""
        MATCH (c:Concept {concept_id: $cid})
        OPTIONAL MATCH (c)-[:HAS_ALT_LABEL]->(l:Label)
        RETURN c.concept_id, c.text_raw, c.gist_class, c.confidence,
               c.pathway_strength, c.confidence_low, collect(l.text) AS alt_labels
        """,
        params=("cid",),
        mutating=False,
        description="Fetch concept details and alt labels",
    ),
    NamedQuery(
        name="quests.get_common_neighbors_concepts",
        cypher="""
        MATCH (a:Concept {concept_id: $a})-[]->(n:Concept)<-[]-(b:Concept {concept_id: $b})
        WHERE n.archived = false
        RETURN DISTINCT n.concept_id, n.text_raw LIMIT 10
        """,
        params=("a", "b"),
        mutating=False,
        description="Fetch common neighbors between two concepts",
    ),
    NamedQuery(
        name="quests.get_disambiguation_event_by_id",
        cypher="""
        MATCH (e:DisambiguationEvent {event_id: $eid})
        RETURN e.concept_id_a, e.concept_id_b, e.status
        """,
        params=("eid",),
        mutating=False,
        description="Fetch disambiguation event by id",
    ),
    NamedQuery(
        name="quests.get_two_concepts_details",
        cypher="""
        MATCH (a:Concept {concept_id: $a}), (b:Concept {concept_id: $b})
        RETURN a.concept_id, a.created_at, a.text_raw, b.concept_id, b.created_at, b.text_raw
        """,
        params=("a", "b"),
        mutating=False,
        description="Fetch details for two concepts for disambiguation",
    ),
    NamedQuery(
        name="quests.create_alt_label",
        cypher="""
        CREATE (l:Label {
          label_id: $lid, text: $txt, label_type: 'alternative',
          confidence: 0.95, source: 'user', language: 'en', created_at: timestamp($now)
        })
        """,
        params=("lid", "txt", "now"),
        mutating=True,
        description="Create alternative Label node",
    ),
    NamedQuery(
        name="quests.set_label_embedding",
        cypher="""
        MATCH (l:Label {label_id: $lid}) SET l.embedding = $emb
        """,
        params=("lid", "emb"),
        mutating=True,
        description="Set embedding on Label node",
    ),
    NamedQuery(
        name="quests.link_concept_has_alt_label",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid})
        CREATE (c)-[:HAS_ALT_LABEL {created_at: timestamp($now)}]->(l)
        """,
        params=("cid", "lid", "now"),
        mutating=True,
        description="Link Concept to Label via HAS_ALT_LABEL",
    ),
    NamedQuery(
        name="quests.archive_concept",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}) SET c.archived = true
        """,
        params=("cid",),
        mutating=True,
        description="Archive Concept node",
    ),
    NamedQuery(
        name="quests.boost_canonical_concept",
        cypher="""
        MATCH (c:Concept {concept_id: $cid})
        SET c.pathway_strength = c.pathway_strength + 0.15,
            c.confidence_low = false,
            c.last_accessed_at = timestamp($now)
        """,
        params=("cid", "now"),
        mutating=True,
        description="Boost canonical Concept pathway_strength and touch last_accessed_at",
    ),
    NamedQuery(
        name="quests.link_distinct_from",
        cypher="""
        MATCH (a:Concept {concept_id: $a}), (b:Concept {concept_id: $b})
        SET a.confidence_low = false, b.confidence_low = false
        CREATE (a)-[:DISTINCT_FROM {created_at: timestamp($now), source: 'user'}]->(b)
        """,
        params=("a", "b", "now"),
        mutating=True,
        description="Link concepts via DISTINCT_FROM",
    ),
    NamedQuery(
        name="quests.update_disambiguation_event_status",
        cypher="""
        MATCH (e:DisambiguationEvent {event_id: $eid})
        SET e.status = $status, e.resolved_at = timestamp($now), e.resolved_by = 'user'
        """,
        params=("eid", "status", "now"),
        mutating=True,
        description="Update DisambiguationEvent status and resolution",
    ),
    NamedQuery(
        name="quests.get_anomalies_branch_scope",
        cypher="""
        MATCH (q:MainQuest {quest_id: $quest_id})
        MATCH (n:Concept)-[:REIFIED_AS]-(a:Decision)-[:ESTABLISHED_IN]->(s:Session)
        MATCH (s)-[:WORKING_ON]->(q)
        WHERE n.flagged_for_review = true
        MATCH (n)-[r:ANOMALY_DETECTED]->(gc:GlobalConstraint)
        RETURN n, r, gc
        LIMIT $limit
        """,
        params=("quest_id", "limit"),
        mutating=False,
        description="Review anomalies under branch scope",
    ),
    NamedQuery(
        name="quests.get_anomalies_global_scope",
        cypher="""
        MATCH (n)
        WHERE n.flagged_for_review = true AND (n:Concept OR n:Decision OR n:Constraint OR
              n:Requirement OR n:ActionItem OR n:Message OR n:DocumentExtract)
        MATCH (n)-[r:ANOMALY_DETECTED]->(gc:GlobalConstraint)
        RETURN n, r, gc
        LIMIT $limit
        """,
        params=("limit",),
        mutating=False,
        description="Review anomalies under global scope",
    ),
    NamedQuery(
        name="quests.get_session_onboarding_status",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        OPTIONAL MATCH (s)-[:WORKING_ON]->(q:MainQuest)
        RETURN s.onboarded, q.name, q.git_branch
        """,
        params=("sid",),
        mutating=False,
        description="Get Session onboarding status and quest details",
    ),
    NamedQuery(
        name="quests.set_session_onboarded",
        cypher="""
        MATCH (s:Session {session_id: $sid}) SET s.onboarded = true
        """,
        params=("sid",),
        mutating=True,
        description="Set Session onboarded flag to true",
    ),

    NamedQuery(
        name="quests.redirect_edge_requires",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:REQUIRES]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:REQUIRES]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect REQUIRES edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_enables",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:ENABLES]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:ENABLES]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect ENABLES edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_replaces",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:REPLACES]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:REPLACES]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect REPLACES edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_contradicts",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:CONTRADICTS]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:CONTRADICTS]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect CONTRADICTS edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_part_of",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:PART_OF]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:PART_OF]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect PART_OF edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_chosen_over",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:CHOSEN_OVER]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:CHOSEN_OVER]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect CHOSEN_OVER edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_implements",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:IMPLEMENTS]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:IMPLEMENTS]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect IMPLEMENTS edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_extends",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:EXTENDS]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:EXTENDS]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect EXTENDS edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_alternative_to",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:ALTERNATIVE_TO]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:ALTERNATIVE_TO]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect ALTERNATIVE_TO edge from duplicate to canonical concept",
    ),
    NamedQuery(
        name="quests.redirect_edge_co_occurs_with",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:CO_OCCURS_WITH]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:CO_OCCURS_WITH]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect CO_OCCURS_WITH edge from duplicate to canonical concept",
    ),
)
