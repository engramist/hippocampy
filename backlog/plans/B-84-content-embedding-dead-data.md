# B84 Plan — Remove or Use Session content_embedding Dead Data

Card: B84
Priority: LOW
Finding: R2-S2
Depends on: None

## Summary

Decide whether Session.content_embedding should be used or removed, then implement.

## Technical Approach

**Option A (Remove):** Remove `content_embedding` from schema, remove writes in hippocampus and notify_turn. Simplest fix.

**Option B (Use):** Add session-scoped retrieval: "find sessions similar to this query" using HNSW search on Session.content_embedding. Useful for cross-session context discovery.

Recommendation: Option A unless a specific use case is identified.

## Concrete File Changes

### Option A (Remove):
1. `mcp_engine/schema.py` — remove `content_embedding FLOAT[384]`, `embedding_model`, `embedding_dim` from Session table
2. `mcp_engine/hippocampus.py` — remove content_embedding writes
3. `mcp_engine/tools/__init__.py` — remove content_embedding writes in notify_turn

### Option B (Use):
1. Add `find_similar_sessions(query_embedding, limit)` query
2. Wire into a tool or internal helper

## Test Updates

- Update tests that reference Session.content_embedding
- `pytest -q` must pass

## Acceptance Criteria

- No dead writes to content_embedding (Option A) or new reads exist (Option B)
- `pytest -q` passes

## Validation Commands

```bash
rg "content_embedding" mcp_engine/
pytest -q
```

## Risks

- Option A: if someone later needs session similarity search, the column must be re-added. Low risk — easy to re-add.
