# B-284 — Bound the Lexical Fallback and Property Scans

Card: backlog/B284.md
Priority: P2
Dependencies: none

## Summary

The episodic lexical fallback in `current_truth` is an unbounded CONTAINS scan over Message. Bound it by recency (its actual design intent), probe for FTS support, and pin the bound with a regression test.

## Concrete Changes

### 1. Recency-bounded lexical query — `thalamus/tools/__init__.py` (~line 1208)

Current query:
```cypher
MATCH (m:Message)
WHERE lower(m.text_raw) CONTAINS lower($query)
RETURN ... ORDER BY m.created_at DESC LIMIT {lexical_limit}
```

Replace with:
```python
window_days = float(config.get("retrieval", {}).get("lexical_window_days", 14))
lexical_limit = int(config.get("retrieval", {}).get("lexical_limit", max(limit, 5)))
cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

rr = db.execute(
    "MATCH (m:Message) "
    "WHERE m.created_at > timestamp($cutoff) "
    "  AND lower(m.text_raw) CONTAINS lower($query) "
    "RETURN m.message_id, m.text_raw, m.role, m.confidence, "
    "m.confidence_low, m.pathway_strength, m.created_at "
    f"ORDER BY m.created_at DESC LIMIT {lexical_limit}",
    {"cutoff": cutoff, "query": query},
)
```

Note: Kuzu evaluates predicates left-to-right per conjunct ordering is not guaranteed, but the timestamp comparison is cheap either way; the win is mostly that old rows short-circuit the expensive `lower(text_raw) CONTAINS`. Verify the `timestamp($param)` cast syntax against existing usage (grep `timestamp($` in the repo — sweep.py uses it).

Keep `lexical_exact: True` and `score: 1.0` on results (B287 will revisit fusion).

Also check `reconstruct_timeline` and any other tool using `CONTAINS` on Message (`rg "CONTAINS" campy/brain/thalamus/tools/__init__.py`) — apply the same window where the semantic is "recent episodic", leave alone where the semantic is genuinely "all history" (e.g. timeline reconstruction is explicitly historical — leave it, but add the LIMIT it may be missing).

### 2. FTS capability probe — `kuzu_client.py`

```python
def has_fts(self) -> bool:
    """True if the FTS extension is loadable in this Kuzu build."""
    if self._fts_checked is not None:
        return self._fts_checked
    try:
        self.execute("INSTALL fts; LOAD EXTENSION fts;")
        self._fts_checked = True
    except Exception:
        self._fts_checked = False
    return self._fts_checked
```

Reality check: kuzu 0.11.3 is pinned and archived; extension download may fail offline. Treat `has_fts()` False as the normal case. Only if True: create the index at schema init (`CALL CREATE_FTS_INDEX('Message', 'message_fts_idx', ['text_raw'])` — verify exact syntax for the version) and add:

```python
def fts_search(self, table: str, index: str, query: str, limit: int) -> list[dict]:
    ...  # CALL QUERY_FTS_INDEX(...) YIELD node, score
```

In `current_truth`, branch: `if db.has_fts(): use fts_search else: windowed CONTAINS`. Keep the branch tiny; both produce the same result shape.

If probing shows the extension simply isn't available at 0.11.3, implement only the windowed CONTAINS path, leave `has_fts()` in place returning False, and note in the card validation that FTS activates automatically after an engine upgrade (B281's exit strategy).

### 3. Accepted-scan documentation

Add a comment block at the top of `sweep.py` near `SWEEP_TABLES`:

```python
# SCAN BUDGET NOTE (B284): sweep-time full-table scans (archived=false filters,
# count(n)) are accepted — sweeps are background, low-frequency, and Kuzu 0.11
# has no secondary indexes. Hot-path scans are NOT accepted; see
# retrieval.lexical_window_days for the bounded episodic fallback.
```

### 4. Config — `brainstem/config.py`

Add under a `retrieval` section (create if absent): `lexical_window_days: 14`, `lexical_limit: 10`.

## Tests (`tests/test_lexical_fallback.py`)

Mock-DB capture style:

1. `test_lexical_query_has_window_and_limit` — call `current_truth` with a mock db capturing executed queries; assert the Message CONTAINS query includes `timestamp($cutoff)` and `LIMIT`.
2. `test_recent_message_surfaces` — mock returns a row; assert result contains it with `lexical_exact` handling intact (check final result shape keys).
3. `test_config_overrides_window` — `{"retrieval": {"lexical_window_days": 2}}` → cutoff param ≈ now-2d.
4. `test_fts_probe_graceful_failure` — KuzuClient.has_fts() returns False when execute raises; no exception escapes.

## Validation Commands

```bash
pytest tests/test_lexical_fallback.py -v
pytest tests/test_web.py -q
python3 -m py_compile campy/brain/thalamus/tools/__init__.py campy/brain/hippocampus/graph/kuzu_client.py
```

## Risks

- Users asking about something said 3 weeks ago lose the lexical path — but vector search still covers it; the window only bounds exact-substring recall. Document in the tool description if it mentions exact matching.
- `timestamp()` cast behavior on string params — copy the working pattern from sweep.py rather than inventing one.
