"""B317 — deterministic fixture graph for the capability-conformance suite.

Writes known content through the real ingest handlers
(`campy.brain.hippocampus.facts.ingest_entities` / `ingest_facts`) — never
raw Cypher — so the eval exercises genuine ingest-path output, matching
`benchmarks/ask_eval/fixtures.py`'s convention.

**Scope note (read before adding entities):** per backlog/B317.md's
post-card scope narrowing, the customer's stable-identifier audit found
only three entity types with a usable stable identifier in the real
platform today: `capability`, `agent`, `mcp_tool`. Every entity of any
other `entity_type` in this fixture (`policy`, `dataset`, `infrastructure`,
`artifact`, `run`, `approver`) is a **structural stand-in**, not a
plausible real identifier — its `entity_id` is prefixed `synthetic:` so
that is never mistaken for real data, and none of it should be presented
as representative of the real platform's graph. It exists only so the
predicates that inherently need those types (`CONSTRAINED_BY`,
`DEPLOYED_ON`, `PRODUCED`, `APPROVED_BY`, `READS`, `WRITES`) have
something to point at, and so `capability.lineage_of` (Q4) is exercised
end-to-end even though it is, by the same audit, unverifiable against the
real platform until Artifact/Infrastructure IDs exist there. See this
directory's README.md and the B317 PR description for the full story.

Deliberate difficulty built into the graph (see questions.py for which
question exercises which piece):
  - a blocked path (CAP_GUARDED_1 gated by an `elevated`-tier policy)
  - a superseded edge (CAP_ENTRY's original REQUIRES edge to CAP_OPEN_1,
    re-ingested at a newer source_version)
  - two near-duplicate capabilities with **lexically dissimilar** labels
    but near-identical embeddings (CAP_DUP_1 / CAP_DUP_2) — Q5 must find
    this pair by embedding similarity, not by string overlap
  - a diamond dependency (CAP_DIAMOND_TOP depends on both
    CAP_DIAMOND_MID_A and CAP_DIAMOND_MID_B, both of which depend on
    CAP_DIAMOND_ROOT) — Q3 must not double-count CAP_DIAMOND_TOP
"""

from __future__ import annotations

from datetime import datetime, timezone

from campy.brain.hippocampus.facts import (
    FactEntityEnvelope,
    FactEnvelope,
    ingest_entities,
    ingest_facts,
)

SOURCE = "harvest:capability-catalog"
SOURCE_V1 = "v1"
SOURCE_V2 = "v2"

