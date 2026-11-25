# Paper 2 Draft: Architectural Drift in Autonomous Coding Agents

**Working Title:** *Architectural Drift in Autonomous Coding Agents: Measuring Local Greedy Optimization Away from Declarative Graph Systems*  
**Status:** Living draft (started 2026-11-24; case-study evidence logged, multi-model controlled benchmark protocol to be executed)  
**Target Venues:** ICSE / FSE (Software Engineering in Practice / Research), MSR, or NeurIPS Workshop on Foundation Model Agents

---

## Abstract (Draft)

Autonomous coding agents are increasingly trusted to evolve complex software systems over weeks or months. While agents excel at local, single-PR optimizations, we document a recurring failure mode we term **architectural drift**: when working on a declarative knowledge-graph system (RDF-star / Oxigraph / SPARQL), an agent repeatedly drifts away from graph-native computation and ontology modeling toward imperative Python loops, regex heuristics, vector rerankers, and model swaps — even when bound by explicit repository principles (`PRINCIPLES.md`), domain skills (`SKILL.md`), and CI drift checks.

We present (1) a longitudinal empirical case study from the HippoCampy repository showing how per-PR metric gating interacts with pretraining priors to create a self-reinforcing loop away from graph architecture, and (2) a controlled, reproducible multi-model benchmark protocol (`GraphDriftBench`) to measure declarative-vs-imperative drift across frontier coding models (Claude, Gemini, GPT) under identical schemas, prompts, and explicit architectural rules.

---

## 1. Motivation & Problem Statement

- Software architecture often encodes long-term bets (e.g., single source of truth in a graph store, declarative SPARQL queries, ontology-driven inference) that pay off only after multiple coordinated stages (capture → schema → taxonomy → query) are in place.
- Coding agents, however, operate turn-by-turn and PR-by-PR. When a benchmark score is enforced per PR, any lever with immediate local payoff (reranking text chunks, tweaking prompts, escalating to a larger LLM) dominates multi-step structural fixes — causing the codebase to silently converge toward a flat vector-RAG / Python-script architecture despite explicit user instructions to build a Knowledge Graph.

---

## 2. Longitudinal Case Study: HippoCampy (Oct–Nov 2026)

### 2.1 Documented Instances of Graph-to-Python / Graph-to-RAG Drift
1. **Imperative counting over flat rows (`B505`):** Answering *"How many pets will Andrew have?"* by regex-parsing `"pets"`, fetching every `INSTANCE_OF pet` row, and running `len(items)` in Python with no subject anchor — counting every pet in the conversation (11). Triggered the creation of `PRINCIPLES.md` (P2, P8) and `skills/campy-graph/SKILL.md`.
2. **Python transitive loops over graph edges (`gateway.py:_successor_statements`):** Pulling `REPLACES` edges into a Python `dict` and running a hand-written loop + text span matching instead of a single SPARQL `REPLACES*` + `MENTIONS` query.
3. **Regex/capitalization heuristics replacing closed-set Concept lookup (`memory_decision.py:_is_multi_entity`):** Counting capitalized words to detect multi-entity queries when the graph already holds the closed Concept set.
4. **The "Fixed Broken Capture" Local Optimum (Nov 10–22):** After 8B capture rebuild (`B542`) failed and a 26B capture probe hit a memory guard at 78s, the agent treated the 35–53%-wrong, 6%-typed graph as fixed and spent 18 consecutive experiments (`ND-1` through `ND-18b`) optimizing cross-encoder reranking, prompt markup, hedge rules, and 2B/26B answer escalation. Every shipped gain was text/model-side, while multi-hop stayed flat at 29.4%.
5. **Breaking the drift (Nov 22–24):** Direct Oxigraph triple inspection + `num_ctx: 4096` KV-cache fix + context-aware 26B entity-resolved capture raised typed `HAS_OBJECT` from ~6% to **76.3%** and pure-SPARQL `query_hits` from **13.7% to 34.0%** in 48 hours.

### 2.2 Effectiveness of Governance Mechanisms
- What worked: `PRINCIPLES.md`, `skills/campy-graph/SKILL.md`, `pr-score-effect` CI checks, pre-registered pass/kill lines, and `scripts/drift_report.py` successfully prevented *unmeasured* claims and shadow stores.
- What was *not* enough: per-PR score gating alone **incentivized** local text/model levers over multi-step graph capture fixes.

---

## 3. Controlled Multi-Model Benchmark Protocol (`GraphDriftBench`) — *[To Be Executed]*

To test objectively whether architectural drift away from graph technology differs across frontier models (or is universal across LLMs due to training-data distribution and greedy planning), we propose a clean, reproducible evaluation harness:

### 3.1 Task Suite (12–16 Standardized Tasks over a Real Oxigraph Store Copy)
Each task gives the model an isolated, read-only copy of an Oxigraph `brain.db` + the schema (`campy:` predicates) + a real engineering prompt across 4 categories:
1. **Aggregation & Counting:** e.g., *"Implement a function returning how many distinct pets a given person owns, with provenance turns."* (Graph-native: subject-anchored `COUNT(DISTINCT ?obj)` SPARQL; Drift: Python `len()` / regex over text.)
2. **Transitive / Taxonomy Inference:** e.g., *"Find all turns where a person mentions any musical instrument or hobby."* (Graph-native: `INSTANCE_OF/BROADER*` property path; Drift: hardcoded Python keyword list or vector similarity.)
3. **Temporal / Supersession Chains:** e.g., *"Return the current (non-deprecated) occupation of a person."* (Graph-native: `FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?newer }` + `ORDER BY DESC(?at) LIMIT 1`; Drift: pulling all rows and sorting/filtering in Python.)
4. **Capture-Gap Diagnosis (The P8 Test):** Give a store where the needed edge is *missing* (e.g., `HAS_OBJECT` is null on 90% of facts) and ask the agent to improve accuracy on multi-hop/count questions. (Graph-native: diagnose missing edge and propose a capture fix; Drift: add a Python fallback, regex, or reranker.)

### 3.2 Experimental Conditions (2 × N Matrix)
- **Models:** Claude (Opus/Sonnet), Gemini (Pro/Flash), GPT (frontier), open-weights coding models.
- **Prompting conditions:**
  - `C0 (Unconstrained)`: Standard repo context, no explicit graph rule.
  - `C1 (Rule-Constrained)`: With `PRINCIPLES.md` + `skills/campy-graph/SKILL.md` loaded.
- **Automated Metrics (Zero Subjective Grading):**
  - **Graph-Native Compliance Rate:** % of solutions using a parameterized SPARQL query (no Python counting/joining/looping over raw rows, no hardcoded domain keywords).
  - **SPARQL Validity & Correctness:** % passing execution on Oxigraph and matching exact ground-truth answers (including proper abstention on empty results).
  - **Capture-First Rate (Category 4):** % of runs that identify the missing graph edge rather than approximating it in Python/RAG.
  - **Drift Persistence:** Across a 3-turn follow-up where the initial graph query scores lower than a quick Python hack, how often does the model abandon the graph?

---

## 4. Expected Contributions & Next Steps
1. Finalize the HippoCampy longitudinal data table once `task-322` (809 gate) and the evergreen SKOS taxonomy pass complete.
2. Build and run `GraphDriftBench` (`benchmarks/graph_drift/`) on 3+ model families under `C0` and `C1`.
3. Release the anonymized store snapshots, SPARQL test suite, and scoring harness as a reproducible artifact.
