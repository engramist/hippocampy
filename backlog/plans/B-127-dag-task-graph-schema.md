# B-127 Plan - DAG Task Graph Schema

Card: B127
Priority: P1
Dependencies: B66

## Summary
Introduce first-class TaskGraph/TaskNode DAG schema in SideQuests for durable dependency-aware execution tracking.

## Ecosystem / Ownership
- Layer: Data Products & Memory.
- Schema and tool helper code only under `mcp_engine/`.

## Technical Approach
1. Add node tables in schema:
- `TaskGraph`
- `TaskNode`
2. Add relation tables:
- `TASK_OF` (`TaskNode -> TaskGraph`)
- `DEPENDS_ON` (`TaskNode -> TaskNode`)
3. Add cycle detection helper logic for edge insertion:
- `_dag_has_cycle(graph_id, from_task_id, to_task_id)`
4. Add frontier query helper:
- `_get_ready_tasks_query(graph_id)`

## Concrete File Changes
- Modify: `mcp_engine/schema.py`
- Create/Modify helper module: `mcp_engine/tools/task_graph.py`
- Create tests: `tests/test_b127_dag_schema.py`

## Test Plan
- `pytest -q tests/test_b127_dag_schema.py`
- `pytest -q tests/test_web.py`

## Acceptance Criteria Mapping
- Node/edge tables created with expected fields.
- Cyclic edge rejected.
- Ready-frontier query returns only pending nodes with satisfied deps.

## Risks / Constraints
- Keep schema additive and migration-safe.
- Avoid embedding/index additions for this execution-focused schema.
