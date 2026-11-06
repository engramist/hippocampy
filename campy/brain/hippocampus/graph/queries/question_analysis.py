"""
campy/brain/hippocampus/graph/queries/question_analysis.py -- B547 question analysis.

Named queries behind `campy.brain.thalamus.question_analysis.load_lexicon`: the closed sets the analysis
resolves a question against (live Concepts with what says they are people or kinds, and every Concept's
prefLabel/altLabel surfaces). The kind set itself is read by `kinds.live_kinds` / `kinds.kind_alt_labels` /
`kinds.kind_broader_edges` (`kinds.load_kinds`). Reads only; nothing is created.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

QUESTION_ANALYSIS_QUERIES = [
    NamedQuery(
        name="question_analysis.concept_lexicon",
        cypher="""
        MATCH (c:Concept) WHERE c.archived = false
        RETURN c.concept_id AS concept_id, c.text_raw AS text_raw,
               c.schema_org_type AS schema_org_type, c.kind_scheme AS kind_scheme
        """,
        params=(),
        mutating=False,
        description="Every live Concept with its type and the tagger label B544 stores (ner_label), for resolving the people and entities a question names",
        sparql="""
            SELECT ?concept_id ?text_raw ?schema_org_type ?kind_scheme ?ner_label ?entity_standing ?person_basis WHERE {
              ?c a campy:Concept ; campy:concept_id ?concept_id ;
                 campy:text_raw ?text_raw ; campy:archived false .
              OPTIONAL { ?c campy:schema_org_type ?schema_org_type }
              OPTIONAL { ?c campy:kind_scheme ?kind_scheme }
              OPTIONAL { ?c campy:ner_label ?ner_label }
              OPTIONAL { ?c campy:entity_standing ?entity_standing }
              # B549: a person is typed Person (strong), or tagged PERSON and not withdrawn by the standing rule
              # (weak: B547 still needs the question-side tagger to agree). No standing recorded = as before.
              BIND(IF(BOUND(?schema_org_type) && STRENDS(STR(?schema_org_type), "Person"), "strong",
                   IF(COALESCE(STR(?ner_label), "") = "PERSON"
                      && (!BOUND(?entity_standing) || STR(?entity_standing) = "confirmed"), "weak", "")) AS ?person_basis)
            }
            """,
    ),
    NamedQuery(
        name="question_analysis.concept_surfaces",
        cypher="""
        MATCH (c:Concept)-[:HAS_ALT_LABEL]->(l:Label) WHERE c.archived = false
        RETURN c.concept_id AS concept_id, l.text AS surface
        """,
        params=(),
        mutating=False,
        description="The altLabel and prefLabel surfaces of every live Concept (a Concept is found by any wording it has accumulated)",
        sparql="""
            SELECT ?concept_id ?surface WHERE {
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:archived false .
              { ?c campy:HAS_ALT_LABEL ?l } UNION { ?c campy:HAS_PREF_LABEL ?l }
              ?l campy:text ?surface .
            }
            """,
    ),
]
