"""B317 — the customer's five questions, as executable query calls with
expected result sets against `fixtures.py`'s seeded graph.

Mirrors `benchmarks/ask_eval/questions.py`'s "list of dicts" structure,
adapted for exact-set scoring (this suite is a regression/conformance
check, not an LLM-judged eval — see this directory's README.md) rather
than regex-scored free text. Each entry names the registered
`GraphGateway` query, the params to call it with, and the expected
result — `tests/test_capability_queries.py` is the actual grader; this
module exists so the expectations live next to the questions instead of
being duplicated inline in the test file.

Superseded-edge exclusion and the Q5 unsatisfiable-dependency case are
NOT expressed here — they need a direct `GraphGateway.run()` call between
seeding and querying (marking a specific edge/entity superseded without a
replacement) that doesn't fit this static "seed once, then ask" shape.
Those live as dedicated test functions in `test_capability_queries.py`.
"""

from __future__ import annotations

from benchmarks.capability_eval.fixtures import (
    APPROVER_RELEASE_MGR,
    APPROVER_SECURITY_TEAM,
    ARTIFACT_INTERMEDIATE,
    ARTIFACT_QUOTE_REPORT,
    CAP_DIAMOND_MID_A,
    CAP_DIAMOND_MID_B,
    CAP_DIAMOND_ROOT,
    CAP_DIAMOND_TOP,
    CAP_DUP_1,
    CAP_DUP_2,
    CAP_ENTRY,
    CAP_GUARDED_1,
    CAP_GUARDED_2,
    CAP_OPEN_1,
    CAP_OPEN_2,
    CAP_OPEN_3,
    CAP_REUSE_SATISFIABLE,
    CAP_REUSE_UNSATISFIABLE,
    MCP_CATALOG_LOOKUP,
    MCP_UNSATISFIABLE_DEP,
    RUN_BUILD_482,
)

