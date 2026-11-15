"""
campy/brain/hippocampus/graph/queries/roles.py -- B564: the roles of an event fact (flag `[observations] roles`).

Named queries behind `campy.brain.temporal_lobe.observations.roles`.

Writes (idempotent; the rule decides, nothing here chooses):
  roles.ensure_action_concept       an action kind: Concept `wn:<synset>`, kind_scheme "action". NO embedding is
                                    written and none of the vector or text indexes is told about it: an action kind is
                                    reached through its edges and the closed WordNet lookup, never by similarity
  roles.link_action                 `Observation -HAS_ACTION-> action Concept` (at most one, first wins)
  roles.link_place                  `Observation -HAS_PLACE-> Concept` (at most one, first wins)
  roles.link_participant            `Observation -HAS_PARTICIPANT-> Concept` (any number)
  roles.link_participant_phrase     the nameless participant: an ObjectPhrase and its HAS_PARTICIPANT edge
  roles.link_place_phrase           the nameless place: an ObjectPhrase and its HAS_PLACE edge (when none yet)

Reads (every row of a fact carries its EVIDENCED_BY Message id and date; an empty result is "not recorded"):
  roles.action_concept              the action Concept of an id (the closed-set lookup; also the existence check)
  roles.turn_entity_options         the Concepts a turn MENTIONS with a ner_label, other than the fact's subject
                                    (form 2: the closed partner and place options of the roles call)
  roles.session_speakers            the Concepts that spoke (SPOKEN_BY) in the turn's session, other than the subject
  observations.role_fill            the step-1 measure: facts counted by standing and by "shared"
  facts.by_action_kind              the subject's facts whose action is a kind of K (BROADER* path)
  facts.with_participant            the subject's facts done with a given Concept
  facts.participants_of             every participant of the subject's facts (Concept or nameless)
  facts.at_place                    the subject's facts at a given place Concept
  facts.places_of                   every place of the subject's facts (Concept or nameless)
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_NODE_BASE = "https://campy.dev/id/ObjectPhrase/"

_LIVE = r"""
              FILTER NOT EXISTS { ?o campy:archived true }
              FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?_newer }
"""


def _phrase_link(edge: str, capped: bool) -> str:
    guard = f"FILTER NOT EXISTS {{ ?o campy:{edge} ?other }}" if capped else ""
    return f"""
            INSERT {{
              ?p a campy:ObjectPhrase ;
                 campy:phrase_id ?pid ;
                 campy:text_raw ?text ;
                 campy:rule_version ?rv ;
                 campy:archived false ;
                 campy:created_at ?now ;
                 campy:source "rule:roles" .
              ?o campy:{edge} ?p .
            }}
            WHERE {{
              ?o a campy:Observation ; campy:observation_id ?oid .
              {guard}
              BIND(IRI(CONCAT("{_NODE_BASE}", ENCODE_FOR_URI(STR(?pid)))) AS ?p)
            }}
            """


def _facts_sparql(edge: str, target_filter: str, target_select: str) -> str:
    return f"""
            SELECT DISTINCT ?observation_id ?action ?quote ?evidence_message_id ?occurred_at {target_select} WHERE {{
              ?s a campy:Concept ; campy:concept_id ?sid .
              ?o a campy:Observation ; campy:observation_id ?observation_id ; campy:subject_id ?sid ;
                 campy:{edge} ?t ; campy:evidence_text ?quote ; campy:EVIDENCED_BY ?m .
              {target_filter}
              ?m campy:message_id ?evidence_message_id .
              OPTIONAL {{ ?m campy:occurred_at ?occurred_at }}
              OPTIONAL {{ ?o campy:HAS_ACTION ?a . ?a campy:text_raw ?action }}
              {_LIVE}
            }}
            ORDER BY ?occurred_at ?observation_id
            """


_PARTICIPANT_SELECT = "?target_id ?target_text ?nameless"
_TARGET_ANY = """
              OPTIONAL { ?t campy:concept_id ?target_id }
              OPTIONAL { ?t campy:text_raw ?target_text }
              BIND(EXISTS { ?t a campy:ObjectPhrase } AS ?nameless)
