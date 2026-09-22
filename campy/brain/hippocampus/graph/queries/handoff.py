"""
campy/brain/hippocampus/graph/queries/handoff.py — B383 quest-scoped
handoff queries.

New file (not an extension of thalamus.py/arc.py) for the same reason
as model_router.py: avoid colliding with a peer session's in-flight
SPARQL audit of those files.

Only the queries genuinely missing from existing infrastructure:
- Decisions/Constraints ESTABLISHED_IN *any* session WORKING_ON the
  quest (broader than thalamus.work_summary_recent_decisions, which is
  scoped to the single calling session).
- WorkArtifacts CREATED_IN any of the quest's sessions (broader than
  thalamus.work_summary_files_in_flight, same reasoning).

Everything else a handoff needs already exists and is reused directly:
model_router.get_active_plans_for_quest, model_router.
get_active_task_graph_for_session, task_graph.get_graph_tasks,
thalamus.context_deprecated_by_out_{decision,constraint} (DEPRECATED_BY
exclusion, same per-node pattern context_tools.py's
_card_context_deprecated_by already proves out).

MainQuest -> [:WORKING_ON reversed] -> Session ->
[:ESTABLISHED_IN/:CREATED_IN reversed] -> {Decision,Constraint,
WorkArtifact} is a genuine 2-hop bounded traversal on real edges
(WORKING_ON reverse-pattern already used repeatedly in queries/quests.py;
ESTABLISHED_IN/CREATED_IN both "plain" reification in oxigraph_client.py).
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

HANDOFF_QUERIES = [
    NamedQuery(
        name="handoff.get_quest_decisions",
        cypher="""
        MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
        MATCH (d:Decision)-[:ESTABLISHED_IN]->(s)
        WHERE d.archived = false
        RETURN DISTINCT d.decision_id AS decision_id, d.text_raw AS text_raw, d.confidence AS confidence
        ORDER BY d.created_at DESC
        LIMIT 20
        """,
        params=("qid",),
        mutating=False,
        description="Decisions established in any session working on this quest (not just the current session)",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT DISTINCT ?decision_id ?text_raw ?confidence
            WHERE {
              ?q a campy:MainQuest ; campy:quest_id ?qid .
              ?s a campy:Session ; campy:WORKING_ON ?q .
              ?d a campy:Decision ;
                 campy:ESTABLISHED_IN ?s ;
                 campy:archived false ;
                 campy:decision_id ?decision_id ;
                 campy:text_raw ?text_raw .
              OPTIONAL { ?d campy:confidence ?confidence }
            }
            LIMIT 20
        """,
    ),
    NamedQuery(
        name="handoff.get_quest_constraints",
        cypher="""
        MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
        MATCH (c:Constraint)-[:ESTABLISHED_IN]->(s)
        WHERE c.archived = false
        RETURN DISTINCT c.constraint_id AS constraint_id, c.text_raw AS text_raw, c.confidence AS confidence
        ORDER BY c.created_at DESC
        LIMIT 20
        """,
        params=("qid",),
        mutating=False,
        description="Constraints established in any session working on this quest",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT DISTINCT ?constraint_id ?text_raw ?confidence
            WHERE {
              ?q a campy:MainQuest ; campy:quest_id ?qid .
              ?s a campy:Session ; campy:WORKING_ON ?q .
              ?c a campy:Constraint ;
                 campy:ESTABLISHED_IN ?s ;
                 campy:archived false ;
                 campy:constraint_id ?constraint_id ;
                 campy:text_raw ?text_raw .
              OPTIONAL { ?c campy:confidence ?confidence }
            }
            LIMIT 20
        """,
    ),
    NamedQuery(
        name="handoff.get_quest_work_artifacts",
        cypher="""
        MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
        MATCH (wa:WorkArtifact)-[:CREATED_IN]->(s)
        RETURN DISTINCT wa.file_path AS file_path, wa.title AS title, wa.document_type AS document_type
        ORDER BY wa.last_modified_at DESC
        LIMIT 20
        """,
        params=("qid",),
        mutating=False,
        description="Files touched in any session working on this quest",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT DISTINCT ?file_path ?title ?document_type
            WHERE {
              ?q a campy:MainQuest ; campy:quest_id ?qid .
              ?s a campy:Session ; campy:WORKING_ON ?q .
              ?wa a campy:WorkArtifact ;
                  campy:CREATED_IN ?s ;
                  campy:file_path ?file_path .
              OPTIONAL { ?wa campy:title ?title }
              OPTIONAL { ?wa campy:document_type ?document_type }
            }
            LIMIT 20
        """,
    ),
]
