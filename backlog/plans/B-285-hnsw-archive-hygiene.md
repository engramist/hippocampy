# B-285 — Archived-Node HNSW Index Hygiene

Card: backlog/B285.md
Priority: P2
Dependencies: B279 first; B281 recommended

## Summary

Archived nodes pollute HNSW result sets and the fixed `+20` headroom is a band-aid. Add visibility (archived ratio), an automatic rebuild path, and adaptive headroom.

## Step 0 — Capability probe (do this first)

Write a throwaway script against a temp DB to answer, for kuzu==0.11.3:
1. Does `CALL DROP_VECTOR_INDEX('Table', 'idx_name')` (or similar) exist? Check `kuzu` docs for 0.11 / try variants.
2. Does `QUERY_VECTOR_INDEX` see rows inserted AFTER index creation? (If the index is static-on-create, the system has a worse bug — newly created Concepts would be invisible to search until restart. Test this explicitly and report the finding in the PR; if confirmed, the rebuild mechanism becomes the fix for that too and the trigger should ALSO fire on `rows_added_since_index_build`.)
3. Does deleting/updating a row remove it from the index?

The implementation branches on these answers. Record findings as comments in `kuzu_client.py`.

## Path A — Drop/recreate supported (preferred)

### `kuzu_client.py`

```python
def drop_vector_index(self, table: str, index_name: str) -> None:
    self.execute(f"CALL DROP_VECTOR_INDEX('{table}', '{index_name}')")

async def rebuild_vector_index(self, table: str, property: str, index_name: str) -> None:
    """Drop and recreate an HNSW index. Caller must serialize against writes.

    Crash-safety: ensure_schema() recreates missing indexes at startup, so a
    failure between drop and create self-heals on next daemon start.
    """
    async with _get_write_lock():
        await asyncio.to_thread(self.drop_vector_index, table, index_name)
        await asyncio.to_thread(self.create_vector_index, table, property, index_name)
```

Verify the crash-safety claim: read `ensure_schema` (schema.py ~line 1243) — it already try/excepts index creation per table on startup, so a missing index IS recreated. Confirm and reference the line in the docstring.

### `sweep.py` — ratio metric + trigger

```python
async def _index_hygiene(db, config: dict) -> dict:
    threshold = float(config.get("sweep", {}).get("index_rebuild_archived_ratio", 0.5))
    enabled  = bool(config.get("sweep", {}).get("index_rebuild_enabled", True))
    report = {}
    for table, pk, _, index_name in SWEEP_TABLES:
        r = db.execute(
            f"MATCH (n:{table}) RETURN n.archived AS archived, count(n) AS c")
        # → {False: n_active, True: n_archived}; compute ratio (guard div0)
        report[table] = {"archived_ratio": ratio, "total": total}
        if enabled and total >= 200 and ratio >= threshold:
            _logger.warning("[IndexHygiene] %s archived_ratio=%.2f — rebuilding %s",
                            table, ratio, index_name)
            await db.rebuild_vector_index(table, "embedding", index_name)
            report[table]["rebuilt"] = True
    return report
```

Wait — does rebuilding actually help? Only if the index can exclude archived rows. On drop/recreate, the index re-indexes ALL rows including archived ones, so rebuild alone does NOT remove archived vectors. Two sub-options; pick based on Step 0 finding #3:
- **A1 (row deletion removes from index):** physically move archived rows: copy archived rows into `<Table>` with a tombstone… no — simplest correct version: **null out the embedding on archive**. If `SET n.embedding = NULL` removes the row from the HNSW index (test it!), then the archive step in `_decay_and_archive` should also null the embedding, after copying the original to a non-indexed `embedding_archived` column (needed for resurrection similarity checks in `_resurrect_archived` — read that function: it currently uses vector_search to find resurrection candidates; if so, nulling breaks resurrection and you must switch resurrection to numpy cosine over archived rows, which is feasible since archived sets are scanned in batches there anyway). Then "rebuild" is unnecessary.
- **A2 (only full rebuild compacts):** keep archived embeddings but rebuild won't help; fall through to Path B.

This decision tree is the heart of the card — implement the cheapest variant that Step 0 proves works, and document why in code comments.

## Path B — Fallback: archive tables

If neither dropping rows from the index nor null-embedding works: create parallel `ConceptArchived` (etc.) node tables WITHOUT vector indexes; the archive step MOVEs rows (CREATE in archive table + DELETE original). This is invasive (resurrection, MergeEvent rollback, explore_graph references) — if Path B is the only option, STOP and downgrade this card to just the metric + adaptive headroom, and file the finding for an architecture decision. Do not unilaterally implement Path B.

## Adaptive headroom — `step5_retrieval.py`

Regardless of path:

```python
def _headroom(limit: int, archived_ratio: float) -> int:
    return max(5, min(50, math.ceil(limit * (1 + 2 * archived_ratio))))
```

Where does the ratio come from at retrieval time? Cheapest: module-level cache updated by the sweep (sweep writes `report` into a small JSON at `~/.campy/index_health.json`, or a module global via a setter the sweep calls). Avoid querying counts in the hot path. Wire: sweep → `step5_retrieval.set_archived_ratios(report)` (import is acceptable: brainstem may import temporal_lobe? CHECK `docs/ecosystem-rules.md` import boundaries first — if direction is wrong, use the JSON file at `~/.campy/`).

## Tests (`tests/test_hnsw_hygiene.py`)

1. Integration (temp DB, real kuzu): 10 nodes (4 active, 6 archived), run chosen mechanism, assert searching for an active node's vector returns it and result set contains no archived ids within top-4.
2. `test_ratio_metric_in_sweep_stats` — mock DB.
3. `test_rebuild_skipped_below_threshold` / `test_rebuild_respects_disable_flag`.
4. `test_adaptive_headroom_bounds` — pure function: ratio 0→limit*1 (min 5), ratio 0.9→clamped ≤50.

## Validation Commands

```bash
pytest tests/test_hnsw_hygiene.py -v
pytest tests/ -q -k "step5 or retrieval or sweep"
```

## Risks

- Destructive index ops while daemon serves traffic: rebuild runs under the global write lock — reads during rebuild may error; wrap search calls' existing try/except already degrade gracefully (verify retrieve_candidates catches and returns []). Acceptable for a background sweep at low frequency.
- Resurrection path depends on archived embeddings — read `_resurrect_archived` BEFORE choosing variant A1.
- If Step 0 reveals new-rows-invisible-until-restart, escalate that finding immediately (it changes priorities).
