"""
campy/brain/hippocampus/facts.py — B317 fact-envelope ingest for the
projected capability-graph subset.

Composes B312 (provenance), B313 (authority), and B314 (GraphGateway named
queries) into a single write path for harvested facts about an external
system (a capability catalog, agent cards, MCP contracts, ...). Everything
this module writes carries `authority='projected'` — see schema.py's "B317"
comment block above `NODE_TABLES` for why that subgraph is kept structurally
separate from Campy's own earned memory.

Two entry points:

    ingest_entities()  — upsert FactEntity nodes with full attributes
                          (entity_type, label, embedding, properties).
    ingest_facts()      — upsert FACT_* edges between entities, from the
                          ten-predicate vocabulary in schema.FACT_PREDICATES.

Why two functions instead of one: `FactEnvelope` (as specified by the B317
card) carries only subject_id/predicate/object_id/edge-properties — nothing
entity-level (no entity_type, label, or embedding field). That's necessary
for `ingest_facts()`'s edges, but the fixture graph (and any real harvester)
also needs entities that actually carry a type, a label, and — for Q5's
semantic reuse search — an embedding. `ingest_facts()` alone can only ever
merge in a bare stub (id + provenance) for an edge's endpoints, so
`ingest_entities()` exists as the sibling call that supplies the rest.
Calling order doesn't matter: both write paths merge on `entity_id`, and
`capability.upsert_entity_stub`'s `ON CREATE`-only clause never clobbers
attributes an earlier `ingest_entities()` call already set.

Both functions are async, take a `GraphGateway`, and never use the
gateway's raw-Cypher escape hatch — every write and read goes through a
`NamedQuery` registered in `graph/queries/capability.py` (see that module's
docstring for the Kùzu 0.11.3 quirks its Cypher works around).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from campy.brain.hippocampus.provenance import validate_authority
from campy.brain.hippocampus.schema import FACT_PREDICATES

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.gateway import GraphGateway

# Edge-property keys FactEnvelope.properties may carry — the LPG operational
# properties schema.py's _FACT_REL_PROPERTIES declares on every FACT_* rel
# table (minus the provenance/authority/supersession columns, which
# ingest_facts sets itself from the envelope's own fields, never from
# `properties`). Any other key in `properties` is silently ignored — this
# card's ingest path is fed by fixtures, not a real harvester, so there is no
# unknown-key reporting contract to honor yet.
_EDGE_PROPERTY_KEYS = ("version", "access_mode", "confidence", "run_id")


@dataclass(frozen=True)
class FactEnvelope:
    """One harvested fact: a (subject, predicate, object) edge with LPG
    operational properties and B312 provenance. See schema.FACT_PREDICATES
    for the ten valid `predicate` values.
    """

    subject_id: str
    predicate: str
    object_id: str
    properties: dict
    source: str
    source_version: str
    observed_at: datetime
    evidence_ref: str | None = None


@dataclass(frozen=True)
class EntityEnvelope:
    """One harvested entity: a FactEntity's full attributes. See this
    module's docstring for why entities need a separate ingest path from
    `FactEnvelope`'s edges.
    """

    entity_id: str
    entity_type: str
    label: str
    source: str
    source_version: str
    observed_at: datetime
    evidence_ref: str | None = None
    embedding: list[float] | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    properties: dict | None = None


async def ingest_entities(gateway: "GraphGateway", entities: list[EntityEnvelope]) -> dict:
    """Upsert FactEntity nodes with full attributes. Always authority='projected'.

    Idempotent: re-ingesting the same entities updates their attributes in
    place (no duplicate nodes — merges on `entity_id`, the primary key).
    Unlike `ingest_facts()`'s edges, entities in this card have no separate
    supersession chain — attribute updates are last-write-wins, which is
    the FactEntity analogue of provenance_fields()' "same id, refreshed
    values" upsert pattern used elsewhere in this codebase (e.g.
    `lessons.update_lesson`).

    Raises:
        ValueError: any entity is missing `source_version` (via
            `provenance.validate_authority`) — an unversioned projected
            fact is not rebuildable and must not be accepted.

    Returns:
        {"entities": N} — N is the number of distinct entity_ids upserted
        this call (always len(entities); entity-level ingest has no
        rejection path since, unlike predicates, entity_type is
        free-form/open-vocabulary).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    seen: set[str] = set()

    for entity in entities:
        validate_authority("projected", entity.source, entity.source_version)

        await gateway.run(
            "capability.upsert_entity_full",
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            label=entity.label,
            properties=json.dumps(entity.properties, sort_keys=True) if entity.properties else None,
            embedding=entity.embedding,
            embedding_model=entity.embedding_model,
            embedding_dim=entity.embedding_dim,
            source=entity.source,
            source_version=entity.source_version,
            observed_at=entity.observed_at.isoformat(),
            evidence_ref=entity.evidence_ref,
            created_at=now_iso,
        )
        seen.add(entity.entity_id)

    return {"entities": len(seen)}