_SEED_TIME = datetime(2026, 6, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Entity IDs — real (joinable) types use the customer's own ID conventions;
# synthetic types are prefixed `synthetic:` (see module docstring).
# ---------------------------------------------------------------------------

# Agents (directory-name convention)
AGENT_CLAUDE_CODE = "claude-code"
AGENT_CLAUDE_DESIGN = "claude-design"
AGENT_GEMINI_CLI = "gemini-cli"
AGENT_CODEX = "codex-agent"
AGENT_OPS_BOT = "ops-bot"

# Capabilities (agent/<name> convention)
CAP_ENTRY = "agent/claude-design"
CAP_OPEN_1 = "agent/quote-draft"
CAP_OPEN_2 = "agent/quote-price"
CAP_OPEN_3 = "agent/quote-finalize"
CAP_GUARDED_1 = "agent/refund-issue"
CAP_GUARDED_2 = "agent/refund-approve"
CAP_DUP_1 = "agent/quote-verify-fast"
CAP_DUP_2 = "agent/velocity-check-svc"  # near-duplicate of DUP_1, lexically dissimilar label
CAP_DIAMOND_ROOT = "agent/shared-auth"
CAP_DIAMOND_MID_A = "agent/billing-flow"
CAP_DIAMOND_MID_B = "agent/support-flow"
CAP_DIAMOND_TOP = "agent/customer-portal"
CAP_STANDALONE = "agent/standalone-util"
CAP_REUSE_SATISFIABLE = "agent/reuse-satisfiable"
CAP_REUSE_UNSATISFIABLE = "agent/reuse-unsatisfiable"
CAP_REUSE_TARGET = "agent/reuse-target"

# MCP tools (service/<server>#<tool> convention)
MCP_QUOTE_VERIFY = "service/servicesmcp#quote.verify"
MCP_DOC_SEARCH = "service/servicesmcp#doc.search"
MCP_FILE_WRITE = "service/servicesmcp#file.write"
MCP_DATA_READ = "service/servicesmcp#data.read"
MCP_INFRA_DEPLOY = "service/servicesmcp#infra.deploy"
MCP_CATALOG_LOOKUP = "service/servicesmcp#catalog.lookup"
MCP_UNSATISFIABLE_DEP = "service/servicesmcp#retired.endpoint"  # torn down; edge to it gets superseded

# Synthetic (structural stand-ins only — see module docstring)
POLICY_ELEVATED = "synthetic:policy/elevated-tier"
DATASET_CUSTOMER_RECORDS = "synthetic:dataset/customer-records"
DATASET_AUDIT_LOG = "synthetic:dataset/audit-log"
INFRA_PROD_CLUSTER = "synthetic:infra/prod-cluster"
ARTIFACT_QUOTE_REPORT = "synthetic:artifact/quote-report-v1"
ARTIFACT_INTERMEDIATE = "synthetic:artifact/intermediate-dataset-v1"
RUN_BUILD_482 = "synthetic:run/build-482"
APPROVER_RELEASE_MGR = "synthetic:approver/release-manager"
APPROVER_SECURITY_TEAM = "synthetic:approver/security-team"

REAL_ENTITY_TYPES = frozenset({"capability", "agent", "mcp_tool"})


def _entity(entity_id: str, entity_type: str, label: str, *, source_version: str = SOURCE_V1) -> FactEntityEnvelope:
    return FactEntityEnvelope(
        entity_id=entity_id,
        entity_type=entity_type,
        label=label,
        source=SOURCE,
        source_version=source_version,
        observed_at=_SEED_TIME,
        evidence_ref=f"fixture:{entity_id}",
    )


def _fact(subject_id: str, predicate: str, object_id: str, *, properties: dict | None = None,
          source_version: str = SOURCE_V1, evidence_ref: str | None = None) -> FactEnvelope:
    return FactEnvelope(
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        source=SOURCE,
        source_version=source_version,
        properties=properties or {},
        observed_at=_SEED_TIME,
        evidence_ref=evidence_ref or f"fixture:{subject_id}->{predicate}->{object_id}",
    )


_ENTITIES = [
    _entity(AGENT_CLAUDE_CODE, "agent", "Claude Code"),
    _entity(AGENT_CLAUDE_DESIGN, "agent", "Claude Design"),
    _entity(AGENT_GEMINI_CLI, "agent", "Gemini CLI"),
    _entity(AGENT_CODEX, "agent", "Codex Agent"),
    _entity(AGENT_OPS_BOT, "agent", "Ops Bot"),

    _entity(CAP_ENTRY, "capability", "Quote design entry point"),
    _entity(CAP_OPEN_1, "capability", "Draft a quote"),
    _entity(CAP_OPEN_2, "capability", "Price a quote"),
    _entity(CAP_OPEN_3, "capability", "Finalize a quote"),
    _entity(CAP_GUARDED_1, "capability", "Issue a refund"),
    _entity(CAP_GUARDED_2, "capability", "Approve a refund"),
    _entity(CAP_DUP_1, "capability", "Fast quote verification pass"),
    _entity(CAP_DUP_2, "capability", "Velocity checking service for quotes"),
    _entity(CAP_DIAMOND_ROOT, "capability", "Shared authentication check"),
    _entity(CAP_DIAMOND_MID_A, "capability", "Billing workflow"),
    _entity(CAP_DIAMOND_MID_B, "capability", "Support workflow"),
    _entity(CAP_DIAMOND_TOP, "capability", "Customer portal"),
    _entity(CAP_STANDALONE, "capability", "Standalone utility capability"),
    _entity(CAP_REUSE_SATISFIABLE, "capability", "Reuse candidate with satisfiable deps"),
    _entity(CAP_REUSE_UNSATISFIABLE, "capability", "Reuse candidate with unsatisfiable deps"),
    _entity(CAP_REUSE_TARGET, "capability", "Existing chain a new request could reuse"),

    _entity(MCP_QUOTE_VERIFY, "mcp_tool", "Quote verification tool"),
    _entity(MCP_DOC_SEARCH, "mcp_tool", "Document search tool"),
    _entity(MCP_FILE_WRITE, "mcp_tool", "File write tool"),
    _entity(MCP_DATA_READ, "mcp_tool", "Data read tool"),
    _entity(MCP_INFRA_DEPLOY, "mcp_tool", "Infra deploy tool"),
    _entity(MCP_CATALOG_LOOKUP, "mcp_tool", "Catalog lookup tool"),
    _entity(MCP_UNSATISFIABLE_DEP, "mcp_tool", "Retired endpoint (torn down)"),

    _entity(POLICY_ELEVATED, "policy", "Elevated trust tier required"),
    _entity(DATASET_CUSTOMER_RECORDS, "dataset", "Customer records dataset"),
    _entity(DATASET_AUDIT_LOG, "dataset", "Audit log dataset"),
    _entity(INFRA_PROD_CLUSTER, "infrastructure", "Production cluster"),
    _entity(ARTIFACT_QUOTE_REPORT, "artifact", "Quote report v1"),
    _entity(ARTIFACT_INTERMEDIATE, "artifact", "Intermediate dataset v1"),
    _entity(RUN_BUILD_482, "run", "Build #482"),
    _entity(APPROVER_RELEASE_MGR, "approver", "Release manager"),
    _entity(APPROVER_SECURITY_TEAM, "approver", "Security team"),
]

# Facts ingested at v1 (the "current" state of the fixture, minus the one
# deliberately-superseded edge below).
_FACTS_V1 = [
    # INVOKES
    _fact(AGENT_CLAUDE_CODE, "INVOKES", CAP_ENTRY, properties={"confidence": 0.95}),

    # REQUIRES — open chain (permitted at trust_tier='public')
    _fact(CAP_OPEN_1, "REQUIRES", CAP_OPEN_2, properties={"confidence": 0.9}),
    _fact(CAP_OPEN_2, "REQUIRES", CAP_OPEN_3, properties={"confidence": 0.9}),

    # REQUIRES — guarded chain (blocked at trust_tier='public', open at 'elevated')
    _fact(CAP_ENTRY, "REQUIRES", CAP_GUARDED_1, properties={"confidence": 0.9}),
    _fact(CAP_GUARDED_1, "REQUIRES", CAP_GUARDED_2, properties={"confidence": 0.9}),

    # REQUIRES — diamond dependency (CAP_DIAMOND_TOP reachable via two paths from ROOT)
    _fact(CAP_DIAMOND_MID_A, "REQUIRES", CAP_DIAMOND_ROOT, properties={"confidence": 0.9}),
    _fact(CAP_DIAMOND_MID_B, "REQUIRES", CAP_DIAMOND_ROOT, properties={"confidence": 0.9}),
    _fact(CAP_DIAMOND_TOP, "REQUIRES", CAP_DIAMOND_MID_A, properties={"confidence": 0.9}),
    _fact(CAP_DIAMOND_TOP, "REQUIRES", CAP_DIAMOND_MID_B, properties={"confidence": 0.9}),

    # REQUIRES — reuse-candidate satisfiability (Q5)
    _fact(CAP_REUSE_SATISFIABLE, "REQUIRES", MCP_CATALOG_LOOKUP, properties={"confidence": 0.9}),
    _fact(CAP_REUSE_UNSATISFIABLE, "REQUIRES", MCP_UNSATISFIABLE_DEP, properties={"confidence": 0.9}),

    # IMPLEMENTS
    _fact(MCP_QUOTE_VERIFY, "IMPLEMENTS", CAP_ENTRY, properties={"confidence": 0.85}),

    # READS / WRITES
    _fact(CAP_OPEN_2, "READS", DATASET_CUSTOMER_RECORDS, properties={"access_mode": "read-only"}),
    _fact(CAP_OPEN_3, "WRITES", DATASET_AUDIT_LOG, properties={"access_mode": "append-only"}),

    # CONSTRAINED_BY — the trust-tier gate
    _fact(CAP_GUARDED_1, "CONSTRAINED_BY", POLICY_ELEVATED, properties={"access_mode": "elevated", "confidence": 1.0}),

    # DEPLOYED_ON
    _fact(CAP_OPEN_3, "DEPLOYED_ON", INFRA_PROD_CLUSTER, properties={"confidence": 1.0}),

    # PRODUCED — reverse-lineage chain for Q4 (2 hops: report <- intermediate <- build)
    _fact(ARTIFACT_INTERMEDIATE, "PRODUCED", ARTIFACT_QUOTE_REPORT, properties={"confidence": 0.9}),
    _fact(RUN_BUILD_482, "PRODUCED", ARTIFACT_INTERMEDIATE, properties={"confidence": 0.9}),

    # APPROVED_BY — attached to nodes along the PRODUCED chain
    _fact(RUN_BUILD_482, "APPROVED_BY", APPROVER_RELEASE_MGR, properties={"confidence": 1.0}),
    _fact(ARTIFACT_INTERMEDIATE, "APPROVED_BY", APPROVER_SECURITY_TEAM, properties={"confidence": 1.0}),

    # REUSES
    _fact(CAP_ENTRY, "REUSES", CAP_REUSE_TARGET, properties={"confidence": 0.7}),
]

# The one deliberately-superseded edge: CAP_ENTRY originally required
# CAP_OPEN_1 directly (v1); re-ingested at v2 pointing at the same target
# but with a different confidence, so the v1 edge is superseded and only
# reachable with include_superseded=True. Kept separate from _FACTS_V1 so
# seed_fixture_graph can ingest v1 first, then v2, producing a real
# supersession (not just a v1-only edge).
_SUPERSEDED_FACT_V1 = _fact(CAP_ENTRY, "REQUIRES", CAP_OPEN_1, properties={"confidence": 0.5},
                            evidence_ref="fixture:superseded-v1")
_SUPERSEDED_FACT_V2 = _fact(CAP_ENTRY, "REQUIRES", CAP_OPEN_1, properties={"confidence": 0.9},
                             source_version=SOURCE_V2, evidence_ref="fixture:superseded-v2")

# An unknown predicate, deliberately included so ingest's rejection path is
# exercised through the same seed call the rest of the fixture goes
# through (mirrors ask_eval/fixtures.py seeding everything via real
# handlers) rather than only in a synthetic unit test.
_REJECTED_FACT = FactEnvelope(
    subject_id=CAP_ENTRY, predicate="ENDORSES", object_id=CAP_OPEN_1,
    source=SOURCE, source_version=SOURCE_V1, properties={}, observed_at=_SEED_TIME,
)


async def seed_fixture_graph(db, config: dict) -> dict:
    """Seed the B317 capability-conformance fixture via the real ingest
    handlers (`ingest_entities` / `ingest_facts`) — never raw Cypher.

    Returns the combined ingest results (entities/edges/rejected across all
    calls) so callers/tests can sanity-check the seed itself.
    """
    entity_result = await ingest_entities(db, _ENTITIES)

    fact_result_v1 = await ingest_facts(db, _FACTS_V1 + [_SUPERSEDED_FACT_V1, _REJECTED_FACT])
    fact_result_v2 = await ingest_facts(db, [_SUPERSEDED_FACT_V2])

    return {
        "entities": entity_result,
        "facts_v1": fact_result_v1,
        "facts_v2": fact_result_v2,
    }
