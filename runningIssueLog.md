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
  '/Users/djshelton/Desktop/GitProjects/sidequests-brain/.venv/pyvenv.cfg'
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
| 3 | No `README.md` — PyPI publish blocked (also blocked on patent) | Low | Deferred |

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