QUESTIONS: list[dict] = [
    # --- Q1: "Given this user, intent, trust tier and policy set, what
    # capability path is allowed?" ---
    {
        "id": "Q1",
        "query": "capability.permitted_paths",
        "question": "What capability path is allowed from the quote-design entry point, "
                     "for a caller at the 'public' trust tier?",
        "params": {"entry_id": CAP_ENTRY, "trust_tier": "public", "include_superseded": False},
        "expected_entity_ids": {CAP_OPEN_1, CAP_OPEN_2, CAP_OPEN_3},
        "expected_hops": {CAP_OPEN_1: 1, CAP_OPEN_2: 2, CAP_OPEN_3: 3},
        "excluded_entity_ids": {CAP_GUARDED_1, CAP_GUARDED_2},  # blocked: elevated-tier policy
    },
    {
        "id": "Q1-elevated",
        "query": "capability.permitted_paths",
        "question": "Same, but for a caller at the 'elevated' trust tier — the guarded "
                     "refund-issue/approve branch should now be reachable too.",
        "params": {"entry_id": CAP_ENTRY, "trust_tier": "elevated", "include_superseded": False},
        "expected_entity_ids": {CAP_OPEN_1, CAP_OPEN_2, CAP_OPEN_3, CAP_GUARDED_1, CAP_GUARDED_2},
        "expected_hops": {CAP_OPEN_1: 1, CAP_OPEN_2: 2, CAP_OPEN_3: 3, CAP_GUARDED_1: 1, CAP_GUARDED_2: 2},
        "excluded_entity_ids": set(),
    },

    # --- Q2: "Why was this path selected or blocked?" ---
    {
        "id": "Q2-open",
        "query": "capability.explain_path",
        "question": "Why is CAP_ENTRY -> CAP_OPEN_1 on the permitted path?",
        "params": {"pairs": [{"from": CAP_ENTRY, "to": CAP_OPEN_1}], "include_superseded": False},
        "expected_edges": [
            {"from_id": CAP_ENTRY, "to_id": CAP_OPEN_1, "predicate": "FACT_REQUIRES", "edge_confidence": 0.9},
        ],
    },
    {
        "id": "Q2-blocked",
        "query": "capability.explain_path",
        "question": "Why is CAP_ENTRY -> CAP_GUARDED_1 blocked at the public trust tier?",
        "params": {"pairs": [{"from": CAP_ENTRY, "to": CAP_GUARDED_1}], "include_superseded": False},
        "expected_edges": [
            {"from_id": CAP_ENTRY, "to_id": CAP_GUARDED_1, "predicate": "FACT_REQUIRES", "edge_confidence": 0.9},
        ],
        "expected_blocking_policy_entity_id": None,  # CONSTRAINED_BY is on CAP_GUARDED_1 itself, not this edge's source
    },

    # --- Q3: "If this adapter changes, which agents, workflows, apps and
    # policies are affected?" ---
    {
        "id": "Q3-diamond",
        "query": "capability.impact_of",
        "question": "If the shared-auth capability changes, what's impacted? "
                     "(diamond dependency — must not double-count CAP_DIAMOND_TOP)",
        "params": {"entity_id": CAP_DIAMOND_ROOT, "include_superseded": False},
        "expected_entity_ids": {CAP_DIAMOND_MID_A, CAP_DIAMOND_MID_B, CAP_DIAMOND_TOP},
        "expected_hops": {CAP_DIAMOND_MID_A: 1, CAP_DIAMOND_MID_B: 1, CAP_DIAMOND_TOP: 2},
        "expected_row_count": 3,  # the dedup proof: not 4 (which a naive non-deduped join would give)
    },

    # --- Q4: "Which skills, tools, data, approvals and infrastructure
    # produced this artifact?" (SYNTHETIC fixture entities — see
    # fixtures.py's module docstring; unverifiable against the real
    # platform until Artifact/Infrastructure IDs exist there.) ---
    {
        "id": "Q4",
        "query": "capability.lineage_of",
        "question": "What produced the quote report artifact?",
        "params": {"artifact_id": ARTIFACT_QUOTE_REPORT, "include_superseded": False},
        "expected_entity_ids": {ARTIFACT_INTERMEDIATE, RUN_BUILD_482},
        "expected_hops": {ARTIFACT_INTERMEDIATE: 1, RUN_BUILD_482: 2},
        "expected_approved_by": {
            ARTIFACT_INTERMEDIATE: {APPROVER_SECURITY_TEAM},
            RUN_BUILD_482: {APPROVER_RELEASE_MGR},
        },
    },

    # --- Q5: "Can an existing chain of capabilities satisfy the request
    # without building something new?" ---
    {
        "id": "Q5-near-duplicate",
        "query": "capability.reuse_candidates",
        "question": "Is there an existing capability similar enough to CAP_DUP_1 to reuse "
                     "instead of building something new? (near-duplicate pair, lexically "
                     "dissimilar labels — must be found by embedding similarity, not string match)",
        "exclude_entity_id": CAP_DUP_1,
        "floor": 0.70,
        "expected_entity_ids": {CAP_DUP_2},
    },
    {
        "id": "Q5-satisfiable",
        "query": "capability.reuse_candidates",
        "question": "Reuse candidates whose REQUIRES are satisfiable vs. not.",
        "exclude_entity_id": "__none__",
        "floor": 0.70,
        # This entry documents intent; the actual query-embedding construction
        # (which must make CAP_REUSE_SATISFIABLE/CAP_REUSE_UNSATISFIABLE both
        # score above the floor) lives in test_capability_queries.py, since it
        # depends on the test's monkeypatched embedding function.
        "expected_satisfiable": {CAP_REUSE_SATISFIABLE: True, CAP_REUSE_UNSATISFIABLE: False},
        "requires_targets": {
            CAP_REUSE_SATISFIABLE: MCP_CATALOG_LOOKUP,
            CAP_REUSE_UNSATISFIABLE: MCP_UNSATISFIABLE_DEP,
        },
    },
]
