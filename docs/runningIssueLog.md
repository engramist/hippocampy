# SideQuests Brain — Running Issue Log

> Chronological log of bugs encountered during development and first-install testing.
> Each entry: symptom → root cause → fix applied → file(s) changed.

---

## Session: 2026-03-18 — First Local Install + Daemon Startup

---

### ISSUE-001 · Test isolation: module-level stubs contaminating pytest collection
**Symptom:** Running `pytest tests/` caused cascading `ImportError` and `AttributeError` failures across `test_analogical.py`, `test_ingest.py`, `test_quest.py`, `test_schema.py`. Failures were indirect — tests in those files couldn't import the real `mcp_engine` modules.

**Root cause:** `test_explore_graph.py` installed stubs for `sentence_transformers`, `kuzu`, `mcp_engine.graph.embeddings`, `mcp_engine.quest`, `mcp_engine.analogical`, `mcp_engine.ingest` at **module level** (top of file). pytest imports ALL test files during its collection phase before running any tests. Module-level stub code ran during collection, installing minimal stubs into `sys.modules` before any test executed. Other test files that needed the real modules got the stubs instead.

**Fix:** Rewrote `test_explore_graph.py` to use `setup_module` / `teardown_module` hooks. These run at test *execution* time, not collection time. Stubs are installed just before the file's tests run and removed after, so they never contaminate other files.

**Files changed:** `tests/test_explore_graph.py`

---

### ISSUE-002 · `SPACY_AVAILABLE` always False in Python 3.12 venv
**Symptom:** 14 NER and orchestrator tests skipped with "spaCy not compatible with this Python version" even after creating a Python 3.12 venv where `SPACY_AVAILABLE = True` is confirmed.

**Root cause:** `test_loop.py` and `test_orchestrator.py` do `from conftest import SPACY_AVAILABLE`. Both files also do `sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))` which adds the **project root** to the path — but `conftest.py` lives in `tests/`, not the project root. The import raises `ImportError`, the `except` block sets `SPACY_AVAILABLE = False`, and all tests skip.

**Fix:** Added `sys.path.insert(0, os.path.dirname(__file__))` (the `tests/` directory) to both files so `from conftest import SPACY_AVAILABLE` resolves correctly.

**Files changed:** `tests/test_loop.py`, `tests/test_orchestrator.py`

---

### ISSUE-003 · `pip install -e ".[dev]"` fails: README.md not found
**Symptom:**
```
OSError: Readme file does not exist: README.md
error: metadata-generation-failed
```

**Root cause:** `pyproject.toml` had `readme = "README.md"` but no `README.md` file exists in the repo yet (not yet published, no public docs).

**Fix:** Removed the `readme` field from `pyproject.toml`.

**Files changed:** `pyproject.toml`

---

### ISSUE-004 · Kùzu `CREATE_VECTOR_INDEX` wrong argument order
**Symptom:** Daemon crashed at schema init:
```
RuntimeError: Binder exception: Column concept_emb_idx does not exist in table Concept.
```

**Root cause:** `kuzu_client.py` called `CREATE_VECTOR_INDEX(table, property, index_name)`. Kùzu 0.11.3's actual signature is `(table, index_name, property)` — the index name and property are swapped.

**Fix:** Swapped the arguments. Added a comment documenting the correct order.
```python
# Before:
f"CALL CREATE_VECTOR_INDEX('{table}', '{property}', '{index_name}')"
# After:
f"CALL CREATE_VECTOR_INDEX('{table}', '{index_name}', '{property}')"
```

**Files changed:** `mcp_engine/graph/kuzu_client.py`

**How discovered:** Tested both arg orders interactively against a fresh Kùzu DB. The 3-arg error message ("Column my_idx does not exist") confirmed the 3rd arg was being interpreted as a column name, meaning the correct order puts the index name 2nd.

---

### ISSUE-005 · `brain_daemon.main()` is a coroutine — not called with `asyncio.run()`
**Symptom:**
```
RuntimeWarning: coroutine 'main' was never awaited
```
Daemon process exited immediately with no socket created.

**Root cause:** `daemon_ctl.py` called `brain_daemon.main()` directly. `main` is `async def` — calling it without `await` or `asyncio.run()` creates a coroutine object and discards it.

**Fix:**
```python
# Before:
brain_daemon.main()
# After:
asyncio.run(brain_daemon.main())
```

**Files changed:** `sidequests/cli/daemon_ctl.py`

