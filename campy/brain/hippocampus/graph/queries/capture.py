"""
campy/brain/hippocampus/graph/queries/capture.py — Message capture and ingestion queries.
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

CAPTURE_QUERIES = [
    NamedQuery(
        name="capture.set_session_token_limit",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        WHERE s.token_limit IS NULL OR s.token_limit = 0
        SET s.token_limit = $limit
        """,
        params=("sid", "limit"),
        mutating=True,
        description="Initialize session token limit if not already set",
    ),
    NamedQuery(
        name="capture.archive_earlier_message_version",
        cypher="""
        MATCH (m:Message)
        WHERE m.text_raw CONTAINS $marker AND m.archived = false
        SET m.archived = true
        """,
        params=("marker",),
        mutating=True,
        description="Archive earlier live Message carrying source memory key",
    ),
    NamedQuery(
        name="capture.create_message",
        cypher="""
        CREATE (m:Message {
            message_id:      $message_id,
            text_raw:        $text_raw,
            embedding:       $embedding,
            embedding_model: $embedding_model,
            embedding_dim:   $embedding_dim,
            role:            $role,
            byte_start:      0,
            byte_end:        $byte_end,
            confidence:      0.0,
            confidence_low:  true,
            pathway_strength: 0.0,
            archived:        false,
            created_at:      timestamp($created_at)
        })
        """,
        params=(
            "message_id", "text_raw", "embedding", "embedding_model",
            "embedding_dim", "role", "byte_end", "created_at",
        ),
        mutating=True,
        description="Create Message node in graph",
    ),
    NamedQuery(
        name="capture.link_message_sent_in_session",
        cypher="""
        MATCH (s:Session {session_id: $session_id}),
              (m:Message {message_id: $message_id})
        MERGE (m)-[:SENT_IN]->(s)
        """,
        params=("session_id", "message_id"),
        mutating=True,
        description="Link Message to Session with SENT_IN",
    ),
    NamedQuery(
        name="capture.find_previous_message_in_session",
        cypher="""
        MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})
        WHERE m.message_id <> $mid
        RETURN m.message_id, m.created_at
        ORDER BY m.created_at DESC
        LIMIT 1
        """,
        params=("sid", "mid"),
        mutating=False,
        description="Find most recent previous message in same session",
    ),
    NamedQuery(
        name="capture.merge_followed_by",
        cypher="""
        MATCH (p:Message {message_id: $prev}), (c:Message {message_id: $curr})
        MERGE (p)-[r:FOLLOWED_BY]->(c)
        ON CREATE SET r.gap_seconds = $gap
        ON MATCH SET r.gap_seconds = $gap
        """,
        params=("prev", "curr", "gap"),
        mutating=True,
        description="Create FOLLOWED_BY edge with turn gap seconds",
    ),
    NamedQuery(
        name="capture.get_last_loop_summary",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        RETURN s.last_loop_summary
        """,
        params=("sid",),
        mutating=False,
        description="Read previous loop summary JSON from Session node",
    ),
    NamedQuery(
        name="capture.get_last_proactive_push_count",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        RETURN s.last_proactive_push_msg_count
        """,
        params=("sid",),
        mutating=False,
        description="Read last proactive push count from Session",
    ),
    NamedQuery(
        name="capture.find_knowledge_gaps_for_content",
        cypher="""
        MATCH (g:KnowledgeGap)
        WHERE (g.resolved IS NULL OR g.resolved = false)
          AND (lower(g.description) CONTAINS lower($snippet) OR lower(g.domain) CONTAINS lower($snippet))
        RETURN g.gap_id, g.description, g.severity
        ORDER BY g.severity DESC
        LIMIT $lim
        """,
        params=("snippet", "lim"),
        mutating=False,
        description="Find knowledge gaps matching content snippet",
    ),
    NamedQuery(
        name="capture.set_last_proactive_push_count",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        SET s.last_proactive_push_msg_count = $count
        """,
        params=("sid", "count"),
        mutating=True,
        description="Persist last proactive push message count on Session",
    ),
]
