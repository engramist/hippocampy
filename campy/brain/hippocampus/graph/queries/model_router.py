"""
campy/brain/hippocampus/graph/queries/model_router.py — B382 phase-detection queries.

New file (not an extension of thalamus.py or task_graph.py) to avoid
colliding with a peer session's in-flight SPARQL audit of arc.py/
thalamus.py.

Two queries only — everything else phase detection needs (TaskNode
statuses once a graph_id is known) is already covered by
task_graph.get_graph_tasks:

- `model_router.get_active_plan_count_for_quest`: Plan really does carry
  a direct `TARGETS` edge to its MainQuest (see
  `lessons.find_quest_for_plan`/`lessons.create_plan` in
  queries/lessons.py) — a genuine 1-hop, indexed lookup.
- `model_router.get_active_task_graph_for_session`: TaskGraph.session_id
  is a plain property, not an edge (see `task_graph.init_task_graph` in
  queries/task_graph.py) — so this is a direct property-indexed lookup,
  scoped to the caller's own session_id rather than requiring a
  quest -> sessions -> TaskGraph hop.
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

MODEL_ROUTER_QUERIES = [
    NamedQuery(
        name="model_router.get_active_plans_for_quest",
        cypher="""
        MATCH (p:Plan {status: 'active'})-[:TARGETS]->(q:MainQuest {quest_id: $qid})
        RETURN p.plan_id AS plan_id, p.goal AS goal, p.confidence AS confidence
        LIMIT 10
        """,
        params=("qid",),
        mutating=False,
        description="List active (unfinalized) Plans targeting a quest -- doubles as phase signal and bundle content",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?plan_id ?goal ?confidence
            WHERE {
              ?q a campy:MainQuest ; campy:quest_id ?qid .
              ?p a campy:Plan ;
                 campy:status "active" ;
                 campy:TARGETS ?q ;
                 campy:plan_id ?plan_id ;
                 campy:goal ?goal .
              OPTIONAL { ?p campy:confidence ?confidence }
            }
            LIMIT 10
        """,
    ),
    NamedQuery(
        name="model_router.get_active_task_graph_for_session",
        cypher="""
        MATCH (g:TaskGraph {session_id: $sid, status: 'active'})
        RETURN g.graph_id AS graph_id
        ORDER BY g.created_at DESC
        LIMIT 1
        """,
        params=("sid",),
        mutating=False,
        description="Find the most recent active TaskGraph for a session",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?graph_id ?created_at
            WHERE {
              ?g a campy:TaskGraph ;
                 campy:session_id ?sid ;
                 campy:status "active" ;
                 campy:graph_id ?graph_id .
              OPTIONAL { ?g campy:created_at ?created_at }
            }
            ORDER BY DESC(?created_at)
            LIMIT 1
        """,
    ),
]
