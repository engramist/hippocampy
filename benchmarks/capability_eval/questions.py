"""B317 — capability-eval question set.

The five customer questions from the B317 backlog card, each traced BY HAND
against the exact fixture graph `benchmarks/capability_eval/fixtures.py`
seeds (via the real `ingest_entities()`/`ingest_facts()` path) — not
approximated. Every constant here is exact-set, not "returns something":
`tests/test_capability_queries.py` asserts equality (modulo ordering where
the underlying Cypher's `collect(DISTINCT ...)` doesn't guarantee element
order — those fields are compared as sets, documented per-question below).

Mirrors `benchmarks/ask_eval/questions.py`'s role (the hand-checked ground
truth a runner/test asserts against) but not its shape: ask_eval scores
free-text LLM answers by regex, so one generic `QUESTIONS` list of
`{must_match, must_not_match}` works for all 16. This eval instead asserts
exact structured result sets from five *different-shaped* Cypher queries
(a node list, a path-explanation row list, a grouped-by-type impact map, a
producer-lineage row list, a ranked similarity list) — a single generic
comparator would just be a dispatch table in disguise, so this module
exposes one pair of `<QID>_PARAMS` / `<QID>_EXPECTED` constants per question
instead, plus a default/superseded-variant pair for each (every one of the
five customer questions has its own superseded row to exclude-by-default —
see fixtures.py's `_SUPERSEDE_EDGES`/`_SUPERSEDE_ENTITIES`).

`QUESTIONS` at the bottom is a flat summary (id, query name, description)
for the generic checks that DO apply uniformly across all five — registered
under `GraphGateway`, bounded traversal, callable via `gateway.run()`.
"""

from __future__ import annotations

from benchmarks.capability_eval.fixtures import QUERY_EMBEDDING

# ---------------------------------------------------------------------------
# Q1 — capability.permitted_paths
#
# entry_id=cap.deploy_pipeline, trust_tiers=["public"], bounded INVOKES|
# REQUIRES traversal (*1..5). Traced by hand over fixtures.py's Q1/Q2
# cluster:
#
#   deploy_pipeline -INVOKES-> build_artifact           (CONSTRAINED_BY public_access, mode=public)  -> passes
#   deploy_pipeline -INVOKES-> blocked_admin_action      (CONSTRAINED_BY admin_only, mode=elevated)   -> BLOCKED (not in trust_tiers)
#   deploy_pipeline -REQUIRES-> notify_slack             (CONSTRAINED_BY legacy_slack_policy — SUPERSEDED, excluded by default -> no mode -> passes)
#   ...-> build_artifact -REQUIRES-> compile_code        (inherits build_artifact's public mode)      -> passes
#   ...-> compile_code -REQUIRES-> lint_code             (inherits public mode)                       -> passes
#   ...-> compile_code -REQUIRES-> lint_code_old         (SUPERSEDED edge — unreachable by default)
#
# So the default (include_superseded=False) result excludes both
# blocked_admin_action (access-mode gate, not a supersession matter — stays
# excluded even with include_superseded=True) and lint_code_old (only
# reachable through the superseded REQUIRES edge).
# ---------------------------------------------------------------------------

Q1_PARAMS = {
    "entry_id": "cap.deploy_pipeline",
    "trust_tiers": ["public"],
    "include_superseded": False,
}
Q1_EXPECTED = [
    {"entity_id": "cap.build_artifact", "entity_type": "capability", "label": "Build Artifact"},
    {"entity_id": "cap.compile_code", "entity_type": "capability", "label": "Compile Code"},
    {"entity_id": "cap.lint_code", "entity_type": "capability", "label": "Lint Code"},
    {"entity_id": "cap.notify_slack", "entity_type": "capability", "label": "Notify Slack Channel"},
]

Q1_PARAMS_INCLUDE_SUPERSEDED = {**Q1_PARAMS, "include_superseded": True}
# Only cap.lint_code_old reappears — blocked_admin_action is excluded on
# trust-tier grounds, unrelated to supersession, so it never reappears.
Q1_EXPECTED_INCLUDE_SUPERSEDED = sorted(
    Q1_EXPECTED
    + [{"entity_id": "cap.lint_code_old", "entity_type": "capability", "label": "Lint Code (Legacy)"}],
    key=lambda row: row["entity_id"],
)

# ---------------------------------------------------------------------------
# Q2 — capability.explain_path
#
# Two scenarios:
#   (a) "primary" — cap.build_artifact -> cap.compile_code (direct REQUIRES
#       edge, 1 hop): build_artifact carries an ACTIVE (non-superseded)
#       CONSTRAINED_BY policy.public_access, so the primary case proves a
#       real policy explanation with full provenance round-trips.
#   (b) "superseded" — cap.deploy_pipeline -> cap.notify_slack (direct
#       REQUIRES edge, 1 hop): notify_slack's only CONSTRAINED_BY edge
#       (-> policy.legacy_slack_policy) is superseded, so by default the
#       node's policy fields are all NULL; with include_superseded=True the
#       legacy policy reappears. This is Q2's superseded-exclusion proof.
# ---------------------------------------------------------------------------

