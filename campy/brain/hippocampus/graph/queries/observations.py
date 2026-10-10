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
