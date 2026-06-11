# B-280 — Server-Side Traversal for explore_graph

Card: backlog/B280.md
Priority: P1
Dependencies: B279 recommended first

## Summary

Replace Python-side BFS/DFS that issues O(tables × rels × directions) queries per node with bounded server-side Cypher traversal. Preserve the exact tool response contract.

## Current Architecture (what you're replacing)

`explore_graph.py`:
- `_get_neighbors(db, node_id, node_table, edge_types, direction)` — nested loops over `_NODE_TABLES` (12) × `edge_types` (up to ~90 from `get_relationship_types()`) × direction (≤2), one `db.execute` each.
- `_get_node_data(db, node_id, table)` — one query per node to fetch `text_raw`/`confidence`.
- `_bfs_traversal` / `_dfs_traversal` — drive the above in Python, build path objects, cycle-detect with sets, cap at `MAX_NODES=1000`.

## Target Architecture

### Key Kuzu capabilities to use (verify against kuzu==0.11.3 docs/behavior)

1. **Multi-rel patterns**: `-[r:REQUIRES|ENABLES|PART_OF]->` matches any listed rel type in one pattern.
2. **Bounded variable-length**: `-[r:REL1|REL2*1..3]->` with `*1..{depth}`.
3. **Path binding**: Kuzu supports named paths / `nodes(p)` and `rels(p)` functions in recent versions — **verify on 0.11.3**. If unsupported, use the iterative-frontier fallback (below), which is still ~depth×2 queries instead of thousands.

### Primary approach: variable-length path query

Because Kuzu requires node tables in patterns to be labeled (or multi-labeled), build the query against a label union. Kuzu 0.11 supports multi-label node patterns like `(n:Concept:Decision:...)` — verify; if not supported, the frontier fallback handles it.

```cypher
MATCH p = (start:{start_table})-[r:{REL_LIST}*1..{depth}]-(end)
WHERE start.{pk} = $start_id
RETURN p LIMIT {max_paths}
```

Direction handling: `-[...]->` for outgoing, `<-[...]-` for incoming, `-[...]-` for both.

### Fallback approach (use if path binding or multi-label is unsupported on 0.11.3): iterative frontier expansion

One query per depth level per direction — depth 3 both-directions = 6 queries total:

```python
async def _expand_frontier(db, frontier_ids: list[str], edge_types: list[str],
                            direction: str) -> list[dict]:
    """Expand one hop from all frontier nodes in ONE query per direction.

    Returns [{src_id, dst_id, dst_table, rel_type, rel_conf, dst_text, dst_confidence}].
    """
    rel_pattern = "|".join(edge_types)          # validated against allowlist upstream
    rows_out = []
    arrows = []
    if direction in ("outgoing", "both"):
        arrows.append(("-", "->"))
    if direction in ("incoming", "both"):
        arrows.append(("<-", "-"))
    for left, right in arrows:
        # Kuzu: unlabeled (a)/(b) scans all node tables — exactly what we want here.
        query = (
            f"UNWIND $ids AS seed_id "
            f"MATCH (a){left}[r:{rel_pattern}]{right}(b) "
            # id(a)/id(b) are internal IDs; we need domain PKs. Use the COALESCE
            # trick over known pk properties, or RETURN a, b and extract in Python:
            f"WHERE {_pk_match_predicate('a')} "
            f"RETURN a, b, label(r), r.confidence"
        )
        result = await db.execute_read(query, {"ids": frontier_ids})
        rows_out.extend(result)
    return rows_out
```

Implementation notes for the fallback:
- **PK matching across heterogeneous tables**: each table has a different pk column. Two workable options:
  a. `WHERE coalesce(a.concept_id, a.decision_id, a.constraint_id, a.requirement_id, a.action_item_id, a.global_constraint_id, a.global_preference_id, a.quest_id, a.message_id, a.document_id, a.lesson_id) = seed_id` — single query, relies on Kuzu tolerating missing properties on unlabeled patterns (it returns NULL for absent props — verify; if it errors, fall back to per-table UNION, which is still only 12 queries per hop, not 2000).
  b. Return whole nodes (`RETURN a, b`) and extract pk + text + confidence from the node dict in Python (Kuzu returns node properties as a dict including a `_label` field). **Prefer (b)** — it also eliminates `_get_node_data` entirely because `b`'s properties ride along.
