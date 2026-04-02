# B-128 Plan - DAG Task Graph MCP Tools

Card: B128
Priority: P1
Dependencies: B127

## Summary
Expose execution DAG operations through MCP + BrainClientProtocol so ARC and future agents can register/query/advance/fail task graphs.

## Ecosystem / Ownership
- SideQuests handlers in `mcp_engine/tools/`.
- Interface boundary in `benchmarks/arc3/adapter.py` only.
- No ARC direct imports from `mcp_engine`.

## Technical Approach
1. Add tool schemas:
- `register_task_graph`
- `get_ready_tasks`
- `advance_task`
- `fail_task`
- `get_task_graph`
2. Implement handlers in `mcp_engine/tools/task_graph.py`.
3. Wire exports in `mcp_engine/tools/__init__.py`.
4. Extend `BrainClientProtocol` + Local/NoOp/Ledger clients in `benchmarks/arc3/adapter.py`.
5. Update docs for tool catalog and phase constraints.

## Concrete File Changes
- Modify: `mcp_engine/tool_schemas.py`
- Modify: `mcp_engine/tools/__init__.py`
- Modify/Create: `mcp_engine/tools/task_graph.py`
- Modify: `benchmarks/arc3/adapter.py`
- Modify: `docs/tool-catalog.md`
- Modify: `docs/arc-harness-rules.md`
- Create tests: `tests/test_b128_task_graph_tools.py`

## Test Plan
- `pytest -q tests/test_b128_task_graph_tools.py tests/test_adapters.py`
- `pytest -q tests/test_web.py`

## Acceptance Criteria Mapping
- All five methods callable via Local/NoOp/Ledger clients.
- Cycle errors surfaced from `register_task_graph`.
- Frontier updates after `advance_task` complete/skipped.
- `fail_task` returns blocked dependents.
- `get_task_graph` returns full nodes+edges state.

## Risks / Constraints
- Keep NoOp behavior deterministic for CI/offline runs.
- Ensure ledger wrapper logs new calls consistently.
