"""
campy/brain/hippocampus/graph/queries/subjects.py -- who a fact may be about (flag `[observations] group_subjects`).

User ruling 2026-11-14 (item 3, option A): "we" and people named by relation ("my kids") may be the subject of a
fact. The rule in `temporal_lobe/observations/subjects.py` decides; these are its only writers and reads.

Writes:
  subjects.ensure_relation_concept   a person named by relation: Concept `rel:<speaker id>:<head lemma>`, kind_scheme
                                     "relation", relation_label = the head lemma. No name, no ner_label, no embedding.
  subjects.link_relation_of          `relation Concept -RELATION_OF-> speaker Concept` (at most one, first wins)
  subjects.mark_group_subject        `Observation.group_subject = true`: the speaker as one of a group ("we")
Reads:
  subjects.turn_persons_named        the PERSON Concepts a turn MENTIONS whose label is one of the given names (the
                                     group anchor's co-participants: the X of "X and I", or the object of "with")
  subjects.turn_named_people         the Concepts a turn MENTIONS as PERSON / ORG / NORP, other than the subject, whose
                                     label occurs in the quote (the named partners of a "we" fact)
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

SUBJECT_QUERIES = [
    NamedQuery(
        name="subjects.ensure_relation_concept",
        cypher="""
        MERGE (c:Concept {concept_id: $cid})
        ON CREATE SET c.text_raw = $text, c.kind_scheme = 'relation', c.relation_label = $label,
                      c.archived = false, c.created_at = $now
        """,
        params=("cid", "text", "label", "now"),
        mutating=True,
        description=("Create the Concept of a person named by relation (concept_id 'rel:<speaker>:<lemma>', kind_scheme "
                     "'relation', relation_label the head lemma) when it does not exist; no embedding, no index entry"),
        sparql="""
            INSERT {
              ?c a campy:Concept ;
                 campy:concept_id ?cid ;
                 campy:text_raw ?text ;
                 campy:kind_scheme "relation" ;
                 campy:relation_label ?label ;
                 campy:gist_class "Relation" ;
                 campy:schema_org_type "Thing" ;
                 campy:confidence 0.95 ;
                 campy:confidence_low false ;
                 campy:pathway_strength 0.80 ;
                 campy:archived false ;
                 campy:flagged_for_review false ;
                 campy:source "rule:relation_subject" ;
                 campy:created_at ?now ;
                 campy:last_accessed_at ?now .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/id/Concept/", ENCODE_FOR_URI(STR(?cid)))) AS ?c)
              FILTER NOT EXISTS { ?c a campy:Concept }
            }
            """,
    ),
    NamedQuery(
        name="subjects.link_relation_of",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}), (s:Concept {concept_id: $sid})
        WHERE NOT (c)-[:RELATION_OF]->()
        MERGE (c)-[:RELATION_OF]->(s)
        """,
        params=("cid", "sid"),
        mutating=True,
        description="Record whose relation a relation Concept is (RELATION_OF the speaker; at most one, first wins)",
        sparql="""
            INSERT { ?c campy:RELATION_OF ?s . }
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              ?s a campy:Concept ; campy:concept_id ?sid .
              FILTER NOT EXISTS { ?c campy:RELATION_OF ?other }
            }
            """,
    ),
    NamedQuery(
        name="subjects.mark_group_subject",
        cypher="MATCH (o:Observation {observation_id: $oid}) SET o.group_subject = true",
        params=("oid",),
        mutating=True,
        description="Mark an Observation whose subject is the speaker as one of a group ('we')",
        sparql="""
            DELETE { ?o campy:group_subject ?old }
            INSERT { ?o campy:group_subject true }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              OPTIONAL { ?o campy:group_subject ?old }
            }
            """,
    ),
    NamedQuery(
        name="subjects.turn_persons_named",
        cypher=("MATCH (m:Message {message_id: $mid})-[:MENTIONS]->(c:Concept) "
                "WHERE c.ner_label = 'PERSON' AND c.concept_id <> $sid AND toLower(c.text_raw) IN $names "
                "RETURN c.concept_id AS concept_id"),
        params=("mid", "sid", "names"),
        mutating=False,
        description=("The PERSON Concepts a turn MENTIONS, other than the speaker, whose label is one of the given names "
                     "(the people a rule found as 'X' in 'X and I' or after 'with'): the co-participants of a 'we' fact"),
        sparql="""
            SELECT DISTINCT ?concept_id WHERE {
              VALUES ?name { }
              ?m campy:message_id ?mid ; campy:MENTIONS ?c .
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:ner_label "PERSON" ; campy:text_raw ?text .
              FILTER(?concept_id != ?sid && LCASE(STR(?text)) = ?name)
              FILTER NOT EXISTS { ?c campy:archived true }
            }
            ORDER BY ?concept_id
            """,
    ),
    NamedQuery(
        name="subjects.turn_named_people",
        cypher=("MATCH (m:Message {message_id: $mid})-[:MENTIONS]->(c:Concept) "
                "WHERE c.ner_label IN ['PERSON', 'ORG', 'NORP'] AND c.concept_id <> $sid "
                "AND toLower($quote) CONTAINS toLower(c.text_raw) RETURN c.concept_id AS concept_id"),
        params=("mid", "sid", "quote"),
        mutating=False,
        description=("The Concepts a turn MENTIONS as PERSON / ORG / NORP, other than the subject, whose label occurs "
                     "in the quote: the named partners of a group-subject fact"),
        sparql="""
            SELECT DISTINCT ?concept_id WHERE {
              ?m campy:message_id ?mid ; campy:MENTIONS ?c .
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:ner_label ?label ; campy:text_raw ?text .
              FILTER(?label IN ("PERSON", "ORG", "NORP") && ?concept_id != ?sid)
              FILTER(CONTAINS(LCASE(?quote), LCASE(?text)))
              FILTER NOT EXISTS { ?c campy:archived true }
            }
            ORDER BY ?concept_id
            """,
    ),
]
