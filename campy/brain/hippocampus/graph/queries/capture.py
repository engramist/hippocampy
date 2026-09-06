"""
campy/brain/hippocampus/graph/queries/capture.py — Message capture and ingestion queries.

B393: `sparql=` added to every query per docs/rdf-schema-mapping.md. Two
conventions used throughout this file (documented here once rather than
per query):

- **`LIMIT $param`** has no SPARQL equivalent — the SPARQL `LIMIT` clause
  only accepts an integer literal, never a bound variable. Queries that
  Cypher-limits via a parameter keep their `ORDER BY` (so results are
  deterministically ordered) and omit the `LIMIT` clause entirely; the
  caller-supplied limit becomes a post-query slice in the future execution
  layer, not part of the query text itself. `LIMIT <integer literal>`
  constants (e.g. `LIMIT 1`) are unaffected and translate directly.
- **Array-valued params** (none in this file, but the convention is shared
  across the B393 batch): represented as an empty `VALUES ?var { }` block
  for the future binding layer to expand into one row per element —
  pyoxigraph's `substitutions=` API binds only single terms per variable,
  so multi-value params need textual VALUES expansion, which is
  infrastructure work out of scope for this card (same category of gap as
  B391's "params on SPARQL Update text" note).
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
        sparql="""
            DELETE { ?s campy:token_limit ?old_limit }
            INSERT { ?s campy:token_limit ?limit }
            WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                OPTIONAL { ?s campy:token_limit ?old_limit }
                FILTER(!BOUND(?old_limit) || ?old_limit = "0"^^xsd:long)
            }
            """,
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
        sparql="""
            DELETE { ?m campy:archived ?old_archived }
            INSERT { ?m campy:archived true }
            WHERE {
                ?m a campy:Message ;
                   campy:text_raw ?text_raw .
                FILTER(CONTAINS(?text_raw, ?marker))
                OPTIONAL { ?m campy:archived ?old_archived }
                FILTER(!BOUND(?old_archived) || ?old_archived = false)
            }
            """,
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
        # $embedding (FLOAT[384]) is never written to Oxigraph — spec §3.1/§5:
        # vectors live in sqlite-vec, keyed by this node's full instance URI,
        # not in the graph. This query's sparql= covers every other
        # property; the embedding write is a separate, orthogonal step
        # (sqlite-vec insert) that does not go through this NamedQuery's
        # SPARQL text at all, same as write_node()'s existing behavior of
        # silently skipping FLOAT[384] columns.
        sparql="""
            INSERT {
                ?m a campy:Message ;
                   campy:message_id ?message_id ;
                   campy:text_raw ?text_raw ;
                   campy:embedding_model ?embedding_model ;
                   campy:embedding_dim ?embedding_dim ;
                   campy:role ?role ;
                   campy:byte_start "0"^^xsd:long ;
                   campy:byte_end ?byte_end ;
                   campy:confidence "0.0"^^xsd:double ;
                   campy:confidence_low true ;
                   campy:pathway_strength "0.0"^^xsd:double ;
                   campy:archived false ;
                   campy:created_at ?created_at .
            }
            WHERE {
                BIND(IRI(CONCAT("https://campy.dev/id/Message/", ?message_id)) AS ?m)
            }
            """,
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
        # SENT_IN is "plain" (property-free) in EDGE_REIFICATION — inserting
        # the same plain triple twice is a no-op under RDF set semantics,
        # so MERGE's idempotent-insert behavior needs no delete-then-insert.
        sparql="""
            INSERT {
                ?m campy:SENT_IN ?s .
            }
            WHERE {
                ?s a campy:Session ;
                   campy:session_id ?session_id .
                ?m a campy:Message ;
                   campy:message_id ?message_id .
            }
            """,
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
        sparql="""
            SELECT ?message_id ?created_at WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                ?m campy:SENT_IN ?s ;
                   a campy:Message ;
                   campy:message_id ?message_id ;
                   campy:created_at ?created_at .
                FILTER(?message_id != ?mid)
            }
            ORDER BY DESC(?created_at)
            LIMIT 1
            """,
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
        # FOLLOWED_BY is "star" (singleton edge carrying properties,
        # confirmed MERGE...SET at this exact call site). Spec §4.2a: assert
        # the plain triple AND the quoted-triple annotation together;
        # MERGE has no SPARQL equivalent (spec §7.7) so this is a single
        # DELETE-old-then-INSERT-new Update, one Oxigraph transaction.
        sparql="""
            DELETE {
                << ?p campy:FOLLOWED_BY ?c >> campy:gap_seconds ?old_gap .
            }
            INSERT {
                ?p campy:FOLLOWED_BY ?c .
                << ?p campy:FOLLOWED_BY ?c >> campy:gap_seconds ?gap .
            }
            WHERE {
                ?p a campy:Message ;
                   campy:message_id ?prev .
                ?c a campy:Message ;
                   campy:message_id ?curr .
                OPTIONAL { << ?p campy:FOLLOWED_BY ?c >> campy:gap_seconds ?old_gap }
            }
            """,
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
        sparql="""
            SELECT ?last_loop_summary WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                OPTIONAL { ?s campy:last_loop_summary ?last_loop_summary }
            }
            """,
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
        sparql="""
            SELECT ?last_proactive_push_msg_count WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                OPTIONAL { ?s campy:last_proactive_push_msg_count ?last_proactive_push_msg_count }
            }
            """,
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
        # LIMIT $lim -> ORDER BY kept, LIMIT clause dropped (see module docstring).
        sparql="""
            SELECT ?gap_id ?description ?severity WHERE {
                ?g a campy:KnowledgeGap ;
                   campy:gap_id ?gap_id ;
                   campy:description ?description ;
                   campy:severity ?severity ;
                   campy:domain ?domain .
                OPTIONAL { ?g campy:resolved ?resolved }
                FILTER(!BOUND(?resolved) || ?resolved = false)
                FILTER(CONTAINS(LCASE(?description), LCASE(?snippet)) || CONTAINS(LCASE(?domain), LCASE(?snippet)))
            }
            ORDER BY DESC(?severity)
            """,
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
        sparql="""
            DELETE { ?s campy:last_proactive_push_msg_count ?old_count }
            INSERT { ?s campy:last_proactive_push_msg_count ?count }
            WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                OPTIONAL { ?s campy:last_proactive_push_msg_count ?old_count }
            }
            """,
    ),
]
