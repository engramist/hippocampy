"""
campy/brain/hippocampus/graph/queries/typed_objects.py -- B546: the object of a fact is a typed entity.

Named queries behind `campy.brain.temporal_lobe.observations.typed_objects`.

Writes (all idempotent; the rule decides, nothing here chooses):
  typed_objects.link_object_phrase   an ObjectPhrase node and `Observation -HAS_OBJECT-> phrase`, only when the
                                     Observation has no object edge yet (first wins, the B522 rule)
  typed_objects.link_phrase_kind     `ObjectPhrase -INSTANCE_OF-> kind` (a kind of the closed set)
  typed_objects.set_phrase_candidate `ObjectPhrase campy:kind_candidate "<head lemma>"` when no kind matched

Reads:
  typed_objects.message_entities     the named entities B544 admitted for a turn (Concept with `ner_label`, MENTIONS)
  typed_objects.speakers             the speakers of the conversation (Message.speaker)
  typed_objects.named_entity_texts   texts of the non-kind Concepts that are named entities (the kind guard)
  typed_objects.live_observations    live Observations with their evidence Message (the backfill's rows)
  typed_objects.exact_role_turns     (KX) the subject's facts whose OBJECT, by the HAS_OBJECT role, is under a kind,
                                     entity or phrase, each with its source turn. B548 votes with this
  typed_objects.loose_role_turns     (K+) the same, also taking an entity the fact merely names
                                     (OBSERVATION_ABOUT), which is how the L3 kind query read
  typed_objects.phrase_kind_candidates  the untyped heads and how many facts they head (what a steward may confirm)

Every read of a fact returns its `EVIDENCED_BY` Message, so each row links to its source turn.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_NODE_BASE = "https://campy.dev/id/ObjectPhrase/"

# The subject's live Observations (anchored by the literal subject_id), their object under a kind.
# Liveness is the pattern used everywhere: not archived, not DEPRECATED_BY a newer Observation.
_LIVE = r"""
              FILTER NOT EXISTS { ?o campy:archived true }
              FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?_newer }
