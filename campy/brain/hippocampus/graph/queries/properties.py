"""
campy/brain/hippocampus/graph/queries/properties.py -- B509 OWL attribute properties.

Named queries behind `campy.brain.hippocampus.attribute_properties`. An attribute name
("age", "personal best 5K") is an `AttributeProperty` node (an owl:DatatypeProperty or
owl:ObjectProperty, a skos:Concept in campy:PropertyScheme). The edges are plain and
idempotent: `HAS_PROPERTY` (Observation -> AttributeProperty), `BROADER` / `CLOSE_MATCH`
between two properties, `HAS_ALT_LABEL` to a Label. An Observation's separated value lives
in its `attr_value*` columns.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_NODE_BASE = "https://campy.dev/id/AttributeProperty/"

PROPERTY_QUERIES = [
    NamedQuery(
        name="properties.create_property",
        cypher="""
        CREATE (p:AttributeProperty {
            property_id: $pid, text_raw: $txt, match_key: $mkey, prop_type: $ptype,
            functional_basis: $basis, confirmed_by: NULL, advised_one: 0, advised_many: 0,
            archived: false, created_at: $now, source: 'rule:attribute-property', authority: 'earned'
        })
        """,
        params=("pid", "txt", "mkey", "ptype", "basis", "now"),
        mutating=True,
        description="Create an AttributeProperty node (use attribute_properties.resolve, which consolidates by rule)",
        sparql=f"""
            INSERT {{
              ?p a campy:AttributeProperty ;
                 campy:property_id ?pid ;
                 campy:text_raw ?txt ;
                 campy:match_key ?mkey ;
                 campy:prop_type ?ptype ;
                 campy:functional_basis ?basis ;
                 campy:advised_one 0 ;
                 campy:advised_many 0 ;
                 campy:archived false ;
                 campy:created_at ?now ;
                 campy:source "rule:attribute-property" ;
                 campy:authority "earned" .
            }}
            WHERE {{
              BIND(IRI(CONCAT("{_NODE_BASE}", ENCODE_FOR_URI(STR(?pid)))) AS ?p)
            }}
            """,
    ),
    NamedQuery(
        name="properties.live_properties",
        cypher="""
        MATCH (p:AttributeProperty) WHERE p.archived = false
        RETURN p.property_id AS property_id, p.text_raw AS text_raw, p.match_key AS match_key,
               p.prop_type AS prop_type, p.functional_basis AS functional_basis,
               p.advised_one AS advised_one, p.advised_many AS advised_many
        """,
        params=(),
        mutating=False,
        description="Every live AttributeProperty",
        sparql="""
            SELECT ?property_id ?text_raw ?match_key ?prop_type ?functional_basis ?advised_one ?advised_many WHERE {
              ?p a campy:AttributeProperty ; campy:property_id ?property_id ; campy:text_raw ?text_raw ;
                 campy:match_key ?match_key ; campy:prop_type ?prop_type ; campy:archived false .
              OPTIONAL { ?p campy:functional_basis ?functional_basis }
              OPTIONAL { ?p campy:advised_one ?advised_one }
              OPTIONAL { ?p campy:advised_many ?advised_many }
            }
            """,
    ),
    NamedQuery(
        name="properties.alt_labels",
        cypher="""
        MATCH (p:AttributeProperty)-[:HAS_ALT_LABEL]->(l:Label) WHERE p.archived = false
        RETURN p.property_id AS property_id, l.text AS alt
        """,
        params=(),
        mutating=False,
        description="The altLabels of every live AttributeProperty",
        sparql="""
            SELECT ?property_id ?alt WHERE {
              ?p a campy:AttributeProperty ; campy:property_id ?property_id ; campy:archived false ;
                 campy:HAS_ALT_LABEL ?l .
              ?l campy:text ?alt .
            }
            """,
    ),
    NamedQuery(
        name="properties.broader_edges",
        cypher="""
        MATCH (a:AttributeProperty)-[:BROADER]->(b:AttributeProperty)
        RETURN a.property_id AS child, b.property_id AS parent
        """,
        params=(),
        mutating=False,
        description="Every property -> broader property edge",
        sparql="""
            SELECT ?child ?parent WHERE {
              ?a a campy:AttributeProperty ; campy:BROADER ?b ; campy:property_id ?child .
              ?b a campy:AttributeProperty ; campy:property_id ?parent .
            }
            """,
    ),
    NamedQuery(
        name="properties.link_alt_label",
        cypher="""
        MATCH (p:AttributeProperty {property_id: $pid}), (l:Label {label_id: $lid})
        MERGE (p)-[:HAS_ALT_LABEL]->(l)
        """,
        params=("pid", "lid"),
        mutating=True,
        description="Link an AttributeProperty to an altLabel (HAS_ALT_LABEL, plain, idempotent)",
        sparql="""
            INSERT { ?p campy:HAS_ALT_LABEL ?l . }
            WHERE {
              ?p a campy:AttributeProperty ; campy:property_id ?pid .
              ?l a campy:Label ; campy:label_id ?lid .
            }
            """,
    ),
    NamedQuery(
        name="properties.link_broader",
        cypher="""
        MATCH (a:AttributeProperty {property_id: $cid}), (b:AttributeProperty {property_id: $pid})
        MERGE (a)-[:BROADER]->(b)
        """,
        params=("cid", "pid"),
        mutating=True,
        description="Property is narrower than a broader property (BROADER = skos:broader, plain, idempotent)",
        sparql="""
            INSERT { ?a campy:BROADER ?b . }
            WHERE {
              ?a a campy:AttributeProperty ; campy:property_id ?cid .
              ?b a campy:AttributeProperty ; campy:property_id ?pid .
            }
            """,
    ),
    NamedQuery(
        name="properties.link_close_match",
        cypher="""
        MATCH (a:AttributeProperty {property_id: $cid}), (b:AttributeProperty {property_id: $oid})
        MERGE (a)-[:CLOSE_MATCH]->(b)
        """,
        params=("cid", "oid"),
        mutating=True,
        description="Two properties look alike (CLOSE_MATCH = skos:closeMatch; advisory, never merged)",
        sparql="""
            INSERT { ?a campy:CLOSE_MATCH ?b . }
            WHERE {
              ?a a campy:AttributeProperty ; campy:property_id ?cid .
              ?b a campy:AttributeProperty ; campy:property_id ?oid .
            }
            """,
    ),
    NamedQuery(
        name="properties.add_advice",
        cypher="""
        MATCH (p:AttributeProperty {property_id: $pid})
        SET p.advised_one = coalesce(p.advised_one, 0) + $d1,
            p.advised_many = coalesce(p.advised_many, 0) + $d2
        """,
        params=("pid", "d1", "d2"),
        mutating=True,
        description="Count one more piece of extractor advice about cardinality (a candidate, never a fact)",
        sparql="""
            DELETE { ?p campy:advised_one ?o1 . ?p campy:advised_many ?o2 }
            INSERT { ?p campy:advised_one ?n1 . ?p campy:advised_many ?n2 }
            WHERE {
              ?p a campy:AttributeProperty ; campy:property_id ?pid .
              OPTIONAL { ?p campy:advised_one ?o1 }
              OPTIONAL { ?p campy:advised_many ?o2 }
              BIND(COALESCE(?o1, 0) + ?d1 AS ?n1)
              BIND(COALESCE(?o2, 0) + ?d2 AS ?n2)
            }
            """,
    ),
    NamedQuery(
        name="properties.set_functional",
        cypher="""
        MATCH (p:AttributeProperty {property_id: $pid})
        SET p.functional_basis = $basis, p.confirmed_by = $by
        """,
        params=("pid", "basis", "by"),
        mutating=True,
        description="Record why a property is functional ('modifier' or 'confirmed') and the Observation that confirmed it",
        sparql="""
            DELETE { ?p campy:functional_basis ?o1 . ?p campy:confirmed_by ?o2 }
            INSERT { ?p campy:functional_basis ?basis . ?p campy:confirmed_by ?by }
            WHERE {
              ?p a campy:AttributeProperty ; campy:property_id ?pid .
              OPTIONAL { ?p campy:functional_basis ?o1 }
              OPTIONAL { ?p campy:confirmed_by ?o2 }
            }
            """,
    ),
    NamedQuery(
        name="properties.set_type",
        cypher="""
        MATCH (p:AttributeProperty {property_id: $pid})
        SET p.prop_type = $ptype
        """,
        params=("pid", "ptype"),
        mutating=True,
        description="Set datatype vs object property",
        sparql="""
            DELETE { ?p campy:prop_type ?o }
            INSERT { ?p campy:prop_type ?ptype }
            WHERE {
              ?p a campy:AttributeProperty ; campy:property_id ?pid .
              OPTIONAL { ?p campy:prop_type ?o }
            }
            """,
    ),
    NamedQuery(
        name="properties.link_property",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}), (p:AttributeProperty {property_id: $pid})
        MERGE (o)-[:HAS_PROPERTY]->(p)
        """,
        params=("oid", "pid"),
        mutating=True,
        description="Link an attribute Observation to its AttributeProperty (HAS_PROPERTY, plain, idempotent)",
        sparql="""
            INSERT { ?o campy:HAS_PROPERTY ?p . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              ?p a campy:AttributeProperty ; campy:property_id ?pid .
            }
            """,
    ),
    NamedQuery(
        name="properties.set_attribute_value",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})
        SET o.attr_value = $value, o.attr_value_kind = $kind, o.attr_value_num = $num,
            o.attr_value_unit = $unit, o.attr_value_time = $time
        """,
        params=("oid", "value", "kind", "num", "unit", "time"),
        mutating=True,
        description="Store an attribute Observation's value apart from its name: text, kind, and the parsed typed literal",
        sparql="""
            INSERT {
              ?o campy:attr_value ?value ; campy:attr_value_kind ?kind ; campy:attr_value_num ?num ;
                 campy:attr_value_unit ?unit ; campy:attr_value_time ?time .
            }
            WHERE { ?o a campy:Observation ; campy:observation_id ?oid . }
            """,
    ),
    NamedQuery(
        name="properties.set_value_ref",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})
        SET o.attr_value_ref = $ref
        """,
        params=("oid", "ref"),
        mutating=True,
        description="An object-valued attribute's value is this Concept",
        sparql="""
            INSERT { ?o campy:attr_value_ref ?ref }
            WHERE { ?o a campy:Observation ; campy:observation_id ?oid . }
            """,
    ),
    NamedQuery(
        name="properties.property_of",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})-[:HAS_PROPERTY]->(p:AttributeProperty)
        RETURN p.property_id AS property_id, p.prop_type AS prop_type, o.attr_value_kind AS kind
        LIMIT 1
        """,
        params=("oid",),
        mutating=False,
        description="The property an Observation states a value of, with its type and the Observation's value kind",
        sparql="""
            SELECT ?property_id ?prop_type ?kind WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid ; campy:HAS_PROPERTY ?p .
              ?p campy:property_id ?property_id ; campy:prop_type ?prop_type .
              OPTIONAL { ?o campy:attr_value_kind ?kind }
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="properties.value_count",
        cypher="""
        MATCH (o:Observation)-[:HAS_PROPERTY]->(p:AttributeProperty {property_id: $pid})
        RETURN count(o) AS n
        """,
        params=("pid",),
        mutating=False,
        description="How many Observations state a value of a property",
        sparql="""
            SELECT (COUNT(DISTINCT ?o) AS ?n) WHERE {
              ?p a campy:AttributeProperty ; campy:property_id ?pid .
              ?o campy:HAS_PROPERTY ?p .
            }
            """,
    ),
    NamedQuery(
        name="properties.live_values",
        cypher="""
        MATCH (o:Observation)-[:HAS_PROPERTY]->(p:AttributeProperty {property_id: $pid})
        WHERE o.archived = false AND o.polarity = 'asserted' AND o.superseded_by IS NULL
        RETURN o.observation_id AS observation_id, o.subject_id AS subject_id, o.subject_text AS subject_text,
               o.speaker AS speaker, o.observed_at AS observed_at, o.created_at AS created_at,
               o.attr_value AS attr_value, o.attr_value_kind AS attr_value_kind,
               o.attr_value_num AS attr_value_num, o.attr_value_unit AS attr_value_unit,
               o.attr_value_time AS attr_value_time, o.superseded_by AS superseded_by
        """,
        params=("pid",),
        mutating=False,
        description="Live asserted Observations stating a value of one property (the caller filters the subject)",
        sparql="""
            SELECT ?observation_id ?subject_id ?subject_text ?speaker ?observed_at ?created_at
                   ?attr_value ?attr_value_kind ?attr_value_num ?attr_value_unit ?attr_value_time ?superseded_by WHERE {
              ?p a campy:AttributeProperty ; campy:property_id ?pid .
              ?o campy:HAS_PROPERTY ?p ; a campy:Observation ; campy:observation_id ?observation_id ;
                 campy:subject_text ?subject_text ; campy:polarity "asserted" ; campy:archived false ;
                 campy:created_at ?created_at .
              FILTER NOT EXISTS { ?o campy:superseded_by ?sup }
              OPTIONAL { ?o campy:subject_id ?subject_id }
              OPTIONAL { ?o campy:speaker ?speaker }
              OPTIONAL { ?o campy:observed_at ?observed_at }
              OPTIONAL { ?o campy:attr_value ?attr_value }
              OPTIONAL { ?o campy:attr_value_kind ?attr_value_kind }
              OPTIONAL { ?o campy:attr_value_num ?attr_value_num }
              OPTIONAL { ?o campy:attr_value_unit ?attr_value_unit }
              OPTIONAL { ?o campy:attr_value_time ?attr_value_time }
              OPTIONAL { ?o campy:superseded_by ?superseded_by }
            }
            """,
    ),
    NamedQuery(
        name="properties.unlinked_attributes",
        cypher="""
        MATCH (o:Observation)
        WHERE o.predicate = 'has_attribute' AND o.archived = false
        RETURN o.observation_id AS observation_id, o.created_at AS created_at
        ORDER BY o.observed_at, o.created_at
        """,
        params=(),
        mutating=False,
        description="has_attribute Observations (the caller skips those that already have a HAS_PROPERTY edge)",
        sparql="""
            SELECT ?observation_id ?created_at ?observed_at WHERE {
              ?o a campy:Observation ; campy:observation_id ?observation_id ; campy:predicate "has_attribute" ;
                 campy:archived false ; campy:created_at ?created_at .
              OPTIONAL { ?o campy:observed_at ?observed_at }
              FILTER NOT EXISTS { ?o campy:HAS_PROPERTY ?p }
            }
            ORDER BY ?observed_at ?created_at
            """,
    ),
]
