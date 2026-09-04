# B-380-patent-evidence-pack — Non-Provisional Patent Claim Verification & Audit Evidence Pack

**Card:** B380 | **Priority:** P0 | **Depends on:** B233, B279, B304, B312  
**Branch:** `feat/b380-patent-claim-verification` | **PR Target:** `main`

---

## 1. Summary

Build a dedicated, deterministic patent claim verification suite covering all 9 core intellectual property claims from U.S. Provisional Patent Application #64/017,066. This suite runs against the current working codebase *before* major storage re-platforming (B384), freezing defensible reduction-to-practice evidence for patent counsel.

To ensure evidence remains valid and fully decoupled from internal query syntax after B384 replaces Kùzu with Oxigraph, all test assertions target **observable mechanism outputs** (returned context bundles, MCP tool responses, loop-step return values, token estimates, and confidence gate outcomes) across an engine-agnostic canonical fixture: `tests/fixtures/patent_conformance_graph.jsonl`.

---

## 2. The 9 Claim Tests

1. **Claim 1: Gated Consolidation Loop** (`tests/patent_claims/test_claim_1_consolidation_loop.py`):
   - Proves the 9-step biomimetic pipeline (Steps 1–7 + 1b, 3b, 4b) processes incoming turns deterministically.
2. **Claim 2: Shape-First Principle** (`tests/patent_claims/test_claim_2_shape_first.py`):
   - Proves ontological grounding (`gist` / `schema.org`) executes prior to semantic vector indexing.
3. **Claim 3: Kahneman System 1/2 Dual-Process Classifier** (`tests/patent_claims/test_claim_3_kahneman_classifier.py`):
   - Proves fast centroid similarity (>0.85) resolves reflexively while intermediate confidence (0.60–0.85) escalates to deliberate LLM analysis.
4. **Claim 4: Cocktail Party Selective Attention Gate** (`tests/patent_claims/test_claim_4_cocktail_party_filter.py`):
   - Proves confidence thresholding discards conversational noise (<0.60) while retaining salient signals (>0.90).
5. **Claim 5: Context Window as Working Memory Model** (`tests/patent_claims/test_claim_5_working_memory_tracking.py`):
   - Proves active session tracking of `[LOADED]` graph nodes and token budget estimation.
6. **Claim 6: Smart Deduplication via Load Tracking** (`tests/patent_claims/test_claim_6_smart_dedup.py`):
   - Proves that recently loaded nodes are demoted in rank rather than omitted, preserving contextual awareness without duplicate prompt bloat.
7. **Claim 7: Session Handoff Intelligence** (`tests/patent_claims/test_claim_7_session_handoff.py`):
   - Proves cross-session continuity transfer of decisions, active constraints, and negative controls.
8. **Claim 8: Bloat Detection via Token Estimation** (`tests/patent_claims/test_claim_8_bloat_detection.py`):
   - Proves proactive bloat warnings and token utilization metrics during retrieval assembly.
9. **Claim 9: Valence-Weighted Graph Retrieval & Amygdala Reflex** (`tests/patent_claims/test_claim_9_valence_weighted_retrieval.py`):
   - Proves outcome valence propagation from Plan nodes through graph edges to deter repeating failed strategies.

---

## 3. Implementation Steps

1. **Canonical Conformance Fixture:**
   - Create `tests/fixtures/patent_conformance_graph.jsonl` containing nodes and relationships modeling all 9 scenarios.
2. **Claim Suite Implementation:**
   - Author isolated pytest files in `tests/patent_claims/`.
   - Assert on observable public mechanism outputs (returned bundles, step return objects, tool responses) rather than inspecting private Cypher queries or database tables.
3. **Automated Evidence Generator:**
   - Create `scripts/generate_patent_evidence.py` to execute the suite, capture stdout/stderr traces, record git commit hash and timestamp, and generate `docs/patent-evidence-pack.md`.
4. **Gate 2 Post-B384 Re-Certification:**
   - Run the exact same observable mechanism suite against Oxigraph + sqlite-vec to provide dual-engine legal proof.

---

## 4. Acceptance Criteria

- [ ] `tests/fixtures/patent_conformance_graph.jsonl` created.
- [ ] All 9 claim verification tests pass with 0 failures and zero mocks.
- [ ] `scripts/generate_patent_evidence.py` executes cleanly and outputs `docs/patent-evidence-pack.md`.
- [ ] Work committed to `feat/b380-patent-claim-verification` targeting `main`.
