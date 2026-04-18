# B-219 Plan - Fix `register_task_graph` Kuzu Parser Failure on `TaskNode` Creation

## Card

- B219
- Title: Fix `register_task_graph` Kuzu Parser Failure on `TaskNode` Creation
- Priority: P0
- State: ready

## Summary

Repair the SideQuests task-graph write path so the published `register_task_graph` MCP tool works in real MCP-backed ARC usage. The current failure occurs during `TaskNode` creation inside `mcp_engine/tools/task_graph.py`, producing a Kuzu parser exception before the DAG can be persisted.

## Implementation Approach

1. Reproduce the failure with the smallest possible registration payload.
2. Narrow the parser break to the exact unsupported Cypher shape or expression.
3. Replace the failing write with a Kuzu-compatible sequence that still preserves the B128 contract.
4. Add a regression test that fails on the old query shape and passes on the new one.
5. Re-run the MCP-backed smoke or an equivalent integration path to confirm the tool now registers graphs successfully.

## Concrete File Edits

- `mcp_engine/tools/task_graph.py`
  - inspect `register_task_graph`
  - isolate the failing `TaskNode` create statement
  - rewrite it into the most Kuzu-compatible form available
  - prefer simpler write steps if needed:
    - create node
    - match graph
    - create `TASK_OF`
  - keep response schema unchanged
- `tests/test_b128_task_graph_tools.py`
  - add regression coverage for:
    - single-task registration
    - multi-task registration with at least one dependency edge
  - assert the response includes `graph_id`, `task_ids`, `ready_tasks`, and `cycle_errors`
- `docs/tool-catalog.md`
  - update only if a contract clarification is needed

## Investigation Targets

Check these likely incompatibilities in the current Kuzu version/runtime:

- multi-clause `CREATE ... WITH ... MATCH ... CREATE` shape
- inline function/property expression like `timestamp($now)`
- reserved-word or parser sensitivity around property names
- parameter binding behavior in node creation for `TaskNode`

## Tests To Add

- focused regression in `tests/test_b128_task_graph_tools.py`
- if the existing test suite already covers registration success, add a case that specifically exercises the previously failing `TaskNode` write path rather than relying on mocks

## Validation Commands

Run at minimum:

```bash
pytest -q tests/test_b128_task_graph_tools.py
```

If a real MCP smoke is available locally, also verify the external caller path after the fix.

## Assumptions and Defaults

- The consumer repo is correct to call `register_task_graph` through MCP.
- The fault is in the SideQuests backend implementation, not the client seam.
- Preserve the B128 external contract unless there is a compelling reason to version it.
