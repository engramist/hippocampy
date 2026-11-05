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
               c.kind_scheme AS kind_scheme
        """,
        params=("cid",),
        mutating=False,
        description="A Concept's NER label, schema.org type and kind scheme (the kind guard reads these)",
        sparql="""
            SELECT ?ner_label ?schema_org_type ?kind_scheme WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              OPTIONAL { ?c campy:ner_label ?ner_label }
              OPTIONAL { ?c campy:schema_org_type ?schema_org_type }
              OPTIONAL { ?c campy:kind_scheme ?kind_scheme }
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
]
