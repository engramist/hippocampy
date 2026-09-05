# Subagent Fan-Out Execution Plan: Strategic Roadmap (B374 – B386)
*Incorporating Ground-Truth Codebase Audits & Claude Opus 5 Architectural Reviews*

## 1. Executive Summary & Economics

This document formalizes the execution plan for implementing HippoCampy's strategic backlog cards (**B380, B374, B381, B386, B384, B375, B382, B383, B385**) via **subagent fan-out**.

### Why Fan Out With Subagents?

1. **Context Window Isolation (Cost & Accuracy):**
   - Sequential execution across complex cards in a single continuous conversation would balloon context to 100k–150k+ tokens. Every subsequent reasoning step and tool call bills for that entire history.
   - Isolated subagents operate in clean 20k–50k token contexts per card, reducing total token expenditure by ~60%–75% while preventing context rot and attention dilution.
2. **True Git-Worktree Isolation (Time):**
   - Using dedicated worktree branches isolates each subagent in its own directory on a dedicated branch. Subagents write code, run pytest suites, and commit simultaneously without lock contention, test pollution, or merge conflicts.
3. **Decoupled Risk & Failure Domains (Robustness):**
   - Subagents can fail, iterate, or be killed independently without corrupting the working tree or other active tasks.

---

## 2. Architecture & Orchestration Flow

```
                                  [ Current Working Base ]
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
             [ Subagent 1 ]            [ Subagent 3 ]            [ Workstream B386 ]
                  B380                      B381                   (Gateway Chokepoint)
           (Patent Evidence)         (Benchmark Harness)          Groups A-E Sub-Batches
         Observable Assertions       Sibling Repo Wiring          592 Cypher Lines -> 0
                    │                         │                         │
                    ▼                         │                         │
             [ Subagent 2 ]                   │                         │
                  B374                        │                         │
         (Two-Lane Compression)               │                         │
        Delta on Shipped ask.py               │                         │
                    │                         │                         │
                    └─────────────────────────┼─────────────────────────┘
                                              ▼
                                   [ Integration Gate 1 ]
                      - Freeze Patent Baseline (Observable Outputs)
                      - Sibling Benchmarks Wired
                      - Two-Lane Compression Verified
                      - Ratchet at 0 (All Queries in graph/queries/)
                                              │
                                              ▼
                                  Phase 2: Featherweight Engine
                                              │
                                              ▼
                                       [ Subagent 4A ]
                                   Phase 2A: Ingestion
                                (ONNX NER, Drop PyTorch/spaCy)
                                  (RSS: ~1.2 GB -> ~245 MB)
                                              │
                                              ▼
                                       [ Subagent 4B ]
                                 Phase 2B: Storage Re-Platform
                              - Translate graph/queries/ to SPARQL
                              - Handlers for Vector ANN & RDF-star
                              - Oxigraph + sqlite-vec (<80 MB RAM)
                              - Update check_cypher_ratchet allowlist
                                              │
                                              ▼
                                   [ Integration Gate 2 ]
                               (Dual-Engine Patent Re-Certify)
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
            [ Subagent 5 ]             [ Subagent 6 ]             [ Subagent 7 ]
                 B375                       B382                       B383
            (Warm Frontier)             (Model Router)            (Auto Handoff)
                    │                         │                         │
                    └─────────────────────────┼─────────────────────────┘
                                              ▼
                                   [ Integration Gate 3 ]
                            (Run Sibling Benchmark Scorecard)
```

---

## 3. Detailed Workstream Breakdown

### Phase 1: Concurrent Baseline, Patent Freeze, Two-Lane Delta & Gateway Chokepoint

*Because B386 has zero file collisions with B380, B381, and B374, it runs concurrently in Phase 1 across 5 disjoint sub-batches. This eliminates B386 from the critical path and leaves Phase 2 strictly focused on ONNX ingestion and Oxigraph storage cutover.*

