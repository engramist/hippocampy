# Paper 1 Draft: Why Knowledge Graphs Fail in LLM Agent Memory (And How to Fix Them)

**Working Title:** *Why Knowledge Graphs Fail in LLM Agent Memory (And How to Fix Them): An Empirical Post-Mortem on Long-Horizon Conversational QA*  
**Status:** Living draft (started 2026-11-24; results updated as pre-registered gates complete)  
**Target Venues:** ACL / EMNLP (Long Paper), NeurIPS Datasets & Benchmarks, or ISWC (Research Track)

---

## Abstract (Draft)

Knowledge graphs (KGs) are widely proposed as a structured backbone for long-horizon LLM agent memory, yet in practice flat retrieval-augmented generation (RAG) and cross-encoder rerankers routinely outperform KG-backed pipelines on conversational QA benchmarks such as LoCoMo and LongMemEval. Through a longitudinal, pre-registered ablation campaign of 50+ controlled experiments on an embedded RDF-star / SPARQL memory engine (HippoCampy / Oxigraph), we diagnose *why* graph memory fails in practice and demonstrate how to make it work.

We show that naive KG failure is not a flaw of graph representation or SPARQL inference, but a compounding failure of **isolated single-turn small-LLM extraction**: extracting facts turn-by-turn with an 8B model yields 35–53% factual error rates, leaves ~94% of object phrases as unlinked free-text strings, fragments ~50% of Concepts into degree-1 islands, and causes downstream graph retrieval and graph-facts prompt sections to *decrease* end-to-end QA accuracy (-1.4 to -5.3 points). When we replace isolated 8B extraction with context-aware, entity-resolved, SHACL-validated capture (26B model with 3-turn coreference context, closed entity-set grounding, speaker-alias merging, and person-anchored subjects), blind triple error drops from **35–53% to 4.0%**, typed `HAS_OBJECT -> Concept` linking jumps **12.7×** (`~6% → 76.3%` across 3,342 observations), and pure-SPARQL zero-vector `query_hits` jump **2.5×** (`13.7% → 34.0%` on 809 LoCoMo questions). On a single-conversation pilot (`conv-26`), the cleaner graph lifts multi-hop accuracy by **+9.4 points** (`21.9% → 31.2%`) — orthogonal to reader-side escalation, which is blind to multi-hop (AUC 0.52) — and stacks to **66.5%**. `[TBD: Insert full 809 + Category-5 gate result from task-322 and evergreen SKOS taxonomy results.]`

---

## 1. Introduction & Motivation

- **The promise of KG memory:** Subject-anchored facts, provenance (`EVIDENCED_BY`), symbolic computation (`COUNT`, `LIST`, `LATEST`, `BEFORE/AFTER`), and ontology/taxonomy inference (`INSTANCE_OF`, `BROADER*`, `DEPRECATED_BY+`).
- **The empirical paradox:** Across our first 6 weeks of benchmarking on LoCoMo (809 category 1–4 questions + 222 category-5 adversarial questions), every winning lever was text/RAG or reader-side (`B482` token budget, `B487` ±2 neighbour turns, `B538` inline dates, `B578` window-mode cross-encoder `+2.3 pts`, `ND-18b` 2B checker + 26B escalation `+4.3 pts` / `+17.1` cat-5), while every graph lever tied or lost (`principled` vs `main` `+0.2 pts`, `graph_facts` `-1.4` to `-2.5 pts`, `concept_walk` `-5` to `-7 pts`).
- **Core thesis:** Evaluating graph retrieval on top of an unverified, low-linking, 8B-extracted graph measures *capture noise*, not *graph utility*.

---

## 2. System & Experimental Methodology

- **Store:** Embedded Oxigraph (`pyoxigraph`, single default graph, RDF-star reifiers) + `sqlite-vec` / FTS5 as a non-authoritative index.
- **Inference choice (B407):** Empirical benchmark rejected runtime OWL 2 RL materialization (>10,000× write amplification at 500 entities; >60s at 50k entities) in favor of zero-write-penalty SPARQL property paths (`BROADER*`, `DEPRECATED_BY+`, 0.026 ms).
- **Measurement discipline:**
  - Single headline metric: LoCoMo categories 1–4 (`n=809`, five per-conversation isolated stores), 26B 3-vote strict judge (±1.7 pt noise; pass > +1.9 pts), plus Category-5 abstention (`n=222`) to prevent hallucination tradeoffs.
  - Pre-registered pass/kill lines before every run; deterministic offline proxies (`Step Q` pure-SPARQL `query_hits`, `ND-7` context coverage) validated against previously killed gates.
  - Strict separation of published-judge comparison column (`69.8%` on control vs. our strict judge `53.6%`).

---

## 3. Post-Mortem: Why Naive Graph Memory Failed

