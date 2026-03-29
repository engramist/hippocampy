# B83 Plan — Add Truncation Warning to explore_graph

Card: B83
Priority: LOW
Finding: R2-G4
Depends on: None

## Summary

Add an `exploration_truncated` boolean to the explore_graph response.

## Technical Approach

After BFS/DFS loop exits:
```python
truncated = len(visited_nodes) >= MAX_NODES
return {"nodes": [...], "edges": [...], "exploration_truncated": truncated}
```

## Concrete File Changes

### 1. `mcp_engine/tools/explore_graph.py`
- Track whether MAX_NODES was hit
- Add `"exploration_truncated"` key to response dict

## Test Updates

- Add test with small MAX_NODES (e.g., 3) that triggers truncation and verifies flag

## Acceptance Criteria

- Flag present in response
- `pytest tests/ -k explore_graph -q` passes

## Validation Commands

```bash
pytest tests/ -k explore_graph -q
```

## Risks

None — additive response field.