#### Subagent 1: B380 – Non-Provisional Patent Claim Verification & Evidence Pack
- **Branch:** `feat/b380-patent-claim-verification`
- **Plan File:** `backlog/plans/B-380-patent-evidence-pack.md`
- **Model:** `inherit`
- **Mandate:** Freeze deterministic legal evidence of reduction to practice on the current, working codebase (Kùzu + FastEmbed) **before** storage engine refactoring.
- **Key Deliverables:**
  - `tests/fixtures/patent_conformance_graph.jsonl`: Canonical, engine-agnostic graph fixture modeling multi-hop topologies, cyclic references, valence-weighted outcomes, and contradictory constraints (`migration-security-testing.md`).
  - 9 isolated verification tests under `tests/patent_claims/` (Claim 1 through Claim 9).
  - **Observable Mechanism Assertions:** Tests assert strictly against observable mechanism outputs (returned context bundles, MCP tool responses, loop-step return values, token estimates, confidence gate classifications) rather than inspecting private Cypher queries or database tables. This makes the suite fully engine-agnostic and guarantees seamless Gate 2 re-certification.
  - `scripts/generate_patent_evidence.py`: Automated report generator producing `docs/patent-evidence-pack.md` with timestamped execution traces and exact line citations.
- **Verification:** All 9 claim tests pass deterministically against the fixture with zero mocks.

#### Subagent 3: B381 – Benchmark Harness Adapter Wiring & KPI Monitor
- **Branch:** `feat/b381-decision-grade-ask-eval`
- **Plan File:** `backlog/plans/B-381-decision-grade-ask-eval.md`
- **Model:** `inherit` (ensures accurate characterization of live codebase)
- **Mandate:** Wire external benchmark adapters in sibling repo `campy-benchmarks` and build core daemon KPI monitoring.
- **Key Deliverables:**
  - Sibling repo `/Users/djshelton/Desktop/GitProjects/campy-benchmarks`:
    - `locomo/`: Multi-session factual recall and dynamic constraint updates.
    - `memory_gym/`: 2D RL/spatial persistence over 500 steps.
    - `membench/`: Persona fact retention and contradiction arbitration.
    - `run_all.py`: Unified harness with `--baseline` and `--compare` flags.
  - Core repo `hippocampy`:
    - `benchmarks/kpi_monitor.py`: 4-tier local KPI tracking.
    - **Accurate Baseline Table:** Reflects that B289 compression is active in `ask.py`; sets retrieval compilation latency target to `<10ms` (via B375) and LLM generation latency target to `<1.0s` (via B374).
    - **Graph Traversal KPIs (`performance-and-debugging.md`):** Isolated $\le 2$ hop latency (<5ms), edge scan counts, query plan boundedness checks.
- **Verification:** `python run_all.py --smoke` executes across all suites; `kpi_monitor.py` exports baseline JSON.

#### Subagent 2: B374 – Two-Lane Thalamic Routing & Budget-Gated Pressure Relief Valve
- **Branch:** `feat/b374-two-lane-thalamic-compressor`
- **Plan File:** `backlog/plans/B-374-two-lane-thalamic-compressor.md`
- **Model:** `inherit`
- **Mandate:** Surgical delta on top of shipped B289 foundation (`campy/brain/thalamus/compression/` and `ask.py`).
- **Key Deliverables:**
  - Two-Lane Content Routing in `ContentRouter` (`compression/__init__.py`):
    - **Protected Lane (Zero Loss):** Decisions, active Constraints, Negative Controls, and exact facts bypass compression entirely.
    - **Bulk Lane (Lossy-Tolerant Compression):** Summaries, concepts, code extracts compressed only when exceeding budget.
  - Budget-Gated Pressure-Relief Valve in `ask.py`: When bundle estimated tokens $\le$ `budget_tokens`, bypass compression completely (eliminating 1-2s LLM latency). When over budget, compress Bulk Lane to fit.
  - Prompt Tuning in `llm_prose.py`: Hardened constraints enforcing verbatim retention of entity names, decisions, numbers, and negative assertions.
  - Respect Standing Guardrail: Do NOT replace `GraphBundleCompressor` with generic JSON crushers.
- **Verification:** Unit tests in `tests/test_thalamic_compression.py` and integration tests in `tests/test_ask_pipeline.py`.

