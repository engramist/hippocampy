"""
campy/brain/hippocampus/graph/queries/retrieval.py — Retrieval and search queries.
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

RETRIEVAL_QUERIES = [
    NamedQuery(
        name="retrieval.timeline_starts_by_session",
        cypher="""
        MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})
        WHERE lower(m.text_raw) CONTAINS lower($topic)
        RETURN m.message_id, m.text_raw, m.created_at
        ORDER BY m.created_at ASC
        LIMIT $limit
        """,
        params=("sid", "topic", "limit"),
        mutating=False,
        description="Find timeline start messages by session and topic",
    ),
    NamedQuery(
        name="retrieval.timeline_starts_all",
        cypher="""
        MATCH (m:Message)
        WHERE lower(m.text_raw) CONTAINS lower($topic)
        RETURN m.message_id, m.text_raw, m.created_at
        ORDER BY m.created_at ASC
        LIMIT $limit
        """,
        params=("topic", "limit"),
        mutating=False,
        description="Find timeline start messages across all sessions by topic",
    ),
    NamedQuery(
        name="retrieval.timeline_starts_from_decisions",
        cypher="""
        MATCH (m:Message)-[:ESTABLISHED]->(d:Decision)
        WHERE lower(d.text_raw) CONTAINS lower($topic)
        RETURN m.message_id, m.text_raw, m.created_at
        ORDER BY m.created_at ASC
        LIMIT $limit
        """,
        params=("topic", "limit"),
        mutating=False,
        description="Find timeline start messages that established matching decisions",
    ),
    NamedQuery(
        name="retrieval.get_message_by_id",
        cypher="MATCH (m:Message {message_id: $mid}) RETURN m.message_id, m.text_raw, m.created_at",
        params=("mid",),
        mutating=False,
        description="Fetch a message by ID",
    ),
    NamedQuery(
        name="retrieval.get_decisions_for_message",
        cypher="MATCH (m:Message {message_id: $mid})-[:ESTABLISHED]->(d:Decision) RETURN d.decision_id, d.text_raw ORDER BY d.created_at ASC",
        params=("mid",),
        mutating=False,
        description="Fetch decisions established by a message",
    ),
    NamedQuery(
        name="retrieval.get_followed_by_message",
        cypher="""
        MATCH (m:Message {message_id: $mid})-[:FOLLOWED_BY]->(n:Message)
        RETURN n.message_id, n.text_raw, n.created_at
        LIMIT 1
        """,
        params=("mid",),
        mutating=False,
        description="Fetch next message in FOLLOWED_BY chain",
    ),
    NamedQuery(
        name="retrieval.get_main_quest_for_session",
        cypher="""
        MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest)
        RETURN q.quest_id
        """,
        params=("sid",),
        mutating=False,
        description="Resolve main quest ID for session",
    ),
    NamedQuery(
        name="retrieval.lexical_message_fallback",
        cypher="""
        MATCH (m:Message)
        WHERE lower(m.text_raw) CONTAINS lower($query)
          AND m.archived = false
          AND m.created_at > timestamp($cutoff)
        RETURN m.message_id, m.text_raw, m.role, m.confidence,
               m.confidence_low, m.pathway_strength, m.created_at
        ORDER BY m.created_at DESC
        LIMIT $limit
        """,
        params=("query", "cutoff", "limit"),
        mutating=False,
        description="Episodic exact-match fallback for messages",
    ),
    NamedQuery(
        name="retrieval.batch_outcome_signals",
        cypher="""
        UNWIND $ids AS nid
        OPTIONAL MATCH (ps:PlanStep)-[o:OUTCOME_SIGNAL]->(c:Concept {concept_id: nid})
        OPTIONAL MATCH (ps2:PlanStep)-[o2:OUTCOME_SIGNAL]->(c2:Concept)-[:REIFIED_AS]->(a)
        WHERE (a.decision_id = nid OR a.constraint_id = nid OR a.requirement_id = nid OR a.action_item_id = nid)
        WITH nid,
             CASE WHEN o IS NOT NULL THEN o.valence ELSE o2.valence END AS v
        WHERE v IS NOT NULL
        RETURN nid, avg(v), count(v)
        """,
        params=("ids",),
        mutating=False,
        description="Batch outcome signal lookup for retrieved nodes",
    ),
    NamedQuery(
        name="retrieval.get_knowledge_gaps_unresolved",
        cypher=(
            "MATCH (g:KnowledgeGap) WHERE g.resolved = false AND g.severity >= $min "
            "RETURN g.gap_id, g.domain, g.gap_type, g.description, g.severity, g.message_count, g.lesson_count, g.created_at "
            "ORDER BY g.severity DESC LIMIT $lim"
        ),
        params=("min", "lim"),
        mutating=False,
        description="Return unresolved KnowledgeGaps",
    ),
    NamedQuery(
        name="retrieval.get_knowledge_gaps_all",
        cypher=(
            "MATCH (g:KnowledgeGap) WHERE g.severity >= $min "
            "RETURN g.gap_id, g.domain, g.gap_type, g.description, g.severity, g.message_count, g.lesson_count, g.created_at "
            "ORDER BY g.severity DESC LIMIT $lim"
        ),
        params=("min", "lim"),
        mutating=False,
        description="Return all KnowledgeGaps with min severity",
    ),
    NamedQuery(
        name="retrieval.get_open_loops",
        cypher="""
        MATCH (c:Concept {confidence_low: true, archived: false})
        RETURN c.concept_id, c.text_raw, c.gist_class, c.schema_org_type,
               c.confidence, c.pathway_strength, c.created_at
        ORDER BY c.created_at DESC
        LIMIT $limit
        """,
        params=("limit",),
        mutating=False,
        description="Return soft-lock Concept nodes awaiting confirmation",
    ),
    NamedQuery(
        name="retrieval.get_distinct_pairs",
        cypher="""
        MATCH (a:Concept)-[:DISTINCT_FROM]-(b:Concept)
        WHERE a.concept_id IN $ids
        RETURN b.concept_id
        """,
        params=("ids",),
        mutating=False,
        description="Get concept IDs that are DISTINCT_FROM any of the given IDs",
    ),
    NamedQuery(
        name="retrieval.get_neighbor_concepts",
        cypher="""
        MATCH (c:Concept)-[r]->(n:Concept)
        WHERE c.concept_id IN $ids
          AND n.archived = false
          AND NOT n.concept_id IN $ids
        RETURN DISTINCT n.concept_id
        """,
        params=("ids",),
        mutating=False,
        description="Get 1-hop neighbor concept IDs for concepts",
    ),
    NamedQuery(
        name="retrieval.get_co_occurring_neighbors",
        cypher="""
        MATCH (c:Concept)-[r:CO_OCCURS_WITH]->(n:Concept)
        WHERE c.concept_id IN $ids
          AND r.count >= 3
          AND n.archived = false
          AND NOT n.concept_id IN $ids
        RETURN DISTINCT n.concept_id
        """,
        params=("ids",),
        mutating=False,
        description="Get strong CO_OCCURS_WITH neighbor concept IDs for concepts",
    ),
]

_DIFF_TABLES = [
    ("Concept", "concept_id", "concept"),
    ("Decision", "decision_id", "decision"),
    ("Constraint", "constraint_id", "constraint"),
    ("Requirement", "requirement_id", "requirement"),
    ("ActionItem", "action_item_id", "actionitem"),
]

for label, pk, key in _DIFF_TABLES:
    RETRIEVAL_QUERIES.extend([
        NamedQuery(
            name=f"retrieval.diff_since_{key}",
            cypher=f"""
            MATCH (a:{label})
            WHERE a.archived = false AND a.created_at > $since
            RETURN a.{pk}, a.text_raw, a.confidence, a.confidence_low,
                   a.pathway_strength, a.created_at
            ORDER BY a.created_at DESC
            LIMIT $limit
            """,
            params=("since", "limit"),
            mutating=False,
            description=f"Diff {label} nodes created since timestamp",
        ),
        NamedQuery(
            name=f"retrieval.get_originating_message_{key}",
            cypher=f"""
            MATCH (n:{label})-[r:ESTABLISHED_IN]->(m:Message)
            WHERE n.{pk} = $id
            RETURN m.content
            LIMIT 1
            """,
            params=("id",),
            mutating=False,
            description=f"Find originating message for {label}",
        ),
    ])

# Also add DocumentExtract and Message for get_originating_message
RETRIEVAL_QUERIES.append(
    NamedQuery(
        name="retrieval.get_originating_message_documentextract",
        cypher="""
        MATCH (n:DocumentExtract)-[r:ESTABLISHED_IN]->(m:Message)
        WHERE n.extract_id = $id
        RETURN m.content
        LIMIT 1
        """,
        params=("id",),
        mutating=False,
        description="Find originating message for DocumentExtract",
    )
)
RETRIEVAL_QUERIES.append(
    NamedQuery(
        name="retrieval.get_originating_message_message",
        cypher="""
        MATCH (n:Message)-[r:ESTABLISHED_IN]->(m:Message)
        WHERE n.message_id = $id
        RETURN m.content
        LIMIT 1
        """,
        params=("id",),
        mutating=False,
        description="Find originating message for Message",
    )
)
