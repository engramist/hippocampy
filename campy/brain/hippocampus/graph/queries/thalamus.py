"""thalamus.py — named queries for Thalamus context tools, bundle compiler, wiki projection, etc."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_GRAPH_REL_TYPES = (
    "REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER"
    "|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO"
)

THALAMUS_QUERIES: tuple[NamedQuery, ...] = (
    # _shared.py
    NamedQuery(
        name="thalamus.session_active_plan_id",
        cypher="MATCH (p:Plan)-[:PLANNED_IN]->(s:Session {session_id: $sid}) "
               "WHERE p.status = 'active' "
               "RETURN p.plan_id "
               "ORDER BY p.created_at DESC LIMIT 1",
        params=("sid",),
        mutating=False,
        description="Get active plan_id for session",
    ),

    # trigger_manifest.py
    NamedQuery(
        name="thalamus.trigger_manifest_procedures",
        cypher="MATCH (p:Procedure) "
               "WHERE p.archived = false "
               "  AND p.trigger_pattern IS NOT NULL "
               "  AND p.trigger_pattern <> '' "
               "RETURN p.procedure_id AS id, p.name AS name, "
               "       p.description AS description, p.steps_json AS steps_json, "
               "       p.trigger_pattern AS pattern, p.trigger_hook_type AS hook_type, "
               "       p.trigger_tool AS tool, p.trigger_project_scope AS project_scope, "
               "       p.pathway_strength AS strength, p.domain AS domain "
               "ORDER BY p.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Get active procedures with trigger patterns",
    ),
    NamedQuery(
        name="thalamus.trigger_manifest_lessons",
        cypher="MATCH (l:Lesson) "
               "WHERE l.archived = false "
               "  AND l.trigger_pattern IS NOT NULL "
               "  AND l.trigger_pattern <> '' "
               "RETURN l.lesson_id AS id, l.text_raw AS text, "
               "       l.lesson_type AS lesson_type, "
               "       l.trigger_pattern AS pattern, l.trigger_hook_type AS hook_type, "
               "       l.trigger_tool AS tool, l.trigger_project_scope AS project_scope, "
               "       l.pathway_strength AS strength, l.domain AS domain "
               "ORDER BY l.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Get active lessons with trigger patterns",
    ),

    # file_bridge.py
    NamedQuery(
        name="thalamus.file_bridge_concepts",
        cypher="MATCH (c:Concept) "
               "WHERE c.archived = false AND c.confidence >= 0.6 "
               "RETURN c.concept_id AS id, c.prefLabel AS name, "
               "       c.text_raw AS definition, c.gist_class AS gist_class, "
               "       c.altLabel AS alt_labels, c.pathway_strength AS strength "
               "ORDER BY c.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Fetch concepts for CONTEXT.md file bridge",
    ),
    NamedQuery(
        name="thalamus.file_bridge_concept_relationships",
        cypher="MATCH (a:Concept)-[r]->(b:Concept) "
               "WHERE a.archived = false AND b.archived = false "
               "RETURN a.prefLabel AS from_name, type(r) AS rel_type, "
               "       b.prefLabel AS to_name "
               "ORDER BY a.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Fetch concept relationships for CONTEXT.md file bridge",
    ),
    NamedQuery(
        name="thalamus.file_bridge_global_constraints",
        cypher="MATCH (g:GlobalConstraint) "
               "WHERE g.archived = false "
               "RETURN g.text_raw AS text "
               "ORDER BY g.pathway_strength DESC LIMIT 3",
        params=(),
        mutating=False,
        description="Fetch global constraints for CONTEXT.md file bridge",
    ),
    NamedQuery(
        name="thalamus.file_bridge_decisions",
        cypher="MATCH (d:Decision) "
               "WHERE d.archived = false AND d.confidence >= 0.8 "
               "RETURN d.decision_id AS id, d.prefLabel AS title, "
               "       d.text_raw AS context, d.created_at AS created_at "
               "ORDER BY d.created_at ASC",
        params=(),
        mutating=False,
        description="Fetch decisions for ADR generation",
    ),

    # artifacts.py
    NamedQuery(
        name="thalamus.artifacts_find_existing",
        cypher="MATCH (wa:WorkArtifact {file_path: $fp}) RETURN wa.artifact_id",
        params=("fp",),
        mutating=False,
        description="Find existing WorkArtifact by file_path",
    ),
    NamedQuery(
        name="thalamus.artifacts_update",
        cypher="MATCH (wa:WorkArtifact {file_path: $fp}) "
               "SET wa.last_modified_at = timestamp($ts), "
               "    wa.title = CASE WHEN $ti IS NOT NULL THEN $ti ELSE wa.title END, "
               "    wa.summary = CASE WHEN $su IS NOT NULL THEN $su ELSE wa.summary END, "
               "    wa.linked_card = CASE WHEN $lc IS NOT NULL THEN $lc ELSE wa.linked_card END, "
               "    wa.document_type = CASE WHEN $dt IS NOT NULL THEN $dt ELSE wa.document_type END",
        params=("fp", "ts", "ti", "su", "lc", "dt"),
        mutating=True,
        description="Update WorkArtifact properties",
    ),
    NamedQuery(
        name="thalamus.artifacts_create",
        cypher="CREATE (wa:WorkArtifact {\n"
               "  artifact_id: $aid, file_path: $fp, document_type: $dt,\n"
               "  title: $ti, summary: $su, linked_card: $lc,\n"
               "  session_id: $sess, agent_source: $ag_src,\n"
               "  created_at: timestamp($ts), last_modified_at: timestamp($ts)\n"
               "})",
        params=("aid", "fp", "dt", "ti", "su", "lc", "sess", "ag_src", "ts"),
        mutating=True,
        description="Create WorkArtifact node",
    ),
    NamedQuery(
        name="thalamus.artifacts_link_session",
        cypher="MATCH (wa:WorkArtifact {artifact_id: $aid}), (s:Session {session_id: $sid}) "
               "MERGE (wa)-[:CREATED_IN]->(s)",
        params=("aid", "sid"),
        mutating=True,
        description="Link WorkArtifact CREATED_IN Session",
    ),

    # work_summary.py
    NamedQuery(
        name="thalamus.work_summary_active_plan",
        cypher="MATCH (p:Plan)-[:PLANNED_IN]->(s:Session {session_id: $sid}) "
               "WHERE p.archived = false "
               "RETURN p.plan_id, p.goal "
               "ORDER BY p.created_at DESC LIMIT 1",
        params=("sid",),
        mutating=False,
        description="Fetch active plan for session work summary",
    ),
    NamedQuery(
        name="thalamus.work_summary_recent_decisions",
        cypher="MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid}) "
               "WHERE d.archived = false "
               "RETURN d.text_raw "
               "ORDER BY d.created_at DESC LIMIT 5",
        params=("sid",),
        mutating=False,
        description="Fetch recent decisions for session work summary",
    ),
    NamedQuery(
        name="thalamus.work_summary_files_in_flight",
        cypher="MATCH (wa:WorkArtifact)-[:CREATED_IN]->(s:Session {session_id: $sid}) "
               "RETURN wa.file_path, wa.title "
               "ORDER BY wa.last_modified_at DESC LIMIT 10",
        params=("sid",),
        mutating=False,
        description="Fetch files in flight for session work summary",
    ),
    NamedQuery(
        name="thalamus.work_summary_get_existing",
        cypher="MATCH (ws:WorkSummary {summary_id: $sid}) RETURN ws.turn_count",
        params=("sid",),
        mutating=False,
        description="Fetch existing WorkSummary turn_count",
    ),
    NamedQuery(
        name="thalamus.work_summary_update",
        cypher="MATCH (ws:WorkSummary {summary_id: $sid}) "
               "SET ws.resume_line = $rl, ws.turn_count = $tc, "
               "    ws.last_updated_at = timestamp($ts), ws.git_branch = $br, "
               "    ws.git_commit = $co, ws.agent_source = $as, ws.active_card = $card, "
               "    ws.snapshot_text = CASE WHEN $has_snap = true THEN $snap ELSE ws.snapshot_text END",
        params=("sid", "rl", "tc", "ts", "br", "co", "as", "card", "has_snap", "snap"),
        mutating=True,
        description="Update WorkSummary node",
    ),
    NamedQuery(
        name="thalamus.work_summary_create",
        cypher="CREATE (ws:WorkSummary {\n"
               "  summary_id: $sid, session_id: $sess, agent_source: $as,\n"
               "  git_branch: $br, git_commit: $co, active_card: $card,\n"
               "  resume_line: $rl, snapshot_text: $snap, turn_count: $tc,\n"
               "  last_updated_at: timestamp($ts)\n"
               "})",
        params=("sid", "sess", "as", "br", "co", "card", "rl", "snap", "tc", "ts"),
        mutating=True,
        description="Create WorkSummary node",
    ),

    # analogical.py
    NamedQuery(
        name="thalamus.analogical_resolve_quest_concept",
        cypher="MATCH (art:Concept {concept_id: $nid}) "
               "MATCH (msg:Message)-[:ESTABLISHED]->(art) "
               "MATCH (msg)-[:SENT_IN]->(sess:Session) "
               "MATCH (sess)-[:WORKING_ON]->(q:MainQuest) "
               "RETURN q.quest_id, q.name LIMIT 1",
        params=("nid",),
        mutating=False,
        description="Resolve MainQuest for Concept node",
    ),
    NamedQuery(
        name="thalamus.analogical_resolve_quest_decision",
        cypher="MATCH (art:Decision {decision_id: $nid}) "
               "MATCH (msg:Message)-[:ESTABLISHED]->(art) "
               "MATCH (msg)-[:SENT_IN]->(sess:Session) "
               "MATCH (sess)-[:WORKING_ON]->(q:MainQuest) "
               "RETURN q.quest_id, q.name LIMIT 1",
        params=("nid",),
        mutating=False,
        description="Resolve MainQuest for Decision node",
    ),
    NamedQuery(
        name="thalamus.analogical_resolve_quest_constraint",
        cypher="MATCH (art:Constraint {constraint_id: $nid}) "
               "MATCH (msg:Message)-[:ESTABLISHED]->(art) "
               "MATCH (msg)-[:SENT_IN]->(sess:Session) "
               "MATCH (sess)-[:WORKING_ON]->(q:MainQuest) "
               "RETURN q.quest_id, q.name LIMIT 1",
        params=("nid",),
        mutating=False,
        description="Resolve MainQuest for Constraint node",
    ),
    NamedQuery(
        name="thalamus.analogical_get_quest_embedding",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) RETURN q.embedding, q.name",
        params=("qid",),
        mutating=False,
        description="Get MainQuest embedding and name",
    ),

    # wiki_projection.py
    NamedQuery(
        name="thalamus.wiki_lessons",
        cypher="MATCH (l:Lesson) WHERE l.archived = false AND l.lesson_type = 'synthesis' "
               "RETURN l.lesson_id, l.text_raw, l.domain, l.pathway_strength "
               "ORDER BY l.pathway_strength DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch synthesis lessons for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_lessons_by_domain",
        cypher="MATCH (l:Lesson) WHERE l.archived = false AND l.lesson_type = 'synthesis' AND l.domain IN $domains "
               "RETURN l.lesson_id, l.text_raw, l.domain, l.pathway_strength "
               "ORDER BY l.pathway_strength DESC LIMIT $lim",
        params=("domains", "lim"),
        mutating=False,
        description="Fetch synthesis lessons by domain for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_procedures",
        cypher="MATCH (p:Procedure) WHERE p.archived = false "
               "RETURN p.procedure_id, p.name, p.description, p.archetype "
               "ORDER BY p.name LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch procedures for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_procedures_by_domain",
        cypher="MATCH (p:Procedure) WHERE p.archived = false AND p.domain IN $domains "
               "RETURN p.procedure_id, p.name, p.description, p.archetype "
               "ORDER BY p.name LIMIT $lim",
        params=("domains", "lim"),
        mutating=False,
        description="Fetch procedures by domain for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_arc_runs",
        cypher="MATCH (r:ArcRun) "
               "RETURN r.run_id, r.summary, r.domain, r.status, r.task_count, "
               "       r.solved_count, r.failed_count, r.step_count, r.source_files "
               "ORDER BY r.created_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcRuns for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_arc_run_wm_summary",
        cypher="MATCH (r:ArcRun {run_id: $run_id})-[:ARC_RUN_HAS_WORLD_MODEL_SUMMARY]->(s:ArcWorldModelSummary) "
               "RETURN s.graph_bounded, s.compiler_active, s.falsification_active, "
               "       s.reasoning_gated, s.planner_grounded, s.memory_transfer_active, "
               "       s.single_action_stall_detected, s.full_reasoning_cycles_avoided "
               "ORDER BY s.created_at DESC LIMIT 1",
        params=("run_id",),
        mutating=False,
        description="Fetch ArcWorldModelSummary for an ArcRun",
    ),
    NamedQuery(
        name="thalamus.wiki_arc_task_results",
        cypher="MATCH (t:ArcTaskResult) "
               "RETURN t.task_result_id, t.summary, t.domain, t.status, t.task_id, "
               "       t.puzzle_id, t.correct, t.steps, t.failure_class "
               "ORDER BY t.created_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcTaskResults for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_arc_artifacts",
        cypher="MATCH (a:ArcArtifact) "
               "RETURN a.artifact_id, a.artifact_kind, a.path, a.content_hash, "
               "       a.record_count, a.captured_at, a.ingested_at, a.domain, a.summary "
               "ORDER BY a.ingested_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcArtifacts for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_arc_events",
        cypher="MATCH (e:ArcEvent) "
               "RETURN e.event_id, e.run_id, e.task_id, e.event_type, e.timestamp, "
               "       e.step_index, e.actor, e.tool_name, e.action_name, e.outcome, "
               "       e.domain, e.summary "
               "ORDER BY e.timestamp DESC, e.step_index DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcEvents for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_arc_wm_steps",
        cypher="MATCH (s:ArcWorldModelStep) "
               "RETURN s.world_model_step_id, s.task_id, s.step_index, s.node_count, "
               "       s.edge_count, s.compiled_claim_count, s.action_effect_class, s.reasoning_mode, "
               "       s.planner_candidate_count, s.single_action_stall_detected, s.summary "
               "ORDER BY s.created_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcWorldModelSteps for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_arc_wm_summaries",
        cypher="MATCH (s:ArcWorldModelSummary) "
               "RETURN s.world_model_summary_id, s.task_id, s.graph_bounded, s.compiler_active, "
               "       s.falsification_active, s.reasoning_gated, s.planner_grounded, s.memory_transfer_active, "
               "       s.single_action_stall_detected, s.full_reasoning_cycles_avoided, s.summary "
               "ORDER BY s.created_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcWorldModelSummaries for wiki projection",
    ),
    NamedQuery(
        name="thalamus.wiki_arc_mechanics",
        cypher="MATCH (m:ArcMechanic) "
               "RETURN m.mechanic_id, m.name, m.signature, m.confidence, "
               "       m.terminal_relevance, m.coordinate_relevance, m.evidence_count, m.summary "
               "ORDER BY m.confidence DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcMechanics for wiki projection",
    ),

    # context_tools.py
    # Target resolution: exact
    NamedQuery(
        name="thalamus.context_resolve_exact_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.name = $tid RETURN n.quest_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in MainQuest",
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.name = $tid RETURN n.quest_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in SideQuest",
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_plan",
        cypher="MATCH (n:Plan) WHERE n.goal = $tid RETURN n.plan_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in Plan",
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_lesson",
        cypher="MATCH (n:Lesson) WHERE n.text_raw = $tid RETURN n.lesson_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in Lesson",
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_procedure",
        cypher="MATCH (n:Procedure) WHERE n.name = $tid RETURN n.procedure_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in Procedure",
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.text_raw = $tid RETURN n.action_item_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in ActionItem",
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.text_raw CONTAINS $tid RETURN n.action_item_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in ActionItem",
    ),

    # Target resolution: contains
    NamedQuery(
        name="thalamus.context_resolve_contains_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.name CONTAINS $tid RETURN n.quest_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in MainQuest",
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.name CONTAINS $tid RETURN n.quest_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in SideQuest",
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_plan",
        cypher="MATCH (n:Plan) WHERE n.goal CONTAINS $tid RETURN n.plan_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in Plan",
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_lesson",
        cypher="MATCH (n:Lesson) WHERE n.text_raw CONTAINS $tid RETURN n.lesson_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in Lesson",
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_procedure",
        cypher="MATCH (n:Procedure) WHERE n.name CONTAINS $tid RETURN n.procedure_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in Procedure",
    ),

    # Target resolution: workspace
    NamedQuery(
        name="thalamus.context_resolve_workspace",
        cypher="MATCH (w:Workspace) WHERE w.branch_name = $tid RETURN w.workspace_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id branch_name match in Workspace",
    ),

    # Lessons for quest
    NamedQuery(
        name="thalamus.context_lessons_for_quest",
        cypher="MATCH (q:MainQuest {quest_id: $qid})-[:PRODUCED_LESSON]->(l:Lesson) "
               "RETURN l.lesson_id, l.text_raw, l.confidence, l.archived LIMIT 20",
        params=("qid",),
        mutating=False,
        description="Fetch lessons produced by MainQuest",
    ),

    # DEPRECATED_BY
    NamedQuery(
        name="thalamus.context_deprecated_by_out_concept",
        cypher="MATCH (a:Concept {concept_id: $id})-[:DEPRECATED_BY]->(b:Concept) RETURN b.concept_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Concept is deprecated by",
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_in_concept",
        cypher="MATCH (a:Concept)-[:DEPRECATED_BY]->(b:Concept {concept_id: $id}) RETURN a.concept_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Concept deprecates",
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_out_decision",
        cypher="MATCH (a:Decision {decision_id: $id})-[:DEPRECATED_BY]->(b:Decision) RETURN b.decision_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Decision is deprecated by",
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_in_decision",
        cypher="MATCH (a:Decision)-[:DEPRECATED_BY]->(b:Decision {decision_id: $id}) RETURN a.decision_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Decision deprecates",
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_out_constraint",
        cypher="MATCH (a:Constraint {constraint_id: $id})-[:DEPRECATED_BY]->(b:Constraint) RETURN b.constraint_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Constraint is deprecated by",
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_in_constraint",
        cypher="MATCH (a:Constraint)-[:DEPRECATED_BY]->(b:Constraint {constraint_id: $id}) RETURN a.constraint_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Constraint deprecates",
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_out_lesson",
        cypher="MATCH (a:Lesson {lesson_id: $id})-[:DEPRECATED_BY]->(b:Lesson) RETURN b.lesson_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Lesson is deprecated by",
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_in_lesson",
        cypher="MATCH (a:Lesson)-[:DEPRECATED_BY]->(b:Lesson {lesson_id: $id}) RETURN a.lesson_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Lesson deprecates",
    ),

    # SOLVED_BY
    NamedQuery(
        name="thalamus.context_solved_by_decision",
        cypher="MATCH (n:Decision {decision_id: $id})-[r:SOLVED_BY]->(w:AgentWorker) "
               "RETURN w.worker_id, r.confidence, r.observed_at LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find worker solving Decision",
    ),
    NamedQuery(
        name="thalamus.context_solved_by_actionitem",
        cypher="MATCH (n:ActionItem {action_item_id: $id})-[r:SOLVED_BY]->(w:AgentWorker) "
               "RETURN w.worker_id, r.confidence, r.observed_at LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find worker solving ActionItem",
    ),
    NamedQuery(
        name="thalamus.context_solved_by_lesson",
        cypher="MATCH (n:Lesson {lesson_id: $id})-[r:SOLVED_BY]->(w:AgentWorker) "
               "RETURN w.worker_id, r.confidence, r.observed_at LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find worker solving Lesson",
    ),

    # bundle_compiler.py
    # Exact facts
    # Concept
    NamedQuery(
        name="thalamus.bundle_exact_facts_concept",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Concept",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_concept_auth",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Concept with authority",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_concept_flagged",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Concept excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_concept_flagged_auth",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Concept with authority excluding flagged",
    ),

    # Decision
    NamedQuery(
        name="thalamus.bundle_exact_facts_decision",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Decision",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_decision_auth",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Decision with authority",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_decision_flagged",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Decision excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_decision_flagged_auth",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Decision with authority excluding flagged",
    ),

    # Constraint
    NamedQuery(
        name="thalamus.bundle_exact_facts_constraint",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Constraint",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_constraint_auth",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Constraint with authority",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_constraint_flagged",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Constraint excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_constraint_flagged_auth",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Constraint with authority excluding flagged",
    ),

    # Semantic context
    # Concept
    NamedQuery(
        name="thalamus.bundle_semantic_concept",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Concept",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_concept_auth",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Concept with authority",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_concept_flagged",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Concept excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_concept_flagged_auth",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Concept with authority excluding flagged",
    ),

    # Decision
    NamedQuery(
        name="thalamus.bundle_semantic_decision",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Decision",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_decision_auth",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Decision with authority",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_decision_flagged",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Decision excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_decision_flagged_auth",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Decision with authority excluding flagged",
    ),

    # Constraint
    NamedQuery(
        name="thalamus.bundle_semantic_constraint",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Constraint",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_constraint_auth",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Constraint with authority",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_constraint_flagged",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Constraint excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_constraint_flagged_auth",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Constraint with authority excluding flagged",
    ),

    # Graph structure
    NamedQuery(
        name="thalamus.bundle_graph_anchors",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.concept_id as id, n.text_raw as text, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT 5",
        params=("query_embedding",),
        mutating=False,
        description="Fetch anchor concepts for bundle graph structure",
    ),
    NamedQuery(
        name="thalamus.bundle_graph_anchors_flagged",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.concept_id as id, n.text_raw as text, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT 5",
        params=("query_embedding",),
        mutating=False,
        description="Fetch anchor concepts excluding flagged for bundle graph structure",
    ),
    NamedQuery(
        name="thalamus.bundle_graph_one_hop",
        cypher="MATCH (a:Concept)-[r:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(b:Concept) "
               "WHERE a.concept_id = $aid "
               "RETURN label(r), b.concept_id, b.text_raw LIMIT 10",
        params=("aid",),
        mutating=False,
        description="Fetch 1-hop neighbors for anchor concept",
    ),
    NamedQuery(
        name="thalamus.bundle_graph_one_hop_flagged",
        cypher="MATCH (a:Concept)-[r:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(b:Concept) "
               "WHERE a.concept_id = $aid "
               "  AND (b.flagged_for_review IS NULL OR b.flagged_for_review = false) "
               "RETURN label(r), b.concept_id, b.text_raw LIMIT 10",
        params=("aid",),
        mutating=False,
        description="Fetch 1-hop neighbors for anchor concept excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_graph_two_hop",
        cypher="MATCH (a:Concept)-[r1:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(mid:Concept) "
               "      -[r2:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(c:Concept) "
               "WHERE a.concept_id = $aid AND c.concept_id <> a.concept_id "
               "RETURN label(r1), mid.text_raw, label(r2), c.concept_id, c.text_raw LIMIT 10",
        params=("aid",),
        mutating=False,
        description="Fetch 2-hop neighbors for anchor concept",
    ),
    NamedQuery(
        name="thalamus.bundle_graph_two_hop_flagged",
        cypher="MATCH (a:Concept)-[r1:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(mid:Concept) "
               "      -[r2:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(c:Concept) "
               "WHERE a.concept_id = $aid AND c.concept_id <> a.concept_id "
               "  AND (mid.flagged_for_review IS NULL OR mid.flagged_for_review = false) "
               "  AND (c.flagged_for_review IS NULL OR c.flagged_for_review = false) "
               "RETURN label(r1), mid.text_raw, label(r2), c.concept_id, c.text_raw LIMIT 10",
        params=("aid",),
        mutating=False,
        description="Fetch 2-hop neighbors for anchor concept excluding flagged",
    ),

    # Tabular
    NamedQuery(
        name="thalamus.bundle_tabular_described_by_dataset",
        cypher="MATCH (n:Concept)-[:DESCRIBED_BY_DATASET]->(d:Dataset) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "      AND d.archived = false "
               "RETURN DISTINCT d.dataset_id as dataset_id, d.name as name, "
               "       d.description as description LIMIT 5",
        params=("query_embedding",),
        mutating=False,
        description="Fetch datasets describing concept",
    ),

    # Wiki
    NamedQuery(
        name="thalamus.bundle_wiki_lessons",
        cypher="MATCH (n:Lesson) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "      AND n.archived = false AND n.lesson_type = 'synthesis' "
               "RETURN n.lesson_id as id, n.text_raw as text, 'Lesson' as node_type, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Fetch wiki lessons for bundle",
    ),
    NamedQuery(
        name="thalamus.bundle_wiki_procedures",
        cypher="MATCH (n:Procedure) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "      AND n.archived = false "
               "RETURN n.procedure_id as id, n.description as text, 'Procedure' as node_type, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Fetch wiki procedures for bundle",
    ),
)


def build_card_hop_query(table: str, pk: str, rel: str, direction: str, props: tuple[str, ...]) -> str:
    """Build single hop query for card context traversal."""
    prop_select = "".join(f", r.{p} AS {p}" for p in props)
    if direction == "out":
        pattern = f"(a:{table} {{{pk}: $id}})-[r:{rel}]->(b)"
    else:
        pattern = f"(a:{table} {{{pk}: $id}})<-[r:{rel}]-(b)"
    return f"MATCH {pattern} RETURN label(b) AS b_label, b{prop_select} LIMIT 20"


CARD_HOP_QUERIES: list[NamedQuery] = []
for _table, _pk in (("MainQuest", "quest_id"), ("SideQuest", "quest_id"), ("ActionItem", "action_item_id"), ("Workspace", "workspace_id")):
    for _rel in ("TASK_BLOCKS", "TASK_ENABLES", "ANCHORED_TO"):
        _props = ("declared_by", "confidence", "observed_at", "source", "source_version", "authority") if _rel != "ANCHORED_TO" else ()
        _prop_select = "".join(f", r.{p} AS {p}" for p in _props)
        for _direction, _pattern in (
            ("out", f"(a:{_table} {{{_pk}: $id}})-[r:{_rel}]->(b)"),
            ("in", f"(a:{_table} {{{_pk}: $id}})<-[r:{_rel}]-(b)"),
        ):
            CARD_HOP_QUERIES.append(
                NamedQuery(
                    name=f"thalamus.card_hop_{_table.lower()}_{_rel.lower()}_{_direction}",
                    cypher=f"MATCH {_pattern} RETURN label(b) AS b_label, b{_prop_select} LIMIT 25",
                    params=("id",),
                    mutating=False,
                    description=f"Card context dependency hop {_table} {_rel} {_direction}",
                )
            )

THALAMUS_QUERIES = list(THALAMUS_QUERIES) + CARD_HOP_QUERIES


BUNDLE_EXTRA_QUERIES: list[NamedQuery] = []

for _label in ("GlobalConstraint", "GlobalPreference"):
    _lbl_lower = _label.lower()
    BUNDLE_EXTRA_QUERIES.extend([
        NamedQuery(
            name=f"thalamus.bundle_exact_{_lbl_lower}",
            cypher=f"MATCH (n:{_label}) "
                   "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                   "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
                   "LIMIT $limit",
            params=("query_embedding", "limit"),
            mutating=False,
            description=f"Exact facts {_label} base",
        ),
        NamedQuery(
            name=f"thalamus.bundle_exact_{_lbl_lower}_auth",
            cypher=f"MATCH (n:{_label}) "
                   "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                   "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
                   "LIMIT $limit",
            params=("query_embedding", "limit"),
            mutating=False,
            description=f"Exact facts {_label} with authority",
        ),
        NamedQuery(
            name=f"thalamus.bundle_exact_{_lbl_lower}_flagged",
            cypher=f"MATCH (n:{_label}) "
                   "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                   "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
                   "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
                   "LIMIT $limit",
            params=("query_embedding", "limit"),
            mutating=False,
            description=f"Exact facts {_label} excluding flagged",
        ),
        NamedQuery(
            name=f"thalamus.bundle_exact_{_lbl_lower}_flagged_auth",
            cypher=f"MATCH (n:{_label}) "
                   "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                   "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
                   "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
                   "LIMIT $limit",
            params=("query_embedding", "limit"),
            mutating=False,
            description=f"Exact facts {_label} with authority excluding flagged",
        ),
    ])

BUNDLE_EXTRA_QUERIES.extend([
    NamedQuery(
        name="thalamus.bundle_semantic_requirement",
        cypher="MATCH (n:Requirement) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context Requirement base",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_requirement_auth",
        cypher="MATCH (n:Requirement) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context Requirement with authority",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_requirement_flagged",
        cypher="MATCH (n:Requirement) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context Requirement excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_requirement_flagged_auth",
        cypher="MATCH (n:Requirement) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context Requirement with authority excluding flagged",
    ),
])

THALAMUS_QUERIES = list(THALAMUS_QUERIES) + BUNDLE_EXTRA_QUERIES


# B374: bundle_semantic_*/bundle_graph_anchors* variants for archived and
# superseded_by filtering. archived/superseded_by are base columns on every
# real schema.py-created table, but a handful of reduced test fixtures build
# these tables directly without them (see _table_has_column's docstring), so
# — same as flagged/authority above — a missing column needs its own query
# text rather than a runtime-toggled WHERE clause (Kuzu's binder validates
# every referenced column regardless of runtime branching). The base
# (archived=False, superseded=False) slice is exactly the 16 bundle_semantic_*
# and 2 bundle_graph_anchors* queries registered above; this generates the
# remaining combinations rather than hand-duplicating them.
ARCHIVED_SUPERSEDED_QUERIES: list[NamedQuery] = []

for _label in ("Concept", "Decision", "Constraint", "Requirement"):
    _lbl_lower = _label.lower()
    for _flagged in (False, True):
        for _archived in (False, True):
            for _superseded in (False, True):
                for _auth in (False, True):
                    if not _archived and not _superseded:
                        continue  # already registered above
                    _suffix_parts = []
                    _filters = []
                    if _flagged:
                        _suffix_parts.append("flagged")
                        _filters.append(
                            "AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false)"
                        )
                    if _archived:
                        _suffix_parts.append("archived")
                        _filters.append("AND (n.archived IS NULL OR n.archived = false)")
                    if _superseded:
                        _suffix_parts.append("superseded")
                        _filters.append(
                            "AND (n.superseded_by IS NULL OR n.superseded_by = '')"
                        )
                    if _auth:
                        _suffix_parts.append("auth")
                    _suffix = "".join(f"_{p}" for p in _suffix_parts)
                    _filter_text = " ".join(_filters)
                    _auth_select = ", n.authority as authority" if _auth else ""
                    ARCHIVED_SUPERSEDED_QUERIES.append(
                        NamedQuery(
                            name=f"thalamus.bundle_semantic_{_lbl_lower}{_suffix}",
                            cypher=f"MATCH (n:{_label}) "
                                   f"WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                                   f"{_filter_text} "
                                   f"RETURN n.text_raw as text, label(n) as node_type, "
                                   f"       n.pathway_strength as pathway_strength, n.confidence as confidence, "
                                   f"       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist{_auth_select} "
                                   f"ORDER BY dist ASC LIMIT $limit",
                            params=("query_embedding", "limit"),
                            mutating=False,
                            description=f"Semantic context for {_label}"
                                        + (f" ({', '.join(_suffix_parts)})" if _suffix_parts else ""),
                        )
                    )

for _flagged in (False, True):
    for _archived in (False, True):
        for _superseded in (False, True):
            if not _archived and not _superseded:
                continue  # already registered above
            _suffix_parts = []
            _filters = []
            if _flagged:
                _suffix_parts.append("flagged")
                _filters.append(
                    "AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false)"
                )
            if _archived:
                _suffix_parts.append("archived")
                _filters.append("AND (n.archived IS NULL OR n.archived = false)")
            if _superseded:
                _suffix_parts.append("superseded")
                _filters.append("AND (n.superseded_by IS NULL OR n.superseded_by = '')")
            _suffix = "".join(f"_{p}" for p in _suffix_parts)
            _filter_text = " ".join(_filters)
            ARCHIVED_SUPERSEDED_QUERIES.append(
                NamedQuery(
                    name=f"thalamus.bundle_graph_anchors{_suffix}",
                    cypher="MATCH (n:Concept) "
                           "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                           f"{_filter_text} "
                           "RETURN n.concept_id as id, n.text_raw as text, "
                           "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
                           "ORDER BY dist ASC LIMIT 5",
                    params=("query_embedding",),
                    mutating=False,
                    description=f"Fetch anchor concepts for bundle graph structure ({', '.join(_suffix_parts)})",
                )
            )

THALAMUS_QUERIES = list(THALAMUS_QUERIES) + ARCHIVED_SUPERSEDED_QUERIES
