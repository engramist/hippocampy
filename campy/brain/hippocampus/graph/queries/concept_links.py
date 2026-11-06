"""
campy/brain/hippocampus/graph/queries/concept_links.py -- B503 graph linking.

Named queries behind `campy.brain.hippocampus.concept_links`: the two new plain
edges (`MENTIONS` Message -> Concept, `IS_A` Concept -> Concept) and the reads
the rule linker and the one-shot backfill need. Plain edges are idempotent under
RDF set semantics, so re-linking is a no-op. The retrieval walk itself is a
Python handler (`thalamus.bundle_concept_walk`, registered in thalamus.py).
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

CONCEPT_LINK_QUERIES = [
    NamedQuery(
        name="concept_links.link_message_concept",
        cypher="""
        MATCH (m:Message {message_id: $mid}), (c:Concept {concept_id: $cid})
        MERGE (m)-[:MENTIONS]->(c)
        """,
        params=("mid", "cid"),
        mutating=True,
        description="Link a user Message to a Concept it names (MENTIONS, plain, idempotent)",
        sparql="""
            INSERT { ?m campy:MENTIONS ?c . }
            WHERE {
              ?m a campy:Message ; campy:message_id ?mid .
              ?c a campy:Concept ; campy:concept_id ?cid .
            }
            """,
    ),
    NamedQuery(
        name="concept_links.link_is_a",
        cypher="""
        MATCH (a:Concept {concept_id: $cid}), (b:Concept {concept_id: $pid})
        MERGE (a)-[:IS_A]->(b)
        """,
        params=("cid", "pid"),
        mutating=True,
        description="Link a Concept to its category Concept (IS_A, plain, idempotent)",
        sparql="""
            INSERT { ?a campy:IS_A ?b . }
            WHERE {
              ?a a campy:Concept ; campy:concept_id ?cid .
              ?b a campy:Concept ; campy:concept_id ?pid .
            }
            """,
    ),
    NamedQuery(
        name="concept_links.live_concepts",
        cypher="""
        MATCH (c:Concept) WHERE c.archived = false
        RETURN c.concept_id AS concept_id, c.text_raw AS text_raw
        """,
        params=(),
        mutating=False,
        description="Every live Concept's id and text (the rule linker matches spans against these)",
        sparql="""
            SELECT ?concept_id ?text_raw WHERE {
              ?c a campy:Concept ; campy:concept_id ?concept_id ;
                 campy:text_raw ?text_raw ; campy:archived false .
            }
            """,
    ),
    NamedQuery(
        name="concept_links.list_user_messages",
        cypher="""
        MATCH (m:Message) WHERE m.role = 'user' AND m.archived = false
        RETURN m.message_id AS message_id, m.text_raw AS text_raw
        """,
        params=(),
        mutating=False,
        description="Live user Messages (backfill candidates for MENTIONS)",
        sparql="""
            SELECT ?message_id ?text_raw WHERE {
              ?m a campy:Message ; campy:message_id ?message_id ;
                 campy:text_raw ?text_raw ; campy:role "user" .
              FILTER NOT EXISTS { ?m campy:archived true }
            }
            """,
    ),
    NamedQuery(
        name="concept_links.list_live_observations",
        cypher="""
        MATCH (o:Observation) WHERE o.archived = false
        RETURN o.observation_id AS observation_id, o.subject_text AS subject_text,
               o.predicate AS predicate, o.object_text AS object_text,
               o.event_text AS event_text, o.subject_id AS subject_id,
               o.object_id AS object_id, o.evidence_ref AS evidence_ref
        """,
        params=(),
        mutating=False,
        description="Live Observations with what the rule linker reads (backfill candidates)",
        sparql="""
            SELECT ?observation_id ?subject_text ?predicate ?object_text ?event_text
                   ?subject_id ?object_id ?evidence_ref WHERE {
              ?o a campy:Observation ; campy:observation_id ?observation_id ;
                 campy:subject_text ?subject_text ; campy:predicate ?predicate ;
                 campy:object_text ?object_text ; campy:evidence_ref ?evidence_ref ;
                 campy:archived false .
              OPTIONAL { ?o campy:event_text ?event_text }
              OPTIONAL { ?o campy:subject_id ?subject_id }
              OPTIONAL { ?o campy:object_id ?object_id }
            }
            """,
    ),
]
