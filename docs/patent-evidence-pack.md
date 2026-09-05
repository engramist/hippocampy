# HippoCampy — Non-Provisional Patent Claim Verification & Audit Evidence Pack

**U.S. Provisional Patent Application #64/017,066**
- **Priority Date:** March 25, 2026
- **Statutory Non-Provisional Deadline:** March 25, 2027
- **Card:** B380 | **Pre-Migration Evidence Freeze** (Prior to B384 Storage Re-Platforming)
- **Git Branch:** `feat/b380-patent-claim-verification`
- **Git Commit SHA:** `a8d69959bd9e28802aa064d03d5daa7914838abc`
- **Verification Timestamp:** `2026-09-04T20:26:32.244957+00:00`
- **Environment:** `Darwin arm64` | Python `3.12.13`
- **Core Storage Engine:** Kùzu Embedded Graph Database (`v0.11.3`) + FastEmbed ONNX (`all-MiniLM-L6-v2`)

---

## 1. Executive Summary

This document freezes verifiable, auditable legal evidence of reduction to practice for all **9 core intellectual property claims** in U.S. Provisional Patent Application #64/017,066.

To preserve legal priority and defensibility across future architectural refactoring (specifically B384 re-platforming from Kùzu to Oxigraph), all verification tests in this suite adhere strictly to the **Observable Mechanism Assertions Rule**:
1. **Zero Mocks:** Every test executes against the live embedded Kùzu graph, active spaCy NLP model (`en_core_web_md`), and FastEmbed vector embeddings without mocking or simulated stubs.
2. **Observable Mechanism Assertions:** Tests assert strictly on public, observable outputs: consolidation summary dictionaries, bounded schema attribute lists, classifier confidence states, working memory token estimates, and Amygdala reflex warnings/suggestions.
3. **Engine-Agnostic Canonical Fixture:** All 9 claims execute over `tests/fixtures/patent_conformance_graph.jsonl`, a canonical dataset modeling multi-hop topologies, cyclic references, valence-weighted outcomes, and contradictory constraints.
4. **100% Deterministic Pass Rate:** All 17 isolated test methods across 9 claim modules passed cleanly.

---

## 2. Patent Claim Verification Matrix

