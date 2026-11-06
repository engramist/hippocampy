"""
campy/brain/hippocampus/graph/queries/entity_admission.py -- B544 entity admission.

Named queries behind `campy.brain.hippocampus.entity_admission`. The one new term is the
Concept property `ner_label` (the label spaCy gave the span that admitted the Concept as a
named entity). It is read by `entity_admission.concept_status` (the kind guard) and by
`entity_admission.named_entities` (what a turn's MENTIONS reach, by label).
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

ENTITY_ADMISSION_QUERIES = [
    NamedQuery(
        name="entity_admission.set_ner_label",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}) WHERE c.ner_label IS NULL
        SET c.ner_label = $label
        """,
        params=("cid", "label"),
        mutating=True,
        description="Record the NER label that admitted a Concept as a named entity (first label wins)",
        sparql="""
            INSERT { ?c campy:ner_label ?label }
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              FILTER NOT EXISTS { ?c campy:ner_label ?old }
            }
            """,
    ),
    NamedQuery(
        name="entity_admission.concept_status",
        cypher="""
        MATCH (c:Concept {concept_id: $cid})
        RETURN c.ner_label AS ner_label, c.schema_org_type AS schema_org_type,
               c.kind_scheme AS kind_scheme, c.entity_standing AS entity_standing
        """,
        params=("cid",),
        mutating=False,
        description=("A Concept's NER label, schema.org type, kind scheme and standing, and whether it can be a kind "
                     "(the kind guard reads `can_be_kind`: not a Person; not a labelled Concept unless its standing "
                     "is doubtful, B549)"),
        sparql="""
            SELECT ?ner_label ?schema_org_type ?kind_scheme ?entity_standing ?can_be_kind WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              OPTIONAL { ?c campy:ner_label ?ner_label }
              OPTIONAL { ?c campy:schema_org_type ?schema_org_type }
              OPTIONAL { ?c campy:kind_scheme ?kind_scheme }
              OPTIONAL { ?c campy:entity_standing ?entity_standing }
              BIND(!((BOUND(?ner_label) && COALESCE(STR(?entity_standing), "") != "doubtful")
                     || (BOUND(?schema_org_type) && STRENDS(STR(?schema_org_type), "Person"))) AS ?can_be_kind)
            }
            """,
    ),
    NamedQuery(
        name="entity_admission.named_entities",
        cypher="""
        MATCH (m:Message)-[:MENTIONS]->(c:Concept)
        WHERE c.ner_label IS NOT NULL AND c.archived = false
        RETURN c.ner_label AS ner_label, c.concept_id AS concept_id, c.text_raw AS text_raw,
               count(DISTINCT m) AS turns
        """,
        params=(),
        mutating=False,
        description="Every live named-entity Concept some turn MENTIONS, with its label and turn count",
        sparql="""
            SELECT ?ner_label ?concept_id ?text_raw (COUNT(DISTINCT ?m) AS ?turns) WHERE {
              ?m campy:MENTIONS ?c .
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw ;
                 campy:ner_label ?ner_label ; campy:archived false .
            }
            GROUP BY ?ner_label ?concept_id ?text_raw
            """,
    ),
    NamedQuery(
        name="entity_admission.unlinked_entities",
        cypher="""
        MATCH (c:Concept)
        WHERE c.ner_label IS NOT NULL AND c.archived = false AND NOT (:Observation)-[:OBSERVATION_ABOUT]->(c)
        RETURN c.ner_label AS ner_label, c.concept_id AS concept_id, c.text_raw AS text_raw
        """,
        params=(),
        mutating=False,
        description=("B554: admitted named-entity Concepts no Observation is OBSERVATION_ABOUT (no fact hangs off "
                     "them); the coverage number of the evidence-link rule, read by its backfill"),
        sparql="""
            SELECT ?ner_label ?concept_id ?text_raw WHERE {
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw ; campy:ner_label ?ner_label .
              FILTER NOT EXISTS { ?c campy:archived true }
              FILTER NOT EXISTS { ?o campy:OBSERVATION_ABOUT ?c }
            }
            """,
    ),
    NamedQuery(
        name="entity_admission.entity_links",
        cypher="""
        MATCH (o:Observation)-[:OBSERVATION_ABOUT]->(c:Concept)
        WHERE c.ner_label IS NOT NULL AND c.archived = false
        RETURN o.observation_id AS observation_id, c.concept_id AS concept_id
        """,
        params=(),
        mutating=False,
        description=("B554: the (Observation, admitted entity) pairs already linked by OBSERVATION_ABOUT; the "
                     "backfill counts only links that are new against these"),
        sparql="""
            SELECT ?observation_id ?concept_id WHERE {
              ?o a campy:Observation ; campy:observation_id ?observation_id ; campy:OBSERVATION_ABOUT ?c .
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:ner_label ?ner_label .
              FILTER NOT EXISTS { ?c campy:archived true }
            }
            """,
    ),
]
