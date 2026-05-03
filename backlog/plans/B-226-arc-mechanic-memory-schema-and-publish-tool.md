# Plan for B226 - ARC Mechanic Memory Schema and Publish Tool

## Card Metadata

- **Card ID**: B226
- **Priority**: P0
- **Dependencies**: B225

## Summary

Implement durable graph-native storage for ARC aggregate mechanic memory and expose `publish_mechanic_summary`.

Graph-solution classification:

- **Decision**: graph is the right tool because mechanics are defined by relationships among actions, effects, hypotheses, failures, recoveries, and games.
- **Model**: labeled property graph, not RDF. The runtime needs bounded operational traversals and edge properties for confidence/provenance.
- **Implementation**: KuzuDB schema plus MCP tool handler.

## Technical Approach

### Step 1: Add schema

Modify `mcp_engine/schema.py` using existing schema helper patterns.

Add node tables defensively:

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcMechanic(
  mechanic_id STRING,
  name STRING,
  signature STRING,
  confidence DOUBLE,
  terminal_relevance DOUBLE,
  coordinate_relevance DOUBLE,
  source_task_ids STRING,
  evidence_count INT64,
  contradiction_count INT64,
  domain STRING,
  summary STRING,
  created_at STRING,
  updated_at STRING,
  PRIMARY KEY (mechanic_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcActionPattern(
  pattern_id STRING,
  signature STRING,
  action_set STRING,
  action_count INT64,
  summary STRING,
  PRIMARY KEY (pattern_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcEffectPattern(
  pattern_id STRING,
  signature STRING,
  effect_class STRING,
  terminal_trend STRING,
  object_progress DOUBLE,
  summary STRING,
  PRIMARY KEY (pattern_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcPrecondition(
  precondition_id STRING,
  kind STRING,
  signature STRING,
  summary STRING,
  PRIMARY KEY (precondition_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcFailureMode(
  failure_mode_id STRING,
  name STRING,
  signature STRING,
  summary STRING,
  PRIMARY KEY (failure_mode_id)
)
```

```cypher
CREATE NODE TABLE IF NOT EXISTS ArcRecoveryPolicy(
  recovery_policy_id STRING,
  name STRING,
  summary STRING,
  confidence DOUBLE,
  PRIMARY KEY (recovery_policy_id)
)
```

Add relationships:

```cypher
CREATE REL TABLE IF NOT EXISTS ARC_MECHANIC_HAS_ACTION_PATTERN(FROM ArcMechanic TO ArcActionPattern, confidence DOUBLE, evidence_count INT64)
CREATE REL TABLE IF NOT EXISTS ARC_MECHANIC_CAUSES_EFFECT_PATTERN(FROM ArcMechanic TO ArcEffectPattern, confidence DOUBLE, evidence_count INT64)
CREATE REL TABLE IF NOT EXISTS ARC_MECHANIC_REQUIRES(FROM ArcMechanic TO ArcPrecondition, confidence DOUBLE)
CREATE REL TABLE IF NOT EXISTS ARC_MECHANIC_FAILS_AS(FROM ArcMechanic TO ArcFailureMode, evidence_count INT64)
CREATE REL TABLE IF NOT EXISTS ARC_FAILURE_RECOVERED_BY(FROM ArcFailureMode TO ArcRecoveryPolicy, confidence DOUBLE)
```

If existing generic provenance relationships are available, connect mechanics to source run/task records created by B225. Otherwise store source IDs as bounded string fields and leave a TODO for a future provenance edge card.

### Step 2: Implement upsert helper

Create `mcp_engine/tools/arc_mechanics.py`.

Public function:

```python
async def publish_mechanic_summary(params: dict, db, config: dict) -> dict:
    ...
```

Accepted params:

```python
{
  "summary": {
    "id": "mech-task-hash",
    "name": "...",
    "task_id": "arc_eval_001",
    "action_set_signature": "ACTION6",
    "hypotheses": [...],
    "effects": [...],
    "confidence": 0.8,
    "terminal_relevance": 0.0,
    "coordinate_relevance": 0.0,
    "failure_modes": ["single_action_terminal_stall"],
    "recovery_policies": [...]
  },
  "async_dispatch": true
}
```

Implementation requirements:

- Normalize missing fields safely.
- Compute stable IDs from explicit `summary.id` when present; otherwise hash normalized signature fields.
- Use parameterized Kuzu queries.
- Upsert nodes before edges.
- Aggregate repeated publication by updating confidence/evidence counts and `updated_at`.
- Keep summaries bounded to a configured length.

### Step 3: Expose tool

Modify:

- `mcp_engine/tools/__init__.py`
- `mcp_engine/tool_schemas.py`
- any adapter pass-throughs or allow-lists that do not centralize from tool schemas

Run:

```bash
rg -n "TOOL_HANDLERS|TOOLS|publish_mechanic_summary" mcp_engine sidequests adapters docs tests
```

### Step 4: Tests

Create `tests/test_arc_mechanic_memory.py`:

- schema initializes with new tables
- publish creates one mechanic, action pattern, effect pattern, and edges
- repeated publish is idempotent
- missing optional fields do not crash
- large raw payload fields are bounded
- tool appears in `tools/list`

## Validation Commands

```bash
pytest -q tests/test_arc_mechanic_memory.py tests/test_adapters.py
rg -n "publish_mechanic_summary|ArcMechanic|ArcActionPattern|ArcEffectPattern|ARC_MECHANIC" mcp_engine sidequests tests docs
```

## Risks

- Kuzu schema migration must remain additive.
- Avoid high-degree global `ACTION6` nodes by scoping action-pattern signatures through mechanic/action-set signatures.
- Do not turn mechanic summaries into raw JSON shadow storage.
