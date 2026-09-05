"""
campy/brain/hippocampus/graph/queries/working_memory.py — Working memory and context tracking queries.
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

WORKING_MEMORY_QUERIES = [
    NamedQuery(
        name="working_memory.update_session_loaded_stats",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        SET s.loaded_node_count = $count,
            s.last_injection_at = timestamp($now),
            s.injection_count = coalesce(s.injection_count, 0) + $processed,
            s.dedup_tokens_saved = coalesce(s.dedup_tokens_saved, 0) + $dedup
        """,
        params=("sid", "count", "now", "processed", "dedup"),
        mutating=True,
        description="Update session loaded node counts and token metrics",
    ),
    NamedQuery(
        name="working_memory.get_token_estimate",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        RETURN s.token_estimate
        """,
        params=("sid",),
        mutating=False,
        description="Get session cumulative token estimate",
    ),
    NamedQuery(
        name="working_memory.set_token_estimate",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        SET s.token_estimate = $est
        """,
        params=("sid", "est"),
        mutating=True,
        description="Set session cumulative token estimate",
    ),
    NamedQuery(
        name="working_memory.get_session_token_state",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        RETURN s.token_estimate, s.token_limit, s.loaded_node_count,
               s.dedup_tokens_saved, s.injection_count
        """,
        params=("sid",),
        mutating=False,
        description="Return current token usage vs limit for session",
    ),
    NamedQuery(
        name="working_memory.count_session_messages",
        cypher="""
        MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})
        WHERE m.archived IS NULL OR m.archived = false
        RETURN count(m)
        """,
        params=("sid",),
        mutating=False,
        description="Count active messages sent in session",
    ),
    NamedQuery(
        name="working_memory.find_prior_session_on_quest",
        cypher="""
        MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
        WHERE s.session_id <> $new_sid
        RETURN s.session_id
        ORDER BY s.last_active_at DESC
        LIMIT 1
        """,
        params=("qid", "new_sid"),
        mutating=False,
        description="Find most recent prior session working on same quest",
    ),
]

_NODE_PK_MAP = {
    "Concept":          ("concept_id", "concept"),
    "Decision":         ("decision_id", "decision"),
    "Constraint":       ("constraint_id", "constraint"),
    "Requirement":      ("requirement_id", "requirement"),
    "ActionItem":       ("action_item_id", "actionitem"),
    "GlobalConstraint": ("global_constraint_id", "globalconstraint"),
    "GlobalPreference": ("global_preference_id", "globalpreference"),
}

for node_type, (pk_col, key) in _NODE_PK_MAP.items():
    WORKING_MEMORY_QUERIES.extend([
        NamedQuery(
            name=f"working_memory.check_loaded_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type} {{{pk_col}: $nid}})
            RETURN l.load_hits
            """,
            params=("sid", "nid"),
            mutating=False,
            description=f"Check if {node_type} is already LOADED in session",
        ),
        NamedQuery(
            name=f"working_memory.update_loaded_hit_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type} {{{pk_col}: $nid}})
            SET l.injected_at = timestamp($now),
                l.load_hits = $hits,
                l.token_estimate = $tokens
            """,
            params=("sid", "nid", "now", "hits", "tokens"),
            mutating=True,
            description=f"Update existing LOADED edge on {node_type} hit",
        ),
        NamedQuery(
            name=f"working_memory.create_loaded_edge_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}}), (n:{node_type} {{{pk_col}: $nid}})
            CREATE (s)-[:LOADED {{injected_at: timestamp($now), token_estimate: $tokens, source: $source, load_hits: 1}}]->(n)
            """,
            params=("sid", "nid", "now", "tokens", "source"),
            mutating=True,
            description=f"Create new LOADED edge between Session and {node_type}",
        ),
        NamedQuery(
            name=f"working_memory.get_loaded_ids_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type})
            RETURN n.{pk_col}
            """,
            params=("sid",),
            mutating=False,
            description=f"Get loaded {node_type} IDs for session",
        ),
        NamedQuery(
            name=f"working_memory.count_loaded_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type})
            RETURN count(*)
            """,
            params=("sid",),
            mutating=False,
            description=f"Count loaded {node_type} edges for session",
        ),
        NamedQuery(
            name=f"working_memory.get_handoff_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type})
            WHERE n.archived = false
            RETURN n.{pk_col}, n.text_raw, n.pathway_strength
            ORDER BY n.pathway_strength DESC
            LIMIT $limit
            """,
            params=("sid", "limit"),
            mutating=False,
            description=f"Get top {node_type} nodes for cross-session handoff",
        ),
        NamedQuery(
            name=f"working_memory.get_timeline_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type})
            RETURN n.{pk_col}, l.injected_at, l.token_estimate, l.load_hits
            ORDER BY l.injected_at ASC
            """,
            params=("sid",),
            mutating=False,
            description=f"Get chronological timeline of LOADED events for {node_type}",
        ),
    ])