#### Workstream B386: GraphGateway Chokepoint Completion (Drive Cypher Ratchet to Zero)
- **Branch:** `feat/b386-gateway-chokepoint-completion`
- **Plan File:** `backlog/plans/B-386-gateway-chokepoint-completion.md`
- **Model:** `inherit`
- **Mandate:** Migrate all 592 lines of inline Cypher scattered across 48 application files into `campy/brain/hippocampus/graph/queries/`.
- **Sub-Batch Decomposition (Disjoint Files):**
  - **Group A (ARC):** `arc_queries.py` (46), `arc_artifacts.py` (27), `arc_mechanics.py` (27) = 100 lines -> Modify existing `queries/arc.py` (134 lines, established `arc.<verb>_<subject>` naming).
  - **Group B (Brainstem + Core):** `sweep.py` (68), `quest.py` (27), `hippocampus.py` (19), `export.py` (13) = 127 lines -> Create `queries/sweep.py`, create `queries/quests.py`.
  - **Group C (Loop + Retrieval):** `step7_pathway.py` (27), `orchestrator.py` (24), `retrieval.py` (16), `working_memory.py` (14), `capture.py` (14), `ingest.py` (11) = 106 lines -> Create `queries/pathways.py`, `queries/orchestrator.py`, `queries/retrieval.py`.
  - **Group D (Tools + Web):** `quests.py` (42), `task_graph.py` (27), `web/server.py` (31), `procedure_synthesis.py` (11), `wiki_projection.py` (10) = 121 lines -> Create `queries/task_graph.py`, create `queries/web.py`.
  - **Group E (Tail):** ~30 remaining files = ~138 lines.
- **Key Deliverables:**
  - Follow conventions of existing migrated modules (`arc.py`, `lessons.py`, `capability.py`, `continuity.py`, `backup.py`).
  - Refactor all 48 offending files to call `await gateway.run(...)`.
  - Eliminate direct application imports of `KuzuClient`.
  - Semantic `NamedQuery` contract with provisional `sparql` string and clear handler dispatch boundaries for vector ANN and RDF-star edge reification.
  - Drive `scripts/check_cypher_ratchet.py` count from **592 down to 0**.
- **Verification:** `scripts/check_cypher_ratchet.py` reports 0 inline Cypher outside allowed DDL; all existing tests pass.

#### Integration Gate 1:
1. Re-run B380 patent claim suite to verify zero regression from B374 and B386.
2. Verify `scripts/check_cypher_ratchet.py` passes with **count = 0**.
3. Capture canonical baseline snapshot: `python benchmarks/kpi_monitor.py --out baseline_snapshot.json`.
4. Merge B380, B381, B374, and B386 branches to `main`.

---

### Phase 2: Featherweight Engine Re-Platforming (Sequential B384)

*With all 592 lines of Cypher centralized and zero application files importing KuzuClient, Phase 2 is lean and strictly focused on engine replacement:*

#### Subagent 4A: B384 Phase 2A – Ingestion Plane (Pure ONNX + Rule Parser, Drop PyTorch)
- **Branch:** `feat/b384-ingestion-torch-free`
- **Model:** `inherit`
- **Key Deliverables:**
  - `campy/brain/temporal_lobe/loop/step1_zoning.py`: Replace `spacy`/`thinc` NER with ONNX token classification via `fastembed`'s existing ONNX Runtime provider.
  - `campy/brain/temporal_lobe/loop/step1b_fast_relations.py`: Lightweight dependency/verb parser extracting universal lemmas (*require, enable, replace, contradict, part_of*).
  - Purge `torch`, `torchvision`, `thinc`, and `spacy` from `pyproject.toml` and `requirements.txt`.
- **Milestone 1 Verification:** `tests/test_torch_free_import.py` proves zero instances of `torch` or `thinc` in `sys.modules`. Process RSS drops from **~1.2 GB down to ~245 MB**.

