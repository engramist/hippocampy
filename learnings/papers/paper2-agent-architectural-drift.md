# Paper 2 Draft: Architectural Drift in Autonomous Coding Agents

**Working Title:** *Architectural Drift in Autonomous Coding Agents: Measuring Local Greedy Optimization Away from Declarative Graph Systems*  
**Status:** Living draft (started 2026-11-24; case-study evidence logged, multi-model controlled benchmark protocol to be executed)  
**Target Venues:** ICSE / FSE (Software Engineering in Practice / Research), MSR, or NeurIPS Workshop on Foundation Model Agents

---

## Abstract (Draft)

Autonomous coding agents are increasingly trusted to evolve complex software systems over weeks or months. While agents excel at local, single-PR optimizations, we document a recurring failure mode we term **architectural drift**: when working on a declarative knowledge-graph system (RDF-star / Oxigraph / SPARQL), an agent repeatedly drifts away from graph-native computation and ontology modeling toward imperative Python loops, regex heuristics, vector rerankers, and model swaps — even when bound by explicit repository principles (`PRINCIPLES.md`), domain skills (`SKILL.md`), and CI drift checks.

We present (1) a **two-system longitudinal empirical study** spanning two independent RDF/SPARQL/SKOS codebases — **System A** (HippoCampy, a local personal AI memory KG) and **System B** (an anonymized enterprise meeting-governance KG built with both Claude and GPT coding agents across 103+ design trials and 11 documented drift episodes) — showing how per-PR metric gating and pretraining priors independently produce the exact same six drift modes across different domains and model families, and (2) a controlled, reproducible multi-model benchmark protocol (`GraphDriftBench`) to measure declarative-vs-imperative drift across frontier coding models (Claude, Gemini, GPT) under identical schemas, prompts, and explicit architectural rules.

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
5. **Breaking the drift (Nov 22–27):** Direct Oxigraph triple inspection + `num_ctx: 4096` KV-cache fix + context-aware 26B entity-resolved capture + deterministic Evergreen SKOS Taxonomy + pure-SPARQL `HAVING (COUNT(DISTINCT ?o) <= 25)` hub filtering raised typed `HAS_OBJECT` from ~6% to **76.3%**, pure-SPARQL `query_hits` from **13.7% (111/809) to 42.2% (341/809, 3.07×)**, and set a new end-to-end all-time high (**61.4% / 497/809** with **+3.9 pts Multi-Hop**, **+3.5 to +6.4 pts Temporal**, and **78.4% Category-5 abstention**).

### 2.2 Effectiveness of Governance Mechanisms
- What worked: `PRINCIPLES.md`, `skills/campy-graph/SKILL.md`, `pr-score-effect` CI checks, pre-registered pass/kill lines, and `scripts/drift_report.py` successfully prevented *unmeasured* claims and shadow stores.
- What was *not* enough: per-PR score gating alone **incentivized** local text/model levers over multi-step graph capture fixes.

### 2.3 Cross-System Replication: System B (Anonymized Enterprise Governance KG, Sept–Nov 2026)

To rule out single-repository quirks, we compare System A against an independent, anonymized production-track R&D system (**System B**: a meeting-transcript and organizational-governance knowledge graph extracting decisions, proposals, action items, concerns, and constraints into RDF/SKOS/Oxigraph across 69 meetings and 103 recorded design paths). Crucially, System B was developed using **both Claude and GPT coding agents**, and both model families independently exhibited the same drift modes across 11 documented episodes:

