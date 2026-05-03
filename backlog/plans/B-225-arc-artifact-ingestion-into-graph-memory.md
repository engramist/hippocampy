# Plan for B225 - ARC Artifact Ingestion Into Graph Memory

## Card Metadata

- **Card ID**: B225
- **Priority**: P0
- **Dependencies**: B220, B221, B222, B223, B224

## Summary

Create a graph-native ingestion path for ARC run artifacts produced by the sibling `ARC_AGI` repository.

The goal is to make ARC run evidence visible to SideQuests memory and the `arc_agi` wiki persona without violating the core invariant: KuzuDB is authoritative, raw artifact files are evidence inputs, and Markdown is read-only projection.

## Technical Approach

### Step 1: Add graph schema for ARC artifacts

In `mcp_engine/schema.py`, add schema elements defensively so existing installs upgrade cleanly.

Use additive node/relationship types. Do not reuse generic `Lesson` as the only storage shape for raw run evidence.

Proposed node types:

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcRun(
  run_id STRING,
  artifact_hash STRING,
  source_root STRING,
  source_files STRING,
  started_at STRING,
  completed_at STRING,
  status STRING,
  variant STRING,
  task_count INT64,
  solved_count INT64,
  failed_count INT64,
  step_count INT64,
  domain STRING,
  summary STRING,
  created_at STRING,
  updated_at STRING,
  PRIMARY KEY (run_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcTaskResult(
  task_result_id STRING,
  run_id STRING,
  task_id STRING,
  puzzle_id STRING,
  status STRING,
  correct BOOL,
  steps INT64,
  tokens_input INT64,
  tokens_output INT64,
  failure_class STRING,
  trajectory_score DOUBLE,
  domain STRING,
  summary STRING,
  created_at STRING,
  updated_at STRING,
  PRIMARY KEY (task_result_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcArtifact(
  artifact_id STRING,
  artifact_kind STRING,
  path STRING,
  content_hash STRING,
  record_count INT64,
  captured_at STRING,
  ingested_at STRING,
  domain STRING,
  summary STRING,
  PRIMARY KEY (artifact_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcEvent(
  event_id STRING,
  run_id STRING,
  task_id STRING,
  event_type STRING,
  timestamp STRING,
  step_index INT64,
  actor STRING,
  tool_name STRING,
  action_name STRING,
  outcome STRING,
  domain STRING,
  summary STRING,
  PRIMARY KEY (event_id)
)
```

Proposed relationships:

```cypher
CREATE REL TABLE IF NOT EXISTS ARC_RUN_HAS_TASK(FROM ArcRun TO ArcTaskResult)
CREATE REL TABLE IF NOT EXISTS ARC_RUN_HAS_ARTIFACT(FROM ArcRun TO ArcArtifact)
CREATE REL TABLE IF NOT EXISTS ARC_TASK_HAS_EVENT(FROM ArcTaskResult TO ArcEvent)
CREATE REL TABLE IF NOT EXISTS ARC_EVENT_FROM_ARTIFACT(FROM ArcEvent TO ArcArtifact)
```

Implementation note: if this repo uses helper wrappers for schema creation, follow the existing pattern in `init_schema()` rather than pasting raw Cypher in a new style.

### Step 2: Implement artifact parser and importer

Create `mcp_engine/tools/arc_artifacts.py`.

Required public function:

```python
async def ingest_arc_artifacts(params: dict, db, config: dict) -> dict:
    """Import ARC artifact files into graph-backed SideQuests memory."""
```

Supported params:

```python
{
    "artifact_root": "/absolute/path/to/ARC_AGI",  # optional
    "include_live_jsonl": True,
    "dry_run": False,
    "max_events": 5000,
}
```

Default artifact root resolution:

```python
Path(params["artifact_root"]) if provided else Path.cwd().parent / "ARC_AGI"
```

Only use the default if it exists. Otherwise return a clear error asking for `artifact_root`.

Required file discovery:

```python
ARTIFACT_FILES = {
    "master_timeline": "master_timeline.json",
    "agent_execution_trace": "agent_execution_trace.json",
    "submission_arc_server": "submission_results_arcServer.json",
    "submission_single": "submission_results_single.json",
    "submission_single_live": "submission_results_single.live.jsonl",
}
```

Importer behavior:

- Read JSON files as objects/lists.
- Read JSONL one line at a time and tolerate malformed lines.
- Compute SHA-256 per source file and per normalized record.
- Build deterministic IDs from stable fields plus hash.
- Upsert graph nodes and relationships; do not append duplicates.
- Store compact summaries, not unbounded raw payloads.
- Keep raw payload snippets bounded by config if snippets are needed for debugging.

### Step 3: Add MCP schema and tool exposure

In `mcp_engine/tool_schemas.py`, add `ingest_arc_artifacts`.

Schema shape:

```python
{
    "name": "ingest_arc_artifacts",
    "description": "Import ARC_AGI run artifacts into SideQuests graph memory for retrieval and wiki projection.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "artifact_root": {"type": "string"},
            "include_live_jsonl": {"type": "boolean", "default": True},
            "dry_run": {"type": "boolean", "default": False},
            "max_events": {"type": "integer", "default": 5000},
        },
        "additionalProperties": False,
    },
}
```

Wire the handler through the existing tool dispatch path in `mcp_engine/tools/__init__.py` or the current tool registry pattern.

### Step 4: Add CLI wrapper

Create `sidequests/cli/arc.py` if the CLI supports submodules, then expose it from `sidequests/cli/main.py`.

Command:

```bash
sidequests arc ingest-artifacts --artifact-root /Users/djshelton/Desktop/GitProjects/ARC_AGI
```

Flags:

```text
--artifact-root PATH
--no-live-jsonl
--dry-run
--max-events INT
```

CLI output should include:

```text
ARC artifact ingestion complete
Artifacts scanned: N
Artifacts ingested: N
Runs upserted: N
Task results upserted: N
Events upserted: N
Malformed records skipped: N
Dry run: true|false
```

### Step 5: Extend wiki projection for ARC records

Modify `mcp_engine/wiki_projection.py` so personas that include `ArcRun`, `ArcTaskResult`, or the `arc_agi` domain can emit ARC pages.

Suggested config update in `sidequests.toml`:

```toml
[[wiki_projection.personas]]
name = "arc_agi"
output_dir = "wiki/personas/arc_agi"
include_domains = ["arc", "arc_agi", "benchmark", "benchmarks", "evaluation", "puzzle", "agent-learning"]
include_node_types = ["ArcRun", "ArcTaskResult", "ArcArtifact", "ArcEvent", "Lesson", "KnowledgeGap", "Procedure", "Decision", "Constraint"]
max_pages_per_sweep = 80
max_chars_per_page = 8000
max_related_pages = 12
home_title = "ARC-AGI Memory"
```

ARC run pages should include:

- run status
- task/puzzle counts
- solved/failed counts
- step count
- notable failures or warnings
- SideQuests tool-call summary when available
- links to task result pages
- source graph IDs and artifact provenance

Do not link Obsidian pages directly to raw JSON as the authority. Raw paths may appear under a `Provenance` section, but the page must identify graph source IDs first.

### Step 6: Add tests

Create `tests/test_arc_artifact_ingestion.py` with fixtures for:

- minimal `master_timeline.json`
- minimal `agent_execution_trace.json`
- minimal `submission_results_single.json`
- minimal `submission_results_arcServer.json`
- minimal `submission_results_single.live.jsonl`
- one malformed JSONL line

Test cases:

- missing root returns useful error
- missing individual files are skipped
- dry run reports planned writes without writing
- ingestion creates one `ArcRun`
- ingestion creates task result records
- ingestion creates bounded event records
- repeated ingestion is idempotent
- malformed JSONL records increment skipped count
- imported nodes include ARC domains and provenance fields

Create `tests/test_wiki_projection_arc.py`:

- ingest fixture artifacts into a temp Kuzu DB
- run wiki projection with `arc_agi` persona
- assert `wiki/personas/arc_agi/pages/` contains at least one ARC run page
- assert page front matter contains source node IDs
- assert page body includes run summary and provenance
- assert drift guard behavior still works for ARC pages

### Step 7: Update docs

Update `docs/wiki-projection-architecture.md` with an ARC section:

```text
ARC_AGI artifacts are evidence inputs. They become browseable only after ingestion into KuzuDB. The wiki does not scrape raw artifact JSON directly.
```

Update `docs/ARCHITECTURE.md` to show:

```text
ARC_AGI artifacts -> ingest_arc_artifacts -> Kuzu ArcRun/ArcEvent graph -> arc_agi wiki projection
```

Also document the invariant:

```text
Only ~/.sidequests/brain.db is canonical. Test/probe DBs under ~/.sidequests are out of spec.
```

## Validation Commands

Run exactly:

```bash
pytest -q tests/test_arc_artifact_ingestion.py tests/test_wiki_projection_arc.py tests/test_wiki_projection.py tests/test_cli_wiki.py
rg -n "ingest_arc_artifacts|ArcRun|ArcArtifact|ArcTaskResult|ArcEvent|arc_agi|artifact_root|submission_results_single.live" mcp_engine sidequests tests docs sidequests.toml
find ~/.sidequests -maxdepth 1 -type f \( -name 'brain_test*.db' -o -name 'brain_single_test*.db' -o -name 'probe.db' \) -print
```

Expected result for the final command:

```text
```

It must print nothing.

## Risks

- ARC artifact schemas may vary between runs. Parsers must be tolerant and summary-oriented.
- Large live JSONL traces can be expensive to ingest. Use `max_events`, stable hashes, and bounded summaries.
- Direct raw JSON wiki export would create a shadow memory system. Keep raw files as provenance only.
- Existing daemon timeouts may block live ingestion through MCP. If that appears, file a separate daemon-health card rather than weakening the ingestion model.

## Non-Goals

- Do not move ARC runtime code back into `sidequests-brain`.
- Do not create any new `~/.sidequests/brain_test*.db`, `~/.sidequests/brain_single_test*.db`, or `~/.sidequests/probe.db` files.
- Do not make Obsidian or Markdown authoritative.
- Do not store entire unbounded ARC raw artifacts as wiki page bodies.
