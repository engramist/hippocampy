"""web.py — named queries for the Memory Control Panel web server & routes."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

WEB_QUERIES: tuple[NamedQuery, ...] = (
    # Node detail & 1-hop neighbors (for each table)
    # Concept
    NamedQuery(
        name="web.get_node_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Concept node by concept_id",
    ),
    NamedQuery(
        name="web.get_neighbors_concept",
        cypher="MATCH (n:Concept)-[r]-(m) WHERE n.concept_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Concept",
    ),
    # Decision
    NamedQuery(
        name="web.get_node_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Decision node by decision_id",
    ),
    NamedQuery(
        name="web.get_neighbors_decision",
        cypher="MATCH (n:Decision)-[r]-(m) WHERE n.decision_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Decision",
    ),
    # Constraint
    NamedQuery(
        name="web.get_node_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Constraint node by constraint_id",
    ),
    NamedQuery(
        name="web.get_neighbors_constraint",
        cypher="MATCH (n:Constraint)-[r]-(m) WHERE n.constraint_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Constraint",
    ),
    # Requirement
    NamedQuery(
        name="web.get_node_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Requirement node by requirement_id",
    ),
    NamedQuery(
        name="web.get_neighbors_requirement",
        cypher="MATCH (n:Requirement)-[r]-(m) WHERE n.requirement_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Requirement",
    ),
    # ActionItem
    NamedQuery(
        name="web.get_node_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch ActionItem node by action_item_id",
    ),
    NamedQuery(
        name="web.get_neighbors_actionitem",
        cypher="MATCH (n:ActionItem)-[r]-(m) WHERE n.action_item_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for ActionItem",
    ),
    # Message
    NamedQuery(
        name="web.get_node_message",
        cypher="MATCH (n:Message) WHERE n.message_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Message node by message_id",
    ),
    NamedQuery(
        name="web.get_neighbors_message",
        cypher="MATCH (n:Message)-[r]-(m) WHERE n.message_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Message",
    ),
    # Document
    NamedQuery(
        name="web.get_node_document",
        cypher="MATCH (n:Document) WHERE n.document_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Document node by document_id",
    ),
    NamedQuery(
        name="web.get_neighbors_document",
        cypher="MATCH (n:Document)-[r]-(m) WHERE n.document_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Document",
    ),
    # MainQuest
    NamedQuery(
        name="web.get_node_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.quest_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch MainQuest node by quest_id",
    ),
    NamedQuery(
        name="web.get_neighbors_mainquest",
        cypher="MATCH (n:MainQuest)-[r]-(m) WHERE n.quest_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for MainQuest",
    ),
    # SideQuest
    NamedQuery(
        name="web.get_node_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.quest_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch SideQuest node by quest_id",
    ),
    NamedQuery(
        name="web.get_neighbors_sidequest",
        cypher="MATCH (n:SideQuest)-[r]-(m) WHERE n.quest_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for SideQuest",
    ),
    # Lesson
    NamedQuery(
        name="web.get_node_lesson",
        cypher="MATCH (n:Lesson) WHERE n.lesson_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Lesson node by lesson_id",
    ),
    NamedQuery(
        name="web.get_neighbors_lesson",
        cypher="MATCH (n:Lesson)-[r]-(m) WHERE n.lesson_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Lesson",
    ),
    # Stats counts
    NamedQuery(
        name="web.count_active_concept",
        cypher="MATCH (n:Concept) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Concept nodes",
    ),
    NamedQuery(
        name="web.count_active_decision",
        cypher="MATCH (n:Decision) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Decision nodes",
    ),
    NamedQuery(
        name="web.count_active_constraint",
        cypher="MATCH (n:Constraint) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Constraint nodes",
    ),
    NamedQuery(
        name="web.count_active_requirement",
        cypher="MATCH (n:Requirement) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Requirement nodes",
    ),
    NamedQuery(
        name="web.count_active_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active ActionItem nodes",
    ),
    NamedQuery(
        name="web.count_active_message",
        cypher="MATCH (n:Message) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Message nodes",
    ),
    NamedQuery(
        name="web.count_total_document",
        cypher="MATCH (n:Document) RETURN count(n)",
        params=(),
        mutating=False,
        description="Count total Document nodes",
    ),
    NamedQuery(
        name="web.count_total_mergeevent",
        cypher="MATCH (n:MergeEvent) RETURN count(n)",
        params=(),
        mutating=False,
        description="Count total MergeEvent nodes",
    ),
    NamedQuery(
        name="web.count_active_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active MainQuest nodes",
    ),
    NamedQuery(
        name="web.count_active_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active SideQuest nodes",
    ),
    # Graph visualization
    NamedQuery(
        name="web.graph_concepts",
        cypher="MATCH (c:Concept) WHERE c.archived = false "
               "RETURN c.concept_id, c.text_raw, c.gist_class, "
               "       c.confidence, c.pathway_strength, c.confidence_low "
               "ORDER BY c.pathway_strength DESC LIMIT 30",
        params=(),
        mutating=False,
        description="Fetch top active concepts for graph visualization",
    ),
    NamedQuery(
        name="web.graph_decisions",
        cypher="MATCH (d:Decision) WHERE d.archived = false "
               "RETURN d.decision_id, d.text_raw, d.confidence, "
               "       d.pathway_strength, d.confidence_low "
               "ORDER BY d.pathway_strength DESC LIMIT 20",
        params=(),
        mutating=False,
        description="Fetch top active decisions for graph visualization",
    ),
    NamedQuery(
        name="web.graph_constraints",
        cypher="MATCH (c:Constraint) WHERE c.archived = false "
               "RETURN c.constraint_id, c.text_raw, c.confidence, "
               "       c.pathway_strength, c.confidence_low "
               "ORDER BY c.pathway_strength DESC LIMIT 20",
        params=(),
        mutating=False,
        description="Fetch top active constraints for graph visualization",
    ),
    NamedQuery(
        name="web.graph_main_quests",
        cypher="MATCH (q:MainQuest) WHERE q.archived = false "
               "RETURN q.quest_id, q.name, q.status LIMIT 10",
        params=(),
        mutating=False,
        description="Fetch active main quests for graph visualization",
    ),
    NamedQuery(
        name="web.graph_side_quests",
        cypher="MATCH (q:SideQuest) WHERE q.archived = false "
               "RETURN q.quest_id, q.name, q.status LIMIT 10",
        params=(),
        mutating=False,
        description="Fetch active side quests for graph visualization",
    ),
    NamedQuery(
        name="web.graph_co_occurs_with",
        cypher="MATCH (a:Concept)-[r:CO_OCCURS_WITH]->(b:Concept) "
               "WHERE a.archived = false AND b.archived = false "
               "RETURN a.concept_id, b.concept_id, r.strength, r.count "
               "ORDER BY r.strength DESC LIMIT 60",
        params=(),
        mutating=False,
        description="Fetch CO_OCCURS_WITH edges for graph visualization",
    ),
    NamedQuery(
        name="web.graph_deprecated_by",
        cypher="MATCH (old:Concept)-[:DEPRECATED_BY]->(new:Concept) "
               "RETURN old.concept_id, new.concept_id LIMIT 30",
        params=(),
        mutating=False,
        description="Fetch DEPRECATED_BY edges for graph visualization",
    ),
    NamedQuery(
        name="web.graph_belongs_to",
        cypher="MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest) "
               "RETURN sq.quest_id, mq.quest_id",
        params=(),
        mutating=False,
        description="Fetch BELONGS_TO edges for graph visualization",
    ),
    # Open loops
    NamedQuery(
        name="web.open_loops_concept",
        cypher="MATCH (n:Concept) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.concept_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop Concepts",
    ),
    NamedQuery(
        name="web.open_loops_decision",
        cypher="MATCH (n:Decision) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.decision_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop Decisions",
    ),
    NamedQuery(
        name="web.open_loops_constraint",
        cypher="MATCH (n:Constraint) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.constraint_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop Constraints",
    ),
    NamedQuery(
        name="web.open_loops_requirement",
        cypher="MATCH (n:Requirement) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.requirement_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop Requirements",
    ),
    NamedQuery(
        name="web.open_loops_actionitem",
        cypher="MATCH (n:ActionItem) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.action_item_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop ActionItems",
    ),
    # Soft-lock confirm / reject
    # Concept
    NamedQuery(
        name="web.find_soft_lock_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $nid RETURN n.concept_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock Concept by concept_id",
    ),
    NamedQuery(
        name="web.confirm_soft_lock_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock Concept",
    ),
    NamedQuery(
        name="web.reject_soft_lock_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock Concept",
    ),
    # Decision
    NamedQuery(
        name="web.find_soft_lock_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $nid RETURN n.decision_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock Decision by decision_id",
    ),
    NamedQuery(
        name="web.confirm_soft_lock_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock Decision",
    ),
    NamedQuery(
        name="web.reject_soft_lock_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock Decision",
    ),
    # Constraint
    NamedQuery(
        name="web.find_soft_lock_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $nid RETURN n.constraint_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock Constraint by constraint_id",
    ),
    NamedQuery(
        name="web.confirm_soft_lock_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock Constraint",
    ),
    NamedQuery(
        name="web.reject_soft_lock_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock Constraint",
    ),
    # Requirement
    NamedQuery(
        name="web.find_soft_lock_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $nid RETURN n.requirement_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock Requirement by requirement_id",
    ),
    NamedQuery(
        name="web.confirm_soft_lock_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock Requirement",
    ),
    NamedQuery(
        name="web.reject_soft_lock_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock Requirement",
    ),
    # ActionItem
    NamedQuery(
        name="web.find_soft_lock_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $nid RETURN n.action_item_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock ActionItem by action_item_id",
    ),
    NamedQuery(
        name="web.confirm_soft_lock_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock ActionItem",
    ),
    NamedQuery(
        name="web.reject_soft_lock_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock ActionItem",
    ),
    # Merge events
    NamedQuery(
        name="web.list_merge_events",
        cypher="MATCH (me:MergeEvent) "
               "RETURN me.merge_event_id, me.pre_pathway_strength, "
               "       me.delta_pathway_strength, me.metadata_patch, me.created_at "
               "ORDER BY me.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="List recent MergeEvents with rollback metadata",
    ),
    NamedQuery(
        name="web.get_merge_event",
        cypher="MATCH (me:MergeEvent) WHERE me.merge_event_id = $meid "
               "RETURN me.metadata_patch, me.pre_pathway_strength",
        params=("meid",),
        mutating=False,
        description="Fetch MergeEvent by merge_event_id",
    ),
    NamedQuery(
        name="web.rollback_restore_old_concept",
        cypher="MATCH (c:Concept) WHERE c.concept_id = $id "
               "SET c.archived = false, c.pathway_strength = $strength",
        params=("id", "strength"),
        mutating=True,
        description="Restore old concept during contradiction rollback",
    ),
    NamedQuery(
        name="web.rollback_archive_new_concept",
        cypher="MATCH (c:Concept) WHERE c.concept_id = $id "
               "SET c.archived = true",
        params=("id",),
        mutating=True,
        description="Archive new concept during contradiction rollback",
    ),
    NamedQuery(
        name="web.rollback_delete_deprecated_by",
        cypher="MATCH (old:Concept)-[d:DEPRECATED_BY]->(new:Concept) "
               "WHERE old.concept_id = $old_id AND new.concept_id = $new_id "
               "DELETE d",
        params=("old_id", "new_id"),
        mutating=True,
        description="Delete DEPRECATED_BY edge during contradiction rollback",
    ),
    NamedQuery(
        name="web.rollback_mark_merge_event",
        cypher="MATCH (me:MergeEvent) WHERE me.merge_event_id = $meid "
               "SET me.metadata_patch = $meta",
        params=("meid", "meta"),
        mutating=True,
        description="Mark MergeEvent metadata as rolled back",
    ),
    # Ledger export
    NamedQuery(
        name="web.ledger_constraint",
        cypher="MATCH (c:Constraint) WHERE c.archived = false "
               "RETURN c.constraint_id, c.text_raw, c.confidence, "
               "       c.confidence_low, c.pathway_strength, c.created_at "
               "ORDER BY c.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Fetch active constraints for ledger",
    ),
    NamedQuery(
        name="web.ledger_global_constraint",
        cypher="MATCH (c:GlobalConstraint) WHERE c.archived = false "
               "RETURN c.global_constraint_id, c.text_raw, c.confidence, "
               "       c.confidence_low, c.pathway_strength, c.created_at "
               "ORDER BY c.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Fetch active global constraints for ledger",
    ),
    # Quests
    NamedQuery(
        name="web.quests_main",
        cypher="MATCH (q:MainQuest) WHERE q.archived = false "
               "RETURN q.quest_id, q.name, q.status, q.purpose, q.created_at "
               "ORDER BY q.created_at DESC",
        params=(),
        mutating=False,
        description="Fetch active main quests",
    ),
    NamedQuery(
        name="web.quests_side_belongs_to",
        cypher="MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest) "
               "WHERE sq.archived = false "
               "RETURN sq.quest_id, sq.name, sq.status, sq.purpose, "
               "       sq.created_at, mq.quest_id",
        params=(),
        mutating=False,
        description="Fetch active side quests with parent quest_id",
    ),
    # Thinking tab
    NamedQuery(
        name="web.thinking_decisions",
        cypher="MATCH (d:Decision) WHERE d.archived = false "
               "RETURN d.decision_id, d.text_raw, d.confidence, "
               "       d.pathway_strength, d.confidence_low, d.created_at "
               "ORDER BY d.pathway_strength DESC LIMIT 10",
        params=(),
        mutating=False,
        description="Fetch top decisions for thinking tab",
    ),
    NamedQuery(
        name="web.thinking_concepts",
        cypher="MATCH (c:Concept) WHERE c.archived = false "
               "RETURN c.concept_id, c.text_raw, c.gist_class, "
               "       c.pathway_strength, c.confidence_low "
               "ORDER BY c.pathway_strength DESC LIMIT 25",
        params=(),
        mutating=False,
        description="Fetch top concepts for thinking tab",
    ),
    NamedQuery(
        name="web.thinking_constraints",
        cypher="MATCH (c:Constraint) WHERE c.archived = false "
               "RETURN c.constraint_id, c.text_raw, c.confidence, "
               "       c.pathway_strength, c.confidence_low "
               "ORDER BY c.pathway_strength DESC LIMIT 10",
        params=(),
        mutating=False,
        description="Fetch top constraints for thinking tab",
    ),
    NamedQuery(
        name="web.count_open_loops_concept",
        cypher="MATCH (n:Concept) WHERE n.confidence_low = true "
               "AND n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count open loops in Concept table",
    ),
    NamedQuery(
        name="web.count_open_loops_decision",
        cypher="MATCH (n:Decision) WHERE n.confidence_low = true "
               "AND n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count open loops in Decision table",
    ),
    NamedQuery(
        name="web.count_open_loops_constraint",
        cypher="MATCH (n:Constraint) WHERE n.confidence_low = true "
               "AND n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count open loops in Constraint table",
    ),
    # Metrics
    NamedQuery(
        name="web.recent_sessions_token_metrics",
        cypher="MATCH (s:Session) "
               "RETURN s.session_id, s.started_at, s.last_active_at, "
               "       s.token_estimate, s.token_limit, "
               "       s.loaded_node_count, s.injection_count, "
               "       s.dedup_tokens_saved "
               "ORDER BY s.last_active_at DESC "
               "LIMIT $limit",
        params=("limit",),
        mutating=False,
        description="Fetch recent sessions token metrics",
    ),
)
