# B-374-two-lane-thalamic-compressor — Two-Lane Thalamic Routing & Budget-Gated Pressure Relief Valve

**Card:** B374 | **Priority:** P0 | **Depends on:** B252, B289, B305, B339  
**Branch:** `feat/b374-two-lane-thalamic-compressor` | **PR Target:** `main`

---

## 1. Summary

Build on top of the shipped B289 compression infrastructure (`campy/brain/thalamus/compression/`) and `ask.py` to deliver two critical enhancements:
1. **Two-Lane Routing:** Protected Lane (Decisions, Constraints, Negative Controls) emitted verbatim with zero loss; Bulk Lane (Prose, Summaries, Concepts) compressed only when required.
2. **Budget-Gated Pressure-Relief Valve:** Replace Always-On (Option B) compression with budget-gating: if the assembled bundle is under budget, emit directly to avoid latency and information loss. Trigger compression only when exceeding the token budget.

---

## 2. Technical Design

### A. Two-Lane Content Routing
In `campy/brain/thalamus/compression/__init__.py`:
- Extend `ContentRouter`:
  - `PROTECTED_SECTION_TYPES = {"decision", "constraint", "negative_control", "exact_fact"}`
  - `BULK_SECTION_TYPES = {"summary", "semantic", "graph", "code"}`
- When `ContentRouter.route(section)` is called:
  - If section type is in `PROTECTED_SECTION_TYPES`, return `NoOpCompressor()` regardless of global settings.
  - If section type is in `BULK_SECTION_TYPES`, dispatch to registered specialized compressor (`graph_bundle`, `structured_data`, `llm_prose`, `ast_code`).

### B. Budget-Gated Execution in `ask.py`
In `campy/brain/thalamus/ask.py`:
- In `run_ask(query, budget_tokens, ...)`:
  - Assemble initial bundle from `compile_bundle(...)`.
  - Calculate `total_tokens = sum(s.estimated_tokens for s in bundle.sections)`.
  - If `total_tokens <= budget_tokens`:
    - Log: "Bundle size within budget (%d <= %d). Bypassing compression stage."
    - Skip compression, proceed directly to LLM inference.
  - If `total_tokens > budget_tokens`:
    - Log: "Bundle size exceeds budget (%d > %d). Triggering two-lane compression."
    - Compress Bulk Lane sections while preserving Protected Lane sections verbatim.

### C. Prose Compression Prompt Tuning
In `campy/brain/thalamus/compression/llm_prose.py`:
- Update compression prompt:
  ```
  You are a high-fidelity information compressor.
  Your task: Compress the provided text to fit within {target_tokens} tokens.
  STRICT CONSTRAINTS:
  1. Preserve every entity name, decision identifier, requirement, numeric parameter, and negation verbatim.
  2. Eliminate only prose filler, conversational fluff, pleasantries, and redundant sentences.
  3. Never alter or summarize a negative assertion ("do NOT", "must never").
  ```

---

## 3. Concrete File Changes

- Modify: `campy/brain/thalamus/compression/__init__.py`
- Modify: `campy/brain/thalamus/compression/llm_prose.py`
- Modify: `campy/brain/thalamus/ask.py`
- Modify: `campy/brain/brainstem/config.py` & `campy.toml`
- Create: `tests/test_thalamic_compression.py`
- Create: `tests/test_ask_pipeline.py`

---

## 4. Acceptance Criteria

- [ ] Protected lane items are never modified or compressed.
- [ ] Bundles under token budget bypass compression stage.
- [ ] Bundles exceeding token budget are compressed to fit budget.
- [ ] Graph-native semantic pruning in `GraphBundleCompressor` preserved.
- [ ] 100% test pass in `tests/test_thalamic_compression.py` and `tests/test_ask_pipeline.py`.
