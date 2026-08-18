"""B317 — synthetic capability-graph fixture for the named-query eval pack.

Mirrors `benchmarks/ask_eval/fixtures.py`'s structure: writes known content
through the REAL ingest path (`facts.ingest_entities()` / `facts.ingest_facts()`
via a `GraphGateway`) — never raw Cypher — so the eval exercises genuine
pipeline output, not a hand-rolled shortcut. The one deliberate exception is
the five "mark this specific edge/entity superseded" calls at the bottom of
`seed_fixture_graph()`: those go through the same `GraphGateway.run()`
chokepoint (registered `capability.supersede_edge__*` / `capability.
supersede_entity` queries — never `execute_raw()`), they just aren't
reachable through `ingest_facts()`'s own supersede-on-newer-version path,
because each one models an edge/entity the source system fully *retired*
(no replacement), not one it *replaced*.

This doubles as the backend-conformance suite: see README.md in this
directory — any storage adapter claiming to back Campy must pass
`tests/test_capability_queries.py` unmodified against this fixture.

Entity-id naming convention: `<entity_type-ish prefix>.<slug>`, e.g.
`cap.deploy_pipeline`, `workflow.ci_pipeline` — these are meant to read like
a harvested source system's own stable identifiers (per schema.py's
FactEntity.entity_id contract), not Campy-minted ids.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from campy.brain.hippocampus.facts import EntityEnvelope, FactEnvelope, ingest_entities, ingest_facts

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.gateway import GraphGateway

_SOURCE = "harvest:capability-eval-fixture"
_SOURCE_VERSION = "v1"
_OBSERVED_AT = datetime(2026, 8, 1, tzinfo=timezone.utc)
_EMBEDDING_DIM = 384

# ---------------------------------------------------------------------------
# Deterministic embeddings with an EXACT controlled cosine similarity —
# real sentence-transformers embeddings would require network access this
# sandbox doesn't have (see the B317 implementation notes in
# docs/ARCHITECTURE.md), and Q5 needs precise control over which entities
# land above/below the 0.70 similarity floor anyway, which a real model
# wouldn't reliably give us for hand-picked labels.
# ---------------------------------------------------------------------------


def _unit_vector(seed: str, dim: int = _EMBEDDING_DIM) -> list[float]:
    rng = random.Random(seed)
    v = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def _vector_with_similarity(base: list[float], seed: str, target_similarity: float) -> list[float]:
    """A unit vector whose cosine similarity to `base` is EXACTLY
    `target_similarity` (not approximately) — constructed via Gram-Schmidt:
    pick a random unit vector, orthogonalize it against `base`, then blend
    `base` and the orthogonal component with weights (w, sqrt(1-w^2)) so
    the resulting vector's dot product with `base` is exactly `w`.
    """
    dim = len(base)
    raw = _unit_vector(seed, dim)
    d = sum(x * y for x, y in zip(raw, base))
    orth = [raw[i] - d * base[i] for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in orth))
    orth = [x / norm for x in orth]
    w = target_similarity
    h = math.sqrt(max(0.0, 1.0 - w * w))
    return [w * base[i] + h * orth[i] for i in range(dim)]


_EMAIL_NOTIFIER_EMBEDDING = _unit_vector("cap.email_notifier")
# The near-duplicate pair for Q5 — same underlying capability, a LEXICALLY
# DISSIMILAR label ("Mailer Dispatch Unit" shares no words with "Send Email
# Notification"), and high (0.90) embedding similarity — so a query that
# actually did string matching would miss it, and only real vector
# similarity finds it.
_MAILER_SERVICE_EMBEDDING = _vector_with_similarity(_EMAIL_NOTIFIER_EMBEDDING, "cap.mailer_service", 0.90)
# Below the 0.70 floor — must never appear in Q5 results.
_IMAGE_RESIZER_EMBEDDING = _vector_with_similarity(_EMAIL_NOTIFIER_EMBEDDING, "cap.image_resizer", 0.20)
# Above the floor (0.80) but REQUIRES a superseded (unsatisfiable) node —
# must be found by the similarity search, then excluded by the
# satisfiability check, proving the two filters are independent.
_UNRELIABLE_FORWARDER_EMBEDDING = _vector_with_similarity(
    _EMAIL_NOTIFIER_EMBEDDING, "cap.unreliable_forwarder", 0.80
)

# Public so tests/questions.py can use the exact same query vector Q5 was
# designed against, and so the exact similarity values above are documented
# in one place.
QUERY_EMBEDDING = _EMAIL_NOTIFIER_EMBEDDING


@dataclass(frozen=True)
class _Entity:
    entity_id: str
    entity_type: str
    label: str
    embedding: list[float] | None = None


# ---------------------------------------------------------------------------
# Entity roster — spans every entity type in the customer's ingest list
# (capability catalog entries, agent cards, MCP contracts, workflow
# definitions, policies, Terraform outputs, App/Iteration records,
# build-run evidence) plus `data`/`approval` targets the READS/WRITES/
# APPROVED_BY predicates need somewhere to point.
# ---------------------------------------------------------------------------

_ENTITIES: list[_Entity] = [
    # -- Q1/Q2 cluster: capability path + policy gating -----------------------
    _Entity("cap.deploy_pipeline", "capability", "Deploy Pipeline"),
    _Entity("cap.build_artifact", "capability", "Build Artifact"),
    _Entity("cap.compile_code", "capability", "Compile Code"),
    _Entity("cap.lint_code", "capability", "Lint Code"),
    # Reachable ONLY through an edge this fixture marks superseded below —
    # must disappear from bounded-path results unless include_superseded=True.
    _Entity("cap.lint_code_old", "capability", "Lint Code (Legacy)"),
    _Entity("cap.blocked_admin_action", "capability", "Admin Reset Action"),
    _Entity("cap.notify_slack", "capability", "Notify Slack Channel"),
    _Entity("policy.public_access", "policy", "Public Access Policy"),
    _Entity("policy.admin_only", "policy", "Admin Only Policy"),
    # Its CONSTRAINED_BY edge from cap.notify_slack is marked superseded below.
    _Entity("policy.legacy_slack_policy", "policy", "Legacy Slack Policy"),
    # -- Q3 cluster: impact-of + diamond dependency ----------------------------
    _Entity("infra.terraform_prod_cluster", "infra", "Terraform Prod Cluster"),
    _Entity("workflow.ci_pipeline", "workflow", "CI Pipeline"),
    _Entity("workflow.cd_pipeline", "workflow", "CD Pipeline"),
    # Reachable only via an edge marked superseded below.
    _Entity("workflow.staging_pipeline", "workflow", "Staging Pipeline"),
    _Entity("agent.release_bot", "agent", "Release Bot"),
    _Entity("app.release_dashboard", "app", "Release Dashboard"),
    _Entity("policy.deploy_policy", "policy", "Deploy Policy"),
    _Entity("data.build_logs", "data", "Build Logs"),
    # -- Q4 cluster: lineage-of an artifact -------------------------------------
    _Entity("iteration.sprint_14", "iteration", "Sprint 14"),
    _Entity("evidence.build_run_42", "evidence", "Build Run #42"),
    _Entity("app.release_dashboard_v3", "app", "Release Dashboard v3"),
    _Entity("approval.release_signoff", "approval", "Release Signoff"),
    # Its READS edge from evidence.build_run_42 is marked superseded below.
    _Entity("data.release_config", "data", "Release Config"),
    _Entity("data.deploy_manifest", "data", "Deploy Manifest"),
    # -- Q5 cluster: semantic reuse candidates ---------------------------------
    _Entity("cap.email_notifier", "capability", "Send Email Notification", _EMAIL_NOTIFIER_EMBEDDING),
    _Entity("cap.mailer_service", "capability", "Mailer Dispatch Unit", _MAILER_SERVICE_EMBEDDING),
    _Entity("cap.image_resizer", "capability", "Resize Uploaded Image", _IMAGE_RESIZER_EMBEDDING),
    _Entity("cap.smtp_relay", "capability", "SMTP Relay"),
    # Its REQUIRES edge from cap.email_notifier is marked superseded below.
    _Entity("cap.old_relay_v0", "capability", "Legacy Relay v0"),
    # The NODE itself is marked superseded below (unsatisfiable dependency).
    _Entity("cap.broken_dep", "capability", "Deprecated Dependency"),
    _Entity(
        "cap.unreliable_forwarder", "capability", "Unreliable Forwarder", _UNRELIABLE_FORWARDER_EMBEDDING
    ),
    # -- Padding: MCP contracts, more agent/workflow/app/iteration coverage,
    # and the IMPLEMENTS predicate (not otherwise exercised above) -----------
    _Entity("mcp.file_tool_contract", "mcp_contract", "File Tool MCP Contract"),
    _Entity("cap.read_file", "capability", "Read File"),
    _Entity("agent.file_agent", "agent", "File Agent"),
    _Entity("agent.qa_bot", "agent", "QA Bot"),
    _Entity("workflow.qa_pipeline", "workflow", "QA Pipeline"),
    _Entity("policy.qa_policy", "policy", "QA Policy"),
    _Entity("app.qa_dashboard", "app", "QA Dashboard"),
    _Entity("iteration.sprint_13", "iteration", "Sprint 13"),
    _Entity("infra.terraform_staging_cluster", "infra", "Terraform Staging Cluster"),
]

# (subject_id, predicate, object_id, properties) — properties may carry any
# of facts.py's _EDGE_PROPERTY_KEYS ("version", "access_mode", "confidence",
# "run_id"); omitted keys default to NULL on the edge.
_FACTS: list[tuple[str, str, str, dict]] = [
    # -- Q1/Q2 cluster ----------------------------------------------------------
    ("cap.deploy_pipeline", "INVOKES", "cap.build_artifact", {"confidence": 0.95, "run_id": "run-001"}),
    ("cap.deploy_pipeline", "INVOKES", "cap.blocked_admin_action", {"confidence": 0.9, "run_id": "run-001"}),
    ("cap.deploy_pipeline", "REQUIRES", "cap.notify_slack", {"confidence": 0.9}),
    ("cap.build_artifact", "REQUIRES", "cap.compile_code", {"confidence": 0.97}),
    ("cap.compile_code", "REQUIRES", "cap.lint_code", {"confidence": 0.9}),
    ("cap.compile_code", "REQUIRES", "cap.lint_code_old", {"confidence": 0.4}),
    (
        "cap.build_artifact",
        "CONSTRAINED_BY",
        "policy.public_access",
        {"access_mode": "public", "confidence": 0.99},
    ),
    (
        "cap.blocked_admin_action",
        "CONSTRAINED_BY",
        "policy.admin_only",
        {"access_mode": "elevated", "confidence": 0.99},
    ),
    (
        "cap.notify_slack",
        "CONSTRAINED_BY",
        "policy.legacy_slack_policy",
        {"access_mode": "public", "confidence": 0.6},
    ),
    # -- Q3 cluster ---------------------------------------------------------------
    ("workflow.ci_pipeline", "DEPLOYED_ON", "infra.terraform_prod_cluster", {"access_mode": "write"}),
    ("workflow.cd_pipeline", "DEPLOYED_ON", "infra.terraform_prod_cluster", {"access_mode": "write"}),
    ("workflow.staging_pipeline", "DEPLOYED_ON", "infra.terraform_prod_cluster", {"access_mode": "write"}),
    ("agent.release_bot", "REQUIRES", "workflow.ci_pipeline", {"confidence": 0.9}),
    ("agent.release_bot", "REQUIRES", "workflow.cd_pipeline", {"confidence": 0.9}),
    ("app.release_dashboard", "INVOKES", "agent.release_bot", {"confidence": 0.85}),
    ("policy.deploy_policy", "REQUIRES", "workflow.ci_pipeline", {"confidence": 0.8}),
    ("workflow.ci_pipeline", "WRITES", "data.build_logs", {"access_mode": "write"}),
    # -- Q4 cluster -----------------------------------------------------------------
    ("iteration.sprint_14", "PRODUCED", "evidence.build_run_42", {}),
    ("evidence.build_run_42", "PRODUCED", "app.release_dashboard_v3", {}),
    ("evidence.build_run_42", "APPROVED_BY", "approval.release_signoff", {"confidence": 0.95}),
    ("evidence.build_run_42", "READS", "data.release_config", {"access_mode": "read"}),
    ("evidence.build_run_42", "READS", "data.deploy_manifest", {"access_mode": "read"}),
    ("evidence.build_run_42", "DEPLOYED_ON", "infra.terraform_prod_cluster", {"access_mode": "write"}),
    # -- Q5 cluster ------------------------------------------------------------------
    ("cap.email_notifier", "REQUIRES", "cap.smtp_relay", {"confidence": 0.9}),
    ("cap.email_notifier", "REQUIRES", "cap.old_relay_v0", {"confidence": 0.5}),
    ("cap.mailer_service", "REQUIRES", "cap.smtp_relay", {"confidence": 0.9}),
    ("cap.mailer_service", "REUSES", "cap.smtp_relay", {"confidence": 0.7}),
    ("cap.unreliable_forwarder", "REQUIRES", "cap.broken_dep", {"confidence": 0.6}),
    # -- Padding ------------------------------------------------------------------------
    ("mcp.file_tool_contract", "IMPLEMENTS", "cap.read_file", {"version": "1.2.0"}),
    ("agent.file_agent", "INVOKES", "cap.read_file", {"confidence": 0.8}),
    ("agent.qa_bot", "REQUIRES", "workflow.qa_pipeline", {"confidence": 0.8}),
    ("workflow.qa_pipeline", "DEPLOYED_ON", "infra.terraform_staging_cluster", {"access_mode": "write"}),
    ("policy.qa_policy", "REQUIRES", "workflow.qa_pipeline", {"confidence": 0.7}),
    ("app.qa_dashboard", "INVOKES", "agent.qa_bot", {"confidence": 0.8}),
]

# ---------------------------------------------------------------------------
# Deliberate difficulty: entries retired (never replaced) after the initial
# ingest — one per question, so every one of the five has a superseded row
# that must be excluded by default and recoverable with include_superseded=True.
# (subject_id, predicate, object_id) for edges; a bare entity_id for the
# one node-level retirement (Q5's unsatisfiable-dependency case).
# ---------------------------------------------------------------------------

_SUPERSEDE_EDGES: list[tuple[str, str, str]] = [
    ("cap.compile_code", "REQUIRES", "cap.lint_code_old"),  # Q1
    ("cap.notify_slack", "CONSTRAINED_BY", "policy.legacy_slack_policy"),  # Q2
    ("workflow.staging_pipeline", "DEPLOYED_ON", "infra.terraform_prod_cluster"),  # Q3
    ("evidence.build_run_42", "READS", "data.release_config"),  # Q4
    ("cap.email_notifier", "REQUIRES", "cap.old_relay_v0"),  # Q5 (edge-level)
]

_SUPERSEDE_ENTITIES: list[str] = [
    "cap.broken_dep",  # Q5 (node-level — makes cap.unreliable_forwarder's REQUIRES unsatisfiable)
]


async def seed_fixture_graph(gateway: "GraphGateway") -> dict:
    """Seed the synthetic capability graph via the REAL ingest path
    (`facts.ingest_entities()` / `facts.ingest_facts()`), then retire the
    handful of rows every one of the five questions needs a superseded-row
    exclusion test against.

    Returns the raw `{"entities", "edges", "rejected"}` dict `ingest_facts()`
    returned for the main batch (rejected is always `[]` here — every
    predicate in `_FACTS` is a real one; unknown-predicate rejection is
    exercised by `tests/test_fact_ingest.py`, not this fixture).
    """
    entities = [
        EntityEnvelope(
            entity_id=e.entity_id,
            entity_type=e.entity_type,
            label=e.label,
            source=_SOURCE,
            source_version=_SOURCE_VERSION,
            observed_at=_OBSERVED_AT,
            embedding=e.embedding,
            embedding_model="fixture-deterministic" if e.embedding else None,
            embedding_dim=_EMBEDDING_DIM if e.embedding else None,
        )
        for e in _ENTITIES
    ]
    await ingest_entities(gateway, entities)

    facts = [
        FactEnvelope(
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            properties=properties,
            source=_SOURCE,
            source_version=_SOURCE_VERSION,
            observed_at=_OBSERVED_AT,
            evidence_ref=f"evidence://{subject_id}/{predicate.lower()}/{object_id}",
        )
        for subject_id, predicate, object_id, properties in _FACTS
    ]
    result = await ingest_facts(gateway, facts)

    at = datetime(2026, 8, 5, tzinfo=timezone.utc).isoformat()
    for subject_id, predicate, object_id in _SUPERSEDE_EDGES:
        pred_key = predicate.lower()
        await gateway.run(
            f"capability.supersede_edge__{pred_key}",
            subject_id=subject_id,
            object_id=object_id,
            superseded_by="retired",
            at=at,
            reason="source_removed",
        )
    for entity_id in _SUPERSEDE_ENTITIES:
        await gateway.run(
            "capability.supersede_entity",
            entity_id=entity_id,
            superseded_by="retired",
            at=at,
            reason="source_removed",
        )

    return result
