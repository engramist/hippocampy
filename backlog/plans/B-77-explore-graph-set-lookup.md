# B77 Plan — Graph Cycle Detection: O(n) List Scan → Set Lookup

Card: B77
Priority: MEDIUM
Finding: R2-G3
Depends on: None

## Summary

Replace list comprehension membership check with a maintained `visited_ids: set` in `explore_graph` BFS/DFS.

## Technical Approach

```python
# Before (O(n) per check):
if nbr["id"] in [n["node_id"] for n in curr_nodes]:

# After (O(1) per check):
visited_ids = set()
# ... on visit:
visited_ids.add(node_id)
# ... on check:
if nbr["id"] in visited_ids:
```

## Concrete File Changes

### 1. `mcp_engine/tools/explore_graph.py`
- Add `visited_ids: set = set()` at BFS/DFS init
- Add `visited_ids.add(node_id)` when a node is visited
- Replace list comprehension check with `if nbr_id in visited_ids`

## Test Updates

No new tests needed — existing explore_graph tests validate correctness.

## Acceptance Criteria

- Set-based visited tracking in place
- `pytest tests/ -k explore_graph -q` passes

## Validation Commands

```bash
pytest tests/ -k explore_graph -q
```

## Risks

None — pure performance improvement with no behavioral change.
