# Plan: B-278 — ARC-Specific MCP Query Tools for Agent v2

## Card metadata

- **Card:** B278
- **Priority:** P0
- **Depends on:** B277

## Summary

Implement the 14 ARC-specific MCP query tools in `campy/brain/thalamus/tools/arc_queries.py`, register them in `TOOL_HANDLERS`, and lock the cross-repo contract used by ARC A123.

## Cross-repo contract

This card is the producer for ARC A123.

The exact tool names exposed here must be the names consumed by the ARC-side adapter in `ARC_AGI/agents/arc4/graph_queries.py`.

Do not ask ARC-side cards to call Kuzu directly or import Campy internals. The MCP seam remains the only runtime boundary.

## Implementation approach

### Step 1: Implement `campy/brain/thalamus/tools/arc_queries.py`

Group the 14 tools by purpose and keep each tool bounded over existing ARC schema types only.

Required tool groups:

- sensory ingestion: `arc_perceive_state`
- hippocampus-style game/action context reads and writes
- temporal-lobe goal and hypothesis reads and updates
- basal-ganglia gate and reward-prediction reads

Use existing ARC node types already referenced in the card. Do not introduce new schema families unless the card is explicitly updated.

### Step 2: Normalize response shapes for ARC v2 consumers

Each tool should return compact, predictable dictionaries that the ARC-side adapter can normalize with minimal special-casing.

At minimum, the response keys described in the card body should be stable for:

- untested action lookup
- action evidence lookup
- goal evidence lookup
- action gate checks
- entity movement lookup
- action-effect recording
- goal confidence updates
- hypothesis confirm/contradict writes

### Step 3: Register the tools

Update the tool registration surface so these 14 tools are available through the MCP adapters and visible to tool-surface verification.

### Step 4: Add focused tests

Add a focused test module, for example `tests/test_arc_query_tools.py`, that covers:

- tool registration
- representative read-path queries
- representative write-path tools
- empty-state behavior on a new task
- bounded traversal behavior for causal-path and gate checks

## Concrete file edits

- `campy/brain/thalamus/tools/arc_queries.py`
- the relevant `TOOL_HANDLERS` registration file
- `tests/test_arc_query_tools.py`

## Validation commands

```bash
pytest -q tests/test_arc_query_tools.py
```

```bash
pytest -q tests/test_adapters.py
```

## Assumptions and defaults

- B277 is already complete and provides the basal-ganglia helpers needed for gate-oriented ARC queries.
- Existing adapter and tool-surface conventions from hippocampy still apply.
- If a tool needs a richer payload than the current card suggests, update both this plan and the ARC A123 adapter contract together.