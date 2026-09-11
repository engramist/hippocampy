# B-42 Plan — Concept→Artifact Retrieval Contract Documentation

## Goal
Implement backlog card B42 by producing a clear retrieval contract document that defines how `current_truth` and graph traversal behave across concept and artifact layers.

## Inputs
- `backlog/B42.md`
- `CLAUDE.md`
- `mcp_engine/tools.py`
- `mcp_engine/loop/orchestrator.py`
- existing docs in `docs/` (especially retrieval/architecture docs)

## Deliverables
1. Create or update `docs/retrieval-contract.md` with sections:
- Purpose and scope
- Data layers (`Concept`, `REIFIED_AS`, artifact nodes)
- `current_truth` return-shape rules
- Ranking semantics (pathway_strength, confidence, similarity)
- `explore_graph` + `REIFIED_AS` traversal behavior
- 3+ concrete query examples with expected outputs
- Known limits and non-goals
2. Update `backlog/B42.md`
- Add implementation note and doc path reference.

## Implementation Steps
1. Read existing retrieval and tool behavior from code and docs.
2. Write a normative contract (MUST/SHOULD language where useful).
3. Include examples that cover:
- artifact-first question
- concept-only fallback
- mixed result interpretation
4. Ensure consistency with current implementation (no speculative behavior).

## Constraints
- Documentation only, no functional code changes.
- No API schema changes.
- Keep terminology aligned with `CLAUDE.md`.

## Validation
- `grep -n "current_truth\|REIFIED_AS\|explore_graph" docs/retrieval-contract.md`
- Verify examples reference actual field names used by tools.

## Definition of Done
- Retrieval contract is explicit, testable, and implementation-aligned.
- B42 links to the final contract doc location.
