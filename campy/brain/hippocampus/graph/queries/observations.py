"""
campy/brain/hippocampus/graph/queries/observations.py -- B472 Phase 3a.

Named queries for the `Observation` node table and its two edges
(`EVIDENCED_BY` Observation -> Message, `OBSERVATION_ABOUT` Observation ->
Concept). See backlog/plans/B-472-phase3-observations.md section 3.

Every query carries both a Cypher form (the Kuzu test client / legacy path)
and a `sparql=` form (the Oxigraph runtime). Conventions, once, here:

- `archived` is always written (`false` at create), so the live filter is the
  plain BGP `?o campy:archived false` (docs/rdf-schema-mapping.md 3.4a).
  `superseded_by` is absent on a live row, so liveness there is
  `FILTER NOT EXISTS`.
- A SPARQL param bound to None is `UNDEF`, so an INSERT skips that triple;
  every nullable column is therefore passed as a plain param.
- `$embedding` is never asserted as a triple (FLOAT[384] lives in sqlite-vec,
  keyed by the node's URI -- see vector_indexing._SPECS, which indexes the
  create below when a vector is supplied).
- Edge links are plain-edge MERGEs, so re-linking is a set-semantics no-op.
- Cypher `RETURN` columns are aliased so a row reads the same on both
  backends (`row["observation_id"]`).
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_NODE_BASE = "https://campy.dev/id/Observation/"

# (column, required) -- `required` columns are always written by
# observations.create_observation, so the SPARQL read needs no OPTIONAL.
_READ_COLUMNS: tuple[tuple[str, bool], ...] = (
    ("observation_id", True),
    ("subject_text", True),
    ("subject_id", False),
    ("predicate", True),
    ("object_text", True),
    ("object_id", False),
    ("event_text", False),
    ("time_text", False),
    ("time_start", False),
    ("time_end", False),
    ("time_precision", False),
    ("speaker", False),
    ("polarity", True),
    ("confidence", True),
    ("confidence_low", True),
    ("extraction_method", True),
    ("rule_version", False),
    ("evidence_ref", True),
    ("evidence_start", True),
    ("evidence_end", True),
    ("evidence_text", True),
    ("text_raw", True),
    ("source", False),
    ("source_version", False),
    ("observed_at", False),
    ("superseded_by", False),
    ("superseded_at", False),
    ("authority", False),
    ("content_hash", False),
    ("created_at", True),
    ("last_accessed_at", False),
    ("archived", True),
)

_CYPHER_RETURN = ",\n            ".join(f"o.{c} AS {c}" for c, _ in _READ_COLUMNS)
_SPARQL_SELECT = " ".join(f"?{c}" for c, _ in _READ_COLUMNS)
_SPARQL_REQUIRED = " ;\n                 ".join(
    f"campy:{c} ?{c}" for c, req in _READ_COLUMNS if req
)
_SPARQL_OPTIONAL = "\n                ".join(
    f"OPTIONAL {{ ?o campy:{c} ?{c} }}" for c, req in _READ_COLUMNS if not req
)


def _read_sparql(extra_patterns: str = "", tail: str = "", lead: str = "") -> str:
    """SELECT of every read column. `lead` adds predicate-object pairs to the
    Observation subject block (each must end with ` ;`); `extra_patterns` are
    whole graph patterns joined in before it."""
    return f"""
            SELECT {_SPARQL_SELECT} WHERE {{
                {extra_patterns}
                ?o a campy:Observation ;
                 {lead}
                 {_SPARQL_REQUIRED} .
                {_SPARQL_OPTIONAL}
            }}
            {tail}
            """


# B522: the Concepts an Observation names (OBSERVATION_ABOUT) that could be its object: not the
# subject, not a kind, label of 3+ characters appearing as whole words in object_text, and the
# Observation has neither an object edge nor an object_id. The backfill links one only when it is
# the single candidate (a GROUP BY ... HAVING count), never by taking the first of several.
_OBJECT_CANDIDATES = r"""
              ?o a campy:Observation ; campy:object_text ?object_text ; campy:OBSERVATION_ABOUT ?cand .
              FILTER NOT EXISTS { ?o campy:HAS_OBJECT ?had }
              FILTER NOT EXISTS { ?o campy:object_id ?has_id }
              ?cand a campy:Concept ; campy:concept_id ?cand_id ; campy:text_raw ?label .
              FILTER NOT EXISTS { ?cand campy:kind_scheme "kind" }
              FILTER NOT EXISTS { ?o campy:subject_id ?cand_id }
              FILTER(STRLEN(?label) >= 3)
              FILTER(REGEX(?object_text,
                           CONCAT("(^|[^[:alnum:]])", REPLACE(?label, "([.*+?^${}()|\\[\\]\\\\])", "\\\\$1"),
                                  "($|[^[:alnum:]])"), "i"))
