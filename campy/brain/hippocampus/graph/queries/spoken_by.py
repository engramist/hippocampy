"""
campy/brain/hippocampus/graph/queries/spoken_by.py -- B560 SPOKEN_BY.

Named queries behind `campy.brain.hippocampus.spoken_by`: the plain edge `Message -SPOKEN_BY-> Concept` (the
speaker's Person Concept) and the reads its backfill needs. The edge is read by `thalamus.bundle_concept_walk`
(graph/queries/thalamus.py), which keeps only the turns the question's subject spoke.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

SPOKEN_BY_QUERIES = [
    NamedQuery(
        name="spoken_by.link_spoken_by",
        cypher="""
        MATCH (m:Message {message_id: $mid}), (c:Concept {concept_id: $cid})
        MERGE (m)-[:SPOKEN_BY]->(c)
        """,
        params=("mid", "cid"),
        mutating=True,
        description="Link a Message to the Concept of the person who spoke it (SPOKEN_BY, plain, idempotent)",
        sparql="""
            INSERT { ?m campy:SPOKEN_BY ?c . }
            WHERE {
              ?m a campy:Message ; campy:message_id ?mid .
              ?c a campy:Concept ; campy:concept_id ?cid .
            }
            """,
    ),
    NamedQuery(
        name="spoken_by.unlinked_turns",
        cypher="""
        MATCH (m:Message) WHERE m.archived = false AND m.speaker IS NOT NULL AND NOT (m)-[:SPOKEN_BY]->(:Concept)
        RETURN m.message_id AS message_id, m.speaker AS speaker
        """,
        params=(),
        mutating=False,
        description="Live Messages that name a speaker and have no SPOKEN_BY edge yet (the backfill's candidates)",
        sparql="""
            SELECT ?message_id ?speaker WHERE {
              ?m a campy:Message ; campy:message_id ?message_id ; campy:speaker ?speaker .
              FILTER NOT EXISTS { ?m campy:archived true }
              FILTER NOT EXISTS { ?m campy:SPOKEN_BY ?c }
            }
            """,
    ),
    NamedQuery(
        name="spoken_by.linked_turns",
        cypher="""
        MATCH (m:Message)-[:SPOKEN_BY]->(c:Concept) RETURN count(DISTINCT m) AS turns
        """,
        params=(),
        mutating=False,
        description="How many Messages already have a SPOKEN_BY edge (the backfill's before and after count)",
        sparql="""
            SELECT (COUNT(DISTINCT ?m) AS ?turns) WHERE { ?m campy:SPOKEN_BY ?c }
            """,
    ),
]