#### Subagent 4B: B384 Phase 2B/2C – Storage Re-Platforming (`pyoxigraph` + `sqlite-vec`)
- **Branch:** `feat/b384-storage-oxigraph`
- **Model:** `inherit`
- **Mandate:** Cut over storage to Oxigraph and sqlite-vec using the centralized queries in `graph/queries/`.
- **Key Deliverables:**
  - Add SPARQL definitions to all pure-graph queries in `graph/queries/`.
  - Dispatch Vector ANN search via `sqlite-vec` + hydration in Python.
  - Dispatch RDF-star edge property updates with `:event_id` discriminators via Python handlers.
  - Build `campy/brain/hippocampus/graph/oxigraph_client.py`: In-process RocksDB RDF-star store.
  - Build `campy/brain/hippocampus/graph/vector_store.py`: `sqlite-vec` index over `FLOAT[384]` FastEmbed embeddings.
  - Update `gateway.py` to route through `oxigraph_client.py` and `vector_store.py`.
  - Update `scripts/check_cypher_ratchet.py`: Replace `kuzu_client.py` with `oxigraph_client.py` in `ALLOWLIST_FILES` and adjust scanning regex to avoid false positives on SPARQL `CREATE GRAPH`.
  - Remove `kuzu` from `pyproject.toml` and `requirements.txt`.
- **Milestone 2 Verification:** Process RSS drops from **~245 MB down to <80 MB RAM**.

#### Integration Gate 2:
1. Re-run full Gated Consolidation Loop test suite (`tests/test_loop.py`, `tests/test_retrieval.py`).
2. **Dual-Engine Patent Re-Certification:** Re-run all 9 B380 patent claim verification tests against observable mechanism outputs, confirming 100% claim conformance on Oxigraph.
3. Verify `scripts/check_cypher_ratchet.py` passes under new Oxigraph allowlist.
4. Certify <80 MB physical footprint on macOS (`vmmap -summary`) and Linux (`/proc/[pid]/status`).
5. Merge to `main`.

---

### Phase 3: Cognitive Intelligence & Routing Fan-Out (Parallel)

*Operating on top of the featherweight engine, these three thalamic features interact via `gateway.py` across completely independent modules and run concurrently:*

#### Subagent 5: B375 – Pre-Warmed Selective Activation (Warm Frontier)
- **Branch:** `feat/b375-prewarmed-selective-activation`
- **Plan File:** `backlog/plans/B-375-prewarmed-selective-activation.md`
- **Model:** `inherit`
- **Key Deliverables:**
  - `campy/brain/temporal_lobe/warm_frontier.py`: Bounded in-memory active node set (`max_warm_nodes = 50`) with temporal decay.
  - Passive activation on `notify_turn` for recognized tokens, branch context, and modified paths (<5ms).
  - **Dense Supernode Safeguard (`performance-and-debugging.md`):** If `degree(node) > 50`, bypass open expansion; selectively expand strictly the top 5 incident edges by `pathway_strength DESC`.
  - Retrieval boost multiplier in `bundle_compiler.py` for warm nodes, driving retrieval compilation latency to `<10ms`.
- **Verification:** `tests/test_warm_frontier.py` passing against `gateway.py`.

#### Subagent 6: B382 – Dynamic Phase-Aware Model Router ("The Missing Middle")
- **Branch:** `feat/b382-phase-aware-model-router`
- **Plan File:** `backlog/plans/B-382-phase-aware-model-router.md`
- **Model:** `inherit`
- **Key Deliverables:**
  - `campy/brain/thalamus/model_router.py`: Classifies tasks into `gist:Planning` (routes to Claude Opus 5 / Sonnet 5) vs `gist:Implementation` (routes to local Ollama / GLM 5.3) vs `gist:Reflex` (local syntax/formatting).
  - **Graph Guardrail (`query-patterns-and-translation.md`):** Bounded ontological pattern matching. Anchor on active `Quest`, inspect strictly 1-hop incident neighbors (unfinalized `Decision` nodes vs finalized `ActionItem` DAGs) with execution latency bounded to <5ms.
  - Temporary Context Bundle: Dispatches minimal necessary constraints to cloud, captures response, memory stays local.
  - MCP tool `route_task` and CLI command `campy dispatch`.
- **Verification:** 20 canonical task scenarios in `tests/test_model_router.py`.

#### Subagent 7: B383 – Automated Model Handoff Generator (Zero-Amnesia Swapping)
- **Branch:** `feat/b383-automated-model-handoff`
- **Plan File:** `backlog/plans/B-383-automated-model-handoff.md`
- **Model:** `inherit`
- **Key Deliverables:**
  - `campy/brain/thalamus/handoff.py`: Standardized handoff generation directly from graph state.
  - Realizes Patent Claim #7 (Session Handoff Intelligence).
  - **Boundary Subgraph Extraction (`query-patterns-and-translation.md`, `anti-patterns.md`):** Root anchor at `Quest` and `[LOADED]` nodes, root-level filtering of deprecated/archived nodes, bounded $\le 2$ hops along `:ENABLES`/`:CONSTRAINS`/`:REQUIRES`, topologically sorted `ActionItem` DAGs, and total entity cap $\le 40$ nodes (<500 tokens).
  - CLI `campy handoff --copy` and MCP tool `generate_handoff`.