- `label(r)` returns the rel type for the edge dict. If `label()` is unavailable on rels in 0.11.3, run one query per rel-type *group* (split the ~90 types into chunks) — still bounded and small.
- Apply `edge_types` allowlist before building `rel_pattern` (the existing `_TRAVERSABLE_RELS` filter stays).

### Rebuilding paths

Keep BFS bookkeeping in Python (parents map), but feed it from frontier batches:

```python
frontier = [start_id]
visited = {start_id}
parents = {}            # child_id -> (parent_id, edge_dict)
node_cache = {start_id: start_node_data}
for depth_level in range(1, depth + 1):
    if not frontier or len(visited) >= MAX_NODES:
        break
    edges = await _expand_frontier(db, frontier, edge_types_to_use, direction)
    next_frontier = []
    for e in edges:
        dst = e["dst_id"]
        if dst in visited:
            continue                      # cycle / revisit prevention
        visited.add(dst)
        parents[dst] = (e["src_id"], _edge_dict(e))
        node_cache[dst] = _node_dict(e)   # properties came with the query
        next_frontier.append(dst)
        if len(visited) >= MAX_NODES:
            break
    frontier = next_frontier
```

Then reconstruct one path per visited node by walking `parents` back to start — this exactly reproduces the current BFS semantics ("every node reached completes a path"). `path_strength` = mean of node confidences along the path, identical formula. DFS strategy param: keep accepted but route to the same frontier implementation (document that `strategy` is now advisory; BFS and DFS produced the same path SET, only ordering differed — verify against tests before simplifying; if a test asserts DFS ordering, preserve a DFS-ordered reconstruction).

### `_add_temporal_context`

Batch it: collect all node_ids across paths, run ONE frontier expansion restricted to `["NEXT_MESSAGE", "CAUSED_BY", "ESTABLISHED_IN"]` (note: verify these rel names exist in `get_relationship_types()`; `NEXT_MESSAGE`/`CAUSED_BY` may not exist in REL_TABLES — if absent, this entire context feature is currently a silent no-op; flag in the PR description and keep behavior).

### step5 `_get_neighbor_set`

Same UNWIND batching: one query per direction with unlabeled `(b)` and whole-node return, instead of per-(table×rel) loops.

## Query-count regression test

Wrap the client to count:

```python
class CountingDB:
    def __init__(self, inner): self.inner, self.count = inner, 0
    def execute(self, q, p=None):
        self.count += 1
        return self.inner.execute(q, p)
    async def execute_read(self, q, p=None):
        self.count += 1
        return await self.inner.execute_read(q, p)

async def test_explore_graph_query_budget(populated_db):
    db = CountingDB(populated_db)
    result = await explore_graph(
        {"start_node_id": SEED, "session_id": "t", "depth": 3}, db, {})
    assert result["exploration_complete"]
    assert db.count <= 30, f"explore_graph issued {db.count} queries"
```

Build `populated_db` as a small fixture graph: ~10 Concepts, a few Decisions, REQUIRES/ENABLES/CO_OCCURS_WITH edges, one cycle (A→B→C→A) to exercise cycle prevention.

## Validation Commands

```bash
rg -l "explore_graph" tests/            # find existing tests
pytest tests/ -q -k "explore"
pytest tests/test_web.py -q             # tool surface unchanged
python3 -m py_compile campy/brain/thalamus/tools/explore_graph.py
```

## Risks

- Kuzu 0.11.3 feature support (unlabeled patterns, `label()`, multi-rel `|` syntax) must be verified empirically early — write a throwaway probe script first. The fallback ladder is: path query → unlabeled frontier UNWIND → per-table frontier UNION (12/hop) → keep current code for that sub-case only.
- Response-shape regressions: snapshot a current response on the fixture graph BEFORE refactoring and assert equality after (ordering may legitimately differ — compare as sets of (path node-id tuples)).
