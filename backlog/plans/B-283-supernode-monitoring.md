# B-283 — Supernode Monitoring and Session Edge Pruning

Card: backlog/B283.md
Priority: P2
Dependencies: B282 (reuse `_batch_write`)

## Summary

Make node degree observable (sweep report) and bound the two unbounded edge accumulators: per-session LOADED/WARM_NODE edges (TTL pruning) and per-message CO_OCCURS_WITH writes (pair cap).

## Concrete Changes

### 1. Degree hotspot report — `sweep.py`

New function, called from `run_sweep` after decay:

```python
_DEGREE_REPORT_RELS = [
    # (rel_table, side_to_measure) — measure the side that concentrates
    ("CO_OCCURS_WITH", "both"),
    ("ESTABLISHED_IN", "to"),       # Session side
    ("LOADED",         "from"),     # Session side
    ("WARM_NODE",      "from"),
    ("BELONGS_TO",     "to"),       # MainQuest side
    ("WORKING_ON",     "to"),
]

async def _report_degree_hotspots(db, config: dict) -> list[dict]:
    top_k = int(config.get("sweep", {}).get("degree_report_top_k", 10))
    hotspots = []
    for rel, side in _DEGREE_REPORT_RELS:
        # degree per endpoint; unlabeled endpoints scan all participating tables
        if side in ("from", "both"):
            q = (f"MATCH (a)-[r:{rel}]->() "
                 f"RETURN a, count(r) AS deg ORDER BY deg DESC LIMIT {top_k}")
            hotspots.extend(_rows_to_hotspots(db, q, rel, "out"))
        if side in ("to", "both"):
            q = (f"MATCH ()-[r:{rel}]->(b) "
                 f"RETURN b, count(r) AS deg ORDER BY deg DESC LIMIT {top_k}")
            hotspots.extend(_rows_to_hotspots(db, q, rel, "in"))
    return hotspots
```

`_rows_to_hotspots` extracts node `_label` + best-effort pk from the returned node dict. If Kuzu 0.11.3 rejects unlabeled aggregation patterns, expand per FROM/TO table pair from the schema DDL (mechanical; ESTABLISHED_IN has 4 pairs, LOADED has 7).

Wire into stats: `stats["degree_hotspots"] = hotspots`, and log via the existing activity-log mechanism (find how sweep currently logs — grep `activity` in `brainstem/activity_log.py` and emit one line: `SWEEP degree_hotspots top={table}:{id} deg={n}`). Optional alert: if any degree > `config sweep.degree_alert_threshold` (default 5000), log at WARNING.

### 2. Session edge TTL pruning — `sweep.py`

```python
async def _prune_session_edges(db, config: dict) -> tuple[int, int]:
    ttl_days = float(config.get("sweep", {}).get("session_edge_ttl_days", 30))
    # Find stale sessions. Check Session schema for the right recency field:
    # schema.py Session table (~line 223) — use last_active_at if present,
    # else created_at. READ THE SCHEMA FIRST.
    result = db.execute(
        "MATCH (s:Session) WHERE s.<recency_field> < timestamp($cutoff) "
        "RETURN s.session_id", {"cutoff": cutoff_iso})
    stale = [...]
    deleted = 0
    for rel in ("LOADED", "WARM_NODE"):
        # Kuzu DELETE on rels: MATCH then DELETE r
        deleted += await _batch_write(
            db,
            f"UNWIND $ids AS sid "
            f"MATCH (s:Session)-[r:{rel}]->() WHERE s.session_id = sid "
            f"DELETE r",
            stale,
        )
    return deleted, 0
```

Note: `_batch_write` returns submitted ids, not deleted edges — either adjust the helper to optionally return affected counts (Kuzu result summary) or report sessions-pruned instead of edges-deleted; pick one and keep the stats key name honest (`sessions_pruned`).

Wire into `run_sweep` with its own try/except and stats key. Default ON, but add config `sweep.prune_session_edges: true` for an escape hatch.

### 3. CO_OCCURS_WITH pair cap — `step7_pathway.py`

Find where co-occurrence pairs are written (grep `CO_OCCURS_WITH` in step7_pathway.py; per the module docstring it MERGEs all pairs from the same message). Insert before the write loop:

```python
MAX_PAIRS = int(config.get("loop", {}).get("max_co_occurrence_pairs", 45))
pairs = list(itertools.combinations(concept_entries, 2))
if len(pairs) > MAX_PAIRS:
    # keep pairs whose members have the highest min(confidence)
    pairs.sort(key=lambda ab: min(ab[0]["confidence"], ab[1]["confidence"]), reverse=True)
    pairs = pairs[:MAX_PAIRS]
```

Check how `config` reaches step7 (the orchestrator passes it — verify the call signature; thread it through if absent).

### 4. Config defaults — `brainstem/config.py`

Add to the default config dict (find existing `sweep` section): `session_edge_ttl_days: 30`, `degree_report_top_k: 10`, `degree_alert_threshold: 5000`, `prune_session_edges: true`; under `loop`: `max_co_occurrence_pairs: 45`.

## Tests (`tests/test_supernode_hygiene.py`)

Mock-DB style (see `tests/test_basal_ganglia.py` for conventions):

1. `test_degree_report_returns_topk` — mock rows, assert stats shape `{node_id, table, rel_table, degree, direction}`.
2. `test_stale_session_edges_pruned` — sessions older than TTL → DELETE queries issued with their ids; fresh sessions untouched.
3. `test_prune_respects_config_disable` — `prune_session_edges: false` → no DELETE calls.
4. `test_co_occurrence_cap` — 15 concepts (105 pairs) → exactly 45 MERGE writes, and the kept pairs are the highest-min-confidence ones.
5. `test_prune_never_deletes_nodes` — assert no `DETACH DELETE` and no node DELETE in issued queries.

## Validation Commands

```bash
pytest tests/test_supernode_hygiene.py -v
pytest tests/ -q -k "sweep or step7 or pathway"
python3 -m py_compile campy/brain/brainstem/sweep.py campy/brain/temporal_lobe/loop/step7_pathway.py
```

## Risks

- Deleting WARM_NODE/LOADED edges for a session that resumes later is safe — they're caches, rebuilt on next activity (verify nothing treats LOADED as durable history; grep `load_hits` consumers first; if `context_status` reports rely on them, scope pruning to sessions, not quests).
- Session recency field name must be read from schema.py, not guessed.
- The pair cap changes Hebbian dynamics slightly (fewer weak edges) — that is the point; note it in ARCHITECTURE.md's Hebbian section.