- **Verification:** `tests/test_automated_handoff.py` verifies zero constraint violations when an incoming model is seeded solely with the handoff artifact.

#### Integration Gate 3:
1. Merge Subagents 5, 6, and 7 to `main`.
2. Run `campy-benchmarks` with `python run_all.py --compare baseline_snapshot.json`.
3. **Scorecard Verification:**
   - Ask-Eval overall score reaches $\ge 0.90$.
   - Token compression on **over-budget bundles** achieves 50%–70% reduction.
   - Sub-budget bundles achieve 100% bypass rate with 0s LLM compression latency overhead.
   - Retrieval compilation latency drops to `<10ms`.

---

### Phase 4: Production Deployment & Cloud Delivery (B385)

*B385 cloud foundation is verified on `feat/b385-cloud-vibeguide-service` (116 passing tests).*

- Delivers AWS ECS/Fargate containerization, Amazon EFS volume mounting, multi-tenant workspace isolation, and VibeGuide integration contracts.
- **Resource Footprint Milestones:**
  - Initial Cloud Baseline: Runs stably under Kùzu at ~245 MB RSS (well within 512 MB Fargate allocation).
  - Final Featherweight Cutover: Automatically drops to <80 MB RAM once Phase 2C merges.
- PR ready for `main`.

---

## 4. Subagent Allocation & Resource Matrix

| Phase | Subagent | Role / Focus | Branch | Target Context Size |
|---|---|---|---|---|
| **Phase 1** | Subagent 1 | Patent Verification (B380) | `feat/b380-patent-claim-verification` | ~25k tokens |
| **Phase 1** | Subagent 3 | Benchmark Wiring (B381) | `feat/b381-decision-grade-ask-eval` | ~30k tokens |
| **Phase 1** | Subagent 2 | Two-Lane Routing Delta (B374) | `feat/b374-two-lane-thalamic-compressor` | ~25k tokens |
| **Phase 1** | Subagent 4 (A–E) | GraphGateway Chokepoint Completion (B386) | `feat/b386-gateway-chokepoint-completion` | ~25k tokens per group |
| **Phase 2** | Subagent 5A | ONNX NER & Torch Removal (B384 Phase 2A) | `feat/b384-ingestion-torch-free` | ~35k tokens |
| **Phase 2** | Subagent 5B | Oxigraph Storage Cutover (B384 Phase 2B/2C) | `feat/b384-storage-oxigraph` | ~45k tokens |
| **Phase 3** | Subagent 6 | Warm Frontier (B375) | `feat/b375-prewarmed-selective-activation` | ~25k tokens |
| **Phase 3** | Subagent 7 | Model Router (B382) | `feat/b382-phase-aware-model-router` | ~25k tokens |
| **Phase 3** | Subagent 8 | Automated Handoff (B383) | `feat/b383-automated-model-handoff` | ~25k tokens |

---

## 5. Rules of Engagement & Guardrails

1. **Branch Hygiene:** Every subagent operates strictly on its assigned feature branch; no direct commits to `main`.
2. **Ecosystem Boundaries (`docs/ecosystem-rules.md`):** Zero consumer dependencies in `campy/`. External test frameworks reside exclusively in sibling repositories.
3. **Graph-Solutions Strictness:**
   - Index entry points, never traversals.
   - Bound all variable-length traversals ($\le 2$ hops).
   - Filter early at root before expanding neighborhoods.
   - Degree cap on supernodes (>50 degree $\to$ top 5 by pathway strength).
   - Event occurrence discriminators for repeated interactions in RDF-star.
   - Single-writer POSIX directory sharding per workspace on cloud storage.
4. **Integration Gate Sign-off:** Each phase ends at a formal integration gate where tests are verified, memory footprints are certified, and PRs are merged by the main orchestrating agent.
