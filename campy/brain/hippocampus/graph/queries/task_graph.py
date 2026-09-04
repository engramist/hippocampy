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
    ),
    NamedQuery(
        name="task_graph.get_graph_metadata",
        cypher="""
        MATCH (g:TaskGraph {graph_id: $gid}) RETURN g.label, g.status, g.version
        """,
        params=("gid",),
        mutating=False,
        description="Fetch TaskGraph metadata",
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
            )
        )