Q2_PARAMS = {
    "from_id": "cap.build_artifact",
    "to_id": "cap.compile_code",
    "include_superseded": False,
}
Q2_EXPECTED = [
    {
        "node_id": "cap.build_artifact",
        "policy_id": "policy.public_access",
        "policy_label": "Public Access Policy",
        "access_mode": "public",
        "confidence": 0.99,
        "source": "harvest:capability-eval-fixture",
        "evidence_ref": "evidence://cap.build_artifact/constrained_by/policy.public_access",
    },
    {
        "node_id": "cap.compile_code",
        "policy_id": None,
        "policy_label": None,
        "access_mode": None,
        "confidence": None,
        "source": None,
        "evidence_ref": None,
    },
]

Q2_SUPERSEDED_PARAMS = {
    "from_id": "cap.deploy_pipeline",
    "to_id": "cap.notify_slack",
    "include_superseded": False,
}
Q2_SUPERSEDED_EXPECTED = [
    {
        "node_id": "cap.deploy_pipeline",
        "policy_id": None,
        "policy_label": None,
        "access_mode": None,
        "confidence": None,
        "source": None,
        "evidence_ref": None,
    },
    {
        "node_id": "cap.notify_slack",
        "policy_id": None,
        "policy_label": None,
        "access_mode": None,
        "confidence": None,
        "source": None,
        "evidence_ref": None,
    },
]

Q2_SUPERSEDED_PARAMS_INCLUDE_SUPERSEDED = {**Q2_SUPERSEDED_PARAMS, "include_superseded": True}
Q2_SUPERSEDED_EXPECTED_INCLUDE_SUPERSEDED = [
    Q2_SUPERSEDED_EXPECTED[0],
    {
        "node_id": "cap.notify_slack",
        "policy_id": "policy.legacy_slack_policy",
        "policy_label": "Legacy Slack Policy",
        "access_mode": "public",
        "confidence": 0.6,
        "source": "harvest:capability-eval-fixture",
        "evidence_ref": "evidence://cap.notify_slack/constrained_by/policy.legacy_slack_policy",
    },
]

# ---------------------------------------------------------------------------
# Q3 — capability.impact_of
#
# entity_id=infra.terraform_prod_cluster. Reverse-dependency traversal
# (REQUIRES|INVOKES|READS|WRITES|DEPLOYED_ON, *1..4) over EVERY edge in the
# fixture that eventually reaches the cluster — not just the "Q3 cluster"
# comment block, since evidence.build_run_42 (seeded under the "Q4 cluster"
# comment) also has a direct DEPLOYED_ON edge to the same cluster:
#
#   workflow.ci_pipeline      -DEPLOYED_ON->  terraform_prod_cluster   (1 hop)
#   workflow.cd_pipeline      -DEPLOYED_ON->  terraform_prod_cluster   (1 hop)
#   workflow.staging_pipeline -DEPLOYED_ON->  terraform_prod_cluster   (1 hop, SUPERSEDED)
#   evidence.build_run_42     -DEPLOYED_ON->  terraform_prod_cluster   (1 hop)
#   agent.release_bot   -REQUIRES-> ci_pipeline  -DEPLOYED_ON-> ...    (2 hops, diamond leg 1)
#   agent.release_bot   -REQUIRES-> cd_pipeline  -DEPLOYED_ON-> ...    (2 hops, diamond leg 2)
#   policy.deploy_policy -REQUIRES-> ci_pipeline -DEPLOYED_ON-> ...    (2 hops)
#   app.release_dashboard -INVOKES-> agent.release_bot -> ... -> ...  (3 hops, through either diamond leg)
#
# agent.release_bot is reachable via TWO distinct 2-hop paths (through
# ci_pipeline and through cd_pipeline) — the diamond dependency — and must
# appear exactly once in the "agent" group (DISTINCT collection). Grouped
# by entity_type; each group's element order isn't guaranteed by
# `collect(DISTINCT ...)`, so tests compare as sets.
# ---------------------------------------------------------------------------

Q3_PARAMS = {"entity_id": "infra.terraform_prod_cluster", "include_superseded": False}
Q3_EXPECTED = {
    "agent": {"agent.release_bot"},
    "app": {"app.release_dashboard"},
    "evidence": {"evidence.build_run_42"},
    "policy": {"policy.deploy_policy"},
    "workflow": {"workflow.cd_pipeline", "workflow.ci_pipeline"},
}

Q3_PARAMS_INCLUDE_SUPERSEDED = {**Q3_PARAMS, "include_superseded": True}
Q3_EXPECTED_INCLUDE_SUPERSEDED = {
    **Q3_EXPECTED,
    "workflow": Q3_EXPECTED["workflow"] | {"workflow.staging_pipeline"},
}

