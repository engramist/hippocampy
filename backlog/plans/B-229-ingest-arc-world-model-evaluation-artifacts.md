# Plan for B229 - Ingest ARC World-Model Evaluation Artifacts

## Card Metadata

- **Card ID**: B229
- **Priority**: P1
- **Dependencies**: B225, B226, B227

## Summary

Extend B225 ARC artifact ingestion to include the new world-model evaluation stream and final world-model snapshots emitted by `ARC_AGI`.

Graph-solution classification:

- **Decision**: graph is appropriate because evaluation facts connect runs, tasks, steps, action effects, hypotheses, mechanics, planner decisions, and failure modes.
- **Model**: labeled property graph, with compact metric nodes and provenance edges.
- **Testing**: deterministic fixture graphs and JSONL ingestion regression tests.

## Technical Approach

### Step 1: Add artifact discovery

In `mcp_engine/tools/arc_artifacts.py`, extend file discovery:

```python
ARTIFACT_FILES["submission_single_world_model_live"] = "submission_results_single.world_model.live.jsonl"
```

Do not require the file to exist. Skip with warning if absent.

### Step 2: Add schema if needed

If existing `ArcEvent`/`ArcArtifact` can represent these rows cleanly, reuse them. If not, add compact node types:

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcWorldModelStep(
  world_model_step_id STRING,
  run_id STRING,
  task_id STRING,
  step_index INT64,
  node_count INT64,
  edge_count INT64,
  compiled_claim_count INT64,
  action_effect_class STRING,
  reasoning_mode STRING,
  planner_candidate_count INT64,
  single_action_stall_detected BOOL,
  summary STRING,
  created_at STRING,
  PRIMARY KEY (world_model_step_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcWorldModelSummary(
  world_model_summary_id STRING,
  run_id STRING,
  task_id STRING,
  graph_bounded BOOL,
  compiler_active BOOL,
  falsification_active BOOL,
  reasoning_gated BOOL,
  planner_grounded BOOL,
  memory_transfer_active BOOL,
  single_action_stall_detected BOOL,
  full_reasoning_cycles_avoided INT64,
  summary STRING,
  created_at STRING,
  PRIMARY KEY (world_model_summary_id)
)
```

Relationships:

```cypher
CREATE REL TABLE IF NOT EXISTS ARC_RUN_HAS_WORLD_MODEL_STEP(FROM ArcRun TO ArcWorldModelStep)
CREATE REL TABLE IF NOT EXISTS ARC_RUN_HAS_WORLD_MODEL_SUMMARY(FROM ArcRun TO ArcWorldModelSummary)
CREATE REL TABLE IF NOT EXISTS ARC_WORLD_MODEL_FROM_ARTIFACT(FROM ArcWorldModelStep TO ArcArtifact)
CREATE REL TABLE IF NOT EXISTS ARC_WORLD_MODEL_SUMMARY_FROM_ARTIFACT(FROM ArcWorldModelSummary TO ArcArtifact)
```

### Step 3: Parse JSONL

For each line in `submission_results_single.world_model.live.jsonl`:

- parse as JSON
- inspect `kind`
- if `world_model_step`, upsert `ArcWorldModelStep`
- if `world_model_summary`, upsert `ArcWorldModelSummary`
- otherwise record skipped row count

IDs should be stable:

```text
sha256(kind + task_id + step + source_artifact_hash + normalized_row)
```

### Step 4: Parse final snapshots

In `submission_results_single.json`, look for `world_model_snapshot` per task result.

Extract bounded summary fields:

- node count
- edge count
- labels present
- effect classes present
- active/demoted hypothesis counts if available
- source task/game/result IDs

Do not store the full `nodes`/`edges` payload as unbounded text. Store compact summaries and use hashes for provenance.

### Step 5: Wiki projection

Update `mcp_engine/wiki_projection.py` for the `arc_agi` persona:

- run page includes a World Model Health section
- show graph bounded/compiler/reasoning/planner/memory transfer booleans
- show latest action effect class and stall signal
- link to source graph IDs

### Step 6: Tests

Update `tests/test_arc_artifact_ingestion.py` fixtures:

- minimal world-model JSONL with one step row and one summary row
- malformed row
- `submission_results_single.json` with `world_model_snapshot`

Update `tests/test_wiki_projection_arc.py`:

- projected ARC page includes world-model health without dumping raw snapshot JSON

## Validation Commands

```bash
pytest -q tests/test_arc_artifact_ingestion.py tests/test_wiki_projection_arc.py
rg -n "world_model.live|world_model_snapshot|ArcWorldModel|compiled_claim|single_action_stall" mcp_engine tests docs
```

## Risks

- Do not make world-model JSONL required for older ARC runs.
- Keep raw snapshot payloads bounded to avoid turning graph memory into blob storage.
- Preserve B225 idempotency guarantees.