---

### ISSUE-006 · Daemon `tools/list` returns empty — smoke test reports all tools missing
**Symptom:** `sidequests status` showed:
```
[✗] Tools registered: Missing tools: ['analogical_search', 'branch_quest', 'current_truth', ...]
```
Even though all 9 tools are in `TOOL_HANDLERS`.

**Root cause:** The smoke test sends a JSON-RPC request with `method: "tools/list"`. The daemon's `_dispatch` only routes methods that exist in `TOOL_HANDLERS` by exact name — `tools/list` is an MCP protocol introspection method, not a tool handler. It fell through to the `Unknown method` error path, returning `{"error": ...}` with no `result.tools`. The smoke test parsed this as zero tools.

**Fix:** Added `tools/list` and `initialize` handlers to `_dispatch` before the `TOOL_HANDLERS` lookup:
```python
if method == "initialize":
    return {"jsonrpc": "2.0", "id": req_id,
            "result": {"protocolVersion": "2024-11-05", ...}}
if method == "tools/list":
    tools = [{"name": name} for name in TOOL_HANDLERS]
    return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
```

**Files changed:** `brain_daemon.py`

---

### ISSUE-007 · Kùzu cannot SET an indexed vector property in-place
**Symptom:** Daemon crashed during centroid bootstrap:
```
RuntimeError: Cannot set property vec in table embeddings because it is used
in one or more indexes. Try delete and then insert.
```

**Root cause:** `_bootstrap_centroids` used `MATCH (g:GistClass {name: $name}) SET g.centroid = $centroid`. Kùzu 0.11.3 does not allow in-place mutation of a property that is part of an HNSW vector index. The error message itself suggests the fix.

**Fix:** Replace SET with DETACH DELETE + CREATE, then re-seed the ROUTES_TO edges that DETACH DELETE removes:
```python
# Before:
db.execute("MATCH (g:GistClass {name: $name}) SET g.centroid = $centroid", ...)
# After:
db.execute("MATCH (g:GistClass {name: $name}) DETACH DELETE g", ...)
db.execute("CREATE (:GistClass {name: $name, centroid: $centroid})", ...)
# Re-seed ROUTES_TO edges for this class
for g_name, s_name, _ in ROUTING_TABLE:
    if g_name == class_name:
        db.execute("MATCH (g:GistClass {name: $g}), (s:SchemaOrgType {name: $s}) "
                   "MERGE (g)-[:ROUTES_TO]->(s)", ...)
```

**Files changed:** `mcp_engine/schema.py`

**Note:** First attempt used `DELETE` (not `DETACH DELETE`) which failed because GistClass nodes have connected ROUTES_TO edges. The error `Node has connected edges, cannot be deleted` led to the DETACH DELETE fix.

---

### ISSUE-008 · launchd cannot read venv `pyvenv.cfg` — TCC permission error
**Symptom:** Daemon started via launchd immediately crashed:
```
PermissionError: [Errno 1] Operation not permitted:
  '~/GitProjects/hippocampy/.venv/pyvenv.cfg'
Fatal Python error: init_import_site: Failed to import the site module
```

**Root cause:** macOS Transparency, Consent, and Control (TCC) restricts access to `~/Desktop`, `~/Documents`, and `~/Downloads` for processes that don't have explicit user approval. launchd agents run outside the user's TCC-approved process tree. The venv wrapper script (`sidequests-daemon`) requires Python to read `pyvenv.cfg` to initialize the virtual environment — this read is blocked.

**Fix (partial):** Updated `launchd.py` to use the system `python3.12` (`/opt/homebrew/bin/python3.12`) instead of the venv wrapper, with `PYTHONPATH` set to the venv's `site-packages` in `EnvironmentVariables`. This avoids the `pyvenv.cfg` read entirely.

**Remaining issue:** `PYTHONPATH` still points to `.venv/lib/python3.12/site-packages` under Desktop, which is also TCC-blocked for launchd. **Full fix: move the venv to `~/.sidequests/venv/`** (outside any TCC-protected directory) during `sidequests setup`.

**Workaround:** Run `sidequests start &` manually from a terminal. Works because the terminal process has Desktop TCC approval.

**Files changed:** `sidequests/cli/launchd.py`

---

### ISSUE-009 · MCP adapter not available in new project folders
**Symptom:** Running `claude` in `~/Desktop/sidequests-test` and typing `/mcp` showed only the claude.ai servers — no `sidequests-brain`.