"""


def _turns_sparql(object_edge: str, kind_step: str) -> str:
    return f"""
            SELECT DISTINCT ?observation_id ?evidence_message_id ?object_id ?object_label ?kind_label WHERE {{
              ?s a campy:Concept ; campy:concept_id ?sid .
              ?kind a campy:Concept ; campy:concept_id ?kind_id .
              ?o a campy:Observation ; campy:observation_id ?observation_id ; campy:subject_id ?sid ;
                 {object_edge} ?e ; campy:EVIDENCED_BY ?m .
              ?m campy:message_id ?evidence_message_id .
              FILTER(?e != ?s)
              {kind_step}
              ?k campy:text_raw ?kind_label .
              OPTIONAL {{ ?e campy:concept_id ?object_id }}
              OPTIONAL {{ ?e campy:text_raw ?object_label }}
              {_LIVE}
            }}
            ORDER BY ?evidence_message_id ?observation_id
            """


TYPED_OBJECT_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="typed_objects.link_object_phrase",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})
        WHERE NOT (o)-[:HAS_OBJECT]->()
        MERGE (p:ObjectPhrase {phrase_id: $pid})
        SET p.text_raw = $text, p.rule_version = $rv, p.archived = false,
            p.created_at = $now, p.source = 'rule:typed-objects'
        MERGE (o)-[:HAS_OBJECT]->(p)
        """,
        params=("oid", "pid", "text", "rv", "now"),
        mutating=True,
        description=("Write the ObjectPhrase of an Observation's nameless object and link it by HAS_OBJECT; "
                     "nothing is written when the Observation already has an object edge (first wins)"),
        sparql=f"""
            INSERT {{
              ?p a campy:ObjectPhrase ;
                 campy:phrase_id ?pid ;
                 campy:text_raw ?text ;
                 campy:rule_version ?rv ;
                 campy:archived false ;
                 campy:created_at ?now ;
                 campy:source "rule:typed-objects" .
              ?o campy:HAS_OBJECT ?p .
            }}
            WHERE {{
              ?o a campy:Observation ; campy:observation_id ?oid .
              FILTER NOT EXISTS {{ ?o campy:HAS_OBJECT ?other }}
              BIND(IRI(CONCAT("{_NODE_BASE}", ENCODE_FOR_URI(STR(?pid)))) AS ?p)
            }}
            """,
    ),
    NamedQuery(
        name="typed_objects.link_phrase_kind",
        cypher="""
        MATCH (p:ObjectPhrase {phrase_id: $pid}), (k:Concept {concept_id: $kid})
        MERGE (p)-[:INSTANCE_OF]->(k)
        """,
        params=("pid", "kid"),
        mutating=True,
        description="An ObjectPhrase is an instance of a kind Concept (INSTANCE_OF, idempotent)",
        sparql="""
            INSERT { ?p campy:INSTANCE_OF ?k . }
            WHERE {
              ?p a campy:ObjectPhrase ; campy:phrase_id ?pid .
              ?k a campy:Concept ; campy:concept_id ?kid .
            }
            """,
    ),
    NamedQuery(
        name="typed_objects.set_phrase_candidate",
        cypher="""
        MATCH (p:ObjectPhrase {phrase_id: $pid}) WHERE p.kind_candidate IS NULL
        SET p.kind_candidate = $cand
        """,
        params=("pid", "cand"),
        mutating=True,
        description="Record the head lemma of a phrase whose head matched no kind (a candidate; asserts nothing)",
        sparql="""
            INSERT { ?p campy:kind_candidate ?cand . }
            WHERE {
              ?p a campy:ObjectPhrase ; campy:phrase_id ?pid .
              FILTER NOT EXISTS { ?p campy:kind_candidate ?old }
            }
            """,
    ),
    NamedQuery(
        name="typed_objects.message_entities",
        cypher="""
        MATCH (m:Message {message_id: $mid})-[:MENTIONS]->(c:Concept)
        WHERE c.archived = false AND c.kind_scheme IS NULL
        RETURN DISTINCT c.concept_id AS concept_id, c.text_raw AS text_raw
        """,
        params=("mid",),
        mutating=False,
        description=("The named entities a user turn mentions: Concepts with the tagger label B544 stores "
                     "(ner_label; the SPARQL form needs it, so without B544 the result is empty), not kinds"),
        sparql="""
            SELECT DISTINCT ?concept_id ?text_raw ?ner_label WHERE {
              ?m a campy:Message ; campy:message_id ?mid ; campy:MENTIONS ?c .
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw ; campy:ner_label ?ner_label .
              FILTER NOT EXISTS { ?c campy:archived true }
              FILTER NOT EXISTS { ?c campy:kind_scheme "kind" }
            }
            """,
    ),
    NamedQuery(
        name="typed_objects.speakers",
        cypher="MATCH (m:Message) WHERE m.speaker IS NOT NULL RETURN DISTINCT m.speaker AS speaker",
        params=(),
        mutating=False,
        description="The speakers of the conversation (distinct Message.speaker): the certain persons (B549)",
        sparql="""
            SELECT DISTINCT ?speaker WHERE { ?m a campy:Message ; campy:speaker ?speaker . }
            """,
    ),
    NamedQuery(
        name="typed_objects.named_entity_texts",
        cypher="""
        MATCH (c:Concept) WHERE c.archived = false AND c.kind_scheme IS NULL AND c.schema_org_type = 'Person'
        RETURN c.text_raw AS text_raw
        """,
        params=(),
        mutating=False,
        description=("Texts of the live non-kind Concepts that are named entities (a tagger label, or schema.org "
                     "Person): a kind label that equals one of them is never created (the kind guard). A labelled Concept whose "
                     "standing is doubtful (B549: a common word the tagger caught) is not one of them"),
        sparql="""
            SELECT DISTINCT ?text_raw WHERE {
              ?c a campy:Concept ; campy:text_raw ?text_raw .
              FILTER NOT EXISTS { ?c campy:archived true }
              FILTER NOT EXISTS { ?c campy:kind_scheme "kind" }
              { ?c campy:ner_label ?_l . FILTER NOT EXISTS { ?c campy:entity_standing "doubtful" } }
              UNION { ?c campy:schema_org_type ?ty . FILTER(STRENDS(STR(?ty), "Person")) }
            }
            """,
    ),
    NamedQuery(
        name="typed_objects.live_observations",
        cypher="""
        MATCH (o:Observation)-[:EVIDENCED_BY]->(m:Message)
        WHERE o.archived = false AND m.message_id = o.evidence_ref
        RETURN o.observation_id AS observation_id, o.predicate AS predicate, o.object_text AS object_text,
               o.subject_text AS subject_text, o.subject_id AS subject_id, o.evidence_start AS evidence_start,
               o.evidence_end AS evidence_end, o.evidence_text AS evidence_text,
               m.message_id AS message_id, m.text_raw AS message_text, m.speaker AS speaker
        """,
        params=(),
        mutating=False,
        description=("Live Observations (not archived, not DEPRECATED_BY) with the Message named by evidence_ref: "
                     "the rows the typed-object backfill walks, one per Observation"),
        sparql="""
            SELECT ?observation_id ?predicate ?object_text ?subject_text ?subject_id ?evidence_start ?evidence_end
                   ?evidence_text ?message_id ?message_text ?speaker WHERE {
              ?o a campy:Observation ; campy:observation_id ?observation_id ; campy:predicate ?predicate ;
                 campy:object_text ?object_text ; campy:subject_text ?subject_text ;
                 campy:evidence_start ?evidence_start ; campy:evidence_end ?evidence_end ;
                 campy:evidence_text ?evidence_text ; campy:evidence_ref ?ref .
              ?m a campy:Message ; campy:message_id ?ref ; campy:text_raw ?message_text .
              BIND(?ref AS ?message_id)
              OPTIONAL { ?o campy:subject_id ?subject_id }
              OPTIONAL { ?m campy:speaker ?speaker }
              FILTER NOT EXISTS { ?o campy:archived true }
              FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?_newer }
            }
            """,
    ),
    NamedQuery(
        name="typed_objects.exact_role_turns",
        cypher="""
        MATCH (s:Concept {concept_id: $sid}), (kind:Concept {concept_id: $kind_id}),
              (o:Observation {subject_id: $sid})-[:HAS_OBJECT]->(e:Concept)-[:INSTANCE_OF]->(:Concept)-[:BROADER*0..]->(kind),
              (o)-[:EVIDENCED_BY]->(m:Message)
        WHERE o.archived = false AND e.concept_id <> $sid AND NOT (o)-[:DEPRECATED_BY]->(:Observation)
        RETURN DISTINCT o.observation_id AS observation_id, m.message_id AS evidence_message_id,
               e.concept_id AS object_id, e.text_raw AS object_label
        """,
        params=("sid", "kind_id"),
        mutating=False,
        description=("KX: the subject's live facts whose object, by the HAS_OBJECT role only (an entity Concept or an "
                     "ObjectPhrase), is INSTANCE_OF the kind or a kind BROADER* below it; each row with its evidence "
                     "turn. Empty when the subject or the kind is unresolved: there is no fallback. The Cypher form "
                     "reads entity objects only; phrases are SPARQL-side."),
        sparql=_turns_sparql("campy:HAS_OBJECT", "?e campy:INSTANCE_OF ?k . ?k campy:BROADER* ?kind ."),
    ),
    NamedQuery(
        name="typed_objects.loose_role_turns",
        cypher="""
        MATCH (s:Concept {concept_id: $sid}), (kind:Concept {concept_id: $kind_id}),
              (o:Observation {subject_id: $sid})-[:OBSERVATION_ABOUT|HAS_OBJECT]->(e:Concept)-[:INSTANCE_OF]->(:Concept)-[:BROADER*0..]->(kind),
              (o)-[:EVIDENCED_BY]->(m:Message)
        WHERE o.archived = false AND e.concept_id <> $sid AND NOT (o)-[:DEPRECATED_BY]->(:Observation)
        RETURN DISTINCT o.observation_id AS observation_id, m.message_id AS evidence_message_id,
               e.concept_id AS object_id, e.text_raw AS object_label
        """,
        params=("sid", "kind_id"),
        mutating=False,
        description=("K+: like exact_role_turns, but also an entity the fact only names (OBSERVATION_ABOUT) and the "
                     "legacy IS_A kind step, which is how the L3 kind query read. Looser, noisier; the exact form is "
                     "the one a vote should use."),
        sparql=_turns_sparql("(campy:OBSERVATION_ABOUT|campy:HAS_OBJECT)",
                             "?e (campy:INSTANCE_OF|campy:IS_A) ?k . ?k (campy:BROADER|campy:IS_A)* ?kind ."),
    ),
    NamedQuery(
        name="typed_objects.phrase_kind_candidates",
        cypher="MATCH (p:ObjectPhrase) WHERE p.kind_candidate IS NOT NULL RETURN p.kind_candidate AS lemma, count(p) AS n",
        params=(),
        mutating=False,
        description=("The heads of untyped ObjectPhrases and how many facts each heads: what a steward may confirm "
                     "as a kind (a candidate is read here, so it is not write-only)"),
        sparql="""
            SELECT ?lemma (COUNT(DISTINCT ?o) AS ?n) WHERE {
              ?o campy:HAS_OBJECT ?p .
              ?p a campy:ObjectPhrase ; campy:kind_candidate ?lemma .
              FILTER NOT EXISTS { ?p campy:INSTANCE_OF ?k }
            } GROUP BY ?lemma ORDER BY DESC(?n)
            """,
    ),
)
