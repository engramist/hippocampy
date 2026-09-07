"""
campy/brain/hippocampus/graph/queries/retrieval.py — Retrieval and search queries.

B393: `sparql=` added per docs/rdf-schema-mapping.md. Conventions shared
with the rest of the batch (see capture.py's module docstring for the
`LIMIT $param` rationale, and working_memory.py's for the column-naming
note):

- **Array-valued params** (`$ids` here) are represented as an empty
  `VALUES ?var { }` block, expanded by the future binding layer into one
  row per element — pyoxigraph's `substitutions=` only binds single terms
  per variable, so this is infrastructure work out of scope for this card.
- `CO_OCCURS_WITH` is `star` in `EDGE_REIFICATION` (singleton edge with an
  accumulator, spec §4.2c) — its `count`/`strength` properties hang off
  the quoted triple directly (`<< ?a campy:CO_OCCURS_WITH ?b >> campy:count
  ?count`), not off an occurrence node.
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
        sparql="""
            SELECT ?message_id ?text_raw ?created_at WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                ?m campy:SENT_IN ?s ;
                   a campy:Message ;
                   campy:message_id ?message_id ;
                   campy:text_raw ?text_raw ;
                   campy:created_at ?created_at .
                FILTER(CONTAINS(LCASE(?text_raw), LCASE(?topic)))
            }
            ORDER BY ASC(?created_at)
            """,
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
        sparql="""
            SELECT ?message_id ?text_raw ?created_at WHERE {
                ?m a campy:Message ;
                   campy:message_id ?message_id ;
                   campy:text_raw ?text_raw ;
                   campy:created_at ?created_at .
                FILTER(CONTAINS(LCASE(?text_raw), LCASE(?topic)))
            }
            ORDER BY ASC(?created_at)
            """,
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
        sparql="""
            SELECT ?message_id ?text_raw ?created_at WHERE {
                ?m a campy:Message ;
                   campy:ESTABLISHED ?d ;
                   campy:message_id ?message_id ;
                   campy:text_raw ?text_raw ;
                   campy:created_at ?created_at .
                ?d a campy:Decision ;
                   campy:text_raw ?d_text_raw .
                FILTER(CONTAINS(LCASE(?d_text_raw), LCASE(?topic)))
            }
            ORDER BY ASC(?created_at)
            """,
    ),
    NamedQuery(
        name="retrieval.get_message_by_id",
        cypher="MATCH (m:Message {message_id: $mid}) RETURN m.message_id, m.text_raw, m.created_at",
        params=("mid",),
        mutating=False,
        description="Fetch a message by ID",
        sparql="""
            SELECT ?message_id ?text_raw ?created_at WHERE {
                ?m a campy:Message ;
                   campy:message_id ?mid ;
                   campy:text_raw ?text_raw ;
                   campy:created_at ?created_at .
                BIND(?mid AS ?message_id)
            }
            """,
    ),
    NamedQuery(
        name="retrieval.get_decisions_for_message",
        cypher="MATCH (m:Message {message_id: $mid})-[:ESTABLISHED]->(d:Decision) RETURN d.decision_id, d.text_raw ORDER BY d.created_at ASC",
        params=("mid",),
        mutating=False,
        description="Fetch decisions established by a message",
        sparql="""
            SELECT ?decision_id ?text_raw WHERE {
                ?m a campy:Message ;
                   campy:message_id ?mid .
                ?m campy:ESTABLISHED ?d .
                ?d a campy:Decision ;
                   campy:decision_id ?decision_id ;
                   campy:text_raw ?text_raw ;
                   campy:created_at ?created_at .
            }
            ORDER BY ASC(?created_at)
            """,
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
        # FOLLOWED_BY is "star" but this only checks existence of the plain
        # triple (always asserted per spec §4.2a) — no quoted-triple
        # property is read here.
        sparql="""
            SELECT ?message_id ?text_raw ?created_at WHERE {
                ?m a campy:Message ;
                   campy:message_id ?mid .
                ?m campy:FOLLOWED_BY ?n .
                ?n a campy:Message ;
                   campy:message_id ?message_id ;
                   campy:text_raw ?text_raw ;
                   campy:created_at ?created_at .
            }
            LIMIT 1
            """,
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
        sparql="""
            SELECT ?quest_id WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                ?s campy:WORKING_ON ?q .
                ?q a campy:MainQuest ;
                   campy:quest_id ?quest_id .
            }
            """,
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
        sparql="""
            SELECT ?message_id ?text_raw ?role ?confidence ?confidence_low
                   ?pathway_strength ?created_at WHERE {
                ?m a campy:Message ;
                   campy:message_id ?message_id ;
                   campy:text_raw ?text_raw ;
                   campy:role ?role ;
                   campy:confidence ?confidence ;
                   campy:confidence_low ?confidence_low ;
                   campy:pathway_strength ?pathway_strength ;
                   campy:created_at ?created_at .
                FILTER(CONTAINS(LCASE(?text_raw), LCASE(?query)))
                FILTER(?created_at > ?cutoff)
                OPTIONAL { ?m campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?created_at)
            """,
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
        # OUTCOME_SIGNAL is "star" — valence hangs off the quoted triple.
        # REIFIED_AS is "plain". Direct hits (nid is itself a Concept) and
        # reified hits (nid is the id of whatever the Concept was REIFIED_AS)
        # are two disjoint sources of the same `v` — modeled as a UNION so
        # both contribute to the same AVG/COUNT per nid, matching the
        # Cypher CASE's either/or selection. A nid with no outcome signal at
        # all (v never bound) is naturally absent from the result, matching
        # `WHERE v IS NOT NULL` filtering it out of the Cypher aggregation.
        sparql="""
            SELECT ?nid (AVG(?v) AS ?avg_v) (COUNT(?v) AS ?count_v) WHERE {
                VALUES ?nid { }
                {
                    ?c a campy:Concept ;
                       campy:concept_id ?nid .
                    ?ps a campy:PlanStep .
                    ?ps campy:OUTCOME_SIGNAL ?c .
                    << ?ps campy:OUTCOME_SIGNAL ?c >> campy:valence ?v .
                }
                UNION
                {
                    ?c2 a campy:Concept .
                    ?ps2 a campy:PlanStep .
                    ?ps2 campy:OUTCOME_SIGNAL ?c2 .
                    << ?ps2 campy:OUTCOME_SIGNAL ?c2 >> campy:valence ?v .
                    ?c2 campy:REIFIED_AS ?a .
                    { ?a campy:decision_id ?nid }
                    UNION { ?a campy:constraint_id ?nid }
                    UNION { ?a campy:requirement_id ?nid }
                    UNION { ?a campy:action_item_id ?nid }
                }
            }
            GROUP BY ?nid
            """,
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
        sparql="""
            SELECT ?gap_id ?domain ?gap_type ?description ?severity
                   ?message_count ?lesson_count ?created_at WHERE {
                ?g a campy:KnowledgeGap ;
                   campy:gap_id ?gap_id ;
                   campy:domain ?domain ;
                   campy:gap_type ?gap_type ;
                   campy:description ?description ;
                   campy:severity ?severity ;
                   campy:message_count ?message_count ;
                   campy:lesson_count ?lesson_count ;
                   campy:created_at ?created_at .
                OPTIONAL { ?g campy:resolved ?resolved }
                FILTER(!BOUND(?resolved) || ?resolved = false)
                FILTER(?severity >= ?min)
            }
            ORDER BY DESC(?severity)
            """,
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
        sparql="""
            SELECT ?gap_id ?domain ?gap_type ?description ?severity
                   ?message_count ?lesson_count ?created_at WHERE {
                ?g a campy:KnowledgeGap ;
                   campy:gap_id ?gap_id ;
                   campy:domain ?domain ;
                   campy:gap_type ?gap_type ;
                   campy:description ?description ;
                   campy:severity ?severity ;
                   campy:message_count ?message_count ;
                   campy:lesson_count ?lesson_count ;
                   campy:created_at ?created_at .
                FILTER(?severity >= ?min)
            }
            ORDER BY DESC(?severity)
            """,
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
        # confidence_low is a required match (an unset node should NOT
        # count as "soft-locked") — stays a required BGP. archived is the
        # "false-or-unset" soft-default column (spec §3.4) — OPTIONAL+FILTER.
        sparql="""
            SELECT ?concept_id ?text_raw ?gist_class ?schema_org_type
                   ?confidence ?pathway_strength ?created_at WHERE {
                ?c a campy:Concept ;
                   campy:confidence_low true ;
                   campy:concept_id ?concept_id ;
                   campy:text_raw ?text_raw ;
                   campy:gist_class ?gist_class ;
                   campy:schema_org_type ?schema_org_type ;
                   campy:confidence ?confidence ;
                   campy:pathway_strength ?pathway_strength ;
                   campy:created_at ?created_at .
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?created_at)
            """,
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
        # DISTINCT_FROM is "occurrence" but this only checks existence of
        # the plain triple (always asserted per spec §4.2b) — undirected
        # Cypher pattern -[:DISTINCT_FROM]- means either endpoint order.
        sparql="""
            SELECT ?concept_id WHERE {
                VALUES ?aid { }
                ?a a campy:Concept ;
                   campy:concept_id ?aid .
                { ?a campy:DISTINCT_FROM ?b } UNION { ?b campy:DISTINCT_FROM ?a }
                ?b a campy:Concept ;
                   campy:concept_id ?concept_id .
            }
            """,
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
        sparql="""
            SELECT DISTINCT ?concept_id WHERE {
                VALUES ?cid { }
                ?c a campy:Concept ;
                   campy:concept_id ?cid .
                ?c ?p ?n .
                ?n a campy:Concept ;
                   campy:concept_id ?concept_id .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                FILTER NOT EXISTS { VALUES ?cid2 { } FILTER(?concept_id = ?cid2) }
            }
            """,
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
        sparql="""
            SELECT DISTINCT ?concept_id WHERE {
                VALUES ?cid { }
                ?c a campy:Concept ;
                   campy:concept_id ?cid .
                ?c campy:CO_OCCURS_WITH ?n .
                << ?c campy:CO_OCCURS_WITH ?n >> campy:count ?count .
                FILTER(?count >= "3"^^xsd:long)
                ?n a campy:Concept ;
                   campy:concept_id ?concept_id .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                FILTER NOT EXISTS { VALUES ?cid2 { } FILTER(?concept_id = ?cid2) }
            }
            """,
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
            sparql=f"""
                SELECT ?{pk} ?text_raw ?confidence ?confidence_low
                       ?pathway_strength ?created_at WHERE {{
                    ?a a campy:{label} ;
                       campy:{pk} ?{pk} ;
                       campy:text_raw ?text_raw ;
                       campy:confidence ?confidence ;
                       campy:confidence_low ?confidence_low ;
                       campy:pathway_strength ?pathway_strength ;
                       campy:created_at ?created_at .
                    OPTIONAL {{ ?a campy:archived ?archived }}
                    FILTER(!BOUND(?archived) || ?archived = false)
                    FILTER(?created_at > ?since)
                }}
                ORDER BY DESC(?created_at)
                """,
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
            # NOTE (pre-existing, not introduced by this translation):
            # `Message` has no `content` column in schema.py (only
            # `text_raw`) — `m.content` is a latent bug at the Cypher
            # layer that always returns NULL. Preserved faithfully: the
            # SPARQL below can never bind campy:content either, since no
            # writer ever asserts it.
            sparql=f"""
                SELECT ?content WHERE {{
                    ?n a campy:{label} ;
                       campy:{pk} ?id .
                    ?n campy:ESTABLISHED_IN ?m .
                    ?m a campy:Message .
                    OPTIONAL {{ ?m campy:content ?content }}
                }}
                LIMIT 1
                """,
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
        # See the get_originating_message_{key} note above — m.content is
        # a pre-existing latent bug (Message has no `content` column),
        # preserved faithfully rather than fixed.
        sparql="""
            SELECT ?content WHERE {
                ?n a campy:DocumentExtract ;
                   campy:extract_id ?id .
                ?n campy:ESTABLISHED_IN ?m .
                ?m a campy:Message .
                OPTIONAL { ?m campy:content ?content }
            }
            LIMIT 1
            """,
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
        sparql="""
            SELECT ?content WHERE {
                ?n a campy:Message ;
                   campy:message_id ?id .
                ?n campy:ESTABLISHED_IN ?m .
                ?m a campy:Message .
                OPTIONAL { ?m campy:content ?content }
            }
            LIMIT 1
            """,
    )
)
