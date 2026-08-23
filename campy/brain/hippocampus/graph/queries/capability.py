"""
campy/brain/hippocampus/graph/queries/capability.py — B317 named-query slice.

Two groups of `NamedQuery` objects, all reached through `GraphGateway.run()`
per B314's chokepoint rule (no raw-Cypher escape hatch, no inline Cypher
at any call site):

1. **Ingest queries** — entity upsert + per-predicate edge
   create/find-live/supersede, consumed by
   `campy/brain/hippocampus/facts.py`. One create/find/supersede triplet
   per predicate in `schema.FACT_PREDICATE_TABLES` (10 predicates -> 30
   queries), generated in a loop rather than hand-written 30 times over —
   the Cypher text each one resolves to is still fully static once the
   module is imported, so this is no different from any other
   `NamedQuery` from `NamedQuery.__post_init__`'s point of view.

2. **The five customer questions** (Q1-Q5) — `capability.permitted_paths`,
   `capability.explain_path`, `capability.impact_of`, `capability.lineage_of`,
   `capability.reuse_candidates`. Every one is bounded (explicit `*N..M` hop
   limit, never a bare `*`) and excludes superseded rows by default via an
   `include_superseded` parameter every query declares.

**A Kùzu 0.11.3 quirk that shaped these queries' shape, worth recording
so nobody "simplifies" them back into the broken form:** passing a
*list of relationships* extracted via `relationships(path)` through a
`WITH` boundary and then doing property access on its elements
(`rel.superseded_by`) crashes the embedded engine with `RuntimeError:
Cannot evaluate expression with type PROPERTY` — confirmed empirically
against the pinned build (not documented upstream; Kùzu 0.11.3 was
archived Oct 2025, so no patch is coming). The workaround used
throughout this module: evaluate `ALL(rel IN relationships(pth) WHERE
...)` **inline**, in the same clause as the `MATCH` that produced `pth`,
never after a `WITH` has touched `pth`. Node lists from `nodes(path)`
don't have this problem — they're carried across `WITH`/`UNWIND` freely
by re-matching on `entity_id` (Kùzu can't bind a `MATCH` node pattern
directly to a struct pulled out of `nodes(path)` either — "Cannot bind
n as node pattern" — so every such lookup goes through
`(m:FactEntity {entity_id: n.entity_id})`, not `(n)` directly).
Similarly, referencing a `$parameter` directly inside an `ALL(...)`/
`ANY(...)` lambda body crashes with a `KU_UNREACHABLE` parser assertion;
the fix is to bind the parameter to a plain variable via an earlier
`WITH $param AS var` and reference `var` inside the lambda instead.
Finally, `WITH` requires every carried-forward variable to be explicitly
`AS`-aliased (`WITH x AS x`), even a bare pass-through — Kùzu does not
auto-alias like some other Cypher engines do.

Naming convention: `capability.<verb>_<subject>` for the ingest half
(mirroring `lessons.py`), `capability.<question_name>` for Q1-Q5 (the
customer's own names, verbatim).
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery
from campy.brain.hippocampus.schema import FACT_PREDICATE_TABLES

# ---------------------------------------------------------------------------
# Entity upsert (facts.py's ingest_entities / auto-vivify path)
# ---------------------------------------------------------------------------

_ENTITY_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="capability.find_fact_entity",
        cypher="""
            MATCH (e:FactEntity {entity_id: $entity_id})
            RETURN e.entity_id AS entity_id, e.entity_type AS entity_type,
                   e.source_version AS source_version
            """,
        params=("entity_id",),
        mutating=False,
        description="Check whether a FactEntity already exists (id, type, current source_version).",
    ),
    NamedQuery(
        name="capability.create_fact_entity",
        cypher="""
            CREATE (e:FactEntity {
                entity_id: $entity_id,
                entity_type: $entity_type,
                label: $label,
                properties: $properties,
                embedding: $embedding,
                embedding_model: $embedding_model,
                embedding_dim: $embedding_dim,
                source: $source,
                source_version: $source_version,
                observed_at: timestamp($observed_at),
                evidence_ref: $evidence_ref,
                authority: $authority,
                superseded_by: NULL,
                superseded_at: NULL,
                supersession_reason: NULL,
                created_at: timestamp($created_at)
            })
            """,
        params=(
            "entity_id", "entity_type", "label", "properties", "embedding",
            "embedding_model", "embedding_dim", "source", "source_version",
            "observed_at", "evidence_ref", "authority", "created_at",
        ),
        mutating=True,
        description="Create a new FactEntity (B317 projected capability-graph node).",
    ),
    NamedQuery(
        name="capability.supersede_fact_entity",
        cypher="""
            MATCH (e:FactEntity {entity_id: $entity_id})
            WHERE e.superseded_by IS NULL
            SET e.superseded_by = $superseded_by,
                e.superseded_at = timestamp($superseded_at),
                e.supersession_reason = $reason
            """,
        params=("entity_id", "superseded_by", "superseded_at", "reason"),
        mutating=True,
        description="Mark a FactEntity superseded/retired (e.g. a decommissioned MCP tool) — "
                    "entity-level, distinct from edge-level supersession; used by "
                    "capability.reuse_candidates' requires-satisfiable check.",
    ),
    NamedQuery(
        name="capability.update_fact_entity",
        cypher="""
            MATCH (e:FactEntity {entity_id: $entity_id})
            SET e.entity_type = $entity_type,
                e.label = $label,
                e.properties = $properties,
                e.embedding = $embedding,
                e.embedding_model = $embedding_model,
                e.embedding_dim = $embedding_dim,
                e.source = $source,
                e.source_version = $source_version,
                e.observed_at = timestamp($observed_at),
                e.evidence_ref = $evidence_ref,
                e.authority = $authority
            """,
        params=(
            "entity_id", "entity_type", "label", "properties", "embedding",
            "embedding_model", "embedding_dim", "source", "source_version",
            "observed_at", "evidence_ref", "authority",
        ),
        mutating=True,
        description="Refresh an existing FactEntity's fields on a newer-source_version re-ingest.",
    ),
)

# ---------------------------------------------------------------------------
# Per-predicate edge queries (generated — 10 predicates x 3 queries)
# ---------------------------------------------------------------------------


def _edge_queries_for(predicate: str, table: str) -> tuple[NamedQuery, ...]:
    lower = predicate.lower()
    return (
        NamedQuery(
            name=f"capability.find_live_edge_{lower}",
            cypher=f"""
                MATCH (s:FactEntity {{entity_id: $subject_id}})-[r:{table}]->(o:FactEntity {{entity_id: $object_id}})
                WHERE r.superseded_by IS NULL
                RETURN r.source_version AS source_version
                LIMIT 1
                """,
            params=("subject_id", "object_id"),
            mutating=False,
            description=f"Find the live (non-superseded) {table} edge between two FactEntities, if any.",
        ),
        NamedQuery(
            name=f"capability.supersede_edge_{lower}",
            cypher=f"""
                MATCH (s:FactEntity {{entity_id: $subject_id}})-[r:{table}]->(o:FactEntity {{entity_id: $object_id}})
                WHERE r.superseded_by IS NULL
                SET r.superseded_by = $superseded_by,
                    r.superseded_at = timestamp($superseded_at),
                    r.supersession_reason = $reason
                """,
            params=("subject_id", "object_id", "superseded_by", "superseded_at", "reason"),
            mutating=True,
            description=f"Mark the live {table} edge superseded (B312-style, edge-shaped: "
                        f"superseded_by carries the new source_version, not a node id — "
                        f"see facts.py's module docstring for why).",
        ),
        NamedQuery(
            name=f"capability.create_edge_{lower}",
            cypher=f"""
                MATCH (s:FactEntity {{entity_id: $subject_id}}), (o:FactEntity {{entity_id: $object_id}})
                CREATE (s)-[:{table} {{
                    version: $version,
                    access_mode: $access_mode,
                    confidence: $confidence,
                    run_id: $run_id,
                    evidence_ref: $evidence_ref,
                    source: $source,
                    source_version: $source_version,
                    observed_at: timestamp($observed_at),
                    authority: $authority,
                    superseded_by: NULL,
                    superseded_at: NULL,
                    supersession_reason: NULL
                }}]->(o)
                """,
            params=(
                "subject_id", "object_id", "version", "access_mode", "confidence",
                "run_id", "evidence_ref", "source", "source_version", "observed_at",
                "authority",
            ),
            mutating=True,
            description=f"Create a live {table} edge (B317 fact-envelope ingest).",
        ),
    )


_EDGE_QUERIES: tuple[NamedQuery, ...] = tuple(
    q
    for predicate, table in FACT_PREDICATE_TABLES.items()
    for q in _edge_queries_for(predicate, table)
)

# ---------------------------------------------------------------------------
# The five customer questions (Q1-Q5)
# ---------------------------------------------------------------------------

_QUESTION_QUERIES: tuple[NamedQuery, ...] = (
    # Q1 — "Given this user, intent, trust tier and policy set, what
    # capability path is allowed?" Bounded INVOKES/REQUIRES path, max 5
    # hops, filtered by CONSTRAINED_BY policies along the path against the
    # caller's trust_tier (encoded on the CONSTRAINED_BY edge's
    # access_mode: NULL/no policy = unconstrained, a value = the trust
    # tier required to pass through the constrained node).
    NamedQuery(
        name="capability.permitted_paths",
        cypher="""
            WITH $include_superseded AS incsup, $trust_tier AS trust_tier
            MATCH pth = (entry:FactEntity {entity_id: $entry_id})-[:FACT_INVOKES|FACT_REQUIRES*1..5]->(target:FactEntity)
            WHERE ALL(rel IN relationships(pth) WHERE rel.superseded_by IS NULL OR incsup)
            WITH target AS target, incsup AS incsup, trust_tier AS trust_tier,
                 nodes(pth) AS ns, length(pth) AS hops
            UNWIND ns AS n
            OPTIONAL MATCH (m:FactEntity {entity_id: n.entity_id})-[c:FACT_CONSTRAINED_BY]->(:FactEntity)
            WHERE (c.superseded_by IS NULL OR incsup)
            WITH target AS target, trust_tier AS trust_tier, hops AS hops,
                 count(CASE WHEN c.access_mode IS NOT NULL AND c.access_mode <> trust_tier THEN 1 END) AS num_blocking_modes
            WHERE num_blocking_modes = 0
            RETURN target.entity_id AS entity_id, target.entity_type AS entity_type,
                   target.label AS label, min(hops) AS hops
            ORDER BY hops, entity_id
            """,
        params=("entry_id", "trust_tier", "include_superseded"),
        mutating=False,
        description="Q1: bounded (max 5 hop) INVOKES/REQUIRES path from an entry capability, "
                    "excluding targets blocked by a CONSTRAINED_BY policy the caller's trust_tier doesn't satisfy.",
    ),
    # Q2 — "Why was this path selected or blocked?" Given an ordered list
    # of entity_ids forming a path (typically Q1's output), return each
    # hop's edge properties plus the CONSTRAINED_BY policies on its source
    # node — the "why" is the provenance (confidence/source/evidence_ref).
    # Trivially bounded: one hop per {from, to} pair, no `*` traversal at all.
    NamedQuery(
        name="capability.explain_path",
        cypher="""
            WITH $include_superseded AS incsup
            UNWIND $pairs AS pair
            MATCH (a:FactEntity {entity_id: pair.from})-[r:FACT_INVOKES|FACT_REQUIRES]->(b:FactEntity {entity_id: pair.to})
            WHERE (r.superseded_by IS NULL OR incsup)
            OPTIONAL MATCH (a)-[c:FACT_CONSTRAINED_BY]->(pol:FactEntity)
            WHERE (c.superseded_by IS NULL OR incsup)
            WITH a AS a, b AS b, r AS r, incsup AS incsup,
                 collect(DISTINCT {
                     policy_id: pol.entity_id, confidence: c.confidence,
                     source: c.source, evidence_ref: c.evidence_ref
                 }) AS policies
            RETURN a.entity_id AS from_id, b.entity_id AS to_id, label(r) AS predicate,
                   r.confidence AS edge_confidence, r.source AS edge_source,
                   r.evidence_ref AS edge_evidence_ref, policies AS policies
            """,
        params=("pairs", "include_superseded"),
        mutating=False,
        description="Q2: for each consecutive (from, to) hop of a given path, the edge's own "
                    "provenance plus any CONSTRAINED_BY policies on its source node.",
    ),
    # Q3 — "If this adapter changes, which agents, workflows, apps and
    # policies are affected?" Reverse traversal over the five
    # forward-dependency predicates, max 4 hops, deduplicated (a diamond
    # dependency must not produce two rows for the same impacted entity —
    # the implicit GROUP BY on the non-aggregated RETURN columns handles
    # that: min(hops) collapses every path to the same entity into one row).
    NamedQuery(
        name="capability.impact_of",
        cypher="""
            WITH $include_superseded AS incsup
            MATCH pth = (changed:FactEntity {entity_id: $entity_id})<-[:FACT_REQUIRES|FACT_INVOKES|FACT_READS|FACT_WRITES|FACT_DEPLOYED_ON*1..4]-(impacted:FactEntity)
            WHERE ALL(rel IN relationships(pth) WHERE rel.superseded_by IS NULL OR incsup)
            WITH impacted AS impacted, length(pth) AS hops
            RETURN impacted.entity_id AS entity_id, impacted.entity_type AS entity_type,
                   impacted.label AS label, min(hops) AS hops
            ORDER BY hops, entity_id
            """,
        params=("entity_id", "include_superseded"),
        mutating=False,
        description="Q3: bounded (max 4 hop) reverse impact analysis over REQUIRES/INVOKES/READS/"
                    "WRITES/DEPLOYED_ON, deduplicated across diamond dependencies.",
    ),
    # Q4 — "Which skills, tools, data, approvals and infrastructure
    # produced this artifact?" Reverse PRODUCED chain (max 6 hops), plus
    # each producer's own APPROVED_BY/READS/DEPLOYED_ON edges (1 hop,
    # trivially bounded) collected alongside it.
    #
    # SCOPE NOTE (customer's stable-identifier audit, post-card): Artifact
    # and Infrastructure entity types have no usable stable ID in the
    # source systems today (two incompatible artifact_id conventions,
    # DocMCP has none at all; Infrastructure is hand-typed Terraform
    # literals). This query is fully implemented and tested, but every
    # Artifact/Run/Infrastructure entity in the fixture graph is
    # EXPLICITLY SYNTHETIC (entity_id prefixed `synthetic:`) — it is
    # unverifiable against the real platform until those IDs exist. See
    # benchmarks/capability_eval/README.md and docs/ARCHITECTURE.md.
    NamedQuery(
        name="capability.lineage_of",
        cypher="""
            WITH $include_superseded AS incsup
            MATCH pth = (artifact:FactEntity {entity_id: $artifact_id})<-[:FACT_PRODUCED*1..6]-(producer:FactEntity)
            WHERE ALL(rel IN relationships(pth) WHERE rel.superseded_by IS NULL OR incsup)
            WITH producer AS producer, incsup AS incsup, length(pth) AS hops
            WITH producer AS producer, incsup AS incsup, min(hops) AS hops
            OPTIONAL MATCH (producer)-[ar:FACT_APPROVED_BY]->(approver:FactEntity)
            WHERE (ar.superseded_by IS NULL OR incsup)
            WITH producer AS producer, incsup AS incsup, hops AS hops,
                 collect(DISTINCT approver.entity_id) AS approved_by
            OPTIONAL MATCH (producer)-[rr:FACT_READS]->(readtarget:FactEntity)
            WHERE (rr.superseded_by IS NULL OR incsup)
            WITH producer AS producer, incsup AS incsup, hops AS hops, approved_by AS approved_by,
                 collect(DISTINCT readtarget.entity_id) AS reads
            OPTIONAL MATCH (producer)-[dr:FACT_DEPLOYED_ON]->(infra:FactEntity)
            WHERE (dr.superseded_by IS NULL OR incsup)
            RETURN producer.entity_id AS entity_id, producer.entity_type AS entity_type,
                   producer.label AS label, hops AS hops,
                   approved_by AS approved_by, reads AS reads,
                   collect(DISTINCT infra.entity_id) AS deployed_on
            ORDER BY hops, entity_id
            """,
        params=("artifact_id", "include_superseded"),
        mutating=False,
        description="Q4: bounded (max 6 hop) reverse PRODUCED lineage from an artifact, with each "
                    "producer's APPROVED_BY/READS/DEPLOYED_ON collected alongside it. "
                    "SYNTHETIC FIXTURE ONLY (see docstring above) — Artifact/Infrastructure IDs "
                    "are not yet stable in the real platform.",
    ),
    # Q5 — "Can an existing chain of capabilities satisfy the request
    # without building something new?" Vector similarity over
    # FactEntity.embedding (entity_type='capability' only), floor 0.70
    # (matches bundle_compiler.py's convention), then verify each
    # candidate's direct REQUIRES resolve to live entities. No `*`
    # traversal at all (a plain filtered scan + 1-hop REQUIRES check) —
    # bounded by construction.
    NamedQuery(
        name="capability.reuse_candidates",
        cypher="""
            WITH $include_superseded AS incsup
            MATCH (c:FactEntity {entity_type: 'capability'})
            WHERE (c.superseded_by IS NULL OR incsup) AND c.entity_id <> $entity_id
            WITH c AS c, incsup AS incsup, array_cosine_similarity(c.embedding, $query_embedding) AS sim
            WHERE sim >= $floor
            OPTIONAL MATCH (c)-[req:FACT_REQUIRES]->(dep:FactEntity)
            WHERE (req.superseded_by IS NULL OR incsup)
            WITH c AS c, sim AS sim, collect(dep.entity_id) AS required_ids,
                 count(CASE WHEN dep.superseded_by IS NOT NULL THEN 1 END) AS num_superseded_deps
            RETURN c.entity_id AS entity_id, c.entity_type AS entity_type, c.label AS label,
                   sim AS similarity, required_ids AS required_ids,
                   (num_superseded_deps = 0) AS requires_satisfiable
            ORDER BY sim DESC, entity_id
            """,
        params=("entity_id", "query_embedding", "floor", "include_superseded"),
        mutating=False,
        description="Q5: capability entities whose embedding clears the 0.70 cosine-similarity "
                    "floor against a query vector, with each candidate's direct REQUIRES verified "
                    "satisfiable (resolve to live, non-superseded entities).",
    ),
)

CAPABILITY_QUERIES: tuple[NamedQuery, ...] = _ENTITY_QUERIES + _EDGE_QUERIES + _QUESTION_QUERIES