"""

ROLE_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="roles.ensure_action_concept",
        cypher="""
        MERGE (c:Concept {concept_id: $cid})
        ON CREATE SET c.text_raw = $text, c.kind_scheme = 'action', c.archived = false, c.created_at = $now
        """,
        params=("cid", "text", "now"),
        mutating=True,
        description=("Create the action-kind Concept of a WordNet synset (concept_id 'wn:<synset>', kind_scheme "
                     "'action') when it does not exist; no embedding and no index entry"),
        sparql="""
            INSERT {
              ?c a campy:Concept ;
                 campy:concept_id ?cid ;
                 campy:text_raw ?text ;
                 campy:kind_scheme "action" ;
                 campy:gist_class "Action" ;
                 campy:schema_org_type "Thing" ;
                 campy:confidence 0.95 ;
                 campy:confidence_low false ;
                 campy:pathway_strength 0.80 ;
                 campy:archived false ;
                 campy:flagged_for_review false ;
                 campy:source "wordnet" ;
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
        name="roles.link_action",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}), (c:Concept {concept_id: $cid})
        WHERE NOT (o)-[:HAS_ACTION]->()
        MERGE (o)-[:HAS_ACTION]->(c)
        """,
        params=("oid", "cid"),
        mutating=True,
        description="Record the action kind of an event Observation (HAS_ACTION; at most one, first wins, idempotent)",
        sparql="""
            INSERT { ?o campy:HAS_ACTION ?c . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              ?c a campy:Concept ; campy:concept_id ?cid .
              FILTER NOT EXISTS { ?o campy:HAS_ACTION ?other }
            }
            """,
    ),
    NamedQuery(
        name="roles.link_place",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}), (c:Concept {concept_id: $cid})
        WHERE NOT (o)-[:HAS_PLACE]->()
        MERGE (o)-[:HAS_PLACE]->(c)
        """,
        params=("oid", "cid"),
        mutating=True,
        description="Record the place Concept of an event Observation (HAS_PLACE; at most one, first wins, idempotent)",
        sparql="""
            INSERT { ?o campy:HAS_PLACE ?c . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              ?c a campy:Concept ; campy:concept_id ?cid .
              FILTER NOT EXISTS { ?o campy:HAS_PLACE ?other }
            }
            """,
    ),
    NamedQuery(
        name="roles.link_participant",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}), (c:Concept {concept_id: $cid})
        MERGE (o)-[:HAS_PARTICIPANT]->(c)
        """,
        params=("oid", "cid"),
        mutating=True,
        description="Record a Concept the subject did it with (HAS_PARTICIPANT; any number, idempotent)",
        sparql="""
            INSERT { ?o campy:HAS_PARTICIPANT ?c . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              ?c a campy:Concept ; campy:concept_id ?cid .
            }
            """,
    ),
    NamedQuery(
        name="roles.link_participant_phrase",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})
        MERGE (p:ObjectPhrase {phrase_id: $pid})
        SET p.text_raw = $text, p.rule_version = $rv, p.archived = false, p.created_at = $now, p.source = 'rule:roles'
        MERGE (o)-[:HAS_PARTICIPANT]->(p)
        """,
        params=("oid", "pid", "text", "rv", "now"),
        mutating=True,
        description="Write the ObjectPhrase of a nameless participant and link it by HAS_PARTICIPANT (idempotent)",
        sparql=_phrase_link("HAS_PARTICIPANT", capped=False),
    ),
    NamedQuery(
        name="roles.link_place_phrase",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}) WHERE NOT (o)-[:HAS_PLACE]->()
        MERGE (p:ObjectPhrase {phrase_id: $pid})
        SET p.text_raw = $text, p.rule_version = $rv, p.archived = false, p.created_at = $now, p.source = 'rule:roles'
        MERGE (o)-[:HAS_PLACE]->(p)
        """,
        params=("oid", "pid", "text", "rv", "now"),
        mutating=True,
        description=("Write the ObjectPhrase of a nameless place and link it by HAS_PLACE; nothing is written when "
                     "the Observation already has a place (first wins)"),
        sparql=_phrase_link("HAS_PLACE", capped=True),
    ),
    NamedQuery(
        name="roles.action_concept",
        cypher="MATCH (c:Concept {concept_id: $cid, kind_scheme: 'action'}) RETURN c.concept_id AS cid, c.text_raw AS text_raw",
        params=("cid",),
        mutating=False,
        description=("The action-kind Concept of a 'wn:<synset>' id, if it exists: the closed-set lookup of a "
                     "question verb (step 3) and the existence check before a write"),
        sparql="""
            SELECT ?cid ?text_raw WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid ; campy:kind_scheme "action" ; campy:text_raw ?text_raw .
            }
            """,
    ),
    NamedQuery(
        name="roles.turn_entity_options",
        cypher=("MATCH (m:Message {message_id: $mid})-[:MENTIONS]->(c:Concept) "
                "WHERE c.archived = false AND c.ner_label IS NOT NULL AND c.concept_id <> $sid "
                "RETURN DISTINCT c.concept_id AS concept_id, c.text_raw AS text_raw, c.ner_label AS ner_label"),
        params=("mid", "sid"),
        mutating=False,
        description=("The named entities a user turn MENTIONS (Concepts with a ner_label, not kinds, not action "
                     "kinds), other than the fact's subject Concept: the closed partner (PERSON, ORG, NORP) and "
                     "place (GPE, LOC, FAC) options of the roles call, one row per Concept with its label"),
        sparql="""
            SELECT DISTINCT ?concept_id ?text_raw ?ner_label WHERE {
              ?m a campy:Message ; campy:message_id ?mid ; campy:MENTIONS ?c .
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw ; campy:ner_label ?ner_label .
              FILTER (?ner_label IN ("PERSON", "ORG", "NORP", "GPE", "LOC", "FAC"))
              FILTER (?concept_id != ?sid)
              FILTER NOT EXISTS { ?c campy:archived true }
              FILTER NOT EXISTS { ?c campy:kind_scheme "kind" }
              FILTER NOT EXISTS { ?c campy:kind_scheme "action" }
            }
            ORDER BY ?ner_label ?concept_id
            """,
    ),
    NamedQuery(
        name="roles.session_speakers",
        cypher=("MATCH (m:Message {message_id: $mid})-[:SENT_IN]->(s:Session)<-[:SENT_IN]-(m2:Message), "
                "(m2)-[:SPOKEN_BY]->(c:Concept) WHERE c.archived = false AND c.concept_id <> $sid "
                "RETURN DISTINCT c.concept_id AS concept_id, c.text_raw AS text_raw"),
        params=("mid", "sid"),
        mutating=False,
        description=("The Concepts that spoke in the turn's session (Message -SPOKEN_BY-> Concept over the Messages "
                     "SENT_IN the same Session), other than the fact's subject Concept: the other speakers, the "
                     "closed partner options every fact of the turn has. Empty without SPOKEN_BY edges"),
        sparql="""
            SELECT DISTINCT ?concept_id ?text_raw WHERE {
              ?m a campy:Message ; campy:message_id ?mid ; campy:SENT_IN ?s .
              ?m2 campy:SENT_IN ?s ; campy:SPOKEN_BY ?c .
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?text_raw .
              FILTER (?concept_id != ?sid)
              FILTER NOT EXISTS { ?c campy:archived true }
            }
            ORDER BY ?concept_id
            """,
    ),
    NamedQuery(
        name="observations.role_fill",
        cypher="MATCH (o:Observation) WHERE o.archived = false RETURN 'anchored' AS standing, false AS shared, count(o) AS n",
        params=(),
        mutating=False,
        description=("The step-1 measure, as counts: live Observations by standing (anchored: an object, action, "
                     "participant, place or typed value; text: none of those; unanchored: no subject) and by shared "
                     "(a role edge to a Concept, which other facts can join through; an ObjectPhrase does not count)"),
        sparql=f"""
            SELECT ?standing ?shared (COUNT(?o) AS ?n) WHERE {{
              ?o a campy:Observation .
              {_LIVE}
              BIND(EXISTS {{ ?o campy:HAS_SUBJECT ?_s1 }} || EXISTS {{ ?o campy:subject_id ?_s2 }} AS ?subj)
              BIND(EXISTS {{ ?o campy:HAS_OBJECT ?_x1 }} || EXISTS {{ ?o campy:HAS_ACTION ?_x2 }}
                   || EXISTS {{ ?o campy:HAS_PARTICIPANT ?_x3 }} || EXISTS {{ ?o campy:HAS_PLACE ?_x4 }}
                   || EXISTS {{ ?o campy:attr_value_kind ?_k . FILTER(?_k != "text") }} AS ?anch)
              BIND(?subj && EXISTS {{ ?o ?_r ?_c . ?_c a campy:Concept .
                            FILTER(?_r IN (campy:HAS_OBJECT, campy:HAS_ACTION, campy:HAS_PARTICIPANT, campy:HAS_PLACE)) }}
                   AS ?shared)
              BIND(IF(!?subj, "unanchored", IF(?anch, "anchored", "text")) AS ?standing)
            }} GROUP BY ?standing ?shared ORDER BY ?standing ?shared
            """,
    ),
    NamedQuery(
        name="facts.by_action_kind",
        cypher=("MATCH (s:Concept {concept_id: $sid}), (k:Concept {concept_id: $kid}), "
                "(o:Observation {subject_id: $sid})-[:HAS_ACTION]->(a:Concept)-[:BROADER*0..]->(k), "
                "(o)-[:EVIDENCED_BY]->(m:Message) WHERE o.archived = false "
                "RETURN o.observation_id AS observation_id, a.text_raw AS action, m.message_id AS evidence_message_id"),
        params=("sid", "kid"),
        mutating=False,
        description=("The subject's live facts whose action is the kind K or a kind BROADER* below it, each with its "
                     "quote, evidence turn id and date, oldest first. Empty when the subject or the kind is unknown: "
                     "the answer is 'not recorded'"),
        sparql="""
            SELECT DISTINCT ?observation_id ?action ?quote ?evidence_message_id ?occurred_at WHERE {
              ?s a campy:Concept ; campy:concept_id ?sid .
              ?k a campy:Concept ; campy:concept_id ?kid .
              ?o a campy:Observation ; campy:observation_id ?observation_id ; campy:subject_id ?sid ;
                 campy:HAS_ACTION ?a ; campy:evidence_text ?quote ; campy:EVIDENCED_BY ?m .
              ?a campy:BROADER* ?k ; campy:text_raw ?action .
              ?m campy:message_id ?evidence_message_id .
              OPTIONAL { ?m campy:occurred_at ?occurred_at }
              FILTER NOT EXISTS { ?o campy:archived true }
              FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?_newer }
            }
            ORDER BY ?occurred_at ?observation_id
            """,
    ),
    NamedQuery(
        name="facts.with_participant",
        cypher=("MATCH (s:Concept {concept_id: $sid}), (p:Concept {concept_id: $pid}), "
                "(o:Observation {subject_id: $sid})-[:HAS_PARTICIPANT]->(p), (o)-[:EVIDENCED_BY]->(m:Message) "
                "WHERE o.archived = false RETURN o.observation_id AS observation_id, m.message_id AS evidence_message_id"),
        params=("sid", "pid"),
        mutating=False,
        description=("The subject's live facts done with the given Concept (what did X and Y do), each with its "
                     "action kind label when it has one, quote, evidence turn id and date"),
        sparql=_facts_sparql("HAS_PARTICIPANT", "?t a campy:Concept ; campy:concept_id ?pid .", ""),
    ),
    NamedQuery(
        name="facts.participants_of",
        cypher=("MATCH (s:Concept {concept_id: $sid}), (o:Observation {subject_id: $sid})-[:HAS_PARTICIPANT]->(p:Concept), "
                "(o)-[:EVIDENCED_BY]->(m:Message) WHERE o.archived = false "
                "RETURN o.observation_id AS observation_id, p.concept_id AS target_id, p.text_raw AS target_text, "
                "m.message_id AS evidence_message_id"),
        params=("sid",),
        mutating=False,
        description=("Every participant (Concept, or nameless ObjectPhrase text) of the subject's live facts (who did "
                     "X with), each with action label, quote, evidence turn id and date"),
        sparql=_facts_sparql("HAS_PARTICIPANT", _TARGET_ANY, _PARTICIPANT_SELECT),
    ),
    NamedQuery(
        name="facts.at_place",
        cypher=("MATCH (s:Concept {concept_id: $sid}), (p:Concept {concept_id: $plid}), "
                "(o:Observation {subject_id: $sid})-[:HAS_PLACE]->(p), (o)-[:EVIDENCED_BY]->(m:Message) "
                "WHERE o.archived = false RETURN o.observation_id AS observation_id, m.message_id AS evidence_message_id"),
        params=("sid", "plid"),
        mutating=False,
        description=("The subject's live facts at the given place Concept, each with its action kind label when it "
                     "has one, quote, evidence turn id and date"),
        sparql=_facts_sparql("HAS_PLACE", "?t a campy:Concept ; campy:concept_id ?plid .", ""),
    ),
    NamedQuery(
        name="facts.places_of",
        cypher=("MATCH (s:Concept {concept_id: $sid}), (o:Observation {subject_id: $sid})-[:HAS_PLACE]->(p:Concept), "
                "(o)-[:EVIDENCED_BY]->(m:Message) WHERE o.archived = false "
                "RETURN o.observation_id AS observation_id, p.concept_id AS target_id, p.text_raw AS target_text, "
                "m.message_id AS evidence_message_id"),
        params=("sid",),
        mutating=False,
        description=("Every place (Concept, or nameless ObjectPhrase text) of the subject's live facts (where), each "
                     "with action label, quote, evidence turn id and date"),
        sparql=_facts_sparql("HAS_PLACE", _TARGET_ANY, _PARTICIPANT_SELECT),
    ),
)
