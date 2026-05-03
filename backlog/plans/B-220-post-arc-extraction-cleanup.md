# Plan for B220 - Post ARC-AGI Extraction Repo Cleanup Audit

## Card Metadata

- **Card ID**: B220
- **Priority**: P1
- **Dependencies**: None

## Summary

Create a reviewable cleanup audit after ARC-AGI was split into its own repo. Classify ARC-related files by ownership and apply only low-risk cleanup changes inside SideQuests Brain.

## Technical Approach

### Step 1: Inventory ARC references

Run:

```bash
rg -n "ARC|arc|ARC_AGI|arc-agi" docs backlog benchmarks agents tests mcp_engine adapters .gitignore
find . -maxdepth 3 -iname '*arc*' -print
```

Group results by directory:

- `mcp_engine/` and `adapters/`: usually SideQuests-owned if they expose generic MCP/task/memory contracts.
- `benchmarks/`, `agents/`, and ARC-specific backlog plans: likely migrated or historical.
- `docs/`: keep only if they describe SideQuests contracts or explicitly label external ARC integration.
- generated result files: ignore or archive.

### Step 2: Create cleanup manifest

Create `docs/arc-extraction-cleanup-audit.md` with:

- scope and date
- inventory command output summary
- ownership classification table
- recommended action per artifact
- "do not remove" list for SideQuests-owned contracts
- follow-up cards if large moves are needed

### Step 3: Apply low-risk cleanup only

Allowed in this card:

- add generated ARC result patterns to `.gitignore`
- add ownership notes to docs
- mark backlog cards as migrated/historical if they are no longer active here

Not allowed in this card:

- delete whole directories without explicit follow-up review
- modify sibling `ARC_AGI`
- change MCP tool behavior
- remove tests that still validate SideQuests-owned contracts

### Step 4: Verify no active contracts broke

Run focused tests for adapters and task graph contracts.

## Acceptance Criteria

- `docs/arc-extraction-cleanup-audit.md` exists and classifies all ARC-related artifacts.
- Active SideQuests-owned integration points are preserved.
- Generated ARC files are ignored or documented.
- Any follow-up cleanup cards are named in the audit document.

## Validation Commands

```bash
rg -n "ARC|arc|ARC_AGI|arc-agi" docs backlog benchmarks agents tests mcp_engine adapters .gitignore
git status --short
pytest -q tests/test_adapters.py tests/test_b128_task_graph_tools.py tests/test_tool_catalog.py
```

## Risks

- Some ARC-named files may still be legitimate SideQuests integration tests.
- The sibling repo boundary may be partly contractual rather than filesystem-obvious.
- Large deletion work should become separate cards after the manifest is reviewed.