"""


OBSERVATION_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="observations.create_observation",
        cypher="""
        CREATE (o:Observation {
            observation_id:    $observation_id,
            subject_text:      $subject_text,
            subject_id:        $subject_id,
            predicate:         $predicate,
            object_text:       $object_text,
            object_id:         $object_id,
            event_text:        $event_text,
            time_text:         $time_text,
            time_start:        $time_start,
            time_end:          $time_end,
            time_precision:    $time_precision,
            speaker:           $speaker,
            polarity:          $polarity,
            confidence:        $confidence,
            confidence_low:    $confidence_low,
            extraction_method: $extraction_method,
            rule_version:      $rule_version,
            evidence_start:    $evidence_start,
            evidence_end:      $evidence_end,
            evidence_text:     $evidence_text,
            text_raw:          $text_raw,
            embedding:         $embedding,
            embedding_model:   $embedding_model,
            embedding_dim:     $embedding_dim,
            last_accessed_at:  $now,
            archived:          false,
            flagged_for_review: false,
            created_at:        $now,
            source:            $source,
            source_version:    $rule_version,
            observed_at:       $observed_at,
            evidence_ref:      $evidence_ref,
            authority:         'earned',
            content_hash:      $content_hash
        })
        """,
        params=(
            "observation_id", "subject_text", "subject_id", "predicate",
            "object_text", "object_id", "event_text", "time_text",
            "time_start", "time_end", "time_precision", "speaker", "polarity",
            "confidence", "confidence_low", "extraction_method", "rule_version",
            "evidence_start", "evidence_end", "evidence_text", "text_raw",
            "embedding", "embedding_model", "embedding_dim", "source",
            "observed_at", "evidence_ref", "content_hash", "now",
        ),
        mutating=True,
        description="Create an Observation node (use observations.record_observation, which validates grounding)",
        sparql=f"""
            INSERT {{
              ?o a campy:Observation ;
                 campy:observation_id ?observation_id ;
                 campy:subject_text ?subject_text ;
                 campy:subject_id ?subject_id ;
                 campy:predicate ?predicate ;
                 campy:object_text ?object_text ;
                 campy:object_id ?object_id ;
                 campy:event_text ?event_text ;
                 campy:time_text ?time_text ;
                 campy:time_start ?time_start ;
                 campy:time_end ?time_end ;
                 campy:time_precision ?time_precision ;
                 campy:speaker ?speaker ;
                 campy:polarity ?polarity ;
                 campy:confidence ?confidence ;
                 campy:confidence_low ?confidence_low ;
                 campy:extraction_method ?extraction_method ;
                 campy:rule_version ?rule_version ;
                 campy:evidence_start ?evidence_start ;
                 campy:evidence_end ?evidence_end ;
                 campy:evidence_text ?evidence_text ;
                 campy:text_raw ?text_raw ;
                 campy:embedding_model ?embedding_model ;
                 campy:embedding_dim ?embedding_dim ;
                 campy:last_accessed_at ?now ;
                 campy:archived false ;
                 campy:flagged_for_review false ;
                 campy:created_at ?now ;
                 campy:source ?source ;
                 campy:source_version ?rule_version ;
                 campy:observed_at ?observed_at ;
                 campy:evidence_ref ?evidence_ref ;
                 campy:authority "earned" ;
                 campy:content_hash ?content_hash .
            }}
            WHERE {{
              BIND(IRI(CONCAT("{_NODE_BASE}", ENCODE_FOR_URI(STR(?observation_id)))) AS ?o)
            }}
            """,
    ),
    NamedQuery(
        name="observations.link_evidenced_by",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}),
              (m:Message {message_id: $mid})
        MERGE (o)-[:EVIDENCED_BY]->(m)
        """,
        params=("oid", "mid"),
        mutating=True,
        description="Link an Observation to a Message that supports it (EVIDENCED_BY, plain, idempotent)",
        sparql="""
            INSERT { ?o campy:EVIDENCED_BY ?m . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              ?m a campy:Message ; campy:message_id ?mid .
            }
            """,
    ),
    NamedQuery(
        name="observations.link_about_concept",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}),
              (c:Concept {concept_id: $cid})
        MERGE (o)-[:OBSERVATION_ABOUT]->(c)
        """,
        params=("oid", "cid"),
        mutating=True,
        description="Link an Observation to a subject/object Concept (OBSERVATION_ABOUT, plain, idempotent)",
        sparql="""
            INSERT { ?o campy:OBSERVATION_ABOUT ?c . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              ?c a campy:Concept ; campy:concept_id ?cid .
            }
            """,
    ),
    # --- B522: subject / object roles --------------------------------------------------
    NamedQuery(
        name="observations.link_subject",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}),
              (c:Concept {concept_id: $cid})
        WHERE NOT (o)-[:HAS_SUBJECT]->()
        MERGE (o)-[:HAS_SUBJECT]->(c)
        """,
        params=("oid", "cid"),
        mutating=True,
        description="Record the Concept that is an Observation's subject (HAS_SUBJECT; at most one, first wins, idempotent)",
        sparql="""
            INSERT { ?o campy:HAS_SUBJECT ?c . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              ?c a campy:Concept ; campy:concept_id ?cid .
              FILTER NOT EXISTS { ?o campy:HAS_SUBJECT ?other }
            }
            """,
    ),
    NamedQuery(
        name="observations.link_object",
        cypher="""
        MATCH (o:Observation {observation_id: $oid}),
              (c:Concept {concept_id: $cid})
        WHERE NOT (o)-[:HAS_OBJECT]->()
        MERGE (o)-[:HAS_OBJECT]->(c)
        """,
        params=("oid", "cid"),
        mutating=True,
        description="Record the Concept that is an Observation's object (HAS_OBJECT; at most one, first wins, idempotent)",
        sparql="""
            INSERT { ?o campy:HAS_OBJECT ?c . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              ?c a campy:Concept ; campy:concept_id ?cid .
              FILTER NOT EXISTS { ?o campy:HAS_OBJECT ?other }
            }
            """,
    ),
    NamedQuery(
        name="observations.set_object_id_from_role",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})-[:HAS_OBJECT]->(c:Concept)
        WHERE o.object_id IS NULL
        SET o.object_id = c.concept_id
        """,
        params=("oid",),
        mutating=True,
        description="Fill an empty object_id literal from the HAS_OBJECT Concept (oid None = every Observation)",
        sparql="""
            INSERT { ?o campy:object_id ?cid . }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid ; campy:HAS_OBJECT ?c .
              ?c campy:concept_id ?cid .
              FILTER NOT EXISTS { ?o campy:object_id ?existing }
            }
            """,
    ),
    NamedQuery(
        name="observations.backfill_subject_roles",
        cypher="""
        MATCH (o:Observation), (c:Concept {concept_id: o.subject_id})
        WHERE NOT (o)-[:HAS_SUBJECT]->()
        MERGE (o)-[:HAS_SUBJECT]->(c)
        """,
        params=(),
        mutating=True,
        description="HAS_SUBJECT for every Observation whose subject_id names a Concept and has no subject edge yet",
        sparql="""
            INSERT { ?o campy:HAS_SUBJECT ?c . }
            WHERE {
              ?o a campy:Observation ; campy:subject_id ?sid .
              ?c a campy:Concept ; campy:concept_id ?sid .
              FILTER NOT EXISTS { ?o campy:HAS_SUBJECT ?other }
            }
            """,
    ),
    NamedQuery(
        name="observations.backfill_object_roles_from_id",
        cypher="""
        MATCH (o:Observation), (c:Concept {concept_id: o.object_id})
        WHERE NOT (o)-[:HAS_OBJECT]->()
        MERGE (o)-[:HAS_OBJECT]->(c)
        """,
        params=(),
        mutating=True,
        description="HAS_OBJECT for every Observation whose object_id names a Concept and has no object edge yet",
        sparql="""
            INSERT { ?o campy:HAS_OBJECT ?c . }
            WHERE {
              ?o a campy:Observation ; campy:object_id ?oid .
              ?c a campy:Concept ; campy:concept_id ?oid .
              FILTER NOT EXISTS { ?o campy:HAS_OBJECT ?other }
            }
            """,
    ),
    NamedQuery(
        name="observations.backfill_object_roles_from_text",
        cypher="""
        MATCH (o:Observation)-[:OBSERVATION_ABOUT]->(c:Concept)
        WHERE NOT (o)-[:HAS_OBJECT]->() AND o.object_id IS NULL
          AND c.concept_id <> o.subject_id AND toLower(o.object_text) CONTAINS toLower(c.text_raw)
        WITH o, collect(DISTINCT c) AS cs WHERE size(cs) = 1
        UNWIND cs AS c
        MERGE (o)-[:HAS_OBJECT]->(c)
        """,
        params=(),
        mutating=True,
        description=("HAS_OBJECT for an Observation with no object edge and no object_id when exactly one "
                     "non-subject, non-kind OBSERVATION_ABOUT Concept's label appears in its object_text"),
        sparql=f"""
            INSERT {{ ?o campy:HAS_OBJECT ?c . }}
            WHERE {{
              {{ SELECT ?o (SAMPLE(?cand) AS ?c) WHERE {{ {_OBJECT_CANDIDATES} }}
                 GROUP BY ?o HAVING (COUNT(DISTINCT ?cand) = 1) }}
            }}
            """,
    ),
    NamedQuery(
        name="observations.ambiguous_object_candidates",
        cypher="""
        MATCH (o:Observation)-[:OBSERVATION_ABOUT]->(c:Concept)
        WHERE NOT (o)-[:HAS_OBJECT]->() AND o.object_id IS NULL
          AND c.concept_id <> o.subject_id AND toLower(o.object_text) CONTAINS toLower(c.text_raw)
        WITH o, count(DISTINCT c) AS n WHERE n > 1
        RETURN o.observation_id AS observation_id, n
        """,
        params=(),
        mutating=False,
        description="Observations with no object edge where more than one OBSERVATION_ABOUT Concept's label fits the object_text",
        sparql=f"""
            SELECT ?observation_id (COUNT(DISTINCT ?cand) AS ?n) WHERE {{
              {_OBJECT_CANDIDATES}
              ?o campy:observation_id ?observation_id .
            }}
            GROUP BY ?observation_id HAVING (COUNT(DISTINCT ?cand) > 1)
            """,
    ),
    NamedQuery(
        name="observations.role_link_counts",
        cypher="""
        MATCH (o:Observation)
        OPTIONAL MATCH (o)-[s:HAS_SUBJECT]->()
        OPTIONAL MATCH (o)-[b:HAS_OBJECT]->()
        RETURN count(DISTINCT o) AS observations, count(DISTINCT s) AS with_subject,
               count(DISTINCT b) AS with_object
        """,
        params=(),
        mutating=False,
        description="How many Observations exist, and how many carry a HAS_SUBJECT / HAS_OBJECT edge",
        sparql="""
            SELECT (COUNT(DISTINCT ?o) AS ?observations)
                   (COUNT(DISTINCT ?hs) AS ?with_subject)
                   (COUNT(DISTINCT ?ho) AS ?with_object) WHERE {
              ?o a campy:Observation .
              OPTIONAL { ?o campy:HAS_SUBJECT ?hs_c . BIND(?o AS ?hs) }
              OPTIONAL { ?o campy:HAS_OBJECT ?ho_c . BIND(?o AS ?ho) }
            }
            """,
    ),
    NamedQuery(
        name="observations.objects_of_subject",
        cypher="""
        MATCH (o:Observation)-[:HAS_SUBJECT]->(s:Concept {concept_id: $sid}),
              (o)-[:HAS_OBJECT]->(obj:Concept)
        WHERE o.archived = false AND ($predicate IS NULL OR o.predicate = $predicate)
        OPTIONAL MATCH (obj)-[:INSTANCE_OF]->(:Concept)-[:BROADER*0..]->(k:Concept)
        OPTIONAL MATCH (o)-[:EVIDENCED_BY]->(m:Message)
        RETURN o.observation_id AS observation_id, o.predicate AS predicate,
               obj.concept_id AS object_id, obj.text_raw AS object_label,
               collect(DISTINCT k.text_raw) AS kinds, m.message_id AS evidence_message_id,
               m.occurred_at AS occurred_at
        ORDER BY occurred_at, observation_id
        """,
        params=("sid", "predicate"),
        mutating=False,
        description=("What a subject Concept has as objects: object Concept, label, kinds (INSTANCE_OF then "
                     "BROADER*), the Observation's predicate, evidence message and date. predicate None = any."),
        sparql=r"""
            SELECT ?observation_id ?predicate ?object_id ?object_label
                   (GROUP_CONCAT(DISTINCT ?kind_label; separator="|") AS ?kinds)
                   ?evidence_message_id ?occurred_at
            WHERE {
              ?s a campy:Concept ; campy:concept_id ?sid .
              ?o a campy:Observation ; campy:observation_id ?observation_id ;
                 campy:predicate ?predicate ; campy:archived false ;
                 campy:HAS_SUBJECT ?s ; campy:HAS_OBJECT ?obj .
              FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?newer }
              ?obj campy:concept_id ?object_id ; campy:text_raw ?object_label .
              OPTIONAL { ?obj (campy:INSTANCE_OF|campy:IS_A)/campy:BROADER* ?kind . ?kind campy:text_raw ?kind_label }
              OPTIONAL { ?o campy:EVIDENCED_BY ?m . ?m campy:message_id ?evidence_message_id
                         OPTIONAL { ?m campy:occurred_at ?occurred_at } }
            }
            GROUP BY ?observation_id ?predicate ?object_id ?object_label ?evidence_message_id ?occurred_at
            ORDER BY ?occurred_at ?observation_id
            """,
    ),
    # --- B523: the closed set of entities a turn can own -------------------------------
    NamedQuery(
        name="observations.message_concepts",
        cypher="""
        MATCH (m:Message {message_id: $mid})-[:MENTIONS]->(c:Concept)
        WHERE c.archived = false AND c.kind_scheme IS NULL
        RETURN DISTINCT c.concept_id AS concept_id, c.text_raw AS label
        UNION
        MATCH (o:Observation)-[:EVIDENCED_BY]->(m:Message {message_id: $mid}), (o)-[:OBSERVATION_ABOUT]->(c:Concept)
        WHERE c.archived = false AND c.kind_scheme IS NULL
        RETURN DISTINCT c.concept_id AS concept_id, c.text_raw AS label
        """,
        params=("mid",),
        mutating=False,
        description=("Entity Concepts (not kinds) a Message is linked to: MENTIONS from the Message, or "
                     "OBSERVATION_ABOUT from an Observation it evidences. The ownership rule's closed set."),
        sparql="""
            SELECT DISTINCT ?concept_id ?label WHERE {
              ?m a campy:Message ; campy:message_id ?mid .
              { ?m campy:MENTIONS ?c }
              UNION
              { ?o campy:EVIDENCED_BY ?m ; campy:OBSERVATION_ABOUT ?c }
              ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?label .
              FILTER NOT EXISTS { ?c campy:archived true }
              FILTER NOT EXISTS { ?c campy:kind_scheme "kind" }
            }
            """,
    ),
    NamedQuery(
        name="observations.touch_observation",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})
        SET o.last_accessed_at = $now
        """,
        params=("oid", "now"),
        mutating=True,
        description="Bump an Observation's last_accessed_at (a duplicate draft re-asserted it)",
        sparql="""
            DELETE { ?o campy:last_accessed_at ?old }
            INSERT { ?o campy:last_accessed_at ?now }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              OPTIONAL { ?o campy:last_accessed_at ?old }
            }
            """,
    ),
    NamedQuery(
        name="observations.find_live_by_hash",
        cypher="""
        MATCH (o:Observation)
        WHERE o.content_hash = $key AND o.archived = false
              AND o.superseded_by IS NULL
        RETURN o.observation_id AS observation_id
        LIMIT 1
        """,
        params=("key",),
        mutating=False,
        description="Find a live (unarchived, unsuperseded) Observation by its content hash",
        sparql="""
            SELECT ?observation_id WHERE {
              ?o a campy:Observation ;
                 campy:observation_id ?observation_id ;
                 campy:content_hash ?key ;
                 campy:archived false .
              FILTER NOT EXISTS { ?o campy:superseded_by ?sup }
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="observations.get_message",
        cypher="""
        MATCH (m:Message {message_id: $mid})
        RETURN m.message_id AS message_id, m.text_raw AS text_raw,
               m.role AS role, m.speaker AS speaker,
               m.occurred_at AS occurred_at, m.created_at AS created_at,
               m.archived AS archived
        LIMIT 1
        """,
        params=("mid",),
        mutating=False,
        description="Read the fields of an evidence Message that grounding validation needs",
        sparql="""
            SELECT ?message_id ?text_raw ?role ?speaker ?occurred_at ?created_at ?archived WHERE {
              ?m a campy:Message ;
                 campy:message_id ?mid ;
                 campy:message_id ?message_id ;
                 campy:text_raw ?text_raw .
              OPTIONAL { ?m campy:role ?role }
              OPTIONAL { ?m campy:speaker ?speaker }
              OPTIONAL { ?m campy:occurred_at ?occurred_at }
              OPTIONAL { ?m campy:created_at ?created_at }
              OPTIONAL { ?m campy:archived ?archived }
            }
            ORDER BY DESC(?archived)  # B488: a true value must win LIMIT 1
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="observations.get_concept",
        cypher="""
        MATCH (c:Concept {concept_id: $cid})
        RETURN c.concept_id AS concept_id, c.archived AS archived
        LIMIT 1
        """,
        params=("cid",),
        mutating=False,
        description="Check that a Concept id handed to the Observation write API exists",
        sparql="""
            SELECT ?concept_id ?archived WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid ; campy:concept_id ?concept_id .
              OPTIONAL { ?c campy:archived ?archived }
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="observations.get_observation",
        cypher=f"""
        MATCH (o:Observation {{observation_id: $oid}})
        RETURN {_CYPHER_RETURN}
        LIMIT 1
        """,
        params=("oid",),
        mutating=False,
        description="Read one Observation by id (live or not)",
        sparql=_read_sparql(tail="LIMIT 1", lead="campy:observation_id ?oid ;"),
    ),
    NamedQuery(
        name="observations.for_message",
        cypher=f"""
        MATCH (o:Observation)-[:EVIDENCED_BY]->(m:Message {{message_id: $mid}})
        WHERE o.archived = false
        RETURN {_CYPHER_RETURN}
        ORDER BY o.evidence_start, o.created_at
        """,
        params=("mid",),
        mutating=False,
        description="Live Observations a Message supports, in turn order",
        sparql=_read_sparql(
            "?o campy:EVIDENCED_BY ?m . ?m a campy:Message ; campy:message_id ?mid .",
            "ORDER BY ?evidence_start ?created_at",
            lead="campy:archived false ;",
        ),
    ),
    NamedQuery(
        name="observations.for_concept",
        cypher=f"""
        MATCH (o:Observation)-[:OBSERVATION_ABOUT]->(c:Concept {{concept_id: $cid}})
        WHERE o.archived = false
        RETURN {_CYPHER_RETURN}
        ORDER BY o.created_at
        """,
        params=("cid",),
        mutating=False,
        description="Live Observations about a Concept (as subject or entity object), oldest first",
        sparql=_read_sparql(
            "?o campy:OBSERVATION_ABOUT ?c . ?c a campy:Concept ; campy:concept_id ?cid .",
            "ORDER BY ?created_at",
            lead="campy:archived false ;",
        ),
    ),
    NamedQuery(
        name="observations.list_untimed",
        cypher="""
        MATCH (o:Observation)
        WHERE o.archived = false AND o.time_text IS NOT NULL AND o.time_start IS NULL
        RETURN o.observation_id AS observation_id, o.time_text AS time_text,
               o.observed_at AS observed_at
        ORDER BY o.observation_id
        """,
        params=(),
        mutating=False,
        description="Live Observations with a time phrase but no resolved date (B484 backfill candidates)",
        sparql="""
            SELECT ?observation_id ?time_text ?observed_at WHERE {
              ?o a campy:Observation ;
                 campy:observation_id ?observation_id ;
                 campy:archived false ;
                 campy:time_text ?time_text .
              OPTIONAL { ?o campy:observed_at ?observed_at }
              FILTER NOT EXISTS { ?o campy:time_start ?ts }
            }
            ORDER BY ?observation_id
            """,
    ),
    NamedQuery(
        name="observations.set_time",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})
        SET o.time_start = $time_start, o.time_end = $time_end,
            o.time_precision = $time_precision
        """,
        params=("oid", "time_start", "time_end", "time_precision"),
        mutating=True,
        description="Set the resolved date range of an Observation (B484; time_text is never changed)",
        sparql="""
            DELETE { ?o campy:time_start ?os ; campy:time_end ?oe ; campy:time_precision ?op }
            INSERT { ?o campy:time_start ?time_start ; campy:time_end ?time_end ;
                        campy:time_precision ?time_precision }
            WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid .
              OPTIONAL { ?o campy:time_start ?os }
              OPTIONAL { ?o campy:time_end ?oe }
              OPTIONAL { ?o campy:time_precision ?op }
            }
            """,
    ),
    NamedQuery(
        name="observations.live_attributes_by_subject_id",
        cypher=f"""
        MATCH (o:Observation)
        WHERE o.predicate = 'has_attribute' AND o.polarity = 'asserted'
              AND o.archived = false AND o.superseded_by IS NULL
              AND o.subject_id = $sid
        RETURN {_CYPHER_RETURN}
        """,
        params=("sid",),
        mutating=False,
        description="B499: live asserted has_attribute Observations about one subject Concept",
        sparql=_read_sparql(
            "FILTER NOT EXISTS { ?o campy:superseded_by ?sup }",
            lead='campy:predicate "has_attribute" ; campy:polarity "asserted" ; '
                 'campy:archived false ; campy:subject_id ?sid ;',
        ),
    ),
    NamedQuery(
        name="observations.live_attributes_by_subject_text",
        cypher=f"""
        MATCH (o:Observation)
        WHERE o.predicate = 'has_attribute' AND o.polarity = 'asserted'
              AND o.archived = false AND o.superseded_by IS NULL
              AND o.subject_text = $stext
        RETURN {_CYPHER_RETURN}
        """,
        params=("stext",),
        mutating=False,
        description="B499: live asserted has_attribute Observations by exact subject text "
                    "(the caller filters speaker and attribute name)",
        sparql=_read_sparql(
            "FILTER NOT EXISTS { ?o campy:superseded_by ?sup }",
            lead='campy:predicate "has_attribute" ; campy:polarity "asserted" ; '
                 'campy:archived false ; campy:subject_text ?stext ;',
        ),
    ),
    NamedQuery(
        name="observations.mark_superseded",
        cypher="""
        MATCH (n:Observation {observation_id: $oid})
        SET n.superseded_by = $by, n.superseded_at = $at, n.supersession_reason = $reason
        """,
        params=("oid", "by", "at", "reason"),
        mutating=True,
        description="B499: mark an Observation superseded (same three columns as provenance.mark_superseded_*)",
        sparql="""
            DELETE {
                ?n campy:superseded_by ?o1 . ?n campy:superseded_at ?o2 .
                ?n campy:supersession_reason ?o3 . ?n prov:invalidatedAtTime ?o4 .
            }
            INSERT {
                ?n campy:superseded_by ?by . ?n campy:superseded_at ?at .
                ?n campy:supersession_reason ?reason . ?n prov:invalidatedAtTime ?at .
            }
            WHERE {
                ?n a campy:Observation ; campy:observation_id ?oid .
                OPTIONAL { ?n campy:superseded_by ?o1 }
                OPTIONAL { ?n campy:superseded_at ?o2 }
                OPTIONAL { ?n campy:supersession_reason ?o3 }
                OPTIONAL { ?n prov:invalidatedAtTime ?o4 }
            }
            """,
    ),
    NamedQuery(
        name="observations.link_deprecated_by",
        cypher="""
        MATCH (a:Observation {observation_id: $oid}), (b:Observation {observation_id: $by})
        MERGE (a)-[:DEPRECATED_BY]->(b)
        """,
        params=("oid", "by"),
        mutating=True,
        description="B499: (older)-[:DEPRECATED_BY]->(newer) between two Observations",
        sparql="""
            INSERT { ?old campy:DEPRECATED_BY ?new . ?new prov:wasRevisionOf ?old . }
            WHERE {
                ?old a campy:Observation ; campy:observation_id ?oid .
                ?new a campy:Observation ; campy:observation_id ?by .
            }
            """,
    ),
    NamedQuery(
        name="observations.evidence_messages",
        cypher="""
        MATCH (o:Observation {observation_id: $oid})-[:EVIDENCED_BY]->(m:Message)
        RETURN m.message_id AS message_id
        ORDER BY m.created_at
        """,
        params=("oid",),
        mutating=False,
        description="Ids of every Message that supports an Observation",
        sparql="""
            SELECT ?message_id WHERE {
              ?o a campy:Observation ; campy:observation_id ?oid ;
                 campy:EVIDENCED_BY ?m .
              ?m campy:message_id ?message_id .
              OPTIONAL { ?m campy:created_at ?created_at }
            }
            ORDER BY ?created_at ?message_id
            """,
    ),
)
