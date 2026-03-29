# B72 Plan — Expand explore_graph Traversable Edge Types

Card: B72
Priority: HIGH
Finding: R2-G1
Depends on: None

## Summary

Expand `_TRAVERSABLE_RELS` in `explore_graph.py` to include all relationship types from `schema.py`.

## Technical Approach

1. Read all `CREATE REL TABLE` statements from `schema.py` to get the complete edge type list
2. Replace the hardcoded `_TRAVERSABLE_RELS` set with the full list
3. Consider auto-deriving from schema if feasible (similar to B71 approach)

## Concrete File Changes

### 1. `mcp_engine/tools/explore_graph.py`
- Replace `_TRAVERSABLE_RELS` set with all edge types from schema.py
- Add the missing types:
  - Plan: `PLANNED_IN`, `TARGETS`, `STEP_OF`, `NEXT_STEP`, `ACTS_ON`, `OUTCOME_SIGNAL`, `PRODUCED_LESSON`
  - Lesson: `LEARNED`, `APPLIES_TO`, `RELATED_TO`, `CONTAINS_LESSON`
  - Working memory: `LOADED`, `REROUTED_FROM`
  - Anomaly: `ANOMALY_DETECTED`
  - Session: `USED`, `IN_WORKSPACE`, `WORKING_ON`, `SENT_IN`

### 2. `docs/tool-catalog.md`
- Update explore_graph documentation if edge types are listed

## Test Updates

- Add test that verifies `_TRAVERSABLE_RELS` covers all schema edge types:
  ```python
  def test_traversable_rels_complete():
      from mcp_engine.tools.explore_graph import _TRAVERSABLE_RELS
      # compare against schema.py relationship tables
      assert len(_TRAVERSABLE_RELS) >= 30
  ```

## Acceptance Criteria

- `_TRAVERSABLE_RELS` count ≥ 30
- Plan chain traversal works end-to-end
- `pytest tests/ -k explore_graph -q` passes

## Validation Commands

```bash
python -c "from mcp_engine.tools.explore_graph import _TRAVERSABLE_RELS; print(len(_TRAVERSABLE_RELS))"
pytest tests/ -k explore_graph -q
```

## Risks

- Adding too many edge types could make BFS exploration very wide for high-degree nodes. Existing `MAX_NODES=1000` cap mitigates this.
