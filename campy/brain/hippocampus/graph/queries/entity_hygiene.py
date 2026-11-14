"""
campy/brain/hippocampus/graph/queries/entity_hygiene.py -- B565: closed-class words stored as Concepts.

Reads:
  entity_hygiene.closed_class_concepts      the live Concepts whose label is one closed-class word (the `words` VALUES
                                            parameter, always `lexicon.closed_class.CLOSED_CLASS_WORDS`), not written
                                            in capitals of two letters or more; with how many facts have it as subject
  entity_hygiene.closed_class_subject_facts the live facts whose HAS_SUBJECT Concept is an archived closed-class Concept
                                            (the facts B565's cleanup leaves without a live subject)

The cleanup archives each Concept through `quests.archive_concept`; no edge is removed.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_CLOSED_LABEL = """
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?label .
              FILTER(LCASE(STR(?label)) = ?word)
              FILTER(!(STRLEN(?label) >= 2 && UCASE(?label) = ?label))
"""

ENTITY_HYGIENE_QUERIES = [
    NamedQuery(
        name="entity_hygiene.closed_class_concepts",
        cypher=("MATCH (c:Concept) WHERE toLower(c.text_raw) IN $words AND c.archived = false "
                "RETURN c.concept_id AS concept_id, c.text_raw AS label"),
        params=("words",),
        mutating=False,
        description=("Live Concepts whose label is one closed-class word from the `words` list (not an all-capitals "
                     "acronym), with the number of live facts that have it as subject"),
        sparql=f"""
            SELECT ?concept_id ?label (COUNT(DISTINCT ?o) AS ?subject_facts) WHERE {{
              VALUES ?word {{ }}
              {_CLOSED_LABEL}
              FILTER NOT EXISTS {{ ?c campy:archived true }}
              OPTIONAL {{ ?o campy:HAS_SUBJECT ?c . FILTER NOT EXISTS {{ ?o campy:archived true }} }}
            }}
            GROUP BY ?concept_id ?label
            ORDER BY ?label ?concept_id
            """,
    ),
    NamedQuery(
        name="entity_hygiene.closed_class_subject_facts",
        cypher=("MATCH (o:Observation)-[:HAS_SUBJECT]->(c:Concept) WHERE toLower(c.text_raw) IN $words "
                "AND c.archived = true AND o.archived = false RETURN count(DISTINCT o) AS facts"),
        params=("words",),
        mutating=False,
        description="How many live facts have an archived closed-class Concept as their HAS_SUBJECT",
        sparql=f"""
            SELECT (COUNT(DISTINCT ?o) AS ?facts) WHERE {{
              VALUES ?word {{ }}
              {_CLOSED_LABEL}
              ?c campy:archived true .
              ?o campy:HAS_SUBJECT ?c .
              FILTER NOT EXISTS {{ ?o campy:archived true }}
            }}
            """,
    ),
]
