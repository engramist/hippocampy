# B-383-automated-model-handoff — Automated Model Handoff Generator

**Card:** B383 | **Priority:** P1 | **Depends on:** B252, B312, B321, B374, B384  
**Branch:** `feat/b383-automated-model-handoff` | **PR Target:** `main`

---

## 1. Summary

Realize Patent Claim #7 (Session Handoff Intelligence) by generating standardized, zero-amnesia handoff artifacts directly from the graph when switching models or sessions.

---

## 2. Technical Design

### A. Boundary Subgraph Extraction (`campy/brain/thalamus/handoff.py`)
- Root anchor: active `Quest` and current session `[LOADED]` nodes.
- Filter early: exclude `archived = true` and `[:DEPRECATED_BY]` nodes at root.
- Expand late: $\le 2$ hops along `:ENABLES`, `:CONSTRAINS`, `:REQUIRES`.
- Hard-cap extracted subgraph to $\le 40$ entity nodes to fit tight prompt budgets (<500 tokens).
- Topologically sort active `ActionItem` nodes into an executable DAG.

### B. Export Formats
- CLI: `campy handoff --copy` (copies clean markdown to clipboard).
- MCP tool: `generate_handoff(target_tier="economy")`.
- Clean markdown formatting consumable by any model without XML tag dependencies.

---

## 3. Concrete File Changes

- Create: `campy/brain/thalamus/handoff.py`
- Create: `campy/brain/thalamus/tools/generate_handoff.py`
- Modify: `campy/cli/main.py`
- Modify: `docs/tool-catalog.md`
- Create: `tests/test_automated_handoff.py`

---

## 4. Acceptance Criteria

- [ ] `campy handoff` generates structured markdown in <500ms.
- [ ] 100% of confirmed active constraints and decisions included; deprecated facts excluded.
- [ ] Subgraph extraction strictly capped at $\le 2$ hops and $\le 40$ nodes.
- [ ] Seeding a new model with the handoff achieves 100% adherence to historical constraints.
