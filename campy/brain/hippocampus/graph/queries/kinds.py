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
    # --- B534 WordNet proposes BROADER links between existing kinds ---
    NamedQuery(
        name="kinds.link_broader_sourced",
        cypher="""
        MATCH (a:Concept {concept_id: $cid}), (b:Concept {concept_id: $pid})
        MERGE (a)-[r:BROADER]->(b) SET r.link_source = $src
        """,
        params=("cid", "pid", "src"),
        mutating=True,
        description="Kind is narrower than a kind, with the source that proposed the link (RDF-star reifier "
                    "campy:link_source on the BROADER triple); skipped when the pair is already related "
                    "either way through BROADER (no duplicate path, no cycle) or when a steward rejected it (B535)",
        sparql="""
            INSERT {
              ?a campy:BROADER ?b .
              _:r rdf:reifies <<( ?a campy:BROADER ?b )>> .
              _:r campy:link_source ?src .
            }
            WHERE {
              ?a a campy:Concept ; campy:concept_id ?cid .
              ?b a campy:Concept ; campy:concept_id ?pid .
              FILTER(?a != ?b)
              FILTER NOT EXISTS { ?a campy:BROADER+ ?b }
              FILTER NOT EXISTS { ?b campy:BROADER+ ?a }
              FILTER NOT EXISTS { ?rej rdf:reifies <<( ?a campy:BROADER ?b )>> ; campy:link_status "rejected" }
            }
            """,
    ),
    NamedQuery(
        name="kinds.broader_links_by_source",
        cypher="""
        MATCH (a:Concept)-[r:BROADER]->(b:Concept) WHERE a.kind_scheme = 'kind' AND a.archived = false
        RETURN coalesce(r.link_source, 'label_rule') AS source, count(*) AS n
        """,
        params=(),
        mutating=False,
        description="Live kind BROADER links per source: 'wordnet' (campy:link_source on the reifier) or "
                    "'label_rule' (no reifier: the head-noun rule, an extractor is_a, or B525 merges)",
        sparql="""
            SELECT ?source (COUNT(*) AS ?n) WHERE {
              ?a a campy:Concept ; campy:kind_scheme "kind" ; campy:archived false ; campy:BROADER ?b .
              OPTIONAL { ?r rdf:reifies <<( ?a campy:BROADER ?b )>> ; campy:link_source ?s .
                         FILTER NOT EXISTS { ?r campy:link_status "candidate" } }
              BIND(COALESCE(?s, "label_rule") AS ?source)
            } GROUP BY ?source
            """,
    ),
    NamedQuery(
        name="kinds.broader_links_detail",
        cypher="""
        MATCH (a:Concept)-[r:BROADER]->(b:Concept) WHERE a.kind_scheme = 'kind' AND a.archived = false
        RETURN a.text_raw AS child, b.text_raw AS parent, coalesce(r.link_source, 'label_rule') AS source
        """,
        params=(),
        mutating=False,
        description="Every live kind BROADER link with its labels and source (child, parent, source)",
        sparql="""
            SELECT ?child ?parent ?source WHERE {
              ?a a campy:Concept ; campy:kind_scheme "kind" ; campy:archived false ;
                 campy:text_raw ?child ; campy:BROADER ?b .
              ?b campy:text_raw ?parent .
              OPTIONAL { ?r rdf:reifies <<( ?a campy:BROADER ?b )>> ; campy:link_source ?s .
                         FILTER NOT EXISTS { ?r campy:link_status "candidate" } }
              BIND(COALESCE(?s, "label_rule") AS ?source)
            }
            """,
    ),
    # --- B525 kind hygiene (scripts/consolidate_kinds.py; kinds.apply_hygiene) ---
    NamedQuery(
        name="kinds.instance_counts",
        cypher="""
        MATCH (x:Concept)-[:INSTANCE_OF]->(k:Concept) WHERE k.kind_scheme = 'kind'
        RETURN k.concept_id AS concept_id, count(DISTINCT x) AS n
        """,
        params=(),
        mutating=False,
        description="INSTANCE_OF members per kind Concept",
        sparql="""
            SELECT ?concept_id (COUNT(DISTINCT ?x) AS ?n) WHERE {
              ?k a campy:Concept ; campy:concept_id ?concept_id ; campy:kind_scheme "kind" .
              ?x campy:INSTANCE_OF ?k .
            } GROUP BY ?concept_id
            """,
    ),
    NamedQuery(
        name="kinds.set_kind_label",
        cypher="MATCH (c:Concept {concept_id: $cid}) SET c.text_raw = $txt",
        params=("cid", "txt"),
        mutating=True,
        description="Replace a kind Concept's prefLabel (text_raw)",
        sparql="""
            DELETE { ?c campy:text_raw ?old }
            INSERT { ?c campy:text_raw ?txt }
            WHERE { ?c a campy:Concept ; campy:concept_id ?cid ; campy:text_raw ?old }
            """,
    ),
    NamedQuery(
        name="kinds.merge_instance_of",
        cypher="""
        MATCH (x:Concept)-[r:INSTANCE_OF]->(l:Concept {concept_id: $lid}), (s:Concept {concept_id: $sid})
        DELETE r MERGE (x)-[:INSTANCE_OF]->(s)
        """,
        params=("lid", "sid"),
        mutating=True,
        description="Re-point every INSTANCE_OF edge of a merged kind to the surviving kind",
        sparql="""
            DELETE { ?x campy:INSTANCE_OF ?l }
            INSERT { ?x campy:INSTANCE_OF ?s }
            WHERE {
              ?l a campy:Concept ; campy:concept_id ?lid .
              ?s a campy:Concept ; campy:concept_id ?sid .
              ?x campy:INSTANCE_OF ?l .
              FILTER(?x != ?s)
            }
            """,
    ),
    NamedQuery(
        name="kinds.merge_broader_up",
        cypher="""
        MATCH (l:Concept {concept_id: $lid})-[r:BROADER]->(p:Concept), (s:Concept {concept_id: $sid})
        DELETE r MERGE (s)-[:BROADER]->(p)
        """,
        params=("lid", "sid"),
        mutating=True,
        description="A merged kind's BROADER edges now leave the surviving kind",
        sparql="""
            DELETE { ?l campy:BROADER ?p }
            INSERT { ?s campy:BROADER ?p }
            WHERE {
              ?l a campy:Concept ; campy:concept_id ?lid .
              ?s a campy:Concept ; campy:concept_id ?sid .
              ?l campy:BROADER ?p .
              FILTER(?p != ?s)
            }
            """,
    ),
    NamedQuery(
        name="kinds.merge_broader_down",
        cypher="""
        MATCH (c:Concept)-[r:BROADER]->(l:Concept {concept_id: $lid}), (s:Concept {concept_id: $sid})
        DELETE r MERGE (c)-[:BROADER]->(s)
        """,
        params=("lid", "sid"),
        mutating=True,
        description="Kinds narrower than a merged kind are now narrower than the surviving kind",
        sparql="""
            DELETE { ?c campy:BROADER ?l }
            INSERT { ?c campy:BROADER ?s }
            WHERE {
              ?l a campy:Concept ; campy:concept_id ?lid .
              ?s a campy:Concept ; campy:concept_id ?sid .
              ?c campy:BROADER ?l .
              FILTER(?c != ?s)
            }
            """,
    ),
    NamedQuery(
        name="kinds.merge_alt_labels",
        cypher="""
        MATCH (l:Concept {concept_id: $lid})-[r:HAS_ALT_LABEL]->(a:Label), (s:Concept {concept_id: $sid})
        DELETE r MERGE (s)-[:HAS_ALT_LABEL]->(a)
        """,
        params=("lid", "sid"),
        mutating=True,
        description="A merged kind's altLabels move to the surviving kind",
        sparql="""
            DELETE { ?l campy:HAS_ALT_LABEL ?a }
            INSERT { ?s campy:HAS_ALT_LABEL ?a }
            WHERE {
              ?l a campy:Concept ; campy:concept_id ?lid .
              ?s a campy:Concept ; campy:concept_id ?sid .
              ?l campy:HAS_ALT_LABEL ?a .
            }
            """,
    ),
    NamedQuery(
        name="kinds.drop_instance_of",
        cypher="MATCH (:Concept)-[r:INSTANCE_OF]->(k:Concept {concept_id: $kid}) DELETE r",
        params=("kid",),
        mutating=True,
        description="Remove the INSTANCE_OF edges that point at a meta-noun kind (plain edges have no archive form)",
        sparql="""
            DELETE { ?x campy:INSTANCE_OF ?k }
            WHERE { ?k a campy:Concept ; campy:concept_id ?kid . ?x campy:INSTANCE_OF ?k . }
            """,
    ),
    NamedQuery(
        name="kinds.detach_alt_label",
        cypher="MATCH (:Concept {concept_id: $cid})-[r:HAS_ALT_LABEL]->(l:Label {text: $txt}) DELETE r",
        params=("cid", "txt"),
        mutating=True,
        description="Detach one altLabel from a kind (the Label node stays; it only stops naming this kind)",
        sparql="""
            DELETE { ?k campy:HAS_ALT_LABEL ?l }
            WHERE { ?k a campy:Concept ; campy:concept_id ?cid ; campy:HAS_ALT_LABEL ?l . ?l campy:text ?txt . }
            """,
    ),
]
