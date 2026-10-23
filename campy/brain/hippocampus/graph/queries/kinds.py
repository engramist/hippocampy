"""
campy/brain/hippocampus/graph/queries/kinds.py -- B508 SKOS vocabulary for kinds.

Named queries behind `campy.brain.hippocampus.kinds`. The three new edges are plain
(property-free, idempotent under RDF set semantics): `INSTANCE_OF` (entity -> kind),
`BROADER` (kind -> broader kind; the SKOS `skos:broader`) and `CLOSE_MATCH`
(`skos:closeMatch`). A kind is a Concept with `kind_scheme = 'kind'`.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

KIND_QUERIES = [
    NamedQuery(
        name="kinds.mark_kind",
        cypher="MATCH (c:Concept {concept_id: $cid}) SET c.kind_scheme = $scheme",
        params=("cid", "scheme"),
        mutating=True,
        description="Put a Concept in the kind scheme (idempotent)",
        sparql="""
            DELETE { ?c campy:kind_scheme ?old }
            INSERT { ?c campy:kind_scheme ?scheme }
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              OPTIONAL { ?c campy:kind_scheme ?old }
            }
            """,
    ),
    NamedQuery(
        name="kinds.link_instance_of",
        cypher="""
        MATCH (a:Concept {concept_id: $cid}), (b:Concept {concept_id: $kid})
        MERGE (a)-[:INSTANCE_OF]->(b)
        """,
        params=("cid", "kid"),
        mutating=True,
        description="Entity Concept is an instance of a kind Concept (INSTANCE_OF, plain, idempotent)",
        sparql="""
            INSERT { ?a campy:INSTANCE_OF ?b . }
            WHERE {
              ?a a campy:Concept ; campy:concept_id ?cid .
              ?b a campy:Concept ; campy:concept_id ?kid .
            }
            """,
    ),
    NamedQuery(
        name="kinds.link_broader",
        cypher="""
        MATCH (a:Concept {concept_id: $cid}), (b:Concept {concept_id: $pid})
        MERGE (a)-[:BROADER]->(b)
        """,
        params=("cid", "pid"),
        mutating=True,
        description="Kind is narrower than a broader kind (BROADER = skos:broader, plain, idempotent)",
        sparql="""
            INSERT { ?a campy:BROADER ?b . }
            WHERE {
              ?a a campy:Concept ; campy:concept_id ?cid .
              ?b a campy:Concept ; campy:concept_id ?pid .
            }
            """,
    ),
    NamedQuery(
        name="kinds.link_close_match",
        cypher="""
        MATCH (a:Concept {concept_id: $cid}), (b:Concept {concept_id: $oid})
        MERGE (a)-[:CLOSE_MATCH]->(b)
        """,
        params=("cid", "oid"),
        mutating=True,
        description="Two kinds look alike (CLOSE_MATCH = skos:closeMatch; advisory, never merged or walked)",
        sparql="""
            INSERT { ?a campy:CLOSE_MATCH ?b . }
            WHERE {
              ?a a campy:Concept ; campy:concept_id ?cid .
              ?b a campy:Concept ; campy:concept_id ?oid .
            }
            """,
    ),
    NamedQuery(
        name="kinds.live_kinds",
        cypher="""
        MATCH (c:Concept) WHERE c.kind_scheme = 'kind' AND c.archived = false
        RETURN c.concept_id AS concept_id, c.text_raw AS text_raw
        """,
        params=(),
        mutating=False,
        description="Every live kind Concept (prefLabel is text_raw)",
        sparql="""
            SELECT ?concept_id ?text_raw WHERE {
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw ;
                 campy:kind_scheme "kind" ; campy:archived false .
            }
            """,
    ),
    NamedQuery(
        name="kinds.kind_alt_labels",
        cypher="""
        MATCH (c:Concept)-[:HAS_ALT_LABEL]->(l:Label)
        WHERE c.kind_scheme = 'kind' AND c.archived = false
        RETURN c.concept_id AS concept_id, l.text AS alt
        """,
        params=(),
        mutating=False,
        description="The altLabels of every live kind Concept",
        sparql="""
            SELECT ?concept_id ?alt WHERE {
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:kind_scheme "kind" ;
                 campy:archived false ; campy:HAS_ALT_LABEL ?l .
              ?l campy:text ?alt .
            }
            """,
    ),
    NamedQuery(
        name="kinds.kind_broader_edges",
        cypher="""
        MATCH (a:Concept)-[:BROADER]->(b:Concept)
        RETURN a.concept_id AS child, b.concept_id AS parent
        """,
        params=(),
        mutating=False,
        description="Every kind -> broader kind edge",
        sparql="""
            SELECT ?child ?parent WHERE {
              ?a campy:BROADER ?b .
              ?a campy:concept_id ?child . ?b campy:concept_id ?parent .
            }
            """,
    ),
]
