"""
campy/brain/hippocampus/graph/queries/capability.py — B317 named-query slice.

Two families of `NamedQuery` objects, both operating on the projected
capability-graph subset defined in schema.py (`FactEntity` + the ten
`FACT_*` rel tables — see the "B317" comment block above `NODE_TABLES`):

  1. Ingest support (used by `campy/brain/hippocampus/facts.py`'s
     `ingest_entities()` / `ingest_facts()`): entity upsert, and per-predicate
     find/create/supersede for the ten `FACT_*` edge tables. Kùzu rel-table
     Cypher requires a *static* relationship type in the pattern
     (`-[:FACT_INVOKES]->`, never a variable), so these are generated once
     per predicate at import time rather than written as one parameterized
     query — each individual `NamedQuery.cypher` is still a fixed string
     (no runtime interpolation; the predicate is baked in when this module
     is imported, not from caller-supplied data), so this doesn't violate
     B314's "all variable input goes through $param" rule.

  2. The five customer questions (B317's Task 3) — `capability.permitted_paths`
     (Q1), `capability.explain_path` (Q2), `capability.impact_of` (Q3),
     `capability.lineage_of` (Q4), `capability.reuse_candidates` (Q5). Every
     one carries an explicit hop bound (`*1..5`, `*1..4`, `*1..6` — never a
     bare `*`) and excludes superseded rows by default via an
     `include_superseded` parameter every query declares.

Kùzu 0.11.3 quirks this file works around (empirically probed against the
pinned version — see the B317 implementation notes in
docs/ARCHITECTURE.md):

  - A `$parameter` referenced *directly* inside `ALL(x IN list WHERE ...)` /
    `ANY(...)` crashes the binder (`KU_UNREACHABLE` assertion). Fix: bind the
    parameter to a plain variable first via `WITH $param AS local_name`, then
    reference `local_name` inside the predicate — that works fine.
  - `collect(DISTINCT expr)` returns `NULL` (not `[]`) when every collected
    value was `NULL` (e.g. an OPTIONAL MATCH that matched nodes but never
    the property being collected). Every query that later runs
    `ALL(x IN collected_list WHERE ...)` guards with
    `collected_list IS NULL OR ALL(...)` — omitting the guard makes the
    predicate evaluate to `NULL` (falsy) and silently drops rows that should
    have passed.
  - `UNWIND nodes(p) AS pn` produces path-node values that cannot be used as
    a pattern position (`(pn)-[...]->...` raises "Cannot bind pn as node
    pattern"). Fix: match a fresh node variable and join on
    `x.entity_id = pn.entity_id` instead.
  - List comprehensions (`[x IN list WHERE ...]`) are not supported by the
    parser at all (openCypher `ALL`/`ANY`/`collect` are; bracket
    comprehensions are Neo4j-only). Use `UNWIND` + `WITH ... WHERE` or
    `ALL`/`ANY` instead.

Naming convention: `capability.<verb>_<subject>` for the five questions;
`capability.<verb>_edge__<predicate>` / `capability.upsert_entity_*` for
ingest support.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery
from campy.brain.hippocampus.schema import FACT_PREDICATES

# ---------------------------------------------------------------------------
# Ingest support — entity upsert
# ---------------------------------------------------------------------------

_ENTITY_STUB_QUERY = NamedQuery(
    name="capability.upsert_entity_stub",
    cypher="""
        MERGE (n:FactEntity {entity_id: $entity_id})
        ON CREATE SET
            n.authority = 'projected',
            n.source = $source,
            n.source_version = $source_version,
            n.observed_at = timestamp($observed_at),
            n.evidence_ref = $evidence_ref,
            n.created_at = timestamp($created_at)
        """,
    params=("entity_id", "source", "source_version", "observed_at", "evidence_ref", "created_at"),
    mutating=True,
    description=(
        "Upsert a bare FactEntity stub (entity_id + provenance/authority only) as an edge "
        "endpoint — ingest_facts() calls this for every subject_id/object_id it sees; a "
        "no-op if the entity already carries fuller attributes from ingest_entities()."
    ),
)

_ENTITY_SUPERSEDE_QUERY = NamedQuery(
    name="capability.supersede_entity",
    cypher="""
        MATCH (n:FactEntity {entity_id: $entity_id})
        WHERE n.superseded_by IS NULL
        SET n.superseded_by = $superseded_by,
            n.superseded_at = timestamp($at),
            n.supersession_reason = $reason
        """,
    params=("entity_id", "superseded_by", "at", "reason"),
    mutating=True,
    description=(
        "Mark a FactEntity node itself as superseded/retired (distinct from "
        "capability.supersede_edge__<predicate>, which supersedes an EDGE). Used to model "
        "an entity the source system has fully retired — e.g. a capability whose "
        "dependency chain is no longer satisfiable, per Q5's reuse-candidate check."
    ),
)

_ENTITY_FULL_QUERY = NamedQuery(
    name="capability.upsert_entity_full",
    cypher="""
        MERGE (n:FactEntity {entity_id: $entity_id})
        ON CREATE SET
            n.entity_type = $entity_type,
            n.label = $label,
            n.properties = $properties,
            n.embedding = $embedding,
            n.embedding_model = $embedding_model,
            n.embedding_dim = $embedding_dim,
            n.authority = 'projected',
            n.source = $source,
            n.source_version = $source_version,
            n.observed_at = timestamp($observed_at),
            n.evidence_ref = $evidence_ref,
            n.created_at = timestamp($created_at)
        ON MATCH SET
            n.entity_type = $entity_type,
            n.label = $label,
            n.properties = $properties,
            n.embedding = $embedding,
            n.embedding_model = $embedding_model,
            n.embedding_dim = $embedding_dim,
            n.authority = 'projected',
            n.source = $source,
            n.source_version = $source_version,
            n.observed_at = timestamp($observed_at),
            n.evidence_ref = $evidence_ref
        """,
    params=(
        "entity_id", "entity_type", "label", "properties", "embedding",
        "embedding_model", "embedding_dim", "source", "source_version",
        "observed_at", "evidence_ref", "created_at",
    ),
    mutating=True,
    description=(
        "Upsert a fully-attributed FactEntity (entity_type/label/embedding/properties) — "
        "ingest_entities()'s single write path. Idempotent: re-running with the same "
        "entity_id updates attributes in place rather than duplicating (FactEntity has no "
        "separate entity-level supersession chain in this card; only FACT_* edges do)."
    ),
)

# ---------------------------------------------------------------------------
# Ingest support — per-predicate edge find / create / supersede
#
# One of each per FACT_PREDICATES entry, generated here rather than written
# out ten times by hand. Kùzu requires a static rel type in the MATCH/CREATE
# pattern, so the predicate's rel-table name is baked into the Cypher text at
# *import time* (a fixed, closed, ten-entry vocabulary — never caller-supplied
# interpolation) — every other piece of variable input still goes through
# `$param` placeholders.
# ---------------------------------------------------------------------------

_EDGE_QUERIES: list[NamedQuery] = []
for _predicate, _rel_table in FACT_PREDICATES.items():
    _key = _predicate.lower()

    _EDGE_QUERIES.append(
        NamedQuery(
            name=f"capability.find_live_edge__{_key}",
            cypher=f"""
                MATCH (:FactEntity {{entity_id: $subject_id}})
                      -[r:{_rel_table}]->
                      (:FactEntity {{entity_id: $object_id}})
                WHERE r.superseded_by IS NULL
                RETURN r.source_version AS source_version
                LIMIT 1
                """,
            params=("subject_id", "object_id"),
            mutating=False,
            description=f"Find the live (non-superseded) {_rel_table} edge between two entities, if any.",
        )
    )

    _EDGE_QUERIES.append(
        NamedQuery(
            name=f"capability.create_edge__{_key}",
            cypher=f"""
                MATCH (a:FactEntity {{entity_id: $subject_id}}), (b:FactEntity {{entity_id: $object_id}})
                CREATE (a)-[:{_rel_table} {{
                    version: $version,
                    access_mode: $access_mode,
                    confidence: $confidence,
                    run_id: $run_id,
                    evidence_ref: $evidence_ref,
                    source: $source,
                    source_version: $source_version,
                    observed_at: timestamp($observed_at),
                    authority: $authority
                }}]->(b)
                """,
            params=(
                "subject_id", "object_id", "version", "access_mode", "confidence",
                "run_id", "evidence_ref", "source", "source_version", "observed_at", "authority",
            ),
            mutating=True,
            description=f"Create a new {_rel_table} edge carrying the full LPG property set.",
        )
    )

    _EDGE_QUERIES.append(
        NamedQuery(
            name=f"capability.supersede_edge__{_key}",
            cypher=f"""
                MATCH (:FactEntity {{entity_id: $subject_id}})
                      -[r:{_rel_table}]->
                      (:FactEntity {{entity_id: $object_id}})
                WHERE r.superseded_by IS NULL
                SET r.superseded_by = $superseded_by,
                    r.superseded_at = timestamp($at),
                    r.supersession_reason = $reason
                """,
            params=("subject_id", "object_id", "superseded_by", "at", "reason"),
            mutating=True,
            description=(
                f"Mark the live {_rel_table} edge between two entities as superseded "
                "(B312-style: sets superseded_by/at/reason on the OLD edge rather than "
                "overwriting it — the row stays retrievable with include_superseded=True). "
                "Deviates from provenance.mark_superseded()'s exact signature because that "
                "function is node-oriented (matches on a table's primary-key column); a rel "
                "table has no such column, so `superseded_by` here holds the replacing "
                "source_version string rather than a node id."
            ),
        )
    )


# ---------------------------------------------------------------------------
# Task 3 — the five customer questions
# ---------------------------------------------------------------------------

_Q1_PERMITTED_PATHS = NamedQuery(
    name="capability.permitted_paths",
    cypher="""
        MATCH p = (entry:FactEntity {entity_id: $entry_id})
                  -[:FACT_INVOKES|FACT_REQUIRES*1..5]->
                  (dest:FactEntity)
        WHERE $include_superseded OR ALL(r IN relationships(p) WHERE r.superseded_by IS NULL)
        WITH dest, nodes(p) AS path_nodes, $trust_tiers AS allowed_tiers, $include_superseded AS inc
        UNWIND path_nodes AS pn
        OPTIONAL MATCH (x:FactEntity)-[c:FACT_CONSTRAINED_BY]->(pol:FactEntity)
        WHERE x.entity_id = pn.entity_id AND (inc OR c.superseded_by IS NULL)
        WITH dest, collect(DISTINCT c.access_mode) AS modes, allowed_tiers
        WHERE modes IS NULL OR ALL(m IN modes WHERE m IS NULL OR list_contains(allowed_tiers, m))
        RETURN DISTINCT dest.entity_id AS entity_id, dest.entity_type AS entity_type, dest.label AS label
        ORDER BY entity_id
        """,
    params=("entry_id", "trust_tiers", "include_superseded"),
    mutating=False,
    description=(
        "Q1 — Given this user, intent, trust tier and policy set, what capability path is "
        "allowed? Bounded INVOKES/REQUIRES traversal (max 5 hops) from an entry capability, "
        "excluding any destination reachable only through a CONSTRAINED_BY policy whose "
        "access_mode isn't in the caller's trust_tiers."
    ),
)

_Q2_EXPLAIN_PATH = NamedQuery(
    name="capability.explain_path",
    cypher="""
        MATCH p = (src:FactEntity {entity_id: $from_id})
                  -[:FACT_INVOKES|FACT_REQUIRES*1..5]->
                  (dst:FactEntity {entity_id: $to_id})
        WHERE $include_superseded OR ALL(r IN relationships(p) WHERE r.superseded_by IS NULL)
        WITH nodes(p) AS path_nodes, $include_superseded AS inc
        ORDER BY size(path_nodes) ASC
        LIMIT 1
        UNWIND path_nodes AS pn
        OPTIONAL MATCH (x:FactEntity)-[c:FACT_CONSTRAINED_BY]->(pol:FactEntity)
        WHERE x.entity_id = pn.entity_id AND (inc OR c.superseded_by IS NULL)
        RETURN pn.entity_id AS node_id, pol.entity_id AS policy_id, pol.label AS policy_label,
               c.access_mode AS access_mode, c.confidence AS confidence,
               c.source AS source, c.evidence_ref AS evidence_ref
        """,
    params=("from_id", "to_id", "include_superseded"),
    mutating=False,
    description=(
        "Q2 — Why was this path selected or blocked? Resolves the shortest bounded "
        "(max 5 hops) INVOKES/REQUIRES path between two capabilities and returns every "
        "CONSTRAINED_BY policy touching a node on that path, with its provenance "
        "(confidence/source/evidence_ref) — the 'why' is the provenance."
    ),
)

_Q3_IMPACT_OF = NamedQuery(
    name="capability.impact_of",
    cypher="""
        MATCH p = (affected:FactEntity)
                  -[:FACT_REQUIRES|FACT_INVOKES|FACT_READS|FACT_WRITES|FACT_DEPLOYED_ON*1..4]->
                  (changed:FactEntity {entity_id: $entity_id})
        WHERE ($include_superseded OR ALL(r IN relationships(p) WHERE r.superseded_by IS NULL))
              AND affected.entity_id <> $entity_id
        RETURN affected.entity_type AS entity_type, collect(DISTINCT affected.entity_id) AS entity_ids
        ORDER BY entity_type
        """,
    params=("entity_id", "include_superseded"),
    mutating=False,
    description=(
        "Q3 — If this adapter changes, which agents, workflows, apps and policies are "
        "affected? Reverse traversal (max 4 hops) over REQUIRES/INVOKES/READS/WRITES/"
        "DEPLOYED_ON from the changed entity, grouped by entity_type; DISTINCT collection "
        "deduplicates entities reachable via more than one path (a diamond dependency)."
    ),
)

_Q4_LINEAGE_OF = NamedQuery(
    name="capability.lineage_of",
    cypher="""
        MATCH p = (producer:FactEntity)-[:FACT_PRODUCED*1..6]->(artifact:FactEntity {entity_id: $artifact_id})
        WHERE $include_superseded OR ALL(r IN relationships(p) WHERE r.superseded_by IS NULL)
        WITH DISTINCT producer, $include_superseded AS inc
        OPTIONAL MATCH (producer)-[ab:FACT_APPROVED_BY]->(appr:FactEntity)
        WHERE inc OR ab.superseded_by IS NULL
        OPTIONAL MATCH (producer)-[rd:FACT_READS]->(datasrc:FactEntity)
        WHERE inc OR rd.superseded_by IS NULL
        OPTIONAL MATCH (producer)-[dep:FACT_DEPLOYED_ON]->(infra:FactEntity)
        WHERE inc OR dep.superseded_by IS NULL
        RETURN producer.entity_id AS producer_id, producer.entity_type AS producer_type,
               collect(DISTINCT appr.entity_id) AS approved_by,
               collect(DISTINCT datasrc.entity_id) AS reads,
               collect(DISTINCT infra.entity_id) AS deployed_on
        ORDER BY producer_id
        """,
    params=("artifact_id", "include_superseded"),
    mutating=False,
    description=(
        "Q4 — Which skills, tools, data, approvals and infrastructure produced this "
        "artifact? Reverse PRODUCED traversal (max 6 hops) from an artifact, collecting "
        "each producer's APPROVED_BY / READS / DEPLOYED_ON neighbors along the way."
    ),
)

_Q5_REUSE_CANDIDATES = NamedQuery(
    name="capability.reuse_candidates",
    cypher="""
        MATCH (cand:FactEntity)
        WHERE cand.entity_type = 'capability'
              AND (cand.superseded_by IS NULL OR $include_superseded)
              AND (1 - array_cosine_similarity(cand.embedding, $query_embedding)) <= 0.30
        WITH cand, (1 - array_cosine_similarity(cand.embedding, $query_embedding)) AS distance,
             $include_superseded AS inc
        OPTIONAL MATCH (cand)-[req:FACT_REQUIRES]->(dep:FactEntity)
        WHERE inc OR req.superseded_by IS NULL
        WITH cand, distance, collect(DISTINCT dep.entity_id) AS requires,
             collect(DISTINCT dep.superseded_by) AS dep_superseded
        WHERE dep_superseded IS NULL OR ALL(s IN dep_superseded WHERE s IS NULL)
        RETURN cand.entity_id AS entity_id, cand.label AS label, (1.0 - distance) AS similarity, requires
        ORDER BY similarity DESC
        """,
    params=("query_embedding", "include_superseded"),
    mutating=False,
    description=(
        "Q5 — Can an existing chain of capabilities satisfy the request without building "
        "something new? Vector similarity over FactEntity.embedding (entity_type='capability', "
        "floor 0.70 — the (1 - cosine) < 0.30 distance convention from bundle_compiler.py), "
        "then excludes any candidate whose REQUIRES chain points at a superseded (no longer "
        "satisfiable) dependency."
    ),
)

CAPABILITY_QUERIES: tuple[NamedQuery, ...] = (
    _ENTITY_STUB_QUERY,
    _ENTITY_FULL_QUERY,
    _ENTITY_SUPERSEDE_QUERY,
    *_EDGE_QUERIES,
    _Q1_PERMITTED_PATHS,
    _Q2_EXPLAIN_PATH,
    _Q3_IMPACT_OF,
    _Q4_LINEAGE_OF,
    _Q5_REUSE_CANDIDATES,
)
