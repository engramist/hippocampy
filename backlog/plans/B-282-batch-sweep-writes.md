# B-282 — Batch Sweep Writes with UNWIND

Card: backlog/B282.md
Priority: P2
Dependencies: none

## Summary

Replace one-row-per-statement sweep writes with chunked UNWIND batches. The global write lock (`kuzu_client._write_lock`) makes every `execute_write` a serialization point; batching turns O(nodes) lock acquisitions into O(nodes/500).

## Concrete Changes

### 1. Shared batching helper

Add near the top of `campy/brain/brainstem/sweep.py`:

```python
_BATCH_SIZE = 500

async def _batch_write(db, query: str, ids: list, param_key: str = "ids") -> int:
    """Execute an UNWIND-based write in chunks. Returns rows submitted."""
    submitted = 0
    for i in range(0, len(ids), _BATCH_SIZE):
        chunk = ids[i:i + _BATCH_SIZE]
        await db.execute_write(query, {param_key: chunk})
        submitted += len(chunk)
    return submitted
```

### 2. `_decay_and_archive` (sweep.py ~line 500)

Current shape: bulk decay (already batched — keep), then a SELECT of below-threshold ids, then **a per-id archive loop** (~line 553). Replace the loop:

```python
if to_archive:
    archived += await _batch_write(
        db,
        f"UNWIND $ids AS nid "
        f"MATCH (n:{table}) WHERE n.{pk_col} = nid "
        f"SET n.archived = true",
        to_archive,
    )
```

Error accounting: the current code counts per-row errors. With batches, wrap each chunk in try/except inside `_batch_write` (catch → count chunk as errored, continue). Adjust `_batch_write` to return `(submitted, errors)` if you keep per-chunk error counts; keep the function's stats-dict keys identical.

Decayed-count scan: the code runs `MATCH (n:{table}) WHERE n.archived = false RETURN count(n)` purely for stats. Keep ONE count query per table but move it BEFORE the decay (it's the same number) — or better, fold into the candidate SELECT: run `RETURN n.{pk_col}, n.pathway_strength` for active nodes once, count rows in Python, filter below-threshold in Python. One read replaces two.

### 3. `_resurrect_archived` (~line 622)

Same pattern: collect resurrection ids + strengths, then:

```python
await _batch_write(
    db,
    f"UNWIND $rows AS row "
    f"MATCH (n:{table}) WHERE n.{pk_col} = row.id "
    f"SET n.archived = false, n.pathway_strength = row.strength",
    rows,                      # [{"id": ..., "strength": ...}]
    param_key="rows",
)
```

Verify Kuzu 0.11.3 supports UNWIND over a list of structs/maps in parameters. If it rejects map params, fall back to parallel lists: `UNWIND range(0, size($ids)-1) AS i ... $ids[i] ... $strengths[i]` — and if that also fails, batch only the uniform-value updates (archive flag) and leave per-row for value-carrying updates, documenting why.

### 4. `_hebbian_promote` (~line 723)

The promotion writes one MERGE per promoted pair (~line 790). Promotions per sweep are typically few (threshold-crossing pairs), so batching is optional — but the candidate SELECT at line 744 scans all CO_OCCURS_WITH edges. Add `WHERE r.count >= $threshold` into that query if not already present (read the current code; push the filter into Cypher rather than Python).

### 5. `basal_ganglia/frustration_clusters.py`

Check the DISTILLED_FROM edge-creation loop (one MERGE per cluster member). Clusters are ≤ ~20 nodes — borderline. Batch with UNWIND for consistency if trivial; skip if the param shape fights you (note the decision in the PR).

## Tests (`tests/test_sweep_batching.py`)

Mock DB pattern (match existing sweep test conventions in `tests/test_basal_ganglia.py::_make_sweep_db`):

```python
@pytest.mark.asyncio
async def test_archive_batches_under_chunk_limit():
    # 1200 below-threshold nodes → expect ceil(1200/500)=3 UNWIND write calls
    write_calls = []
    db = _make_db(below_threshold_ids=[f"c{i}" for i in range(1200)])
    db.execute_write = AsyncMock(side_effect=lambda q, p=None: write_calls.append((q, p)))
    await _decay_and_archive(db, {"concept": 0.99}, 1.0, 0.2)
    unwind_calls = [c for c in write_calls if "UNWIND" in c[0]]
    assert len(unwind_calls) == 3
    assert sum(len(c[1]["ids"]) for c in unwind_calls) == 1200

@pytest.mark.asyncio
async def test_stats_shape_unchanged():
    # run_sweep returns the same stats keys as before
```

## Validation Commands

```bash
pytest tests/test_sweep_batching.py -v
pytest tests/ -q -k "sweep or dreaming or basal"
python3 -m py_compile campy/brain/brainstem/sweep.py
```

## Risks

- Kuzu UNWIND parameter-type support (lists of maps) is the main unknown — probe first, fallback ladder documented above.
- Batched archive loses per-row error granularity; per-chunk granularity is acceptable (note in docstring).
- Do not change the `SWEEP_TABLES` tuple shape — other code may import it.
