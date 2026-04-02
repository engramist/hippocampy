# B-125 Plan - Context-Windowed Recall

Card: B125
Priority: P2
Dependencies: none

## Summary
Improve memory retrieval quality by returning surrounding rationale/context for recalled nodes/facts.

## Ecosystem / Ownership
- Layer: Data Products & Memory (`mcp_engine/tools/`).
- ARC consumes via existing tool interfaces only.

## Technical Approach
1. Extend `explore_graph` with `context_window: int = 0` (max 3).
2. For each result node, fetch temporal/causal neighbors up to N hops as context slices.
3. Extend `current_truth` with `include_rationale: bool = false`.
4. When enabled, attach originating message/rationale context via existing relation traversal.
5. Truncate each context segment to <= 200 chars.
6. Preserve default behavior when new params are omitted.

## Concrete File Changes
- Modify: `mcp_engine/tools/explore_graph.py`
- Modify: `mcp_engine/tools/current_truth.py`
- Modify: `mcp_engine/tools/__init__.py` (schema wiring)
- Modify tests: `tests/test_explore_graph.py`, `tests/test_current_truth.py`

## Test Plan
- `pytest -q tests/test_explore_graph.py tests/test_current_truth.py`
- `pytest -q tests/test_web.py tests/test_adapters.py`

## Acceptance Criteria Mapping
- `context_window=2` includes neighbors.
- `include_rationale=true` includes rationale text.
- Truncation enforced at 200 chars/neighbor.
- Backward compatibility preserved for defaults.

## Risks / Constraints
- Prevent token bloat; enforce strict truncation and max window.
- Keep queries bounded and deterministic.