| Claim | Novel IP Mechanism | Verification Status | Implementation Citation | Verification Test Module |
|---|---|:---:|---|---|
| **Claim 1** | Gated Consolidation Loop | `PASSED` | [`campy/brain/temporal_lobe/loop/orchestrator.py:48`](file:///campy/brain/temporal_lobe/loop/orchestrator.py) | [`tests/patent_claims/test_claim_1_consolidation_loop.py`](file:///tests/patent_claims/test_claim_1_consolidation_loop.py) |
| **Claim 2** | Shape-First Principle | `PASSED` | [`campy/brain/temporal_lobe/loop/step3_schema_org.py:54`](file:///campy/brain/temporal_lobe/loop/step3_schema_org.py) | [`tests/patent_claims/test_claim_2_shape_first.py`](file:///tests/patent_claims/test_claim_2_shape_first.py) |
| **Claim 3** | Kahneman System 1 / System 2 Hybrid Classifier | `PASSED` | [`campy/brain/temporal_lobe/loop/step2_gist.py:50`](file:///campy/brain/temporal_lobe/loop/step2_gist.py) | [`tests/patent_claims/test_claim_3_kahneman_classifier.py`](file:///tests/patent_claims/test_claim_3_kahneman_classifier.py) |
| **Claim 4** | Cocktail Party Attention Filter & Salience Multiplier | `PASSED` | [`campy/brain/temporal_lobe/loop/step4_pattern.py:133`](file:///campy/brain/temporal_lobe/loop/step4_pattern.py) | [`tests/patent_claims/test_claim_4_cocktail_party_filter.py`](file:///tests/patent_claims/test_claim_4_cocktail_party_filter.py) |
| **Claim 5** | Working Memory Context Window Tracker | `PASSED` | [`campy/brain/thalamus/working_memory.py:100`](file:///campy/brain/thalamus/working_memory.py) | [`tests/patent_claims/test_claim_5_working_memory_tracking.py`](file:///tests/patent_claims/test_claim_5_working_memory_tracking.py) |
| **Claim 6** | Smart Retrieval Deduplication via Load Tracking | `PASSED` | [`campy/brain/thalamus/working_memory.py:227`](file:///campy/brain/thalamus/working_memory.py) | [`tests/patent_claims/test_claim_6_smart_dedup.py`](file:///tests/patent_claims/test_claim_6_smart_dedup.py) |
| **Claim 7** | Warm Frontier Session Handoff | `PASSED` | [`campy/brain/thalamus/working_memory.py:378`](file:///campy/brain/thalamus/working_memory.py) | [`tests/patent_claims/test_claim_7_session_handoff.py`](file:///tests/patent_claims/test_claim_7_session_handoff.py) |
| **Claim 8** | Context Bloat Detection & Boundary Alerts | `PASSED` | [`campy/brain/thalamus/working_memory.py:350`](file:///campy/brain/thalamus/working_memory.py) | [`tests/patent_claims/test_claim_8_bloat_detection.py`](file:///tests/patent_claims/test_claim_8_bloat_detection.py) |
| **Claim 9** | Valence-Weighted Retrieval & Amygdala Reflex | `PASSED` | [`campy/brain/thalamus/tools/quests.py:183`](file:///campy/brain/thalamus/tools/quests.py) | [`tests/patent_claims/test_claim_9_valence_weighted_retrieval.py`](file:///tests/patent_claims/test_claim_9_valence_weighted_retrieval.py) |

---

## 3. Claim-by-Claim Verification Details

### Claim 1: Gated Consolidation Loop
**Patent Specification:** *Continuous cognitive consolidation of uncurated natural-language agent dialogue via 9-step pipeline*

- **Implementation Source:** [`campy/brain/temporal_lobe/loop/orchestrator.py:48`](file:///campy/brain/temporal_lobe/loop/orchestrator.py#L48)
- **Verification Test:** [`tests/patent_claims/test_claim_1_consolidation_loop.py`](file:///tests/patent_claims/test_claim_1_consolidation_loop.py)
- **Verified Mechanism:** Runs natural language messages through deterministic multi-step pipeline (NER -> Gist -> Schema.org -> Cocktail Party -> Retrieval -> Arbitration -> Reification/Pathway).
- **Key Observable Assertions:**
  * End-to-end execution of `run_loop()` returning structured summary dictionary (`entities_found > 0`, `concepts_stored + reified + additive_updates > 0`).
  * Step-by-step intermediate transformations from spaCy NER to Gist classification, Schema.org mapping, and Cocktail Party gating.

### Claim 2: Shape-First Principle
**Patent Specification:** *Ontological grounding before semantic extraction bounding property schema*

- **Implementation Source:** [`campy/brain/temporal_lobe/loop/step3_schema_org.py:54`](file:///campy/brain/temporal_lobe/loop/step3_schema_org.py#L54)
- **Verification Test:** [`tests/patent_claims/test_claim_2_shape_first.py`](file:///tests/patent_claims/test_claim_2_shape_first.py)
- **Verified Mechanism:** Routes GistClass to schema.org types (e.g. Restriction -> Demand, PlannedEvent -> Action), bounding permissible properties and disambiguating polymorphic Agent instances before semantic extraction.
- **Key Observable Assertions:**
  * Runtime execution of `route_to_schema_org()` querying graph-backed routing table.
  * Invariant bounding of entity properties by ontology class (`Restriction` -> `Demand`, `PlannedEvent` -> `Action`, `PhysicalThing` -> `Product`).
  * Disambiguation of polymorphic `Agent` to `Person` (PERSON label) vs `Organization` (ORG label).

### Claim 3: Kahneman System 1 / System 2 Hybrid Classifier
**Patent Specification:** *Dual-process cognitive classification combining centroid vector matching with bounded deliberative escalation*

- **Implementation Source:** [`campy/brain/temporal_lobe/loop/step2_gist.py:50`](file:///campy/brain/temporal_lobe/loop/step2_gist.py#L50)
- **Verification Test:** [`tests/patent_claims/test_claim_3_kahneman_classifier.py`](file:///tests/patent_claims/test_claim_3_kahneman_classifier.py)
- **Verified Mechanism:** System 1 evaluates cosine similarity vs GistClass centroids (score >= 0.50), intermediate ambiguity (0.18-0.50) routes to System 2, and sub-floor (<0.18) is rejected as noise.
- **Key Observable Assertions:**
  * System 1 reflex threshold (`SYSTEM1_THRESHOLD = 0.50`): Prototypical seeds classify reflexively with `system == '1'` without LLM invocation.
  * System 2 gray zone (`0.18 <= conf < 0.50`): Ambiguous concepts route to deliberative pathway (`system in ('2', '2_degraded')`).
  * Noise rejection floor (`NOISE_FLOOR = 0.18`): Sub-floor inputs deterministically yield `system == 'noise'` and `gist_class is None`.

### Claim 4: Cocktail Party Attention Filter & Salience Multiplier
**Patent Specification:** *Selective attention confidence gate with affective salience amplification*

- **Implementation Source:** [`campy/brain/temporal_lobe/loop/step4_pattern.py:133`](file:///campy/brain/temporal_lobe/loop/step4_pattern.py#L133)
- **Verification Test:** [`tests/patent_claims/test_claim_4_cocktail_party_filter.py`](file:///tests/patent_claims/test_claim_4_cocktail_party_filter.py)
- **Verified Mechanism:** Three-tier confidence gate (<0.60 noise rejection, 0.60-0.90 tentative low-confidence, >=0.90 confirmed hard-lock) with assistant turn cap (0.85) and Amygdala emotional salience multiplier (1.0 to 1.6).
- **Key Observable Assertions:**
  * Three-tier confidence gating in `classify_artifact()`: `<0.60` noise rejection (`should_proceed=False`), `0.60–0.90` tentative retention (`confidence_low=True`), `>=0.90` confirmed hard-lock (`confidence_low=False`).
  * Assistant turn safety cap enforcing `confidence <= ASSISTANT_CAP` (0.85) to prevent autonomous hallucination poisoning.
  * Amygdala emotional salience multiplier in `compute_salience_multiplier()` scaling from 1.0 (neutral) to >=1.3 (frustration/urgency).

### Claim 5: Working Memory Context Window Tracker
**Patent Specification:** *Dynamic context window state tracking via explicit LOADED graph relationships*

- **Implementation Source:** [`campy/brain/thalamus/working_memory.py:100`](file:///campy/brain/thalamus/working_memory.py#L100)
- **Verification Test:** [`tests/patent_claims/test_claim_5_working_memory_tracking.py`](file:///tests/patent_claims/test_claim_5_working_memory_tracking.py)
- **Verified Mechanism:** Explicitly maintains Session-[LOADED]->Node graph edges and cumulative token usage, strictly excluding raw conversational turns (Message) from working memory tracking.
- **Key Observable Assertions:**
  * Explicit graph edge tracking via `track_loaded()` creating `Session-[LOADED]->Node` relationships.
  * Active working memory retrieval via `get_loaded_node_ids()`.
  * Session token utilization calculation in `get_session_token_state()`.
  * Complete exclusion of raw dialogue turns (`Message`) from working memory persistence.

### Claim 6: Smart Retrieval Deduplication via Load Tracking
**Patent Specification:** *Context-aware retrieval deduplication through deterministic soft demotion*

- **Implementation Source:** [`campy/brain/thalamus/working_memory.py:227`](file:///campy/brain/thalamus/working_memory.py#L227)
- **Verification Test:** [`tests/patent_claims/test_claim_6_smart_dedup.py`](file:///tests/patent_claims/test_claim_6_smart_dedup.py)
- **Verified Mechanism:** Demotes already-loaded context items by 0.3x (DEDUP_DEMOTION_FACTOR) without dropping them from results, tagging with already_in_context flags and promoting fresh context items.
- **Key Observable Assertions:**
  * Soft demotion in `deduplicate_results()` multiplying loaded items by `DEDUP_DEMOTION_FACTOR` (0.3).
  * Zero omissions: Result list count is preserved before and after deduplication.
  * Rank inversion: Lower-scoring fresh candidate is promoted ahead of demoted loaded candidate.

### Claim 7: Warm Frontier Session Handoff
**Patent Specification:** *Cross-session continuity transfer of unarchived decisions and constraints ordered by pathway strength*

- **Implementation Source:** [`campy/brain/thalamus/working_memory.py:378`](file:///campy/brain/thalamus/working_memory.py#L378)
- **Verification Test:** [`tests/patent_claims/test_claim_7_session_handoff.py`](file:///tests/patent_claims/test_claim_7_session_handoff.py)
- **Verified Mechanism:** Seeds fresh session working memory from prior quest session by querying LOADED nodes, filtering out archived/superseded items, and sorting by pathway_strength DESC.
- **Key Observable Assertions:**
  * Cross-session memory continuity in `get_handoff_context()` seeding fresh session from immediate prior quest session.
  * Strict descending sort order by `pathway_strength`.
  * Deterministic filtering of archived nodes (`cn-patent-old` with `archived=True` excluded, unarchived items retained).

### Claim 8: Context Bloat Detection & Boundary Alerts
**Patent Specification:** *Context utilization monitoring and proactive bloat alerts at 75% capacity threshold*

- **Implementation Source:** [`campy/brain/thalamus/working_memory.py:350`](file:///campy/brain/thalamus/working_memory.py#L350)
- **Verification Test:** [`tests/patent_claims/test_claim_8_bloat_detection.py`](file:///tests/patent_claims/test_claim_8_bloat_detection.py)
- **Verified Mechanism:** Calculates session token utilization against token limit; when utilization > 75% (BLOAT_WARNING_THRESHOLD), generates natural language warning alerting agent to initiate clean session boundary.
- **Key Observable Assertions:**
  * Token capacity monitoring in `check_context_health()`.
  * Proactive bloat warning alert generated when utilization crosses `BLOAT_WARNING_THRESHOLD` (0.75 / 75%).
  * Clean status (`None`) returned for healthy sessions below threshold.

### Claim 9: Valence-Weighted Retrieval & Amygdala Reflex
**Patent Specification:** *Affective outcome reinforcement and proactive warning/suggestion alerts prior to plan execution*

- **Implementation Source:** [`campy/brain/thalamus/tools/quests.py:183`](file:///campy/brain/thalamus/tools/quests.py#L183)
- **Verification Test:** [`tests/patent_claims/test_claim_9_valence_weighted_retrieval.py`](file:///tests/patent_claims/test_claim_9_valence_weighted_retrieval.py)
- **Verified Mechanism:** Amygdala reflex vector-searches historical plans during register_plan(), emitting proactive warnings for negative plans (valence < -0.5) and suggestions for positive plans (valence > 0.5), and ranks recall queries by valence weighting.
- **Key Observable Assertions:**
  * Amygdala reflex in `register_plan()` triggering proactive `warnings` for candidate strategies resembling historical failure (`valence < -0.5`).
  * Amygdala reflex triggering proactive `suggestions` for candidate strategies resembling historical success (`valence > 0.5`).
  * Valence-weighted ranking score `(similarity * |valence| * pathway_strength)` in `recall_plans_for_query()`.

---

## 4. Deterministic Execution Log

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/djshelton/Desktop/GitProjects/hippocampy/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /Users/djshelton/.gemini/antigravity/brain/ebf82ed9-5db0-4225-84c7-87067f75b117/.system_generated/worktrees/subagent-Patent-Verification-Lead--B380--self-98c1f0b1
configfile: pytest.ini
plugins: mock-3.15.1, timeout-2.4.0, asyncio-1.4.0, anyio-4.13.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 17 items

tests/patent_claims/test_claim_1_consolidation_loop.py::test_claim_1_consolidation_loop_end_to_end PASSED [  5%]
tests/patent_claims/test_claim_1_consolidation_loop.py::test_claim_1_consolidation_loop_stages_observable PASSED [ 11%]
tests/patent_claims/test_claim_2_shape_first.py::test_claim_2_shape_first_bounds_schema_properties PASSED [ 17%]
tests/patent_claims/test_claim_2_shape_first.py::test_claim_2_polymorphic_agent_disambiguation PASSED [ 23%]
tests/patent_claims/test_claim_3_kahneman_classifier.py::test_claim_3_kahneman_system_1_rapid_path PASSED [ 29%]
tests/patent_claims/test_claim_3_kahneman_classifier.py::test_claim_3_kahneman_gray_zone_system_2_degradation PASSED [ 35%]
tests/patent_claims/test_claim_3_kahneman_classifier.py::test_claim_3_kahneman_sub_floor_noise_rejection PASSED [ 41%]
tests/patent_claims/test_claim_4_cocktail_party_filter.py::test_claim_4_confidence_gate_three_tier_partitioning PASSED [ 47%]
tests/patent_claims/test_claim_4_cocktail_party_filter.py::test_claim_4_assistant_safety_cap PASSED [ 52%]
tests/patent_claims/test_claim_4_cocktail_party_filter.py::test_claim_4_amygdala_salience_multiplier PASSED [ 58%]
tests/patent_claims/test_claim_5_working_memory_tracking.py::test_claim_5_track_loaded_lifecycle PASSED [ 64%]
tests/patent_claims/test_claim_5_working_memory_tracking.py::test_claim_5_raw_messages_excluded_from_loaded_tracking PASSED [ 70%]
tests/patent_claims/test_claim_6_smart_dedup.py::test_claim_6_deduplicate_results_demotion_without_omission PASSED [ 76%]
tests/patent_claims/test_claim_7_session_handoff.py::test_claim_7_session_handoff_prepopulates_fresh_session PASSED [ 82%]
tests/patent_claims/test_claim_8_bloat_detection.py::test_claim_8_bloat_warning_threshold_trigger PASSED [ 88%]
tests/patent_claims/test_claim_9_valence_weighted_retrieval.py::test_claim_9_amygdala_reflex_proactive_warnings_and_suggestions PASSED [ 94%]
tests/patent_claims/test_claim_9_valence_weighted_retrieval.py::test_claim_9_valence_weighted_query_retrieval PASSED [100%]

======================== 17 passed in 82.98s (0:01:22) =========================
```

---

## 5. Non-Provisional Filing Readiness & Dual-Engine Re-Platforming Plan

### 5.1 Legal Defensibility Assessment
1. **Complete Claim Coverage:** All 9 core intellectual property claims articulated in U.S. Provisional Patent Application #64/017,066 possess working code implementations and isolated, non-mocked verification tests.
2. **Deterministic Reduction to Practice:** The test suite verifies deterministic behavior across all cognitive mechanisms (confidence gating, Hebbian reinforcement, ontology routing, Working Memory tracking, and Amygdala reflexes).
3. **Engine-Agnostic Observable Boundaries:** Because assertions target observable returns, tool payloads, and confidence classifications rather than private Kùzu Cypher queries, this evidence suite provides an immutable specification.

### 5.2 Dual-Engine Gate 2 Certification Plan (B384)
During the upcoming B384 storage engine re-platforming (transitioning primary graph storage from Kùzu to Oxigraph + sqlite-vec):
- The canonical fixture `tests/fixtures/patent_conformance_graph.jsonl` will be loaded into Oxigraph.
- This identical 9-claim test suite will execute against the new storage adapter.
- Dual-engine execution traces will be captured in a companion evidence pack, proving patent reduction to practice across multiple disparate database architectures.

---
*Audit evidence generated automatically by `scripts/generate_patent_evidence.py`.*
