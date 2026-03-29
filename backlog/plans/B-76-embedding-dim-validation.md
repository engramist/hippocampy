# B76 Plan — Add Embedding Dimension Validation at Schema Init

Card: B76
Priority: HIGH
Finding: R2-S1
Depends on: None

## Summary

Add a dimension check at schema init that validates the embedding model output matches the declared `FLOAT[384]` schema.

## Technical Approach

At the end of `init_schema()` (or beginning of centroid bootstrap), embed a test string and compare:

```python
test_vec = emb.embed("dimension validation test")
expected_dim = 384  # matches FLOAT[384] in schema
if len(test_vec) != expected_dim:
    raise ValueError(
        f"Embedding model produces {len(test_vec)} dimensions "
        f"but schema expects {expected_dim}. "
        f"Check config embedding_model setting."
    )
```

## Concrete File Changes

### 1. `mcp_engine/schema.py`
- In `init_schema()`, after embedding model is initialized
- Add test embedding + dimension assertion
- Use the same `emb` instance that will be used throughout the system

## Test Updates

- Add `test_embedding_dimension_validation_pass()` — normal init succeeds
- Add `test_embedding_dimension_mismatch()` — mock `emb.embed()` to return wrong-dimension vector, assert `ValueError` raised with descriptive message

## Acceptance Criteria

- Mismatched embedding model raises `ValueError` at init time
- Normal operation (384-dim model) succeeds without change
- `pytest tests/ -k schema -q` passes

## Validation Commands

```bash
pytest tests/ -k schema -q
```

## Risks

- The test embedding adds ~5ms to startup. Negligible.
- If embedding model requires GPU warmup, first call may be slow. This is a one-time startup cost.
