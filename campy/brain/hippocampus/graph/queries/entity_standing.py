"""
campy/brain/hippocampus/graph/queries/entity_standing.py -- B549 entity standing.

Named queries behind `campy.brain.hippocampus.entity_standing`. The one new term is the Concept property
`entity_standing` (`confirmed | doubtful | unverified`), derived by rule from independent signals (speaker,
capitalisation evidence); the tagger's `ner_label` stays evidence. It is written by `set_standing` and read by
`entity_admission.concept_status` (the kind guard), `typed_objects.named_entity_texts` (the kind-label guard)
and `question_analysis.concept_lexicon` (the B547 persons), each inside its own query, and by
`kind_conflicts` (the backfill's audit).

Evidence reads: `session_speakers` (the speakers of the conversation a turn is in), `turns_by_speakers` /
`turns_unspoken` (the user turns of that conversation containing a word), `turn_entities` (the labelled Concepts
a turn mentions), `concept_turns` (the turns that mention one Concept), `confirmed_texts` (known names for span
trimming). Re-pointing queries move the edges of a trimmed wrapper Concept to its target.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

ENTITY_STANDING_QUERIES = [
    NamedQuery(
        name="entity_standing.set_standing",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}) SET c.entity_standing = $standing
        """,
        params=("cid", "standing"),
        mutating=True,
        description="Record a Concept's derived standing (the last assessment wins: it is derived, not first-wins)",
        sparql="""
            DELETE { ?c campy:entity_standing ?old }
            INSERT { ?c campy:entity_standing ?standing }
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              OPTIONAL { ?c campy:entity_standing ?old }
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.concept_standing",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}) RETURN c.entity_standing AS entity_standing
        """,
        params=("cid",),
        mutating=False,
        description="A Concept's recorded standing (none when it was never assessed); the assessor skips a write that changes nothing",
        sparql="""
            SELECT ?entity_standing WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              OPTIONAL { ?c campy:entity_standing ?entity_standing }
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.session_speakers",
        cypher="""
        MATCH (m:Message {message_id: $mid})-[:SENT_IN]->(s:Session)<-[:SENT_IN]-(o:Message)
        WHERE o.speaker IS NOT NULL RETURN DISTINCT o.speaker AS speaker
        """,
        params=("mid",),
        mutating=False,
        description="The speakers of the sessions a turn is in: the conversation's certain persons (B549)",
        sparql="""
            SELECT DISTINCT ?speaker WHERE {
              ?m a campy:Message ; campy:message_id ?mid ; campy:SENT_IN ?s .
              ?o campy:SENT_IN ?s ; campy:speaker ?speaker .
              FILTER(STR(?speaker) != "")
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.concept_speakers",
        cypher="""
        MATCH (m:Message)-[:MENTIONS]->(c:Concept {concept_id: $cid}), (m)-[:SENT_IN]->(s:Session)<-[:SENT_IN]-(o:Message)
        WHERE o.speaker IS NOT NULL RETURN DISTINCT o.speaker AS speaker
        """,
        params=("cid",),
        mutating=False,
        description=("The speakers of the sessions of the turns that mention one Concept: the conversations its "
                     "evidence is pooled over (B549)"),
        sparql="""
            SELECT DISTINCT ?speaker WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              ?m campy:MENTIONS ?c ; campy:SENT_IN ?s .
              ?o campy:SENT_IN ?s ; campy:speaker ?speaker .
              FILTER(STR(?speaker) != "")
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.turns_by_speakers",
        cypher="""
        MATCH (m:Message) WHERE m.role = 'user' AND m.speaker IN $speakers
          AND toLower(m.text_raw) CONTAINS $key
        RETURN m.message_id AS message_id, m.text_raw AS text
        """,
        params=("speakers", "key"),
        mutating=False,
        description=("The user turns of a conversation (turns by its speakers) whose text contains a word, "
                     "case-insensitively: the capitalisation evidence pool of one entity (B549)"),
        sparql="""
            SELECT ?message_id ?text WHERE {
              VALUES ?speaker { }
              ?m a campy:Message ; campy:message_id ?message_id ; campy:role "user" ;
                 campy:speaker ?speaker ; campy:text_raw ?text .
              FILTER(CONTAINS(LCASE(STR(?text)), ?key))
            }
            ORDER BY ?message_id
            """,
    ),
    NamedQuery(
        name="entity_standing.turns_unspoken",
        cypher="""
        MATCH (m:Message) WHERE m.role = 'user' AND (m.speaker IS NULL OR m.speaker = '')
          AND toLower(m.text_raw) CONTAINS $key
        RETURN m.message_id AS message_id, m.text_raw AS text
        """,
        params=("key",),
        mutating=False,
        description=("The user turns that name no speaker whose text contains a word, case-insensitively: the "
                     "evidence pool when a store has no speakers (B549)"),
        sparql="""
            SELECT ?message_id ?text WHERE {
              ?m a campy:Message ; campy:message_id ?message_id ; campy:role "user" ; campy:text_raw ?text .
              OPTIONAL { ?m campy:speaker ?sp }
              FILTER(!BOUND(?sp) || STR(?sp) = "")
              FILTER(CONTAINS(LCASE(STR(?text)), ?key))
            }
            ORDER BY ?message_id
            """,
    ),
    NamedQuery(
        name="entity_standing.turn_entities",
        cypher="""
        MATCH (m:Message {message_id: $mid})-[:MENTIONS]->(c:Concept)
        WHERE c.archived = false AND c.ner_label IS NOT NULL
        RETURN DISTINCT c.concept_id AS concept_id, c.text_raw AS text_raw
        """,
        params=("mid",),
        mutating=False,
        description="The live labelled Concepts a turn mentions (re-assessed when the turn is processed)",
        sparql="""
            SELECT DISTINCT ?concept_id ?text_raw WHERE {
              ?m a campy:Message ; campy:message_id ?mid ; campy:MENTIONS ?c .
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw ; campy:ner_label ?_l .
              FILTER NOT EXISTS { ?c campy:archived true }
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.labelled_concepts",
        cypher="""
        MATCH (c:Concept) WHERE c.archived = false AND c.ner_label IS NOT NULL
        RETURN c.concept_id AS concept_id, c.text_raw AS text_raw, c.ner_label AS ner_label,
               c.entity_standing AS entity_standing
        """,
        params=(),
        mutating=False,
        description="Every live labelled Concept with its recorded standing (the backfill's worklist)",
        sparql="""
            SELECT ?concept_id ?text_raw ?ner_label ?entity_standing WHERE {
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw ; campy:ner_label ?ner_label .
              FILTER NOT EXISTS { ?c campy:archived true }
              OPTIONAL { ?c campy:entity_standing ?entity_standing }
            }
            ORDER BY ?concept_id
            """,
    ),
    NamedQuery(
        name="entity_standing.concept_turns",
        cypher="""
        MATCH (m:Message)-[:MENTIONS]->(c:Concept {concept_id: $cid})
        RETURN m.message_id AS message_id, m.text_raw AS text, m.speaker AS speaker
        """,
        params=("cid",),
        mutating=False,
        description="The user turns that mention one Concept, with their text and speaker (the trim-merge reads these)",
        sparql="""
            SELECT ?message_id ?text ?speaker WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              ?m campy:MENTIONS ?c ; campy:message_id ?message_id ; campy:text_raw ?text .
              OPTIONAL { ?m campy:speaker ?speaker }
            }
            ORDER BY ?message_id
            """,
    ),
    NamedQuery(
        name="entity_standing.confirmed_texts",
        cypher="""
        MATCH (c:Concept) WHERE c.archived = false AND c.entity_standing = 'confirmed'
        RETURN c.text_raw AS text_raw
        """,
        params=(),
        mutating=False,
        description="Texts of the live Concepts whose standing is confirmed: the known names a wrapped span is trimmed to",
        sparql="""
            SELECT DISTINCT ?text_raw WHERE {
              ?c a campy:Concept ; campy:text_raw ?text_raw ; campy:entity_standing "confirmed" .
              FILTER NOT EXISTS { ?c campy:archived true }
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.kind_conflicts",
        cypher="""
        MATCH (c:Concept) WHERE c.archived = false AND c.kind_scheme = 'kind' AND c.entity_standing = 'confirmed'
        RETURN c.concept_id AS concept_id, c.text_raw AS text_raw
        """,
        params=(),
        mutating=False,
        description="Live kinds whose standing is confirmed: a named entity that is also a kind (reported, never edited)",
        sparql="""
            SELECT ?concept_id ?text_raw WHERE {
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw ;
                 campy:kind_scheme "kind" ; campy:entity_standing "confirmed" .
              FILTER NOT EXISTS { ?c campy:archived true }
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.repoint_mentions",
        cypher="""
        MATCH (m:Message)-[r:MENTIONS]->(w:Concept {concept_id: $wid}), (t:Concept {concept_id: $tid})
        DELETE r MERGE (m)-[:MENTIONS]->(t)
        """,
        params=("wid", "tid"),
        mutating=True,
        description="A trimmed wrapper Concept's MENTIONS edges now reach its target Concept",
        sparql="""
            DELETE { ?m campy:MENTIONS ?w }
            INSERT { ?m campy:MENTIONS ?t }
            WHERE {
              ?w a campy:Concept ; campy:concept_id ?wid .
              ?t a campy:Concept ; campy:concept_id ?tid .
              ?m campy:MENTIONS ?w .
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.repoint_about",
        cypher="""
        MATCH (o:Observation)-[r:OBSERVATION_ABOUT]->(w:Concept {concept_id: $wid}), (t:Concept {concept_id: $tid})
        DELETE r MERGE (o)-[:OBSERVATION_ABOUT]->(t)
        """,
        params=("wid", "tid"),
        mutating=True,
        description="A trimmed wrapper Concept's OBSERVATION_ABOUT edges now reach its target Concept",
        sparql="""
            DELETE { ?o campy:OBSERVATION_ABOUT ?w }
            INSERT { ?o campy:OBSERVATION_ABOUT ?t }
            WHERE {
              ?w a campy:Concept ; campy:concept_id ?wid .
              ?t a campy:Concept ; campy:concept_id ?tid .
              ?o campy:OBSERVATION_ABOUT ?w .
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.repoint_subject",
        cypher="""
        MATCH (o:Observation)-[r:HAS_SUBJECT]->(w:Concept {concept_id: $wid}), (t:Concept {concept_id: $tid})
        DELETE r MERGE (o)-[:HAS_SUBJECT]->(t)
        """,
        params=("wid", "tid"),
        mutating=True,
        description="A trimmed wrapper Concept's HAS_SUBJECT edges now reach its target Concept",
        sparql="""
            DELETE { ?o campy:HAS_SUBJECT ?w }
            INSERT { ?o campy:HAS_SUBJECT ?t }
            WHERE {
              ?w a campy:Concept ; campy:concept_id ?wid .
              ?t a campy:Concept ; campy:concept_id ?tid .
              ?o campy:HAS_SUBJECT ?w .
            }
            """,
    ),
    NamedQuery(
        name="entity_standing.repoint_object",
        cypher="""
        MATCH (o:Observation)-[r:HAS_OBJECT]->(w:Concept {concept_id: $wid}), (t:Concept {concept_id: $tid})
        DELETE r MERGE (o)-[:HAS_OBJECT]->(t)
        """,
        params=("wid", "tid"),
        mutating=True,
        description="A trimmed wrapper Concept's HAS_OBJECT edges now reach its target Concept",
        sparql="""
            DELETE { ?o campy:HAS_OBJECT ?w }
            INSERT { ?o campy:HAS_OBJECT ?t }
            WHERE {
              ?w a campy:Concept ; campy:concept_id ?wid .
              ?t a campy:Concept ; campy:concept_id ?tid .
              ?o campy:HAS_OBJECT ?w .
            }
            """,
    ),
]
