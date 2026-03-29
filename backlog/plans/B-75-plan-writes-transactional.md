# B75 Plan — Make Plan Graph Writes Transactional

Card: B75
Priority: HIGH
Finding: R2-P3
Depends on: None

## Summary

Batch `_create_plan_graph` writes into a single Cypher query to ensure atomicity.

## Technical Approach

Combine all plan creation writes into a single parameterized Cypher query using UNWIND for steps:

```cypher
CREATE (p:Plan {plan_id: $plan_id, goal: $goal, ...})
WITH p
MATCH (s:Session {session_id: $session_id})
CREATE (p)-[:PLANNED_IN]->(s)
WITH p
OPTIONAL MATCH (q:MainQuest {quest_id: $quest_id})
FOREACH (_ IN CASE WHEN q IS NOT NULL THEN [1] ELSE [] END |
    CREATE (p)-[:TARGETS]->(q)
)
WITH p
UNWIND $steps AS step
CREATE (ps:PlanStep {step_id: step.step_id, step_number: step.step_number, ...})
CREATE (ps)-[:STEP_OF]->(p)
```

Then chain NEXT_STEP edges in a second UNWIND or MATCH pattern.

Alternative approach: wrap in try/except with compensating deletes on failure.

## Concrete File Changes

### 1. `mcp_engine/tools/__init__.py`
- Refactor `_create_plan_graph` to build a single compound Cypher string
- Use UNWIND for PlanStep creation
- Add NEXT_STEP chaining in same query or immediately after
- Wrap in try/except: if the batch query fails, execute compensating `DELETE` of the plan_id

## Test Updates

- Add `test_plan_graph_atomic_on_failure()` — simulate DB error mid-write, verify no partial plan exists
- Existing plan tests verify happy path still works

## Acceptance Criteria

- Plan creation uses ≤ 2 `db.execute_write()` calls (down from 5+)
- `pytest tests/ -k "plan or register_plan" -q` passes
- Simulated failure leaves no orphan nodes

## Validation Commands

```bash
pytest tests/ -k "plan or register_plan" -q
```

## Risks

- Complex Cypher queries may be harder to debug. Add logging of the parameterized query on error.
- Kùzu's multi-statement support may require testing for compound query compatibility.
