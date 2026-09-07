"""
campy/brain/hippocampus/graph/queries/task_graph.py — TaskGraph and TaskNode queries.
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

TASK_GRAPH_QUERIES = [
    NamedQuery(
        name="task_graph.create_task_graph",
        cypher="""
        CREATE (g:TaskGraph {
            graph_id: $id,
            name: $name,
            description: $description,
            label: $name,
            status: 'active',
            version: 1,
            created_at: timestamp($now)
        })
        """,
        params=("id", "name", "description", "now"),
        mutating=True,
        description="Create TaskGraph node",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?g a campy:TaskGraph ;
                 campy:graph_id ?id ;
                 campy:name ?name ;
                 campy:description ?description ;
                 campy:label ?name ;
                 campy:status "active" ;
                 campy:version "1"^^xsd:integer ;
                 campy:created_at ?now .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/TaskGraph/", ENCODE_FOR_URI(STR(?id)))) AS ?g)
            }
        """,
    ),
    NamedQuery(
        name="task_graph.create_task_node_with_graph",
        cypher="""
        CREATE (t:TaskNode {
            task_id: $tid,
            graph_id: $gid,
            name: $name,
            label: $name,
            description: $description,
            status: 'pending',
            created_at: timestamp($now)
        })
        WITH t
        MATCH (g:TaskGraph {graph_id: $gid})
        CREATE (t)-[:TASK_OF]->(g)
        """,
        params=("tid", "gid", "name", "description", "now"),
        mutating=True,
        description="Create TaskNode and link to TaskGraph",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?t a campy:TaskNode ;
                 campy:task_id ?tid ;
                 campy:graph_id ?gid ;
                 campy:name ?name ;
                 campy:label ?name ;
                 campy:description ?description ;
                 campy:status "pending" ;
                 campy:created_at ?now ;
                 campy:TASK_OF ?g .
            }
            WHERE {
              ?g a campy:TaskGraph ; campy:graph_id ?gid .
              BIND(IRI(CONCAT("https://campy.dev/data/TaskNode/", ENCODE_FOR_URI(STR(?tid)))) AS ?t)
            }
        """,
    ),
    NamedQuery(
        name="task_graph.create_task_dependency",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid}), (dep:TaskNode {task_id: $did})
        CREATE (t)-[:DEPENDS_ON]->(dep)
        """,
        params=("tid", "did"),
        mutating=True,
        description="Create DEPENDS_ON edge between TaskNodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?t campy:DEPENDS_ON ?dep .
            }
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              ?dep a campy:TaskNode ; campy:task_id ?did .
            }
        """,
    ),
    NamedQuery(
        name="task_graph.check_dag_cycle",
        cypher="""
        MATCH (a:TaskNode {task_id: $to_id}), (b:TaskNode {task_id: $from_id})
        MATCH p = (a)-[:DEPENDS_ON*]->(b)
        RETURN count(p) AS cnt
        """,
        params=("to_id", "from_id"),
        mutating=False,
        description="Check if path exists between TaskNodes for cycle detection",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT (COUNT(?b) AS ?cnt)
            WHERE {
              ?a a campy:TaskNode ; campy:task_id ?to_id .
              ?b a campy:TaskNode ; campy:task_id ?from_id .
              ?a campy:DEPENDS_ON+ ?b .
            }
        """,
    ),
    NamedQuery(
        name="task_graph.get_ready_tasks",
        cypher="""
        MATCH (t:TaskNode)-[:TASK_OF]->(g:TaskGraph {graph_id: $graph_id})
        WHERE t.status = 'pending'
        AND NOT EXISTS {
            MATCH (t)-[:DEPENDS_ON]->(dep:TaskNode)
            WHERE NOT (dep.status IN ['complete', 'skipped'])
        }
        RETURN t.task_id, t.name, t.description, t.status, t.owner
        """,
        params=("graph_id",),
        mutating=False,
        description="Fetch ready tasks in TaskGraph",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?task_id ?name ?description ?status ?owner
            WHERE {
              ?g a campy:TaskGraph ; campy:graph_id ?graph_id .
              ?t a campy:TaskNode ;
                 campy:TASK_OF ?g ;
                 campy:task_id ?task_id ;
                 campy:status "pending" .
              BIND("pending" AS ?status)
              OPTIONAL { ?t campy:name ?name }
              OPTIONAL { ?t campy:description ?description }
              OPTIONAL { ?t campy:owner ?owner }
              FILTER NOT EXISTS {
                ?t campy:DEPENDS_ON ?dep .
                ?dep a campy:TaskNode ;
                     campy:status ?dep_status .
                FILTER(?dep_status != "complete" && ?dep_status != "skipped")
              }
            }
        """,
    ),
    NamedQuery(
        name="task_graph.init_task_graph",
        cypher="""
        CREATE (g:TaskGraph {
            graph_id: $id,
            name: $label,
            label: $label,
            version: 1,
            session_id: $sid,
            owner: $owner,
            status: 'active',
            created_at: timestamp($now)
        })
        """,
        params=("id", "label", "sid", "owner", "now"),
        mutating=True,
        description="Initialize TaskGraph node with session and owner",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?g a campy:TaskGraph ;
                 campy:graph_id ?id ;
                 campy:name ?label ;
                 campy:label ?label ;
                 campy:version "1"^^xsd:integer ;
                 campy:session_id ?sid ;
                 campy:owner ?owner ;
                 campy:status "active" ;
                 campy:created_at ?now .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/TaskGraph/", ENCODE_FOR_URI(STR(?id)))) AS ?g)
            }
        """,
    ),
    NamedQuery(
        name="task_graph.merge_task_node_with_graph",
        cypher="""
        MERGE (t:TaskNode {task_id: $tid})
        ON CREATE SET
            t.graph_id = $gid,
            t.name = $label,
            t.label = $label,
            t.description = $description,
            t.status = 'pending',
            t.owner = $owner,
            t.created_at = timestamp($now)
        WITH t
        MATCH (g:TaskGraph {graph_id: $gid})
        MERGE (t)-[:TASK_OF]->(g)
        """,
        params=("tid", "gid", "label", "description", "owner", "now"),
        mutating=True,
        description="Merge TaskNode and link to TaskGraph",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?target_t a campy:TaskNode ;
                 campy:task_id ?tid ;
                 campy:graph_id ?gid ;
                 campy:name ?label ;
                 campy:label ?label ;
                 campy:description ?description ;
                 campy:status "pending" ;
                 campy:owner ?owner ;
                 campy:created_at ?now ;
                 campy:TASK_OF ?g .
            }
            WHERE {
              ?g a campy:TaskGraph ; campy:graph_id ?gid .
              OPTIONAL { ?t a campy:TaskNode ; campy:task_id ?tid }
              BIND(COALESCE(?t, IRI(CONCAT("https://campy.dev/data/TaskNode/", ENCODE_FOR_URI(STR(?tid))))) AS ?target_t)
            }
        """,
    ),
    NamedQuery(
        name="task_graph.merge_task_dependency",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid}), (dep:TaskNode {task_id: $did})
        MERGE (t)-[:DEPENDS_ON]->(dep)
        """,
        params=("tid", "did"),
        mutating=True,
        description="Merge DEPENDS_ON edge between TaskNodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?t campy:DEPENDS_ON ?dep .
            }
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              ?dep a campy:TaskNode ; campy:task_id ?did .
            }
        """,
    ),
    NamedQuery(
        name="task_graph.update_task_node",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid})
        SET t.status = $status,
            t.started_at = CASE WHEN $status = 'active' THEN timestamp($now) ELSE t.started_at END,
            t.completed_at = CASE WHEN $status IN ['complete', 'skipped'] THEN timestamp($now) ELSE t.completed_at END,
            t.result = CASE WHEN $has_result THEN $result ELSE t.result END
        """,
        params=("tid", "status", "now", "has_result", "result"),
        mutating=True,
        description="Update TaskNode status, timestamps, and result",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?t campy:status ?old_status .
              ?t campy:started_at ?old_started .
              ?t campy:completed_at ?old_completed .
              ?t campy:result ?old_result .
            }
            INSERT {
              ?t campy:status ?status .
              ?t campy:started_at ?target_started .
              ?t campy:completed_at ?target_completed .
              ?t campy:result ?target_result .
            }
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              OPTIONAL { ?t campy:status ?old_status }
              OPTIONAL { ?t campy:started_at ?old_started }
              OPTIONAL { ?t campy:completed_at ?old_completed }
              OPTIONAL { ?t campy:result ?old_result }
              BIND(IF(?status = "active", ?now, ?old_started) AS ?target_started)
              BIND(IF(?status = "complete" || ?status = "skipped", ?now, ?old_completed) AS ?target_completed)
              BIND(IF(?has_result, ?result, ?old_result) AS ?target_result)
            }
        """,
    ),
    NamedQuery(
        name="task_graph.update_task_status",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid})
        SET t.status = $status
        """,
        params=("tid", "status"),
        mutating=True,
        description="Update TaskNode status only",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE { ?t campy:status ?old_status . }
            INSERT { ?t campy:status ?status . }
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              OPTIONAL { ?t campy:status ?old_status }
            }
        """,
    ),
    NamedQuery(
        name="task_graph.update_task_status_completed",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid})
        SET t.status = $status, t.completed_at = timestamp($now)
        """,
        params=("tid", "status", "now"),
        mutating=True,
        description="Update TaskNode status and completed_at",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?t campy:status ?old_status .
              ?t campy:completed_at ?old_completed .
            }
            INSERT {
              ?t campy:status ?status .
              ?t campy:completed_at ?now .
            }
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              OPTIONAL { ?t campy:status ?old_status }
              OPTIONAL { ?t campy:completed_at ?old_completed }
            }
        """,
    ),
    NamedQuery(
        name="task_graph.update_task_status_result",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid})
        SET t.status = $status, t.result = $result
        """,
        params=("tid", "status", "result"),
        mutating=True,
        description="Update TaskNode status and result",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?t campy:status ?old_status .
              ?t campy:result ?old_result .
            }
            INSERT {
              ?t campy:status ?status .
              ?t campy:result ?result .
            }
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              OPTIONAL { ?t campy:status ?old_status }
              OPTIONAL { ?t campy:result ?old_result }
            }
        """,
    ),
    NamedQuery(
        name="task_graph.update_task_status_completed_result",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid})
        SET t.status = $status, t.completed_at = timestamp($now), t.result = $result
        """,
        params=("tid", "status", "now", "result"),
        mutating=True,
        description="Update TaskNode status, completed_at, and result",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?t campy:status ?old_status .
              ?t campy:completed_at ?old_completed .
              ?t campy:result ?old_result .
            }
            INSERT {
              ?t campy:status ?status .
              ?t campy:completed_at ?now .
              ?t campy:result ?result .
            }
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              OPTIONAL { ?t campy:status ?old_status }
              OPTIONAL { ?t campy:completed_at ?old_completed }
              OPTIONAL { ?t campy:result ?old_result }
            }
        """,
    ),
    NamedQuery(
        name="task_graph.fail_task",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid})
        SET t.status = 'failed', t.result = $reason, t.completed_at = timestamp($now)
        """,
        params=("tid", "reason", "now"),
        mutating=True,
        description="Mark TaskNode failed with reason",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?t campy:status ?old_status .
              ?t campy:completed_at ?old_completed .
              ?t campy:result ?old_result .
            }
            INSERT {
              ?t campy:status "failed" .
              ?t campy:result ?reason .
              ?t campy:completed_at ?now .
            }
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              OPTIONAL { ?t campy:status ?old_status }
              OPTIONAL { ?t campy:completed_at ?old_completed }
              OPTIONAL { ?t campy:result ?old_result }
            }
        """,
    ),
    NamedQuery(
        name="task_graph.get_blocked_dependents",
        cypher="""
        MATCH (t:TaskNode {task_id: $tid})<-[:DEPENDS_ON*]-(dep:TaskNode)
        WHERE dep.status = 'pending'
        RETURN DISTINCT dep.task_id
        """,
        params=("tid",),
        mutating=False,
        description="Get pending dependent TaskNodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT DISTINCT ?task_id
            WHERE {
              ?t a campy:TaskNode ; campy:task_id ?tid .
              ?dep campy:DEPENDS_ON+ ?t .
              ?dep a campy:TaskNode ;
                   campy:task_id ?task_id ;
                   campy:status "pending" .
            }
        """,
    ),
    NamedQuery(
        name="task_graph.get_graph_metadata",
        cypher="""
        MATCH (g:TaskGraph {graph_id: $gid}) RETURN g.label, g.status, g.version
        """,
        params=("gid",),
        mutating=False,
        description="Fetch TaskGraph metadata",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?label ?status ?version
            WHERE {
              ?g a campy:TaskGraph ;
                 campy:graph_id ?gid ;
                 campy:label ?label ;
                 campy:status ?status ;
                 campy:version ?version .
            }
        """,
    ),
    NamedQuery(
        name="task_graph.get_graph_tasks",
        cypher="""
        MATCH (t:TaskNode)-[:TASK_OF]->(g:TaskGraph {graph_id: $gid})
        RETURN t.task_id, t.label, t.description, t.status, t.owner, t.result
        """,
        params=("gid",),
        mutating=False,
        description="Fetch all tasks belonging to TaskGraph",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?task_id ?label ?description ?status ?owner ?result
            WHERE {
              ?g a campy:TaskGraph ; campy:graph_id ?gid .
              ?t a campy:TaskNode ;
                 campy:TASK_OF ?g ;
                 campy:task_id ?task_id ;
                 campy:label ?label ;
                 campy:status ?status .
              OPTIONAL { ?t campy:description ?description }
              OPTIONAL { ?t campy:owner ?owner }
              OPTIONAL { ?t campy:result ?result }
            }
        """,
    ),
    NamedQuery(
        name="task_graph.get_graph_edges",
        cypher="""
        MATCH (t1:TaskNode)-[:DEPENDS_ON]->(t2:TaskNode)
        MATCH (t1)-[:TASK_OF]->(g:TaskGraph {graph_id: $gid})
        RETURN t1.task_id, t2.task_id
        """,
        params=("gid",),
        mutating=False,
        description="Fetch all edges belonging to TaskGraph",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?task_id1 ?task_id2
            WHERE {
              ?g a campy:TaskGraph ; campy:graph_id ?gid .
              ?t1 a campy:TaskNode ;
                  campy:TASK_OF ?g ;
                  campy:task_id ?task_id1 ;
                  campy:DEPENDS_ON ?t2 .
              ?t2 a campy:TaskNode ;
                  campy:task_id ?task_id2 .
            }
        """,
    ),
]

# Add cycle check and merge dependency edge queries for the 6 combinations
_TABLE_PKS = {
    "mainquest": ("MainQuest", "quest_id"),
    "sidequest": ("SideQuest", "quest_id"),
    "actionitem": ("ActionItem", "action_item_id"),
}
_RELS = {
    "task_blocks": "TASK_BLOCKS",
    "task_enables": "TASK_ENABLES",
}

for r_key, rel in _RELS.items():
    for t_key, (table, pk) in _TABLE_PKS.items():
        TASK_GRAPH_QUERIES.append(
            NamedQuery(
                name=f"task_graph.cycle_check_{r_key}_{t_key}",
                cypher=f"""
                MATCH p = (b:{table} {{{pk}: $to_id}})-[:{rel}*1..10]->(a:{table} {{{pk}: $from_id}})
                RETURN nodes(p) AS path_nodes LIMIT 1
                """,
                params=("to_id", "from_id"),
                mutating=False,
                description=f"Check cycle for {rel} on {table}",
                sparql=f"""
                    PREFIX campy: <https://campy.dev/ns#>

                    SELECT ?b ?a
                    WHERE {{
                      ?b a campy:{table} ; campy:{pk} ?to_id .
                      ?a a campy:{table} ; campy:{pk} ?from_id .
                      ?b campy:{rel}+ ?a .
                    }}
                    LIMIT 1
                """,
            )
        )
        TASK_GRAPH_QUERIES.append(
            NamedQuery(
                name=f"task_graph.merge_dependency_edge_{r_key}_{t_key}",
                cypher=f"""
                MATCH (a:{table} {{{pk}: $from_id}}), (b:{table} {{{pk}: $to_id}})
                MERGE (a)-[r:{rel}]->(b)
                SET r.declared_by = $declared_by, r.confidence = $confidence,
                    r.observed_at = timestamp($now), r.source = $source,
                    r.source_version = $source_version, r.authority = $authority
                """,
                params=(
                    "from_id", "to_id", "declared_by", "confidence",
                    "now", "source", "source_version", "authority",
                ),
                mutating=True,
                description=f"Merge {rel} edge on {table}",
                sparql=f"""
                    PREFIX campy: <https://campy.dev/ns#>

                    INSERT {{
                      ?a campy:{rel} ?b .
                      << ?a campy:{rel} ?b >> campy:declared_by ?declared_by ;
                                              campy:confidence ?confidence ;
                                              campy:observed_at ?now ;
                                              campy:source ?source ;
                                              campy:source_version ?source_version ;
                                              campy:authority ?authority .
                    }}
                    WHERE {{
                      ?a a campy:{table} ; campy:{pk} ?from_id .
                      ?b a campy:{table} ; campy:{pk} ?to_id .
                    }}
                """,
            )
        )