async def ingest_facts(gateway: "GraphGateway", facts: list[FactEnvelope]) -> dict:
    """Upsert FACT_* edges (and stub endpoints) for a batch of FactEnvelopes.

    Always writes authority='projected' (B313) — every row this function
    creates has an external owner by definition. Reuses B313's
    `validate_authority()`, which rejects a missing `source_version`: an
    unversioned projected fact is not rebuildable and must not be accepted.

    Rules (see the B317 backlog card's Task 2 for the full rationale):
      - Unknown predicate (not a key in `schema.FACT_PREDICATES`) → that
        fact is rejected (appended to the returned "rejected" list), not
        raised — a harvester can report partial success without the whole
        batch aborting.
      - Idempotent: matches on (subject_id, predicate, object_id). Ingesting
        the same envelope twice (same source_version) is a no-op — no
        duplicate edge is created.
      - Re-ingesting the same (subject, predicate, object) triple with a
        *different* source_version supersedes the prior live edge (sets its
        `superseded_by`/`superseded_at`/`supersession_reason` rather than
        overwriting it — see `capability.supersede_edge__<predicate>`'s
        docstring for why this can't literally call
        `provenance.mark_superseded()`, which is node- not edge-oriented)
        and creates a fresh edge carrying the new properties. "Different"
        is a plain inequality check, not a semantic version comparison —
        callers are responsible for actually passing a newer version.

    Raises:
        ValueError: any *accepted* (known-predicate) fact is missing
            `source_version` (via `provenance.validate_authority`) — this
            aborts the whole batch, unlike an unknown predicate.

    Returns:
        {"entities": N, "edges": M, "rejected": [...]} — N is the number of
        distinct subject_id/object_id values touched (via
        `capability.upsert_entity_stub`) across every *accepted* fact; M is
        the number of accepted facts that now have a live edge (whether
        newly created, already-live-and-unchanged, or superseded-and-
        replaced); each `rejected` entry is
        `{"subject_id", "predicate", "object_id", "reason"}`.
    """
    entities_seen: set[str] = set()
    edges_touched = 0
    rejected: list[dict] = []

    for fact in facts:
        rel_table = FACT_PREDICATES.get(fact.predicate)
        if rel_table is None:
            rejected.append(
                {
                    "subject_id": fact.subject_id,
                    "predicate": fact.predicate,
                    "object_id": fact.object_id,
                    "reason": "unknown_predicate",
                }
            )
            continue

        # Raises ValueError if source_version (or source) is missing —
        # intentionally NOT caught here; see docstring.
        validate_authority("projected", fact.source, fact.source_version)

        observed_at_iso = fact.observed_at.isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        for entity_id in (fact.subject_id, fact.object_id):
            if entity_id in entities_seen:
                continue
            await gateway.run(
                "capability.upsert_entity_stub",
                entity_id=entity_id,
                source=fact.source,
                source_version=fact.source_version,
                observed_at=observed_at_iso,
                evidence_ref=fact.evidence_ref,
                created_at=now_iso,
            )
            entities_seen.add(entity_id)

        pred_key = fact.predicate.lower()
        existing_rows = await gateway.run(
            f"capability.find_live_edge__{pred_key}",
            subject_id=fact.subject_id,
            object_id=fact.object_id,
        )
        props = fact.properties or {}
        create_params = {
            "subject_id": fact.subject_id,
            "object_id": fact.object_id,
            "evidence_ref": fact.evidence_ref,
            "source": fact.source,
            "source_version": fact.source_version,
            "observed_at": observed_at_iso,
            "authority": "projected",
            **{key: props.get(key) for key in _EDGE_PROPERTY_KEYS},
        }

        if not existing_rows:
            await gateway.run(f"capability.create_edge__{pred_key}", **create_params)
            edges_touched += 1
            continue

        existing_version = existing_rows[0].get("source_version")
        if existing_version == fact.source_version:
            # Idempotent re-ingest of the exact same fact — no-op.
            edges_touched += 1
            continue

        # A different source_version: supersede the old edge, then create
        # the new one carrying the updated properties.
        await gateway.run(
            f"capability.supersede_edge__{pred_key}",
            subject_id=fact.subject_id,
            object_id=fact.object_id,
            superseded_by=fact.source_version,
            at=now_iso,
            reason="replaced",
        )
        await gateway.run(f"capability.create_edge__{pred_key}", **create_params)
        edges_touched += 1

    return {"entities": len(entities_seen), "edges": edges_touched, "rejected": rejected}
