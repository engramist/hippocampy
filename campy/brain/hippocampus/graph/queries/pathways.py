"""campy/brain/hippocampus/graph/queries/pathways.py — Named queries for Step 7 pathway updates and Hebbian learning."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

PATHWAY_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="pathways.get_concept_pathway_state",
        cypher="""
            MATCH (c:Concept {concept_id: $id})
            RETURN c.pathway_strength, c.last_accessed_at, c.created_at
            """,
        params=("id",),
        mutating=False,
        description="Fetch Concept pathway_strength and access timestamps for additive update.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?pathway_strength ?last_accessed_at ?created_at
            WHERE {
              ?c a campy:Concept ;
                 campy:concept_id ?id ;
                 campy:pathway_strength ?pathway_strength ;
                 campy:last_accessed_at ?last_accessed_at ;
                 campy:created_at ?created_at .
            }
        """,
    ),
    NamedQuery(
        name="pathways.update_concept_pathway_additive",
        cypher="""
            MATCH (c:Concept {concept_id: $id})
            SET c.pathway_strength = c.pathway_strength + $increment,
                c.last_accessed_at = timestamp($now)
            """,
        params=("id", "increment", "now"),
        mutating=True,
        description="Increment Concept pathway_strength and update last_accessed_at.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?c campy:pathway_strength ?old_strength .
              ?c campy:last_accessed_at ?old_accessed .
            }
            INSERT {
              ?c campy:pathway_strength ?new_strength .
              ?c campy:last_accessed_at ?now .
            }
            WHERE {
              ?c a campy:Concept ;
                 campy:concept_id ?id ;
                 campy:pathway_strength ?old_strength .
              OPTIONAL { ?c campy:last_accessed_at ?old_accessed }
              BIND((?old_strength + ?increment) AS ?new_strength)
            }
        """,
    ),
    NamedQuery(
        name="pathways.get_concept_strength",
        cypher="MATCH (c:Concept {concept_id: $id}) RETURN c.pathway_strength",
        params=("id",),
        mutating=False,
        description="Fetch Concept pathway_strength.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?pathway_strength
            WHERE {
              ?c a campy:Concept ;
                 campy:concept_id ?id ;
                 campy:pathway_strength ?pathway_strength .
            }
        """,
    ),
    NamedQuery(
        name="pathways.apply_contradiction",
        cypher="""
            MATCH (old:Concept {concept_id: $old_id}),
                  (new:Concept {concept_id: $new_id})
            SET old.archived = true
            MERGE (old)-[:DEPRECATED_BY]->(new)
            CREATE (me:MergeEvent {
                merge_event_id:        $merge_event_id,
                pre_pathway_strength:  $pre_strength,
                delta_pathway_strength: 0.0,
                alias_added:           [],
                metadata_patch:        $patch,
                created_at:            timestamp($now)
            })
            MERGE (me)-[:UPDATES_PATHWAY]->(new)
            """,
        params=("old_id", "new_id", "merge_event_id", "pre_strength", "patch", "now"),
        mutating=True,
        description="Apply contradiction resolution: archive old, deprecate, and record MergeEvent.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            DELETE {
              ?old campy:archived ?old_archived .
            }
            INSERT {
              ?old campy:archived true .
              ?old campy:DEPRECATED_BY ?new .
              ?me a campy:MergeEvent ;
                  campy:merge_event_id ?merge_event_id ;
                  campy:pre_pathway_strength ?pre_strength ;
                  campy:delta_pathway_strength "0.0"^^xsd:double ;
                  campy:metadata_patch ?patch ;
                  campy:created_at ?now ;
                  campy:UPDATES_PATHWAY ?new .
            }
            WHERE {
              ?old a campy:Concept ; campy:concept_id ?old_id .
              ?new a campy:Concept ; campy:concept_id ?new_id .
              OPTIONAL { ?old campy:archived ?old_archived }
              BIND(IRI(CONCAT("https://campy.dev/data/MergeEvent/", ENCODE_FOR_URI(STR(?merge_event_id)))) AS ?me)
            }
        """,
    ),
    NamedQuery(
        name="pathways.link_message_merge_event",
        cypher="""
            MATCH (m:Message {message_id: $mid}),
                  (me:MergeEvent {merge_event_id: $meid})
            MERGE (m)-[:TRIGGERED]->(me)
            """,
        params=("mid", "meid"),
        mutating=True,
        description="Link Message to MergeEvent via TRIGGERED.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?m campy:TRIGGERED ?me .
            }
            WHERE {
              ?m a campy:Message ; campy:message_id ?mid .
              ?me a campy:MergeEvent ; campy:merge_event_id ?meid .
            }
        """,
    ),
    NamedQuery(
        name="pathways.unwind_co_occurs_with",
        cypher="""
            UNWIND $pairs AS pair
            MATCH (a:Concept {concept_id: pair.a_id}),
                  (b:Concept {concept_id: pair.b_id})
            MERGE (a)-[r:CO_OCCURS_WITH]->(b)
            ON CREATE SET r.count     = 1,
                          r.strength  = $strength
            ON MATCH SET  r.count    = r.count + 1,
                          r.strength = (r.strength + $strength) / 2.0
            """,
        params=("pairs", "strength"),
        mutating=True,
        description="Batch upsert CO_OCCURS_WITH edges for concept pairs.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?a campy:CO_OCCURS_WITH ?b .
              << ?a campy:CO_OCCURS_WITH ?b >> campy:count ?new_count .
              << ?a campy:CO_OCCURS_WITH ?b >> campy:strength ?new_strength .
            }
            WHERE {
              VALUES (?a_id ?b_id) { }
              ?a a campy:Concept ; campy:concept_id ?a_id .
              ?b a campy:Concept ; campy:concept_id ?b_id .
              OPTIONAL {
                << ?a campy:CO_OCCURS_WITH ?b >> campy:count ?old_count .
                << ?a campy:CO_OCCURS_WITH ?b >> campy:strength ?old_strength .
              }
              BIND(IF(BOUND(?old_count), ?old_count + 1, 1) AS ?new_count)
              BIND(IF(BOUND(?old_strength), (?old_strength + ?strength) / 2.0, ?strength) AS ?new_strength)
            }
        """,
    ),
    NamedQuery(
        name="pathways.find_low_confidence_hops",
        cypher="""
            MATCH (anchor:Concept {concept_id: $id})
            MATCH (anchor)-[*1..2]-(neighbor:Concept)
            WHERE neighbor.confidence_low = true
              AND neighbor.archived = false
              AND neighbor.concept_id <> $id
            RETURN DISTINCT neighbor.concept_id,
                   neighbor.confidence,
                   neighbor.pathway_strength
            """,
        params=("id",),
        mutating=False,
        description="Find confidence_low Concepts within 1-2 hops of anchor.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT DISTINCT ?concept_id ?confidence ?pathway_strength
            WHERE {
              ?anchor a campy:Concept ; campy:concept_id ?id .
              {
                { ?anchor ?p1 ?hop1 } UNION { ?hop1 ?p1 ?anchor }
                FILTER(isIRI(?hop1) && ?p1 != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> && STRSTARTS(STR(?p1), "https://campy.dev/ns#"))
                BIND(?hop1 AS ?neighbor)
              }
              UNION
              {
                { ?anchor ?p1 ?hop1 } UNION { ?hop1 ?p1 ?anchor }
                FILTER(isIRI(?hop1) && ?p1 != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> && STRSTARTS(STR(?p1), "https://campy.dev/ns#"))
                { ?hop1 ?p2 ?hop2 } UNION { ?hop2 ?p2 ?hop1 }
                FILTER(isIRI(?hop2) && ?p2 != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> && STRSTARTS(STR(?p2), "https://campy.dev/ns#"))
                BIND(?hop2 AS ?neighbor)
              }
              ?neighbor a campy:Concept ;
                        campy:concept_id ?concept_id ;
                        campy:confidence_low true ;
                        campy:confidence ?confidence ;
                        campy:pathway_strength ?pathway_strength .
              OPTIONAL { ?neighbor campy:archived ?archived }
              FILTER((!BOUND(?archived) || ?archived = false) && ?concept_id != ?id)
            }
        """,
    ),
    NamedQuery(
        name="pathways.count_high_confidence_neighbors",
        cypher="""
            MATCH (c:Concept {concept_id: $cid})-[]-(n:Concept)
            WHERE n.archived = false AND n.confidence >= 0.60
            RETURN count(n) AS neighbor_count,
                   avg(n.pathway_strength) AS avg_strength
            """,
        params=("cid",),
        mutating=False,
        description="Count active high-confidence neighbors for density boost.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            SELECT (COUNT(DISTINCT ?n) AS ?neighbor_count) (AVG(?pathway_strength) AS ?avg_strength)
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              { ?c ?p ?n } UNION { ?n ?p ?c }
              FILTER(isIRI(?n) && ?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> && STRSTARTS(STR(?p), "https://campy.dev/ns#"))
              ?n a campy:Concept ;
                 campy:confidence ?confidence ;
                 campy:pathway_strength ?pathway_strength .
              OPTIONAL { ?n campy:archived ?archived }
              FILTER((!BOUND(?archived) || ?archived = false) && ?confidence >= "0.60"^^xsd:double && ?n != ?c)
            }
        """,
    ),
    NamedQuery(
        name="pathways.update_concept_confidence",
        cypher="""
            MATCH (c:Concept {concept_id: $cid})
            SET c.confidence = $conf,
                c.confidence_low = $low
            """,
        params=("cid", "conf", "low"),
        mutating=True,
        description="Update Concept confidence and confidence_low flag.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?c campy:confidence ?old_conf .
              ?c campy:confidence_low ?old_low .
            }
            INSERT {
              ?c campy:confidence ?conf .
              ?c campy:confidence_low ?low .
            }
            WHERE {
              ?c a campy:Concept ;
                 campy:concept_id ?cid .
              OPTIONAL { ?c campy:confidence ?old_conf }
              OPTIONAL { ?c campy:confidence_low ?old_low }
            }
        """,
    ),
    NamedQuery(
        name="pathways.get_previous_decision",
        cypher="""
            MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid})
            WHERE d.decision_id <> $did
            RETURN d.decision_id, d.created_at
            ORDER BY d.created_at DESC LIMIT 1
            """,
        params=("sid", "did"),
        mutating=False,
        description="Find most recent previous Decision in session.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?decision_id ?created_at
            WHERE {
              ?s a campy:Session ; campy:session_id ?sid .
              ?d a campy:Decision ;
                 campy:decision_id ?decision_id ;
                 campy:ESTABLISHED_IN ?s ;
                 campy:created_at ?created_at .
              FILTER(?decision_id != ?did)
            }
            ORDER BY DESC(?created_at)
            LIMIT 1
        """,
    ),
    NamedQuery(
        name="pathways.count_prior_decisions",
        cypher="""
            MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid})
            WHERE d.decision_id <> $did RETURN count(d)
            """,
        params=("sid", "did"),
        mutating=False,
        description="Count prior decisions in session to compute step_number.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT (COUNT(?d) AS ?count)
            WHERE {
              ?s a campy:Session ; campy:session_id ?sid .
              ?d a campy:Decision ;
                 campy:decision_id ?decision_id ;
                 campy:ESTABLISHED_IN ?s .
              FILTER(?decision_id != ?did)
            }
        """,
    ),
    NamedQuery(
        name="pathways.merge_decision_chain",
        cypher="""
            MATCH (p:Decision {decision_id: $prev}), (c:Decision {decision_id: $curr})
            MERGE (p)-[r:DECISION_CHAIN]->(c)
            ON CREATE SET r.session_id = $sid, r.step_number = $step
            ON MATCH SET r.step_number = $step
            """,
        params=("prev", "curr", "sid", "step"),
        mutating=True,
        description="Link consecutive Decisions via DECISION_CHAIN.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?p campy:DECISION_CHAIN ?c .
              << ?p campy:DECISION_CHAIN ?c >> campy:session_id ?target_sid .
              << ?p campy:DECISION_CHAIN ?c >> campy:step_number ?step .
            }
            WHERE {
              ?p a campy:Decision ; campy:decision_id ?prev .
              ?c a campy:Decision ; campy:decision_id ?curr .
              OPTIONAL {
                << ?p campy:DECISION_CHAIN ?c >> campy:session_id ?old_sid .
              }
              BIND(COALESCE(?old_sid, ?sid) AS ?target_sid)
            }
        """,
    ),
)