**Root cause:** `sidequests setup` wrote `.mcp.json` into the **sidequests-brain project directory** only. Claude Code picks up `.mcp.json` from the current working directory. Any other project folder has no `.mcp.json` and therefore no sidequests-brain MCP server.

**Fix:** Register the adapter globally (user scope) so it's available in every Claude Code session regardless of directory:
```bash
claude mcp add sidequests-brain \
  /path/to/.venv/bin/python3.12 \
  /path/to/adapters/claude_code/adapter.py \
  --scope user
```
This writes to `~/.claude.json` instead of the project's `.mcp.json`.

**Future fix:** Update `sidequests setup` to register with `--scope user` by default instead of writing a project-local `.mcp.json`.

**Files changed:** `~/.claude.json` (via `claude mcp add --scope user`)

---

## Known Remaining Issues

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | launchd venv TCC block — daemon doesn't auto-start at login | Medium | Workaround: `sidequests start &` manually |
| 2 | `sidequests setup` registers MCP locally not globally | Low | Fixed manually; setup.py needs update |
| 3 | PyPI/public install path needs packaging hardening; patent filing is complete | Low | Deferred |

---

### ISSUE-010 · `notify_turn` never called — Brain receives no data
**Symptom:** `current_truth` returns `results: []` even after decisions were stated in Claude Code. The Brain DB is empty despite the adapter being connected.

**Root cause:** The `SYSTEM_PROMPT_FRAGMENT` (which tells Claude to call `notify_turn` after every response and `current_truth` before answering past-decision questions) existed in both adapters but was never delivered to the LLM. The "Wrote 2 memories" shown in Claude Code was Claude Code's own built-in memory system — not the Brain. The Brain received zero `notify_turn` calls.

MCP servers can deliver system prompt instructions via `prompts/list` + `prompts/get` endpoints, but neither adapter implemented them. Claude Code also reads `CLAUDE.md` from the project directory at startup.

**Fix:**
1. Added `prompts/list` + `prompts/get` handlers to `claude_code/adapter.py` and `gemini_cli/adapter.py`
2. Added `CLAUDE.md` to `sidequests-test` with `notify_turn` + `current_truth` instructions

**Pattern for new projects:** Add a `CLAUDE.md` to any project folder where you want the Brain active. The `sidequests setup` command should write this automatically — currently it does not (future fix).

**Files changed:** `adapters/claude_code/adapter.py`, `adapters/gemini_cli/adapter.py`, `~/Desktop/sidequests-test/CLAUDE.md`

---

### ISSUE-011 · TIMESTAMP type mismatch — STRING cannot be implicitly cast
**Symptom:**
```
MCP error -32000: Binder exception: Expression $created_at has data type STRING
but expected TIMESTAMP. Implicit cast is not supported.
```
`notify_turn` fired but failed when writing the Message node to Kùzu.

**Root cause:** All `created_at`, `started_at`, `last_active_at`, `completed_at` parameters were passed as ISO 8601 strings (from `datetime.now(timezone.utc).isoformat()`). Kùzu 0.11.3 does not implicitly cast `STRING → TIMESTAMP` when a column is declared `TIMESTAMP`. The value must be explicitly converted in the Cypher query.

**Fix:** Wrap every `$timestamp_param` in `timestamp()` in the Cypher query string:
```cypher
-- Before:
created_at: $created_at
-- After:
created_at: timestamp($created_at)
```

**Files changed:** `mcp_engine/tools.py`, `mcp_engine/ingest.py`, `mcp_engine/quest.py`, `mcp_engine/loop/orchestrator.py`

---

## Session: 2026-03-18 — Gemini CLI Debugging + End-to-End Fix

---

### ISSUE-012 · `QUERY_VECTOR_INDEX` wrong argument count + wrong YIELD column
**Symptom:** `current_truth` returned empty results. Vector search silently failed.

**Root cause (two bugs):**
1. `vector_search()` passed 3 args `(index_name, embedding, k)` but Kùzu 0.11.3 expects 4: `(table_name, index_name, embedding, k)`.
2. YIELD used `score` but Kùzu 0.11.3 yields `(node, distance)` not `(node, score)`.

**Fix:**
- Added `table_name` as first parameter to `vector_search()` method
- Changed YIELD from `score` to `distance`
- Added distance→similarity conversion: `score = 1.0 / (1.0 + distance)`
- Updated all 5 callers to pass `table_name`