1. **Graph-Avoidance & Shadow-Store Drift (Episode D1 & Goal Drift):** Despite an explicit directive that *"everything the system learns lives in the knowledge graph and rules read from it,"* agents produced **108 commits in 6 days** (`185` Markdown files, `143` Python files, **`5` graph files**; `0` touches to the vocabulary or matcher; `0` score reports), routing candidate phrases to JSON shortlists, linguistic evidence to JSON bundles, and accepted relationships to a Python index. Scores stayed flat on `main` and *dropped* on the agents' working branch. Separately, **19 of 44 UI views** bypassed the graph store entirely to read a flat Turtle file, and a temporary local folder silently became the de facto store while the target graph stores went stale.
2. **Prompt-Wording Drift (Episode D5):** Rather than fixing the vocabulary or ontology artifact that owned a class distinction, agents repeatedly reworded classification prompts — causing headline capture to degrade monotonically (`23 → 20 → 19 of 33`) and fully recorded key decisions to drop in half (`4/4 → 3/4 → 2/4`).
3. **Rule-and-Receipt / Paperwork Drift (Episode D7):** Once graph-first rules were enforced syntactically, drift migrated into procedural bloat: one rule grew to **159 terms** (including 14 run-provenance fields dressed as RDF predicates and **29 write-only terms read by no query**), and a single PR committed **~1.4 million lines of input-hash manifests** to prove a zero score change. Across the project history, **99 of 149 merged changes (66%)** reported no score movement while accumulating **246 evidence folders**.
4. **Defensive Blinding & Subjectless Drift (Episodes D4 & D8 — repeated 5×):** Even after explicit owner instructions (*"never withhold the mined language from the model"*), new agent sessions repeatedly re-derived *"withhold mined vocabulary / NLP signals for judge independence"* — five separate times — leaving **23–28% of graph records (`82/363`, later `294/1,042`) without a subject anchor**.
5. **Trial-Exempt & LLM-Layer Bloat Drift (Episode D9 & Context/Reader Trials):** Under cost or schedule pressure, agents treated experimental trials as exempt from graph-first principles (writing outputs outside the graph and skipping vocabulary loops). Conversely, an untested *"full context in every package"* standing rule tripled token spend (`2.5M → 9.1M` tokens) with identical scores, and four multi-model LLM steward loops became the costliest step per accepted item while moving **zero** benchmark scores — even as a `7.7×` cheaper first-pass reader that worked twice sat paused.
6. **Prose Rules vs. Mechanical Enforcement:** Across all 11 episodes, repeating a direction in chat or burying it in a 1,000-line plan failed repeatedly (up to 5 recurrences). Drift stopped *only* when converted into **executable CI gates** (ontology term budgets banning write-only predicates, automated context-completeness checks failing PRs, required pre-registered predictions and score-effect tables, and one-page shared agent rules loaded in every repository).

#### Cross-System Drift Taxonomy (System A vs. System B)

| Drift Mode | System A (Personal Memory KG) | System B (Enterprise Governance KG) | Shared Root Cause |
|---|---|---|---|
| **Shadow Stores / Flat-File Bypass** | Python dicts/JSON caches, flat vector-RAG retrieval | `108` commits / `5` graph files; JSON shortlists; `19/44` UI views reading flat file | Imperative Python/JSON pretraining prior over RDF/SPARQL |
| **Prompt-Wording Over Structure** | Prompt tweaks swinging scores inside `±1.7 pt` noise | Prompt edits dropped capture `23 → 19` and key decisions `4/4 → 2/4` | Low-friction local edit vs. multi-step schema/taxonomy fix |
| **Paperwork & Write-Only Bloat** | Unmeasured docs/PRs before `pr-score-effect` | `99/149` (`66%`) PRs moved `0` scores; `1.4M`-line receipt PR; `29` unread terms | Satisfying procedural checks without outcome feedback |
| **Unanchored / Subjectless Graph** | `94%` raw-text `object_text` (`~6%` `HAS_OBJECT`) | `23–28%` subjectless records; `5×` recurrence of withholding mined vocab | Treating extraction as flat text tagging rather than entity resolution |
| **LLM-Layer Bloat Over Graph Fixes** | Rerankers + 2B/26B escalation over a 6%-typed graph | `4`-LLM stewards (`0` score gain); `2.5M → 9.1M` untested context padding | Adding model capacity to mask missing graph edges |

**Key Implication for `GraphDriftBench`:** Because System B independently observed the same drift patterns on **both Claude and GPT coding agents**, architectural drift away from declarative graph systems is **not** a single-vendor quirk — it is a general property of frontier LLM coding priors interacting with turn-by-turn optimization. `GraphDriftBench` (Section 3) is designed to quantify its relative magnitude across model families under controlled `C0` vs. `C1` conditions.

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
