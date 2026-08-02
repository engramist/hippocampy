"""B304 — ask-eval question set.

16 questions across 5 families, scored by deterministic regex (no LLM judge).
Regexes are matched case-insensitively. See scoring rules in runner.py.
"""

from __future__ import annotations

# Shared "correctly abstained" pattern for negative-control questions. Broadened
# 2026-08-02 after a live eval run showed the original per-question regex only
# recognized llama3.1:8b's exact phrasing ("I don't have...") and scored three
# other models' equally-correct-but-differently-worded abstentions as failures —
# including gemma4:e2b's answer, which was verbatim Campy's own canonical
# empty-bundle message from ask.py ("No relevant context was found in memory
# for this query."). Covers: "no information/record/memory/context", "do/does
# not have/contain" (with or without the contraction), "not found/mentioned",
# "empty". One shared constant so N1-N4 can't drift out of sync with each other
# again (the pre-fix versions already had — N1 included "memory", N2/N3 didn't).
_ABSTENTION_RE = (
    r"\bno (?:relevant )?(?:information|record|memory|context)\b"
    r"|\b(?:do|does)\s*(?:n't|not)\s+(?:have|contain)\b"
    r"|\bnot (?:found|mentioned)\b"
    r"|\bempty\b"
)

QUESTIONS: list[dict] = [
    # --- Identifier recall (4) ---
    {
        "id": "I1",
        "family": "identifier",
        "question": "What work was done on B292?",
        "must_match": [r"split", r"__init__|module"],
        "must_not_match": [r"no (information|memory)|memory is empty"],
    },
    {
        "id": "I2",
        "family": "identifier",
        "question": "What happened with B293?",
        "must_match": [r"schema|tool_schemas", r"generat"],
        "must_not_match": [r"memory is empty"],
    },
    {
        "id": "I3",
        "family": "identifier",
        "question": "What did the work on B298 accomplish?",
        "must_match": [r"auto.?memory|memory file|piggyback", r"notify_turn|hook"],
        "must_not_match": [r"memory is empty"],
    },
    {
        "id": "I4",
        "family": "identifier",
        "question": "Was B292 completed successfully?",
        "must_match": [r"complete|succeed|success|done"],
        "must_not_match": [r"fail|memory is empty"],
    },
    # --- Paraphrase recall, no identifiers (4) ---
    {
        "id": "P1",
        "family": "paraphrase",
        "question": "Who or what split the big tools module into smaller files?",
        "must_match": [r"B292|__init__|domain modules"],
        "must_not_match": [r"memory is empty"],
    },
    {
        "id": "P2",
        "family": "paraphrase",
        "question": "How do I add a new MCP tool the right way?",
        "must_match": [r"tool_schemas", r"TOOL_HANDLERS|generate_extension_tools"],
        "must_not_match": [r"memory is empty"],
    },
    {
        "id": "P3",
        "family": "paraphrase",
        "question": "Why did a maintenance command fail with a database lock error?",
        "must_match": [r"single.?writer|daemon"],
        "must_not_match": [r"memory is empty"],
    },
    {
        "id": "P4",
        "family": "paraphrase",
        "question": "What license did we pick?",
        "must_match": [r"Apache"],
        "must_not_match": [r"MIT|GPL|memory is empty"],
    },
    # --- Cross-lane (2) ---
    {
        "id": "X1",
        "family": "cross_lane",
        "question": "What lessons came out of the tooling work?",
        "must_match": [r"tool_schemas|regenerate"],
        "must_not_match": [r"memory is empty"],
    },
    {
        "id": "X2",
        "family": "cross_lane",
        "question": "Summarize everything we know about the extension tool surface.",
        "must_match": [r"schema|generat"],
        "must_not_match": [r"memory is empty"],
    },
    # --- Continuation (2) ---
    {
        "id": "C1",
        "family": "continuation",
        "question": "What was the plan for the module split and did every step finish?",
        "must_match": [r"aggregator|parity|steps", r"complete|succeed|finish"],
        "must_not_match": [r"memory is empty"],
    },
    {
        "id": "C2",
        "family": "continuation",
        "question": "What port does the daemon use?",
        "must_match": [r"7799"],
        "must_not_match": [r"memory is empty"],
    },
    # --- Negative controls — anti-hallucination gate (4) ---
    {
        "id": "N1",
        "family": "negative_control",
        "question": "What did we decide about Kubernetes deployment?",
        "must_match": [_ABSTENTION_RE],
        "must_not_match": [r"kubernetes.*(cluster|helm|deploy(ed|ment) (is|was|uses))"],
    },
    {
        "id": "N2",
        "family": "negative_control",
        "question": "Who is the database administrator?",
        "must_match": [_ABSTENTION_RE],
        "must_not_match": [],
    },
    {
        "id": "N3",
        "family": "negative_control",
        "question": "What did we conclude about the React frontend rewrite?",
        "must_match": [_ABSTENTION_RE],
        "must_not_match": [r"react.*(chose|decided|rewrote)"],
    },
    {
        "id": "N4",
        "family": "negative_control",
        "question": "When is the production launch date?",
        "must_match": [_ABSTENTION_RE],
        "must_not_match": [r"\b20\d\d-\d\d-\d\d\b"],
    },
]
