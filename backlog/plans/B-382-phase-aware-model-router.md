# B-382-phase-aware-model-router — Dynamic Phase-Aware Model Router

**Card:** B382 | **Priority:** P1 | **Depends on:** B127/B128, B252, B324, B374, B384  
**Branch:** `feat/b382-phase-aware-model-router` | **PR Target:** `main`

---

## 1. Summary

Bridge local low-cost models (local Ollama, GLM 5.3) and frontier cloud models (Claude Opus 5, Sonnet 5) by using graph-native ontological state to detect project phases:
- `gist:Planning` (unsettled trade-offs, hypotheses) $\to$ Frontier Tier.
- `gist:Implementation` (locked decisions, pending action items) $\to$ Economy Tier.
- `gist:Reflex` (formatting, syntax checks) $\to$ Local Reflex Tier.

---

## 2. Technical Design

### A. Graph-Native Phase Detection (`campy/brain/thalamus/model_router.py`)
- Direct indexed lookup anchored on active `Quest` entry point:
  - Bounded 1-hop inspection:
    - If incident `Decision` nodes have `status IN ['proposed', 'evaluating']` or active contradictory constraints exist $\to$ return `Planning`.
    - If incident `Decision` nodes are locked/approved and incident open tasks are `ActionItem` DAGs with `status = 'pending'` $\to$ return `Implementation`.
  - Latency bounded to <5ms with zero full-graph scans.

### B. Ephemeral Context Bundle Dispatch
- Assemble minimal, temporary context bundle scoped to the decision.
- Send to frontier cloud model; capture output via `notify_turn`. Memory stays local; cloud model is pure ephemeral compute.

---

## 3. Concrete File Changes

- Create: `campy/brain/thalamus/model_router.py`
- Create: `campy/brain/thalamus/tools/route_task.py`
- Modify: `campy/brain/brainstem/config.py` & `campy.toml`
- Modify: `docs/tool-catalog.md`
- Create: `tests/test_model_router.py`

---

## 4. Acceptance Criteria

- [ ] Accurate classification of Planning vs Implementation tasks across 20 test scenarios.
- [ ] Phase detection executes in <5ms via bounded 1-hop pattern matching.
- [ ] Context bundles achieve >70% token savings over full-transcript dumps.