**Files changed:** `mcp_engine/graph/kuzu_client.py`, `mcp_engine/tools.py`, `mcp_engine/analogical.py`, `mcp_engine/sweep.py`, `mcp_engine/loop/step5_retrieval.py`

---

### ISSUE-013 · Daemon readline buffer overflow on large payloads
**Symptom:** Gemini CLI `notify_turn` with large assistant responses caused silent connection drops.

**Root cause:** `asyncio.start_unix_server` defaults to 64KB readline limit. Gemini CLI sends full assistant responses (often >64KB) in a single `notify_turn` JSON-RPC message.

**Fix:** Set `limit=4*1024*1024` (4MB) on the Unix socket server.

**Files changed:** `brain_daemon.py`

---

### ISSUE-014 · Gemini CLI MCP protocol version mismatch + missing `resources/list`
**Symptom:** Gemini CLI showed "Disconnected" for the sidequests-brain MCP server.

**Root cause (two bugs):**
1. Adapter hardcoded `protocolVersion: "2024-11-05"` in initialize response. Gemini CLI sends `2025-06-18` and expects it echoed back.
2. Gemini CLI calls `resources/list` during initialization — adapter returned "Unknown method" error.

**Fix:**
- Echo client's requested `protocolVersion` from the `initialize` params
- Added `resources/list` handler returning `{"resources": []}`
- Applied same fixes to `claude_code/adapter.py` for consistency

**Files changed:** `adapters/gemini_cli/adapter.py`, `adapters/claude_code/adapter.py`

---

### ISSUE-015 · spaCy NER misses software/tech entity names
**Symptom:** Message "We decided to use PostgreSQL over MySQL for the user database because of better JSON support" extracted only "JSON" (mislabeled as NORP). PostgreSQL, MySQL, and other technical terms were invisible to the Loop.

**Root cause:** spaCy `en_core_web_md` NER is trained on news corpora — recognizes PERSON, ORG, GPE but not software names, frameworks, or technical concepts.

**Fix:** Added noun chunk fallback to `step1_ner.py`. When NER finds ≤1 entity, supplement with noun chunks (filtered for pronouns/stopwords). This catches "PostgreSQL", "MySQL", "the user database", "better JSON support" etc.

**Files changed:** `mcp_engine/loop/step1_ner.py`

---

### ISSUE-016 · Step 2 gist classification thresholds unreachable for all-MiniLM-L6-v2
**Symptom:** Every concept classified as noise — zero concepts survived Step 2 to enter the graph.

**Root cause:** Original thresholds (System1=0.85, NoiseFloor=0.60) were calibrated for hypothetical high-scoring embeddings. all-MiniLM-L6-v2 produces cosine similarities of ~0.20–0.58 against mean-pooled centroids. Everything fell below the noise floor.

**Fix:**
- Recalibrated: `SYSTEM1_THRESHOLD = 0.50`, `NOISE_FLOOR = 0.25`
- Added `context` parameter to `classify_concept()` — uses full message embedding for centroid comparison (single words like "PostgreSQL" have no semantic signal alone), returns entity's own embedding for storage/retrieval

**Files changed:** `mcp_engine/loop/step2_gist.py`, `mcp_engine/loop/orchestrator.py`

---

### ISSUE-017 · Additional TIMESTAMP wrapping needed in sweep.py, step7_pathway.py, ingest.py
**Symptom:** Various `Binder exception: STRING cannot be implicitly cast to TIMESTAMP` errors during sweep and pathway update operations.

**Root cause:** Same root cause as ISSUE-011 but in additional files not caught in the initial fix.

**Fix:** Wrapped `$now`, `$created_at`, `$last_modified_at`, `$inferred_at` in `timestamp()` across all remaining Cypher queries.

**Files changed:** `mcp_engine/sweep.py` (1 fix), `mcp_engine/loop/step7_pathway.py` (3 fixes), `mcp_engine/ingest.py` (2 fixes), `mcp_engine/loop/orchestrator.py` (1 additional fix)

---

### Updated Known Remaining Issues

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | launchd venv TCC block — daemon doesn't auto-start at login | Medium | Workaround: `sidequests start &` manually |
| 2 | `sidequests setup` registers MCP locally not globally | Low | Fixed manually; setup.py needs update |
| 3 | PyPI/public install path needs packaging hardening; patent filing is complete | Low | Deferred |
| 4 | Gemini CLI requires `gemini trust` per project folder | Low | User must run manually |
| 5 | Installation process requires too many manual steps | High | Backlog B13 tracks full fix |

