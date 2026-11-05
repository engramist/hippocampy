"""
campy/brain/hippocampus/graph/queries/steward.py -- B535 the vocabulary steward.

Named queries behind `campy.brain.temporal_lobe.steward`. A steward proposal is a REIFIER (an RDF-star
node `rdf:reifies <<( child BROADER parent )>>` or `<<( entity INSTANCE_OF kind )>>`) carrying

  campy:link_source    "steward" for its own proposals, "wordnet" for a B534 link it reviews
  campy:link_status    candidate | promoted | rejected | disputed
  campy:evidence_set   one value per evidence set the steward argued from (sorted ids, comma joined)
  campy:steward_reason the model's one-line reason for the first proposal
  campy:agreed_by      an independent second source: wordnet | recurrence | second_model | person

A candidate reifier does NOT assert the triple it reifies, so the walk and the count (`BROADER*`,
`INSTANCE_OF`) cannot see it. Promotion asserts the triple and sets the status; rejecting a WordNet link
retracts the triple and keeps the reifier as the record (kinds.link_broader_sourced never re-adds it).
The reads at the bottom are what `scripts/graph_structure_report.py` and the steward's own loop use.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_NO_CYCLE = ("FILTER NOT EXISTS { ?a campy:BROADER+ ?b } FILTER NOT EXISTS { ?b campy:BROADER+ ?a }")


def _for(rel: str) -> list[NamedQuery]:
    """The writes for one relation (BROADER: kind to broader kind; INSTANCE_OF: entity to kind)."""
    name = rel.lower()
    cycle = _NO_CYCLE if rel == "BROADER" else "FILTER NOT EXISTS { ?a campy:INSTANCE_OF ?b }"
    both = ("?a a campy:Concept ; campy:concept_id ?cid ; campy:archived false .\n"
            "              ?b a campy:Concept ; campy:concept_id ?pid ; campy:archived false .")
    return [
        NamedQuery(
            name=f"steward.propose_{name}",
            cypher=f"MATCH (a:Concept {{concept_id: $cid}}), (b:Concept {{concept_id: $pid}}) RETURN a, b /* {rel} candidate */",
            params=("cid", "pid", "reason"),
            mutating=True,
            description=f"Write a steward CANDIDATE for {rel} as a reifier only; the triple itself is not asserted, "
                        "so no walk or count sees it. Skipped when the pair is already related or already proposed",
            sparql=f"""
            INSERT {{
              _:r rdf:reifies <<( ?a campy:{rel} ?b )>> ;
                  campy:link_source "steward" ; campy:link_status "candidate" ; campy:steward_reason ?reason .
            }}
            WHERE {{
              {both}
              FILTER(?a != ?b)
              {cycle}
              FILTER NOT EXISTS {{ ?r0 rdf:reifies <<( ?a campy:{rel} ?b )>> ; campy:link_source "steward" }}
            }}
            """,
        ),
        NamedQuery(
            name=f"steward.add_evidence_{name}",
            cypher=f"MATCH (a:Concept {{concept_id: $cid}}) RETURN a /* {rel} evidence */",
            params=("cid", "pid", "lsrc", "es"),
            mutating=True,
            description="Record one more evidence set the steward argued this pair from (idempotent)",
            sparql=f"""
            INSERT {{ ?r campy:evidence_set ?es }}
            WHERE {{
              {both}
              ?r rdf:reifies <<( ?a campy:{rel} ?b )>> ; campy:link_source ?lsrc .
            }}
            """,
        ),
        NamedQuery(
            name=f"steward.agree_{name}",
            cypher=f"MATCH (a:Concept {{concept_id: $cid}}) RETURN a /* {rel} agreement */",
            params=("cid", "pid", "lsrc", "by"),
            mutating=True,
            description="Record an independent second source that agrees with the steward on this pair (idempotent)",
            sparql=f"""
            INSERT {{ ?r campy:agreed_by ?by }}
            WHERE {{
              {both}
              ?r rdf:reifies <<( ?a campy:{rel} ?b )>> ; campy:link_source ?lsrc .
            }}
            """,
        ),
        NamedQuery(
            name=f"steward.promote_{name}",
            cypher=f"MATCH (a:Concept {{concept_id: $cid}}) RETURN a /* {rel} promote */",
            params=("cid", "pid"),
            mutating=True,
            description=f"Promote an agreed steward candidate: assert the {rel} triple and mark the reifier promoted. "
                        "Skipped (stays candidate) when it has no agreeing source or the pair is now related/cyclic",
            sparql=f"""
            DELETE {{ ?r campy:link_status "candidate" }}
            INSERT {{ ?a campy:{rel} ?b . ?r campy:link_status "promoted" }}
            WHERE {{
              {both}
              FILTER(?a != ?b)
              ?r rdf:reifies <<( ?a campy:{rel} ?b )>> ;
                 campy:link_source "steward" ; campy:link_status "candidate" ; campy:agreed_by ?any .
              FILTER(?any IN ("wordnet", "second_model", "person"))
              {cycle}
            }}
            """,
        ),
    ]


KIND_STEWARD_QUERIES = [
    *_for("BROADER"),
    *_for("INSTANCE_OF"),
    # --- review of a WordNet link (B534): the steward's "reject" vote, then a second source decides ---
    NamedQuery(
        name="steward.dispute_broader",
        cypher="MATCH (a:Concept {concept_id: $cid}) RETURN a /* dispute */",
        params=("cid", "pid", "es", "reason"),
        mutating=True,
        description="The steward voted to reject a WordNet link: record the vote (evidence set, reason) and mark the "
                    "link disputed. The link stays asserted until a second source agrees",
        sparql="""
            DELETE { ?r campy:link_status ?old }
            INSERT { ?r campy:link_status "disputed" ; campy:evidence_set ?es ; campy:steward_reason ?reason }
            WHERE {
              ?a a campy:Concept ; campy:concept_id ?cid .
              ?b a campy:Concept ; campy:concept_id ?pid .
              ?r rdf:reifies <<( ?a campy:BROADER ?b )>> ; campy:link_source "wordnet" .
              OPTIONAL { ?r campy:link_status ?old }
              FILTER(!BOUND(?old) || ?old = "disputed")
            }
            """,
    ),
    NamedQuery(
        name="steward.reject_broader",
        cypher="MATCH (a:Concept {concept_id: $cid}) RETURN a /* reject */",
        params=("cid", "pid"),
        mutating=True,
        description="Reject a disputed WordNet link that a second source agrees with: retract the BROADER triple "
                    "(out of the walk) and keep the reifier, status rejected, as the record",
        sparql="""
            DELETE { ?a campy:BROADER ?b . ?r campy:link_status "disputed" }
            INSERT { ?r campy:link_status "rejected" }
            WHERE {
              ?a a campy:Concept ; campy:concept_id ?cid .
              ?b a campy:Concept ; campy:concept_id ?pid .
              ?r rdf:reifies <<( ?a campy:BROADER ?b )>> ;
                 campy:link_source "wordnet" ; campy:link_status "disputed" ; campy:agreed_by ?any .
              FILTER(?any IN ("second_model", "person"))
            }
            """,
    ),
    # --- reads ---
    NamedQuery(
        name="steward.parentless_kinds",
        cypher="MATCH (k:Concept) WHERE k.kind_scheme = 'kind' AND k.archived = false RETURN k.concept_id AS kind_id",
        params=(),
        mutating=False,
        description="Live kinds with no BROADER parent, with how many entities are INSTANCE_OF each (task a)",
        sparql="""
            SELECT ?kind_id ?label (COUNT(DISTINCT ?x) AS ?n) WHERE {
              ?k a campy:Concept ; campy:concept_id ?kind_id ; campy:text_raw ?label ;
                 campy:kind_scheme "kind" ; campy:archived false .
              FILTER NOT EXISTS { ?k campy:BROADER ?p }
              OPTIONAL { ?x campy:INSTANCE_OF ?k }
            } GROUP BY ?kind_id ?label
            """,
    ),
    NamedQuery(
        name="steward.kind_examples",
        cypher="MATCH (k:Concept {concept_id: $kind_id}) RETURN k.concept_id AS kind_id",
        params=("kind_id",),
        mutating=False,
        description="The entities INSTANCE_OF a kind, each with the source quotes of the live Observations that name it "
                    "(as object or subject); the evidence the steward is shown",
        sparql="""
            SELECT DISTINCT ?entity_id ?entity_label ?quote WHERE {
              ?k a campy:Concept ; campy:concept_id ?kind_id .
              ?x campy:INSTANCE_OF ?k ; campy:concept_id ?entity_id ; campy:text_raw ?entity_label .
              OPTIONAL {
                { ?o campy:HAS_OBJECT ?x } UNION { ?o campy:HAS_SUBJECT ?x }
                ?o a campy:Observation ; campy:archived false ; campy:evidence_text ?quote .
              }
            } ORDER BY ?entity_id ?quote
            """,
    ),
    NamedQuery(
        name="steward.narrower_kinds",
        cypher="MATCH (d:Concept)-[:BROADER*]->(k:Concept {concept_id: $kind_id}) RETURN d.concept_id AS kind_id",
        params=("kind_id",),
        mutating=False,
        description="Kinds already narrower than a kind (BROADER+): never offered to it as a parent (they would close a cycle)",
        sparql="""
            SELECT DISTINCT ?narrower_id WHERE {
              ?k a campy:Concept ; campy:concept_id ?kind_id .
              ?d campy:BROADER+ ?k ; campy:concept_id ?narrower_id .
            }
            """,
    ),
    NamedQuery(
        name="steward.recorded_sets",
        cypher="MATCH (a:Concept) RETURN a.concept_id AS child_id",
        params=(),
        mutating=False,
        description="The evidence sets the steward has already argued from, per subject Concept: a set is asked once",
        sparql="""
            SELECT DISTINCT ?child_id ?es WHERE {
              ?r rdf:reifies <<( ?a ?p ?b )>> ; campy:evidence_set ?es .
              FILTER(?p IN (campy:BROADER, campy:INSTANCE_OF))
              ?a campy:concept_id ?child_id .
            }
            """,
    ),
    NamedQuery(
        name="steward.owned_without_kind",
        cypher="MATCH (c:Concept) WHERE c.archived = false RETURN c.concept_id AS entity_id",
        params=(),
        mutating=False,
        description="Entities that are the object of a live `owns` Observation and have no INSTANCE_OF kind (task b)",
        sparql="""
            SELECT DISTINCT ?entity_id ?label WHERE {
              ?o a campy:Observation ; campy:predicate "owns" ; campy:archived false ; campy:HAS_OBJECT ?x .
              FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?newer }
              ?x campy:concept_id ?entity_id ; campy:text_raw ?label .
              FILTER NOT EXISTS { ?x campy:INSTANCE_OF ?anykind }
              FILTER NOT EXISTS { ?x campy:kind_scheme "kind" }
            }
            """,
    ),
    NamedQuery(
        name="steward.entity_turns",
        cypher="MATCH (c:Concept {concept_id: $entity_id}) RETURN c.concept_id AS entity_id",
        params=("entity_id",),
        mutating=False,
        description="The turns that name an entity: user Messages that MENTION it and the evidence turns of "
                    "Observations about it, with the turn's text",
        sparql="""
            SELECT DISTINCT ?message_id ?text WHERE {
              ?x a campy:Concept ; campy:concept_id ?entity_id .
              { ?m campy:MENTIONS ?x }
              UNION
              { ?o campy:HAS_OBJECT ?x ; campy:EVIDENCED_BY ?m }
              UNION
              { ?o campy:HAS_SUBJECT ?x ; campy:EVIDENCED_BY ?m }
              ?m a campy:Message ; campy:message_id ?message_id ; campy:text_raw ?text .
            } ORDER BY ?message_id
            """,
    ),
    NamedQuery(
        name="steward.wordnet_links",
        cypher="MATCH (a:Concept)-[:BROADER]->(b:Concept) RETURN a.concept_id AS child_id",
        params=(),
        mutating=False,
        description="Every live WordNet BROADER link not yet rejected, with its steward status if any (task c)",
        sparql="""
            SELECT ?child_id ?child ?parent_id ?parent ?status WHERE {
              ?a a campy:Concept ; campy:concept_id ?child_id ; campy:text_raw ?child ;
                 campy:kind_scheme "kind" ; campy:archived false ; campy:BROADER ?b .
              ?b campy:concept_id ?parent_id ; campy:text_raw ?parent .
              ?r rdf:reifies <<( ?a campy:BROADER ?b )>> ; campy:link_source "wordnet" .
              OPTIONAL { ?r campy:link_status ?status }
            }
            """,
    ),
    NamedQuery(
        name="steward.recurring",
        cypher="MATCH (a:Concept) RETURN a.concept_id AS child_id",
        params=(),
        mutating=False,
        description="Open steward proposals (a candidate of its own, or a disputed WordNet link) argued from at least "
                    "two different evidence sets and not yet marked recurrent: recorded to strengthen a promotion, never to make one",
        sparql="""
            SELECT ?relation ?lsrc ?child_id ?parent_id (COUNT(DISTINCT ?es) AS ?sets) WHERE {
              ?r rdf:reifies <<( ?a ?p ?b )>> ; campy:link_source ?lsrc ; campy:link_status ?st ; campy:evidence_set ?es .
              FILTER(?p IN (campy:BROADER, campy:INSTANCE_OF))
              FILTER((?lsrc = "steward" && ?st = "candidate") || (?lsrc = "wordnet" && ?st = "disputed"))
              FILTER NOT EXISTS { ?r campy:agreed_by "recurrence" }
              ?a campy:concept_id ?child_id . ?b campy:concept_id ?parent_id .
              BIND(IF(?p = campy:BROADER, "BROADER", "INSTANCE_OF") AS ?relation)
            } GROUP BY ?relation ?lsrc ?child_id ?parent_id HAVING (COUNT(DISTINCT ?es) >= 2)
            """,
    ),
    NamedQuery(
        name="steward.agreed_open",
        cypher="MATCH (a:Concept) RETURN a.concept_id AS child_id",
        params=(),
        mutating=False,
        description="Steward proposals with an independent agreeing source (wordnet, second_model, person; recurrence alone does not count) that are still open (candidate to promote, "
                    "disputed WordNet link to reject)",
        sparql="""
            SELECT DISTINCT ?relation ?lsrc ?child_id ?parent_id WHERE {
              ?r rdf:reifies <<( ?a ?p ?b )>> ; campy:link_source ?lsrc ; campy:link_status ?st ; campy:agreed_by ?any .
              FILTER(?p IN (campy:BROADER, campy:INSTANCE_OF))
              FILTER(?any IN ("wordnet", "second_model", "person"))
              FILTER((?lsrc = "steward" && ?st = "candidate") || (?lsrc = "wordnet" && ?st = "disputed"))
              ?a campy:concept_id ?child_id . ?b campy:concept_id ?parent_id .
              BIND(IF(?p = campy:BROADER, "BROADER", "INSTANCE_OF") AS ?relation)
            }
            """,
    ),
    NamedQuery(
        name="steward.open_candidates",
        cypher="MATCH (a:Concept) RETURN a.concept_id AS child_id",
        params=(),
        mutating=False,
        description="Steward candidates not yet promoted, with labels, to check against WordNet's hypernym closure",
        sparql="""
            SELECT DISTINCT ?relation ?child_id ?child ?parent_id ?parent WHERE {
              ?r rdf:reifies <<( ?a ?p ?b )>> ; campy:link_source "steward" ; campy:link_status "candidate" .
              FILTER(?p IN (campy:BROADER, campy:INSTANCE_OF))
              ?a campy:concept_id ?child_id ; campy:text_raw ?child .
              ?b campy:concept_id ?parent_id ; campy:text_raw ?parent .
              BIND(IF(?p = campy:BROADER, "BROADER", "INSTANCE_OF") AS ?relation)
            }
            """,
    ),
    NamedQuery(
        name="steward.proposals",
        cypher="MATCH (a:Concept) RETURN a.concept_id AS child_id",
        params=(),
        mutating=False,
        description="Every steward decision record: relation, source, status, labels, how many evidence sets, "
                    "which sources agreed, the reason",
        sparql="""
            SELECT ?relation ?source ?status ?child ?parent (COUNT(DISTINCT ?es) AS ?sets)
                   (GROUP_CONCAT(DISTINCT ?by; separator=",") AS ?agreed_by) (SAMPLE(?why) AS ?reason) WHERE {
              ?r rdf:reifies <<( ?a ?p ?b )>> ; campy:link_source ?source ; campy:link_status ?status .
              FILTER(?p IN (campy:BROADER, campy:INSTANCE_OF))
              ?a campy:text_raw ?child . ?b campy:text_raw ?parent .
              OPTIONAL { ?r campy:evidence_set ?es }
              OPTIONAL { ?r campy:agreed_by ?by }
              OPTIONAL { ?r campy:steward_reason ?why }
              BIND(IF(?p = campy:BROADER, "BROADER", "INSTANCE_OF") AS ?relation)
            } GROUP BY ?relation ?source ?status ?child ?parent
            """,
    ),
    NamedQuery(
        name="steward.status_counts",
        cypher="MATCH (a:Concept) RETURN count(a) AS n",
        params=(),
        mutating=False,
        description="Steward records per relation, link source and status (the structure report's steward section)",
        sparql="""
            SELECT ?relation ?source ?status (COUNT(DISTINCT ?r) AS ?n) WHERE {
              ?r rdf:reifies <<( ?a ?p ?b )>> ; campy:link_source ?source ; campy:link_status ?status .
              FILTER(?p IN (campy:BROADER, campy:INSTANCE_OF))
              BIND(IF(?p = campy:BROADER, "BROADER", "INSTANCE_OF") AS ?relation)
            } GROUP BY ?relation ?source ?status
            """,
    ),
]
