# B-91-passive-graph-preactivation — Passive Graph Pre-Activation for Likely-Needed Retrieval

**Card:** B91 | **Priority:** P2 | **Depends on:** B90, B17, B18

## Summary

Prototype a graph-native warm frontier so passive SideQuests processes pre-activate likely-needed nodes and paths before the active agent asks for them. The warmer needs richer initial input and observed-effect signals so it can pattern-match on the right entities and paths instead of generic prompt text.

## Technical Approach

### Activation Model
- derive activation from recent session entities, concept/artifact links, and nearby graph neighborhoods
- maintain a bounded warm set rather than an unbounded cache
- expose retrieval preference for warm items while preserving fallback to normal ranking
- ingest a richer first-input packet with stable ids, key entities, and concise observed-effect summaries
- score activation on recent deltas and path proximity rather than narrative verbosity

### Graph-Native Fit
- use traversal and neighborhood scoring rather than relational-style broad scans
- prefer stable domain ids and bounded path exploration
- model the warm frontier as a compact set of likely-next-use entities, not a transcript of everything seen

## Concrete File Changes

- extend hippocampus or working-memory logic with activation scoring
- update retrieval behavior to consider the warm frontier
- document the retrieval contract and architectural principle
- add targeted tests for activation and fallback behavior

## API/Schema/Test Updates

- avoid new public tool surface unless needed
- if persistence is introduced, keep the schema minimal and justified
- add focused retrieval and hippocampus tests

## Acceptance Criteria

1. A bounded warm frontier is computed from recent activity
2. Retrieval can prefer warm items when confidence is adequate
3. Retrieval falls back cleanly when the warm frontier is empty or weak
4. Activation scoring can consume a richer first-input packet and recent observed effects
5. Tests validate activation scoring, bounded size, preference, and fallback

## Validation Commands

- `.venv/bin/pytest -q tests/test_hippocampus.py`
- `.venv/bin/pytest -q tests/test_retrieval.py`

## Notes on Risks or Constraints

- Keep the warm frontier explainable; hidden magic will be hard to debug
- Guard against supernode fan-out and unbounded traversal