---

### ISSUE-025 · Decisions dropped as noise — NOISE_FLOOR too aggressive for all-MiniLM-L6-v2
**Symptom:** "We decided to use SQLAlchemy as the ORM" processed by the Loop but zero concepts stored. `recent_decisions` always empty. JWT/constraint messages work fine.

**Root cause:** Step 2 `NOISE_FLOOR = 0.25` is too high for `all-MiniLM-L6-v2` cosine similarity scores against gist class centroids. Decision-oriented sentences score 0.20–0.24 against PhysicalThing centroid — just below the noise floor. Constraint sentences score 0.40+ against Restriction centroid — well above. Additionally, seed examples are biased toward constraint/restriction language with no decision-making examples for PhysicalThing or Category.

**Fix:** Lowered `NOISE_FLOOR` from 0.25 to 0.18 (still above cross-class noise range of 0.01–0.13). Added 5 decision-oriented seed examples to PhysicalThing and 3 to Category in `GistSeedExamples.md`.

**Files changed:** `mcp_engine/loop/step2_gist.py`, `InvertorsDocs/GistSeedExamples.md`, `tests/test_loop.py`, `runningIssueLog.md`

---

### ISSUE-026 · Junk concepts leaking — ordinals, system terms, generic noun chunks
**Symptom:** Concepts like "MainQuest", "first", "all endpoints", "the only exception", "a global dependency" stored in the graph. These are not meaningful user concepts — they're ordinals, SideQuests internal terms, or generic noun chunks.

**Root cause:** `_is_junk_entity()` filter didn't cover ordinals (spaCy ORDINAL label), SideQuests system vocabulary (leaked from assistant responses via notify_turn), or generic noun chunks starting with determiners.

**Fix:** Added ordinal regex, system terms set, and determiner-initial noun chunk filter to `step1_ner.py`.

**Files changed:** `mcp_engine/loop/step1_ner.py`, `tests/test_loop.py`, `runningIssueLog.md`

---

## Session: 2026-09-09..11 — ARC_AGI live-smoke rounds (cross-agent, Oxigraph cutover fallout)

> Found by pairing hippocampy (server/graph side) with the ARC_AGI client over four
> live-smoke rounds. Common thread: the Kùzu→Oxigraph / GraphGateway cutover
> (B386/B397) left `sparql=` templates and gateway handlers whose edge label / node
> table / property set drifted from `schema.py`, with nothing checking it until a
> live run raised. See `backlog/B417.md`–`B423.md` and `docs/rdf-schema-mapping.md` §4.2e/4.3.

---

### ISSUE-027 · Semantic recall silently empty for everything written post-cutover (B418a)
**Symptom:** `recall_relevant_lessons` / `current_truth` vector branch returned `[]` for lessons that had just been written and had a real `lesson_id`.

**Root cause:** `sparql=` node-create NamedQueries route to `store.update()` and bypass `OxigraphClient.write_node()` — the only place that calls `vector_store.upsert_vector()`/`index_text()`. So embeddings never reached sqlite-vec. Compounded by a `/id/` vs `/data/` instance-base split (B418b) that also broke hydration.

**Fix:** `VectorIndexSpec` on `NamedQuery` + `_index_vector_after_write()` hook in the gateway `sparql=` dispatch, keyed at the node's real subject URI (base-agnostic `find_subject_uri`); `vector_search`/`fts_search` accept both bases.

