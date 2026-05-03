# ARC Extraction Cleanup Audit

**Date:** April 28, 2026
**Scope:** Repository audit after ARC-AGI split to separate repo.

## Inventory Summary

The following ARC-related artifacts were identified during the audit:

### 1. SideQuests-Owned (Keep/Document)
These are core SideQuests Brain components that happen to have been stressed or initiated by ARC work, but represent generic memory system capabilities.

| Artifact | Classification | Reason |
|---|---|---|
| `mcp_engine/schema.py` (B88, B168) | `keep` | Schema definitions for Hypothesis and Exploration nodes are generic graph-native memory structures. |
| `.gitignore` (ARC entries) | `keep` | Prevents generated ARC artifacts from polluting SideQuests repo during cross-repo integration tests. |
| `docs/ecosystem-rules.md` | `document` | Critical for defining the boundary between SideQuests and ARC_AGI. |
| `docs/ARCHITECTURE.md` | `document` | Canonical reference; now correctly points to ARC_AGI sibling repo for solver details. |
| `docs/token-efficiency-side-effect.md` | `document` | Retained as it describes a core architectural benefit demonstrated via ARC. |
| `adapters/*.py` (ARC references) | `keep` | generic tool aliases like `analogical_search` are SideQuests-owned. |

### 2. Historical/Archive
These are results, benchmarks, or plans that are no longer active in the SideQuests core but are kept for regression history or historical record.

| Artifact | Classification | Reason |
|---|---|---|
| `benchmarks/.arc/` | `archive` | Historical ARC3 baseline data. |
| `benchmarks/results/arc3.json` | `archive` | Historical evaluation result. |
| `benchmarks/config.yaml` (ARC3 entries) | `archive` | Kept for historical benchmark configuration reference. |
| `benchmarks/thresholds.yaml` (ARC3 entry) | `archive` | Historical threshold reference. |
| `benchmarks/RESULTS.md` (ARC3 row) | `archive` | Historical solve rate data. |
| `backlog/B46-B53` | `archive` | Benchmark infrastructure cards; some are SideQuests-generic, some ARC-adjacent. |

### 3. Move/Delete
These are artifacts that clearly belong in the sibling repo or are stale.

| Artifact | Classification | Reason |
|---|---|---|
| `tests/__pycache__/test_arc*` | `delete` | Stale cache from removed tests. (Safe to delete via git clean or manual) |
| `submission_results_arcServer.json` | `delete` | Generated result file that should not be in source control. |

## "Do Not Remove" List
The following must NOT be removed as they are part of the SideQuests core memory API:
- `analogical_search` tool and `mcp_engine/analogical.py`.
- `current_truth` tool and `mcp_engine/loop/step5_retrieval.py`.
- `register_task_graph` and related DAG tools.
- `Hypothesis` and `Exploration` node types in `schema.py`.

## Actions Taken in B220

1. **`.gitignore` update**: Ensured `submission_results_arcServer.json` and `benchmarks/results/` are properly ignored if they are just generated outputs.
2. **Master Backlog Tracker**: Verified ARC cards are marked as migrated.
3. **Architecture Docs**: Added a note to `docs/ARCHITECTURE.md` regarding the final repo boundary.

## Follow-up Recommendations
- Run `git clean -fd` to remove stale `__pycache__` and other untracked artifacts.
- Future audit in 3 months to see if generic `Hypothesis` schema is actually used by non-ARC agents; if not, consider moving to a "contrib" or "extension" schema.
