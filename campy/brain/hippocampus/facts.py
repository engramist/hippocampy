"""
campy/brain/hippocampus/facts.py — B317 fact-envelope ingest.

Write path for the projected capability-graph subset defined in
`schema.py` (`FactEntity` + the ten `FACT_*` rel tables) — the external
platform's "bounded multi-hop conformance suite" this card exists to make
executable. Every write here is `authority='projected'`: this module never
creates `earned` state, because everything it ingests has an external
owner by definition (a harvested capability catalog, agent cards, MCP
contracts, ...). See `docs/ecosystem-rules.md`'s "No shadow stores rule"
(B313 clarification) and `docs/ARCHITECTURE.md`'s B317 section for the
full contract.

**Card-vs-code note (documented here, not silently patched over):** the
card's `FactEnvelope` (`subject_id, predicate, object_id, properties,
source, source_version, observed_at, evidence_ref`) carries only
*edge*-shaped data — no `entity_type`/`label`/`embedding` for the entities
an edge references. But those fields are exactly what Q1/Q3/Q5 need
(`entity_type` to filter/group, `label` for a human-readable answer,
`embedding` for Q5's similarity search) — a real entity can't function
with `entity_type='unknown'`. So this module adds a second envelope,
`FactEntityEnvelope`, and `ingest_entities()`, undocumented in the card,
as the actual entity-authoring path a harvester (or the B317 fixture)
calls first. `ingest_facts()` still does its own auto-vivify of a minimal
stub `FactEntity` (`entity_type='unknown'`) for any `subject_id`/
`object_id` it references that doesn't already exist — so edge ingest
never fails on a missing endpoint — but a real caller should always seed
entities via `ingest_entities()` first. This split is called out again in
the B317 PR description.

**Edge supersession does not literally reuse B312's `mark_superseded()`**
(also worth recording, not silently deviating): that function is
node-shaped — it takes a `table`/`node_id` primary-key pair and requires
`table` be registered in `provenance._PK_COLUMN`. Kùzu relationships have
no primary key, so there is no `node_id` to hand it for an edge. The
`FACT_*` rel tables carry their own `superseded_by`/`superseded_at`/
`supersession_reason` columns (per the card's own DDL) and this module
sets them directly via the `capability.supersede_edge_<predicate>` named
queries — same three-column shape and vocabulary
(`schema.SUPERSESSION_REASONS`) as `mark_superseded()`, just without its
node-pk machinery. One deliberate difference: for a node, `superseded_by`
holds the *replacement node's primary key*. An edge has no such key — the
only thing that changes between an edge and its replacement is
`source_version` (same `(subject_id, predicate, object_id)` triple), so
`superseded_by` on a `FACT_*` edge holds the **new `source_version`
string** instead. That is what "the old edge is still retrievable with
`include_superseded=True`, and a reader can see what replaced it" means
for something with no id of its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.provenance import validate_authority
from campy.brain.hippocampus.schema import FACT_PREDICATE_TABLES

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _gateway(db) -> GraphGateway:
    """Wrap `db` in a `GraphGateway` bound to the shared registry, or pass
    a `GraphGateway` through unchanged (B314 pattern — see
    `thalamus/tools/lessons.py::_gateway`)."""
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)


def _now_iso(at: datetime | None) -> tuple[datetime, str]:
    at = at or datetime.now(timezone.utc)
    return at, at.isoformat()


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactEntityEnvelope:
    """A projected capability-graph entity — see the module docstring for
    why this exists alongside (not in place of) the card's `FactEnvelope`.

    `entity_id` is the source system's stable domain identifier — never a
    Campy-minted one (schema.py's `FactEntity.entity_id` comment). Per the
    scope-narrowing note in backlog/B317.md, only three entity_types have
    a real stable identifier today: `capability`, `agent`, `mcp_tool`.
    Every other `entity_type` value used in the fixture graph is marked
    explicitly synthetic (see `benchmarks/capability_eval/fixtures.py`).
    """

    entity_id: str
    entity_type: str
    label: str
    source: str
    source_version: str
    properties: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime | None = None
    evidence_ref: str | None = None
    embedding: list[float] | None = None
    embedding_model: str | None = None


@dataclass(frozen=True)
class FactEnvelope:
    """One projected capability-graph edge, verbatim per backlog/B317.md
    Task 2. `predicate` must be one of `schema.FACT_PREDICATE_TABLES`'
    ten keys; anything else is rejected (see `ingest_facts()`), not
    raised. `properties` carries the edge's LPG operational fields —
    `version`, `access_mode`, `confidence`, `run_id` — whichever the
    source system supplies; missing keys write NULL. `evidence_ref` is
    the fact's own field (not folded into `properties`), matching B312's
    convention of evidence_ref as a first-class provenance column.
    """

    subject_id: str
    predicate: str
    object_id: str
    source: str
    source_version: str
    properties: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime | None = None
    evidence_ref: str | None = None


# ---------------------------------------------------------------------------
# Entity ingest
# ---------------------------------------------------------------------------


async def ingest_entities(
    gateway: "GraphGateway | KuzuClient",
    entities: list[FactEntityEnvelope],
    *,
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
) -> dict:
    """Upsert `FactEntity` nodes. Always writes `authority='projected'`.

    Idempotent: re-running the same envelope list twice reports the same
    `entities` count both times (create-if-absent, refresh-if-newer-
    version, no-op on an unchanged re-ingest — never a duplicate node,
    since `entity_id` is the primary key).

    Returns `{"entities": N, "rejected": [...]}` — `N` is the count of
    envelopes that were live FactEntity rows by the end of this call;
    `rejected` holds `{"entity_id", "reason"}` for any envelope whose
    authority validation failed... except that never happens silently:
    a missing `source_version` raises (matching `ingest_facts()`'s
    behavior and B313's `validate_authority()` contract), it is not
    collected into `rejected`. `rejected` is here for interface symmetry
    with `ingest_facts()` and is currently always empty; kept as a list
    (not removed) because a real future validation rule (e.g. an
    `entity_type` outside a controlled vocabulary) would want it.
    """
    gw = _gateway(gateway)
    rejected: list[dict] = []
    live_ids: set[str] = set()

    # Validate every envelope before writing anything — a batch-wide
    # authority failure must not leave a partial write behind.
    for ent in entities:
        validate_authority("projected", ent.source, ent.source_version)

    for ent in entities:
        observed_at, observed_at_iso = _now_iso(ent.observed_at)
        emb_model = ent.embedding_model or embedding_model
        embedding = ent.embedding if ent.embedding is not None else emb.embed(ent.label, model_name=emb_model)
        properties_json = json.dumps(ent.properties or {}, sort_keys=True)

        existing = await gw.run("capability.find_fact_entity", entity_id=ent.entity_id)
        if not existing:
            await gw.run(
                "capability.create_fact_entity",
                entity_id=ent.entity_id,
                entity_type=ent.entity_type,
                label=ent.label,
                properties=properties_json,
                embedding=embedding,
                embedding_model=emb_model,
                embedding_dim=len(embedding),
                source=ent.source,
                source_version=ent.source_version,
                observed_at=observed_at_iso,
                evidence_ref=ent.evidence_ref,
                authority="projected",
                created_at=observed_at_iso,
            )
        elif existing[0].get("source_version") != ent.source_version:
            await gw.run(
                "capability.update_fact_entity",
                entity_id=ent.entity_id,
                entity_type=ent.entity_type,
                label=ent.label,
                properties=properties_json,
                embedding=embedding,
                embedding_model=emb_model,
                embedding_dim=len(embedding),
                source=ent.source,
                source_version=ent.source_version,
                observed_at=observed_at_iso,
                evidence_ref=ent.evidence_ref,
                authority="projected",
            )
        live_ids.add(ent.entity_id)

    return {"entities": len(live_ids), "rejected": rejected}


# ---------------------------------------------------------------------------
# Fact (edge) ingest
# ---------------------------------------------------------------------------


async def ingest_facts(
    gateway: "GraphGateway | KuzuClient",
    facts: list[FactEnvelope],
    *,
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
) -> dict:
    """Upsert `FACT_*` edges (and auto-vivify any missing endpoint
    entities). Always writes `authority='projected'`.

    Rules (backlog/B317.md Task 2):
      - Unknown predicate -> rejected (not raised); the rest of the batch
        still processes.
      - Missing/empty `source_version` on an otherwise-valid fact ->
        raises `ValueError` (via `provenance.validate_authority()`),
        aborting the whole call. Validated for every accepted fact
        *before* any write happens, so a bad envelope never leaves a
        partial write behind.
      - Idempotent on `(subject_id, predicate, object_id)`: re-ingesting
        the same fact at the same `source_version` is a no-op (no
        duplicate edge). Re-ingesting at a different `source_version`
        supersedes the prior live edge (see module docstring for why this
        doesn't literally call B312's node-shaped `mark_superseded()`)
        and creates a new live edge.

    Returns `{"entities": N, "edges": M, "rejected": [...]}`. `N` is the
    count of distinct entity_ids referenced by *accepted* facts in this
    batch (whether newly auto-vivified or already present); `M` is the
    count of accepted facts represented by a live edge by the end of this
    call. Both are stable across repeated calls with the same input,
    which is what AC's idempotency check compares.
    """
    gw = _gateway(gateway)
    rejected: list[dict] = []
    accepted: list[FactEnvelope] = []

    for fact in facts:
        if fact.predicate not in FACT_PREDICATE_TABLES:
            rejected.append({
                "subject_id": fact.subject_id,
                "predicate": fact.predicate,
                "object_id": fact.object_id,
                "reason": f"unknown predicate {fact.predicate!r}; must be one of "
                          f"{sorted(FACT_PREDICATE_TABLES)}",
            })
            continue
        accepted.append(fact)

    # Validate every accepted fact's authority before writing anything —
    # see docstring: a missing source_version must abort the whole batch,
    # not leave a partial write behind.
    for fact in accepted:
        validate_authority("projected", fact.source, fact.source_version)

    entity_ids: set[str] = set()
    edges = 0

    for fact in accepted:
        observed_at, observed_at_iso = _now_iso(fact.observed_at)
        lower = fact.predicate.lower()

        for entity_id in (fact.subject_id, fact.object_id):
            if entity_id in entity_ids:
                continue
            existing = await gw.run("capability.find_fact_entity", entity_id=entity_id)
            if not existing:
                stub_embedding = emb.embed(entity_id, model_name=embedding_model)
                await gw.run(
                    "capability.create_fact_entity",
                    entity_id=entity_id,
                    entity_type="unknown",
                    label=entity_id,
                    properties="{}",
                    embedding=stub_embedding,
                    embedding_model=embedding_model,
                    embedding_dim=len(stub_embedding),
                    source=fact.source,
                    source_version=fact.source_version,
                    observed_at=observed_at_iso,
                    evidence_ref=fact.evidence_ref,
                    authority="projected",
                    created_at=observed_at_iso,
                )
            entity_ids.add(entity_id)

        live = await gw.run(
            f"capability.find_live_edge_{lower}",
            subject_id=fact.subject_id, object_id=fact.object_id,
        )
        if live:
            if live[0].get("source_version") == fact.source_version:
                edges += 1  # idempotent no-op: already live at this version
                continue
            await gw.run(
                f"capability.supersede_edge_{lower}",
                subject_id=fact.subject_id,
                object_id=fact.object_id,
                superseded_by=fact.source_version,
                superseded_at=observed_at_iso,
                reason="replaced",
            )

        props = fact.properties or {}
        await gw.run(
            f"capability.create_edge_{lower}",
            subject_id=fact.subject_id,
            object_id=fact.object_id,
            version=props.get("version"),
            access_mode=props.get("access_mode"),
            confidence=props.get("confidence"),
            run_id=props.get("run_id"),
            evidence_ref=fact.evidence_ref,
            source=fact.source,
            source_version=fact.source_version,
            observed_at=observed_at_iso,
            authority="projected",
        )
        edges += 1

    return {"entities": len(entity_ids), "edges": edges, "rejected": rejected}