**Files changed:** `campy/brain/hippocampus/graph/gateway.py`, `oxigraph_client.py`, `queries/lessons.py`, `tests/test_b418_vector_index_roundtrip.py` (PR #197)

---

### ISSUE-028 · ARC entity mapping stuck at 0 — entity↔rule/hypothesis links never written (B420)
**Symptom:** ARC `entities_mapped` pinned at `0/N` every cycle; `arc_get_entity_neighborhood` always `{hypotheses:[],rules:[],mechanics:[]}`.

**Root cause:** gateway handlers for `arc.link_entity_rule`/`arc.link_entity_hypothesis` wrote `ANCHORED_TO` (a `plain` edge → props raise) from an `InvestigationThread` minted off `params["tid"]` (which is the task_id), ignoring `eref`. The queries' own cypher declared `ENTITY_RULE`/`ENTITY_HYPOTHESIS` (`star`).

**Fix:** resolve the GridEntity by `(task_id, region_index)` via new `find_node_uri(table, **filters)`; write the correct `star` edge.

**Files changed:** `gateway.py`, `oxigraph_client.py`, `tests/test_b420_entity_link_handlers.py` (PR #199)

---

### ISSUE-029 · `arc_perceive_state` degrades on every entity move (B421)
**Symptom:** `record_rule`/`arc_perceive_state` raised `MOVED_BY.dr is not a declared column` (208 log hits since the cutover).

**Root cause:** `arc.link_entity_moved_by` handler wrote `MOVED_BY` with props `{dr, dc}` (declared columns are `delta_row`/`delta_col`) from `mint_uri("Entity", eid)` — `Entity` is not a node table; it's `GridEntity`.

**Fix:** `write_edge("MOVED_BY", mint_uri("GridEntity", eid), mint_uri("ActionEffect", aeid), {"delta_row": dr, "delta_col": dc})`.

**Files changed:** `gateway.py`, `tests/test_b421_moved_by_link_handler.py` (PR #200)

---

### ISSUE-030 · Whole mechanic-link handler cluster targets non-existent edges/tables (B422) + CI guard
**Symptom:** proactive audit after ISSUE-029 found all 5 `arc.link_mechanic_*`/`link_failure_*` handlers wrote unclassified bare edges (`HAS_ACTION_PATTERN`, …) over non-existent tables (`Mechanic`, `Pattern`). Latent — only `publish_mechanic_summary` calls them, never exercised.

**Root cause:** same drift class; schema declares `ARC_MECHANIC_HAS_ACTION_PATTERN` etc. (`star`) over Arc-prefixed nodes.

**Fix:** corrected all 5 handlers **and shipped a guard** — `tests/test_b422_handler_edge_schema_guard.py` statically checks every gateway `write_edge` against the schema, so this whole class (8 instances across B413/B418/B420/B421/B422) now fails at CI. See `docs/rdf-schema-mapping.md` §4.2e.

**Files changed:** `gateway.py`, `tests/test_b422_handler_edge_schema_guard.py` (PR #201)

---

### ISSUE-031 · Unbounded logs: `activity.log` (26 MB) and `daemon.log` (69 MB) (B423)
**Symptom:** `~/.campy/activity.log` and `daemon.log` grew without bound.

**Root cause:** `activity.log` was append-only with no rotation. `daemon.log` was launchd's `StandardOut/ErrorPath` redirect (raw stdout/stderr), not Python logging — a rotating handler alone couldn't touch it, and launchd + a handler both writing it would fight rotation.

**Fix:** `activity.log` rotates to `.1` at `config["activity"]["max_bytes"]` (PR #202). `daemon.log` is now owned by an in-process `RotatingFileHandler` (~60 MB ceiling); `_StreamToLogger` routes `print()`/stdout/stderr through it (now timestamped, closing the B371 gap); launchd's stdout/stderr moved to a tiny `daemon.boot.log` for pre-init/crash output (PR #203).

**Files changed:** `campy/brain/brainstem/activity_log.py`, `campy/brain_daemon.py`, `campy/cli/launchd.py`, `campy/paths.py`, `tests/test_b423_activity_log_rotation.py`, `tests/test_b423b_daemon_log_rotation.py`

---

### ISSUE-032 · Reported daemon memory leak — NOT substantiated (investigation, no fix)
**Symptom:** daemon RSS looked high (565–579 MB), reported as a possible leak.

**Root cause / finding:** those were **RSS**, not physical footprint. Physical footprint tracked flat-to-declining vs the ~502 MB startup baseline. Across four live-smoke rounds, growth was proportional to real graph writes; a SIGUSR1 `gc` object-count diff over a heavier round (~378 nodes, +29.8 MB footprint) showed the **Python object count went DOWN** (155,561→155,418) with only single-digit framework/threading/HTTP ephemera growing — the delta lives in native RocksDB/sqlite-vec store (data-at-rest), not the Python heap. A code scan found no unbounded in-memory structures. Not substantiated; residual caveat is only a hypothetical sub-MB/day creep that the ~24 h auto-restart resets.

**Tool note:** `kill -USR1 <brain_daemon pid>` writes an auto-diffing object-count snapshot to `~/.campy/memory_debug.log` — the go-to leak-detection instrument.

**Files changed:** none (investigation; conclusion recorded here and in memory).
