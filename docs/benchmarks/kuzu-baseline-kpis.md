# Canonical Kùzu Baseline KPI Report (Pre-Cutover)

**Recorded Date:** 2026-09-04 (Internal KPIs) / 2026-09-06 (Live External Harness)  
**Git Anchor:** `d35b28b` (Phase 1 completion — B374, B380, B381, B386 merged into `main`)  
**Storage Engine:** KùzuDB v0.11.3  
**Vector / Embeddings:** FastEmbed (`all-MiniLM-L6-v2`)  
**Primary Model Tested:** `llama3.1:8b` via Ollama  
**Source Datasets:** `baseline_snapshot.json`, `benchmarks/RESULTS.md`, `campy-benchmarks/baseline_kuzu_live.json`, `~/.campy/eval_results/ask-eval-20260802T140211Z.json`

---

## 1. Executive Summary & Purpose

This document provides a permanent, immutable record of HippoCampy's performance and resource metrics under the legacy Kùzu graph storage engine prior to the Phase 2 cutover to Oxigraph (RDF-star) + `sqlite-vec`.

These metrics establish the official "Before" baseline against which the lightweight engine refactors (B384, B387-B398) are measured.

---

## 2. 4-Tier Local KPI Matrix (Kùzu Baseline)

| Tier / Metric Category | Kùzu Canonical Baseline (`d35b28b`) | Target Post-Refactor | Architectural Owner |
|---|---|---|---|
| **Tier 1: Daemon Idle RSS** | **245.6 MB** bare; **~1.2 GB** live steady-state (`torch`, `spacy`, `kuzu`) | **<80 MB** physical footprint | B384 / B387 |
| **Tier 1: Write Burst Peak Spike** | **1.1 GB** peak spike during commit bursts | **Zero spikes** (<120 MB peak) | B384 / B311 |
| **Tier 1: Allocation Delta / 100 Turns** | **1.2 MB** / 100 turns | **<2.0 MB** / 100 turns | B384 |
| **Tier 2: Retrieval Latency** | **28.5 ms** (cold graph scan per query) | **<10.0 ms** | B375 |
| **Tier 2: LLM Generation Latency** | **1.54 s** (`llama3.1:8b`) | **<1.0 s** | B374 + B375 |
| **Tier 2: Compression Bypass (Sub-budget)**| **100.0%** (0 overhead on sub-budget queries) | **100.0%** | B374 |
| **Tier 2: Compression Ratio (Over-budget)**| **48.0%** bulk lane compression | **50%–70%** | B374 |
| **Tier 2: Graph 2-Hop Traversal Latency** | **2.53 ms** (isolated <= 2 hop traversal) | **<5.0 ms** | B375 / B386 |
| **Tier 2: Dense Supernode Degree Cap** | Degree <= 15 cap; top 5 incident edges if degree > 50 | Degree <= 15 cap | B375 / B283 |
| **Tier 3: Ask-Eval Overall Composite** | **0.69** | **>= 0.90** | B381 |
| **Tier 3: Identifier Accuracy** | **1.00** (100% exact identifier match) | **1.00** | B304 / B381 |
| **Tier 3: Paraphrase Accuracy** | **0.25** | **>= 0.80** | B381 |
| **Tier 3: Cross-Lane Retrieval Accuracy**| **0.50** | **>= 0.80** | B381 |
| **Tier 3: Continuation Accuracy** | **0.50** | **>= 0.80** | B381 |
| **Tier 3: Negative Control Compliance** | **1.00** (Zero hallucination on empty context) | **>= 0.95** | B305 / B381 |
| **Tier 4: Model Handoff Violations** | **0** (Hard constraints preserved) | **0** | B383 |
| **Tier 4: Model Handoff Latency** | **480 ms** | **<500 ms** | B383 |

---

## 3. Ask-Eval Multi-Model Accuracy Matrix (2026-08-02)

16 deterministic fixture questions across 5 question families evaluated on Kùzu:

| Model | Variant | Overall | Identifier | Paraphrase | Cross-Lane | Continuation | Neg-Control | Median Latency |
|---|---|---|---|---|---|---|---|---|
| `llama3.1:8b` | H0 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 1.54s |
| `llama3.1:8b` | H1 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 1.42s |
| `llama3.1:8b` | H1+H2 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 1.34s |
| `gemma4:e4b` | H0 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 4.49s |
| `gemma4:e2b` | H0 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 2.30s |
| `qwen3:8b` | H0 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 3.18s |

---

## 4. Live External Benchmark Run (`baseline_kuzu_live.json`)

On 2026-09-06, a live baseline snapshot was executed against an isolated Kùzu daemon instance running commit `d35b28b` over the real MCP transport (`campy.adapters.mcp_server`):

| Suite | Key Metric | Score / Rate | Average Latency |
|---|---|---|---|
| **ARC Bridge** | Rule Transfer Rate | **1.0 (100%)** | **31.69 ms** |
| **ARC Bridge** | Disappeared Entity Recall | **1.0 (100%)** | — |
| **LoCoMo** | Deprecation Accuracy | **0.40 (40%)** | **3876.76 ms** |
| **LoCoMo** | F1 Score / Exact Match | **0.0407 / 0.0** | — |
| **MemoryGym** | Episode Success Rate | **0.0%** | **374.01 ms** |
| **MemBench** | Persona Fact Precision | **0.0** | **2688.18 ms** |
| **MemBench** | Token Savings % | **0.0%** | — |

