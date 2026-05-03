# Plan for B227 - ARC Mechanic Prior Retrieval and Ranking Tool

## Card Metadata

- **Card ID**: B227
- **Priority**: P0
- **Dependencies**: B226

## Summary

Implement `recall_mechanic_priors` over the ARC mechanic graph created in B226.

Graph-solution classification:

- **Decision**: graph retrieval is appropriate because the query walks mechanics to action patterns, effect patterns, failure modes, and recovery policies.
- **Model**: labeled property graph.
- **Optimization**: index/filter by entry signatures, bound traversal depth, avoid high-degree hubs.

## Technical Approach

### Step 1: Define input contract

Tool params:

```python
{
  "signature": {
    "action_set": "ACTION6",
    "archetype": "space",
    "effect_class": "pixel_churn",
    "terminal_trend": "flat",
    "coordinate_relevance": "irrelevant",
    "failure_signal": "single_action_terminal_stall"
  },
  "limit": 5,
  "min_confidence": 0.0
}
```

All signature fields are optional. Missing fields should not crash.

### Step 2: Implement bounded retrieval

In `mcp_engine/tools/arc_mechanics.py`, add:

```python
async def recall_mechanic_priors(params: dict, db, config: dict) -> dict:
    ...
```

Retrieval flow:

1. Normalize signature.
2. Filter `ArcMechanic` by `confidence >= min_confidence`.
3. Filter early by action-set signature when present.
4. Join to `ArcActionPattern` and `ArcEffectPattern`.
5. Expand at most one hop to `ArcFailureMode` and one hop to `ArcRecoveryPolicy`.
6. Score in Python if Kuzu query simplicity is preferable.
7. Return at most `limit`.

Ranking factors:

- exact action-set match
- overlapping effect class
- matching terminal trend
- matching coordinate relevance
- matching failure signal
- mechanic confidence
- evidence count
- recency if `updated_at` exists

### Step 3: Response shape

Return:

```python
{
  "results": [
    {
      "id": "mech-...",
      "name": "...",
      "confidence": 0.82,
      "similarity": 0.71,
      "action_patterns": [...],
      "effect_patterns": [...],
      "failure_modes": [...],
      "recovery_policies": [...],
      "evidence_summary": "...",
      "source_task_ids": [...]
    }
  ],
  "query_signature": {...},
  "limit": 5
}
```

Keep result payload compact. Do not return raw source artifacts or full traces.

### Step 4: Expose tool

Update:

- `mcp_engine/tools/__init__.py`
- `mcp_engine/tool_schemas.py`
- adapter allow-lists if needed
- `docs/tool-catalog.md`

### Step 5: Tests

Extend `tests/test_arc_mechanic_memory.py`:

- empty DB returns empty results
- exact action/effect match ranks first
- `limit` caps result count
- `min_confidence` filters low-confidence mechanics
- failure/recovery policy appears when connected
- result payload is bounded

## Validation Commands

```bash
pytest -q tests/test_arc_mechanic_memory.py tests/test_adapters.py
rg -n "recall_mechanic_priors|mechanic_priors|ArcMechanic|ARC_MECHANIC" mcp_engine sidequests tests docs
```

## Risks

- Query plans can become slow if traversal starts from global action labels. Always enter through mechanic/action-set signatures and bound expansion.
- Ranking must treat memory as evidence, not truth. Return confidence and provenance.