### 3.1 Evidence of Failure on the 8B-Extracted Graph
| Lever | Mechanism | 809 Accuracy Delta | Root Cause |
|---|---|---|---|
| `concept_walk` (B503/B560) | Separate "linked" prompt section via `MENTIONS` | `-5.6` to `-7.6 pts` | Prompt bloat + 8B refusals (only 2% of walk rows held gold) |
| `graph_facts` (Step 3) | Render `query_hits` rows in prompt | `-1.4` to `-2.5 pts` | 8B facts 35–53% wrong; fired on 413 q (302 without gold row) |
| `principled` profile (Step 4) | 14 graph hygiene/vote flags together | `+0.2 pts` (tie) | Starved by capture: ~6% `HAS_OBJECT` |
| `bridge_809` (2-hop over `s4p`) | Seed-turn Direct + SKOS `BROADER` bridge | `+0.00 pts` (CE) / `-2.58 pts` (RRF) | ~50% of Concepts are deg-1 islands; multi-turn bridges are generic noun chunks (`memories`, `picture`, `fun`, median 25–45 cands/q) |

### 3.2 Fidelity & Bottleneck Diagnosis (`ND-13`, `ND-16`, `ND-18b`)
- `ND-13` (809/809 = 100.0% exact fidelity against `b10on`): 159 no-gold-in-view misses split cleanly into **73 `outside_vector_top_100` (45.9%)** and **82 ranked below seeds used (51.6%, median CE rank 24.0 vs. 5.5 seeds)**.
- **45.9% (`73/159`) of all no-gold misses are Category-1 multi-hop**, where even 26B escalation (`ND-18b`, `job 1019`) was completely flat (**29.4% vs. 29.4%, +0.0**) and the 2B checker had **AUC 0.52** (coin flip).

---

## 4. Fixing Capture First: Entity-Resolved, Rule-Gated, SHACL-Validated Triples

### 4.1 Three Root Capture Defects Fixed (Pilot v2)
1. **Isolated single-turn extraction → 3-turn coreference context + closed entity list** (resolving `"he"`, `"it"`, `"my class"` → canonical Concepts).
2. **Exact-string object lookup → grounded entity admission** (`HAS_OBJECT -> Concept` verified against closed set or verbatim turn span + SHACL `ObservationShape`).
3. **Speaker alias & topic-subject drift → deterministic alias merging (`HAS_ALT_LABEL` + `repoint_*`) + Principle 8 person-anchored subjects** (plus stripping `[shares an image: ...]` captions).

### 4.2 Empirical Results Across All 5 Conversations (`n=809`)
| Metric (`n=809` unless noted) | 8B Baseline (`s4p`) | 26B Entity-Resolved (Pilot v2) | Improvement |
|---|---|---|---|
| Blind triple error rate (`conv-26`, `n=50`) | `35–53%` wrong | **`4.0%` wrong (`2/50`)** | **~10× cleaner** |
| Non-attribute `HAS_OBJECT -> Concept` (all 5 stores) | `~6%` | **`76.3%` (`2,084/2,730`)** | **12.7× jump** |
| Pure-SPARQL Step Q `HIT` (zero vectors) | `111` (`13.7%`) | **`275` (`34.0%`)** *(+40 too_broad = 38.9%)* | **2.5× (+148%)** |
| Failure: `gold_fact_object_is_text` | `216` | **`53`** | **-75%** |
| Failure: `no_fact_on_gold_turn` | `79` | **`38`** | **-52%** |
| Failure: `gold_fact_without_subject_edge` | `90` | **`47`** | **-48%** |

### 4.3 End-to-End QA & Orthogonal Stacking
- **`conv-26` pilot (`n=152`, 26B 3-vote judge):**
  - 8B Baseline (`b10on`): `62.5%` (MH `21.9%`)
  - 8B + Checker (`b18on`): `65.8%` (MH `21.9%`, `+0.0`)
  - Pilot v2 (`pv2win`): `61.2%` (**MH `31.2%`, `+9.4 pts`**)
  - Pilot v2 + Checker (`pv2chk`): **`66.5%` (`101/152`)** (**MH `31.2%` preserved**, T `78.4%`, SH `80.0%`)
- **Full 809 + Category-5 Gate (`task-322`, 2026-11-24):**
  - `Claude 8B + Checker (b18on)`: **61.1% (494/809)** — Multi-Hop `29.4%` (`45`), Temporal `66.1%` (`113`), Open-Domain `39.2%` (`20`), Single-Hop `72.8%` (`316`), Cat-5 abstention `73.0%` (`162/222`), 809 abstentions `122`.
  - `Pilot v2 + Checker (pv2on)`: **60.1% (486/809, -1.0 pts; g=69, l=77)** — **Multi-Hop `34.6%` (`53`, `+5.2 pts`)**, Temporal `64.9%` (`111`, `-1.2`), Open-Domain `41.2%` (`21`, `+2.0`), **Single-Hop `69.4%` (`301`, `-3.4 pts`, `-15`)**, **Cat-5 abstention `78.4%` (`174/222`, `+5.4 pts`)**, 809 abstentions `139` (`+17`).
  - **Key finding:** Entity-resolved typed capture delivers a real, consistent **+5.2 pt multi-hop gain** across all 5 conversations (where reader escalation alone was flat at +0.0) and **+5.4 pts on adversarial abstention**, but stripping image captions and non-person Observations increased single-hop refusals (`-15` questions, concentrated in `conv-48` `-6` and `conv-49` `-4`), offsetting the multi-hop gain on overall accuracy.