Snapshot raw JSON: `campy-benchmarks/baseline_kuzu_live.json`.

---

## 5. Architectural Findings, Harness Impedance & Validity Analysis

The live benchmark execution surfaced critical architectural interactions between the daemon consolidation pipeline, the bundle retrieval layer, and the external evaluation harness:

### 5.1 Validity Summary by Suite

| Category / Suite | Baseline Validity | Underlying Mechanism |
|---|---|---|
| **ARC Bridge Suite** | **100% Valid** | Direct graph writes, sweeps, and `current_truth` entity recall function as designed. Hot-path latency (31.69ms) is an accurate baseline. |
| **Latency Metrics** | **100% Valid** | Graph retrieval latency (31ms) and Ollama `llama3.1:8b` generation latency (2.6s–3.8s) accurately capture local hardware performance. |
| **Internal 4-Tier KPIs** | **100% Valid** | `baseline_snapshot.json` and the 17/17 zero-mock patent verification claim tests remain the authoritative pre-cutover benchmark. |
| **MemoryGym & MemBench** | **Invalid (Distorted)** | Scores were suppressed by an asynchronous ingestion race condition and harness schema mismatches, not underlying graph capacity. |

---

### 5.2 Technical Root Cause Breakdown

#### 1. The Asynchronous Ingestion Race Condition (The Primary Distortion)
- **Mechanism:** In HippoCampy, `notify_turn` is designed to be non-blocking for real-time agent responsiveness. It pushes messages to an in-memory `asyncio.Queue` and returns immediately (`{"status": "ingested"}` in <2ms).
- **Consolidation Latency:** The Gated Consolidation Loop (GCL) worker pulls from that queue in the background. Processing each turn through spaCy NER, schema classification, and LLM entity extraction requires **~1.0 to 1.5 seconds per turn**.
- **Harness Flaw:** The `campy-benchmarks` runner was originally tested only in mock mode (which updates in-memory dicts synchronously in 0ms). When executed against the live daemon, the harness called `notify_turn()` and immediately executed probe questions on the very next millisecond.
- **Result:** Probe queries executed against an empty or partially populated database while turns were still queued in background workers. Manual post-run queries with `current_truth("PostgreSQL")` confirmed the concepts (`PostgreSQL 16`, `UUID primary keys`, migration statements) had indeed been written to Kùzu once the queue drained.

#### 2. The GCL Loop Worker Unpack Bug in `d35b28b`
- At commit `d35b28b`, `capture.py` was enqueuing a 5-element tuple `(message_id, content, role, session_id, precomputed)` to `_loop_queue`.
- However, `_loop_worker` in `brain_daemon.py` attempted to unpack only 4 elements:
  ```python
  message_id, text, role, session_id = await self._loop_queue.get()  # ValueError: too many values to unpack (expected 4)
  ```
- This caused the background consolidation worker to crash and restart repeatedly on every turn, silently dropping all consolidation in unpatched runs. This had to be patched in the isolated worktree before background ingestion could function.

#### 3. Semantic Relevance Floor in `bundle_compiler` vs. `current_truth`
- Direct lookup via `current_truth` successfully finds facts using Reciprocal Rank Fusion (RRF) across semantic and lexical indices.
- However, `ask()` and `compile_context()` route through `bundle_compiler.py`, which executes a Cypher semantic search with a hardcoded distance threshold:
  ```cypher
  WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30
  ```
- Natural language probe questions (e.g., *"What is Alex's current diet? Are they vegan or pescatarian?"*) evaluated against short concept nodes have an embedding distance of `~0.50` (> `0.30`).
- Without a general lexical fallback (the existing bypass was restricted to `\bB\d+\b` backlog card identifiers), `bundle_compiler` discarded these nodes as below the relevance floor, emitting an empty context bundle (`sections: []`).

#### 4. Harness Token Calculation Key Mismatch
- `membench/runner.py` attempted to read `ctx_res.get("token_count", 380)` to measure bundle token reduction.
- The actual MCP response structure nests the metric under `ctx_res["bundle"]["total_token_estimate"]`.
- Consequently, `membench` defaulted to 380 tokens for every bundle, distorting the `token_savings_pct` calculation to 0.0%.

---

## 6. Sibling Harness Integration (`campy-benchmarks`)

External evaluation suites reside in the sibling repository `/Users/djshelton/Desktop/GitProjects/campy-benchmarks`:
- **LoCoMo (`locomo/`):** Multi-session conversational recall and dynamic constraint updates (`[DEPRECATED_BY]`).
- **MemoryGym (`memory_gym/`):** 2D Grid RL/spatial persistence over 500 steps (`MysteryPath-v0`).
- **MemBench (`membench/`):** Multi-Session Chat (MSC) persona retention and contradictory belief arbitration.
- **ARC Bridge (`arc_bridge/`):** World-model diagnostic integration with `ARC_AGI`. Tool latency <32ms, rule transfer rate 100%.

---

## 7. Reproduction Instructions

### Internal KPI Snapshot:
```bash
python benchmarks/kpi_monitor.py --out baseline_snapshot.json
```

### External Harness Snapshot (Requires Isolated Daemon):
```bash
cd /Users/djshelton/Desktop/GitProjects/campy-benchmarks
CAMPY_SOCKET_PATH=<path_to_socket> CAMPY_MCP_CMD="<python_exec> -m campy.adapters.mcp_server" python run_all.py --smoke --baseline --out baseline_kuzu_live.json
```
