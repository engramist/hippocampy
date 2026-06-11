# B-281 — Kuzu Export/Restore and Engine Exit Strategy

Card: backlog/B281.md
Priority: P1
Dependencies: none

## Summary

Build a streamed JSONL export/import for the whole graph plus a facade conformance suite, so the archived Kuzu 0.11.3 engine can be replaced later without data loss or behavioral surprises.

## Export Format

```
dump_dir/
├── manifest.json
├── nodes/
│   ├── Concept.jsonl          # one JSON object per row, all properties
│   ├── Decision.jsonl
│   └── ...
└── rels/
    ├── CO_OCCURS_WITH.jsonl   # {"_from_table","_from_pk","_to_table","_to_pk", ...props}
    └── ...
```

`manifest.json`:
```json
{
  "format_version": 1,
  "exported_at": "<iso>",
  "engine": "kuzu-0.11.3",
  "embedding_dim": 384,
  "node_tables": {"Concept": {"pk": "concept_id", "rows": 1234}, ...},
  "rel_tables": {"CO_OCCURS_WITH": {"rows": 567}, ...}
}
```

## Technical Approach

### `campy/brain/hippocampus/graph/export.py`

Source of truth for tables: import `NODE_TABLES` and `REL_TABLES` from `campy.brain.hippocampus.schema`. Parse PK per table from the DDL string (`PRIMARY KEY (xxx)` regex) — or better, if B286 (registry consolidation) has landed, import its registry. Do not hardcode the table list.

**Node export** — stream per table:
```python
def export_nodes(db, table: str, out_path: Path) -> int:
    result = db.execute(f"MATCH (n:{table}) RETURN n")
    count = 0
    with out_path.open("w") as f:
        while result.has_next():
            node = result.get_next()[0]      # dict of properties incl. _label/_id
            f.write(json.dumps(_clean(node), default=_json_default) + "\n")
            count += 1
    return count
```
`_clean()` drops Kuzu-internal keys (`_id`, `_label` — keep `_label` if useful, but the filename already encodes the table). `_json_default` handles `datetime` (→ISO string) and any numpy types.

**Rel export** — need endpoint PKs, and a rel table can span multiple FROM/TO pairs (see `ESTABLISHED`, `LOADED` in schema.py). Per rel table:
```python
result = db.execute(f"MATCH (a)-[r:{rel_table}]->(b) RETURN a, r, b")
```
Extract `_from_table` from `a["_label"]`, then look up that table's pk column and read `a[pk]`. Same for `b`. Rel properties from `r` (drop `_src`, `_dst`, `_label`, `_id`). If unlabeled `(a)`/`(b)` patterns fail on 0.11.3, expand per FROM/TO pair parsed from the REL_TABLES DDL — bounded and mechanical.

**Import** — order matters: nodes first, then rels.
```python
# nodes: CREATE with full property map
db.execute(f"CREATE (n:{table} {{{prop_assignments}}})", params)
# rels:
db.execute(
    f"MATCH (a:{ft} {{{ft_pk}: $from_pk}}), (b:{tt} {{{tt_pk}: $to_pk}}) "
    f"CREATE (a)-[r:{rel} {{{rel_props}}}]->(b)", params)
```
Batch with UNWIND where possible (`UNWIND $rows AS row CREATE (n:Concept {concept_id: row.concept_id, ...})`) — chunk size 500. Timestamps: import as `timestamp($iso_string)` cast.

After import, call the existing `ensure_schema(db)` first (creates tables + indexes), then load data, then HNSW indexes need data present — check whether `CREATE_VECTOR_INDEX` on 0.11.3 indexes existing rows or only new ones; if rebuild-on-create works, create indexes AFTER bulk load for speed.

### CLI wiring (`campy/cli/graph_io.py` + `main.py`)

```python
@app.command(name="export-graph")
def export_graph_cmd(out: str = typer.Option(...), db_path: str = typer.Option("")):
    """Export the full memory graph to engine-neutral JSONL."""
```
Default `db_path` = the live DB path (find how brain_daemon resolves it — `campy/paths.py` likely has `get_db_path()`; reuse it). **Warn if the daemon is running** (single-writer engine): check `http://127.0.0.1:7799/health` and require `--force` or open read_only=True (KuzuClient supports `read_only` — use it for export).

### Conformance tests (`tests/test_graph_export.py`)

```python
class TestFacadeConformance:
    """Contract any replacement engine adapter must satisfy."""
    def test_execute_create_and_match(...)
    def test_execute_read_returns_dict_rows(...)
    @pytest.mark.asyncio
    async def test_execute_write_serializes_under_lock(...)   # two concurrent writes both land
    def test_create_vector_index_and_search(...)              # reuse calibration fixture from B279
    def test_close_releases(...)

class TestRoundTrip:
    def test_export_import_equality(tmp_path):
        # seed: 3 Concepts (with embeddings + timestamps), 2 Decisions,
        # CO_OCCURS_WITH w/ count+strength, ESTABLISHED_IN, one archived node
        # export → import to fresh dir → compare counts + sorted property dumps
    def test_embedding_precision(tmp_path):
        # cosine(original, reimported) >= 0.9999
```

### Docs

Add to `docs/ARCHITECTURE.md` under a "Graph Engine Portability" heading: the export format, the migration playbook (export → implement new facade → run conformance suite → import → re-run calibration tests from B279), and the rule that `kuzu_client.py` stays the only kuzu import.

## Validation Commands

```bash
pytest tests/test_graph_export.py -v
campy export-graph --out /tmp/campy_dump   # against live ~/.campy (daemon stopped or read-only)
ls /tmp/campy_dump/nodes | head
python3 -c "import json; m=json.load(open('/tmp/campy_dump/manifest.json')); print(m['node_tables'])"
```

## Risks

- Kuzu `RETURN n` property-dict shape may vary by version — pin behavior in the conformance test.
- Multi-pair rel tables (`ESTABLISHED`, `LOADED`, `WARM_NODE`, `ANOMALY_DETECTED`) are the fiddly part; test them explicitly in the round-trip fixture.
- Live export against a running daemon: enforce read_only or refuse; document in CLI help.