---

## 5. Evergreen SKOS Taxonomy, Specificity-First SPARQL & Shape-Gated Graph Answering

- Even after fixing `HAS_OBJECT` (`76.3%`), **`221 / 809` (27.3%)** of questions still failed Step Q with `gold_object_not_reached_from_named_concept` (e.g., question asks about a `"hobby"`, graph has `"pottery"` with no `INSTANCE_OF / BROADER*` chain to `"hobby"`).
- **Evergreen Automated SKOS Taxonomy (PR #530):** Deterministic inline capture hook (`enrich_concept_inline`) + idempotent GCL sweep (`sweep_store_taxonomy`) using singular lemma normalization, WordNet hypernym walks to a general mid-level ontology ceiling, `HAS_ALT_LABEL` plural/synonym expansion, and B541 cycle protection. Across all 5 Pilot v2 stores (`7.3s` CPU, `0` errors): `+714 INSTANCE_OF`, `+505 BROADER`, `+446 HAS_ALT_LABEL`; reduced `question_names_no_object_concept` from `124 -> 94` (`-30`) and lifted raw SPARQL reach (`HIT + too_broad`) from `315 -> 333 / 809` (`41.2%`).
- **Specificity-First `query_hits.selective_objects` (PR #529):** Adding a single pure-SPARQL selectivity filter (`GROUP BY ?kid HAVING (COUNT(DISTINCT ?o) <= MAX(?max_facts))`) drops over-broad hub Concepts (`group`, `event`, `activity`) before taking the union, converting `too_broad` collisions into hits (`40 -> 13` plain, `57 -> 21` with taxonomy) and lifting pure-SPARQL Step Q hits to **`294 / 809` (`36.3%`, `2.65×` Claude's `111/809`)**.
- **Full 809 + Category-5 Gate with `graph_facts` + `selective_objects` (`task-588`, 2026-11-26):**
  - Overall 809: **`60.8%` (`492/809`)** vs. `b18on` `61.1%` (`494/809`, `-0.25 pts`) and `pv2on` `60.1%` (`486/809`, `+0.74 pts`).
  - **Temporal (`n=171`):** **`72.5%` (`124/171`)** — **`+6.4 pts` (`+11`) over `b18on` (`66.1%`)** and **`+7.6 pts` (`+13`) over `pv2on` (`64.9%`)**! On `dated` queries (`n=136`), accuracy jumped from `75.0% -> 80.1%` (`+5.1 pts`, zero losses in any category).
  - **Category-5 Abstention (`n=222`):** **`78.8%` (`175/222`)** — **`+5.8 pts` over `b18c5on` (`73.0%`)**, new all-time high (unchecked 8B rose `55.9% -> 63.5%`, `+7.6 pts`).
  - **Single-Hop (`n=434`):** recovered `+6` (`69.4% -> 70.7%`).
  - **Critical Negative Finding (Multi-Hop early stopping):** Indiscriminate all-shape `graph_facts` dropped Multi-Hop from `34.6% (53)` back to `28.8% (44)` (`-9`) because showing partial `[computed: list]` / `[computed: count]` / `open` graph rows caused the 8B reader to treat the graph snippet as exhaustive and ignore remaining conversation turns.
  - **Implication:** Graph-computed sections must be **shape-gated** (emit structured `graph_facts` on exact/non-exhaustive `dated` queries where it delivered `+6.4 pts` Temporal with zero regressions, while preserving `pv2on`'s `+5.2 pt` Multi-Hop retrieval for multi-hop synthesis).
- **Dated-Only Shape-Gated `graph_facts` Gate (`task-683`, PR #531, 2026-11-26):**
  - Restricting `graph_facts` to `["when"]` (`CAMPY_GRAPH_FACTS_SHAPES=when`) achieved a **new all-time high of `61.4%` (`497/809`)** (`+0.37 pts` / `+3` vs. `b18on` `494/809`; **`+1.36 pts` / `+11`** vs. `pv2on` `486/809`; beat or tied `b18on` on `4/5` conversations).
  - Reproduced the exact **`80.1%` (`109/136`, `+5.1 pts`)** accuracy on `dated` queries, lifted **Cat-2 Temporal to `69.6%` (`+3.5 pts` vs. `b18on`, `+4.7 pts` vs. `pv2on`)**, recovered **Cat-1 Multi-Hop to `33.3%` (`+3.9 pts` vs. `b18on`, `+7` recovered over all-shape)**, kept **Cat-3 Open-Domain at `39.2%` (`+0.0`)**, and held **Cat-5 Abstention at `78.4%` (`+5.4 pts`)**.

---

## 6. Related Work & Discussion
- Compare against Mem0, Zep/Graphiti, HippoRAG, MemOS (including published-judge vs. strict-judge calibration: +16 pt gap).
- Practical takeaway for builders: *fix capture precision and entity resolution before judging graph retrieval; combine symbolic graph recall (multi-hop) with calibrated reader escalation (in-view reasoning & abstention).*
