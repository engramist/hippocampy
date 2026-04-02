# B-129 Plan - Task Graph API/Test Alignment

Card: B129
Priority: P1
Dependencies: B127, B128

## Summary

Fix stale task-graph test expectations so schema/tool tests match the finalized B128 API surface.

## Ecosystem / Ownership

- Layer: Data Products & Memory (`mcp_engine/tools/`) and test harness (`tests/`).
- No ARC runtime behavior changes.

## Technical Approach

1. Audit exported functions in `mcp_engine/tools/task_graph.py`.
2. Align `tests/test_b127_dag_schema.py` imports/usages to current function names.
3. Preserve B128 tool behavior and adapter integrations.
4. Re-run focused suites and then full regression sweep.

## Concrete File Changes

- `mcp_engine/tools/task_graph.py` (only if explicit compatibility alias/export is needed)
- `tests/test_b127_dag_schema.py`
- `tests/test_b128_dag_tools.py` (if expected surface needs minor test normalization)

## Validation Commands

- `pytest -q tests/test_b127_dag_schema.py`
- `pytest -q tests/test_b128_dag_tools.py tests/test_adapters.py`
- `pytest -q`

## Risks / Constraints

- Keep changes minimal and test-focused.
- Do not break B128 MCP tool contract names.