# ---------------------------------------------------------------------------
# Q4 — capability.lineage_of
#
# artifact_id=app.release_dashboard_v3. Reverse PRODUCED traversal (*1..6):
#
#   evidence.build_run_42 -PRODUCED-> app.release_dashboard_v3        (1 hop)
#   iteration.sprint_14   -PRODUCED-> evidence.build_run_42 -> ...    (2 hops)
#
# For each producer, its APPROVED_BY / READS / DEPLOYED_ON neighbors:
#   evidence.build_run_42: APPROVED_BY approval.release_signoff;
#     READS data.release_config (SUPERSEDED, excluded by default) and
#     data.deploy_manifest (live); DEPLOYED_ON infra.terraform_prod_cluster.
#   iteration.sprint_14: none of the three — every OPTIONAL MATCH fails, so
#     (per capability.py's documented Kùzu quirk) each collect(DISTINCT...)
#     comes back NULL, not [].
# ---------------------------------------------------------------------------

Q4_PARAMS = {"artifact_id": "app.release_dashboard_v3", "include_superseded": False}
Q4_EXPECTED = [
    {
        "producer_id": "evidence.build_run_42",
        "producer_type": "evidence",
        "approved_by": {"approval.release_signoff"},
        "reads": {"data.deploy_manifest"},
        "deployed_on": {"infra.terraform_prod_cluster"},
    },
    {
        "producer_id": "iteration.sprint_14",
        "producer_type": "iteration",
        "approved_by": None,
        "reads": None,
        "deployed_on": None,
    },
]

Q4_PARAMS_INCLUDE_SUPERSEDED = {**Q4_PARAMS, "include_superseded": True}
Q4_EXPECTED_INCLUDE_SUPERSEDED = [
    {
        **Q4_EXPECTED[0],
        "reads": {"data.deploy_manifest", "data.release_config"},
    },
    Q4_EXPECTED[1],
]

# ---------------------------------------------------------------------------
# Q5 — capability.reuse_candidates
#
# query_embedding=QUERY_EMBEDDING (== cap.email_notifier's own embedding, by
# construction — see fixtures.py). Candidates considered (entity_type=
# 'capability', has an embedding):
#
#   cap.email_notifier        similarity=1.00  (identical to the query)
#   cap.mailer_service        similarity=0.90  (near-duplicate; lexically
#                                                dissimilar label — proves
#                                                this is vector, not string,
#                                                matching)
#   cap.unreliable_forwarder  similarity=0.80  (ABOVE the 0.70 floor, but
#                                                REQUIRES cap.broken_dep,
#                                                whose NODE is marked
#                                                superseded at the entity
#                                                level — excluded by the
#                                                satisfiability filter
#                                                regardless of
#                                                include_superseded, proving
#                                                the similarity floor and
#                                                the satisfiability check are
#                                                independent filters)
#   cap.image_resizer         similarity=0.20  (BELOW the 0.70 floor —
#                                                excluded outright, never
#                                                appears in any scenario)
#
# cap.email_notifier's own REQUIRES chain includes an edge-level superseded
# row (-> cap.old_relay_v0) — that's Q5's default-exclusion proof: its
# `requires` set gains cap.old_relay_v0 only with include_superseded=True.
# ---------------------------------------------------------------------------

Q5_PARAMS = {"query_embedding": QUERY_EMBEDDING, "include_superseded": False}
Q5_EXPECTED = [
    {"entity_id": "cap.email_notifier", "label": "Send Email Notification", "similarity": 1.0, "requires": {"cap.smtp_relay"}},
    {"entity_id": "cap.mailer_service", "label": "Mailer Dispatch Unit", "similarity": 0.90, "requires": {"cap.smtp_relay"}},
]

Q5_PARAMS_INCLUDE_SUPERSEDED = {**Q5_PARAMS, "include_superseded": True}
Q5_EXPECTED_INCLUDE_SUPERSEDED = [
    {**Q5_EXPECTED[0], "requires": {"cap.smtp_relay", "cap.old_relay_v0"}},
    Q5_EXPECTED[1],
]

# Entities that must NEVER appear in any Q5 scenario, regardless of
# include_superseded — the below-floor entity (excluded by the similarity
# floor) and the above-floor-but-unsatisfiable entity (excluded by the
# satisfiability filter, independently of supersession inclusion).
Q5_NEVER_APPEARS = {"cap.image_resizer", "cap.unreliable_forwarder"}

# ---------------------------------------------------------------------------
# Flat summary for the generic checks that apply to all five uniformly.
# ---------------------------------------------------------------------------

QUESTIONS: list[dict] = [
    {
        "id": "Q1",
        "name": "capability.permitted_paths",
        "description": "Given a user/trust-tier, what capability path is allowed?",
    },
    {
        "id": "Q2",
        "name": "capability.explain_path",
        "description": "Why was this path selected or blocked?",
    },
    {
        "id": "Q3",
        "name": "capability.impact_of",
        "description": "If this adapter changes, what's affected?",
    },
    {
        "id": "Q4",
        "name": "capability.lineage_of",
        "description": "What produced this artifact?",
    },
    {
        "id": "Q5",
        "name": "capability.reuse_candidates",
        "description": "Can an existing capability chain satisfy this request?",
    },
]
