# B73 Plan — Batch Outcome Signal Lookups in current_truth

Card: B73
Priority: HIGH
Finding: R2-G2
Depends on: None

## Summary

Replace per-concept OUTCOME_SIGNAL queries with a single batched UNWIND query in `current_truth`.

## Technical Approach

After collecting all concept_ids from vector search results, run a single query:

```cypher
UNWIND $ids AS cid
MATCH (ps:PlanStep)-[o:OUTCOME_SIGNAL]->(c:Concept {concept_id: cid})
RETURN cid, avg(o.valence) AS avg_valence, count(o) AS signal_count
```

Build a dict `{cid: (avg_valence, signal_count)}` and look up per result instead of querying per result.

## Concrete File Changes

### 1. `mcp_engine/tools/__init__.py`
- Locate the per-concept OUTCOME_SIGNAL lookup loop
- Collect all `concept_id` values into a list
- Replace the loop with a single UNWIND batch query
- Build lookup dict from batch results
- Apply outcome_boost from the dict during ranking

## Test Updates

- Existing `current_truth` tests should pass unchanged (behavioral equivalence)
- Optional: add a test that mocks `db.execute` and asserts OUTCOME_SIGNAL is queried at most once

## Acceptance Criteria

- Only 1 OUTCOME_SIGNAL query per `current_truth` call (not N)
- Existing tests pass unchanged
- `pytest tests/ -k current_truth -q` passes

## Validation Commands

```bash
pytest tests/ -k current_truth -q
```

## Risks

- If no concepts have OUTCOME_SIGNAL edges, the query returns empty — same as current behavior (each per-concept query returns empty). No behavioral change.
