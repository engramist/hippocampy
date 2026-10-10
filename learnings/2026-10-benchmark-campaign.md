# Benchmark campaign, 2026-09-28 → 2026-10-10: what we learned

The record of a twelve-day effort to vet hippocampy and make campy-benchmarks
say something true about Campy's memory. It covers the benchmark harness,
what the runs showed about Campy, the fixes that moved the numbers (and the
ones that didn't), and how the work was run. It is written so someone who
was not there can pick the work up.

The coordination thread is engramist/hippocampy#278: the cloud agent
(`user-bd`) posts numbered run requests (R1, R2, …) and the user's local
agent, which has the GPU, Ollama and the real models, runs them and posts
results. Results live on the local agent's `local/results` branch; published
runs feed `RESULTS.md` in campy-benchmarks.

Models throughout, unless a row says otherwise: answering `llama3.1:8b`,
judge `gemma4:26b`, embeddings `all-MiniLM-L6-v2`, spaCy `en_core_web_md`.

---

## 1. Starting point (2026-09-28): the benchmark could not say much

The first vetting found that the harness, not Campy, produced most of the
numbers then being reported:

- **Scorers were wrong in both directions.** A correct answer could fail its
  own check (`all()` where `any()` was meant; `symmetric` matching inside
  "asymmetric"); "I don't know" passed (`no` matched inside "know");
  answers that mentioned history failed; "exact match" was a verbatim
  substring test; MemBench precision and recall were the same calculation;
  ARC had hard-coded fallback scores of 0.85/0.9 and passed on a word that
  was in its own query.
- **The suites were not the published benchmarks.** "LoCoMo", "MemBench" and
  "MemoryGym" were small hand-written fixtures (LoCoMo: 25 scenarios of 2–6
  turns, 22 from one template, with the answer's slug in the question).
  MemoryGym tested a verbatim read-back of a coordinate list.
- **No baseline**, so no number meant anything on its own.
- **Runs wrote into the personal `~/.campy` store**, with fixed session ids,
  so runs contaminated each other and the user's memory (later measured and
  purged: B467).
- **No provenance and no per-question records**, so runs could not be
  compared.

What was built in response (campy-benchmarks unless noted):

| Fix | Where |
|---|---|
| Scorer rewrite + a self-test that must reject broken scorers | `scoring.py`, `check_scorers.py` |
| Per-question records and provenance (commits, models, config, data hash) | `records.py`, `provenance.py` |
| Isolated store per run (`CAMPY_HOME`), never the personal store | hippocampy B456, `isolation.py` |
| Fresh store per question for own-history suites, one retry, then recorded error | `fresh_store.py` |
| `--repeat N` with mean and range | `repeats.py` |
| LLM judge (and a check that it agrees with hand labels: 635/637) | `qa_judge.py`, `check_qa_judge.py` |
| Real datasets: LoCoMo-10, LongMemEval (oracle, s), DMR (MSC-Self-Instruct) | `locomo10/`, `longmemeval/`, `dmr/` |
| Fixtures kept, relabelled as regression tests | `locomo/`, `membench/`, `memory_gym/`, `arc_bridge/` |
| Baselines with the same model and judge: no memory, naive RAG (BM25), full context | `baselines.py` |
| A settle step that waits for consolidation to drain before asking | hippocampy B448 |
| Report generation; only clean, isolated, real-daemon runs are "counted" | `report.py` → `RESULTS.md` |
| Turn metadata as fields (`--turn-metadata fields`) | `run_all.py`, B472 Phase 1 |
| Diagnostics (see §7) | `diag_*.py` |

**Lesson:** before trusting any number, test the measuring instrument. A
scorer self-test that is required to *fail* deliberately broken scorers was
the single most useful early step.

---

## 2. Reliability work Campy needed before any score was real

The harness exposed real daemon problems, all fixed:

| Card | Problem |
|---|---|
| B448 | Harness called a `run_sweep` tool that never existed; no way to wait for consolidation |
| B449 | 2–6 s implicit timeout on all external tool calls |
| B450 | A dead or offline daemon could be turned into fake scores |
| B451 | CO_OCCURS_WITH upsert doubled on every rewrite (memory blow-up) |
| B452 | Footprint watchdog missed a 43 GB blow-up |
| B453 | Cold start 4–7 minutes |
| B455 | Running the test suite killed the developer's live daemon |
| B456 | `CAMPY_HOME`: a fully isolated runtime dir |
| B467 | Benchmark data had leaked into the personal store; measured, dry-run, purged |
| B468 | Consolidation Loop LLM steps ran synchronously and froze the daemon mid-run |

**Lesson:** a memory benchmark is also a soak test. Long runs (LongMemEval s
takes ~30 min per question) find event-loop blocking, memory growth and
start-up costs that unit tests do not.

---

## 3. What the benchmarks say about Campy

### 3.1 Headline numbers, latest per suite

| Suite (subset) | Campy | No memory | Naive RAG | Full context | Campy evidence recall |
|---|---|---|---|---|---|
| LoCoMo-10 (conv-26, 60 q) | 0.396 (R20c, R24) | 0.021 | 0.375 | 0.479 | 0.411 (R20c) → 0.496 (R24) |
| LongMemEval oracle (35 q) | 0.600 (R20b) | invalid run | 0.629 | 0.571 | 0.613 |
| LongMemEval s (7 q) | 0.429 | – | – | – | **0.139** |
| DMR (50 q) | 0.620 (R20a, text mode) / 0.500 (R24, fields mode) | 0.120 | 0.580 | 0.800 | 0.531 → 0.580 |

Baselines are all on hippocampy `402c96c` (R20). Reference points from the
literature (other models and judges, orientation only): LoCoMo full-context
GPT-4o-mini ≈ 0.73; LongMemEval oracle GPT-4o ≈ 0.87; DMR MemGPT ≈ 0.93.

### 3.2 Where Campy wins and loses

- **Beats naive RAG** on LoCoMo-10 (+0.02 accuracy, +0.10 recall) and DMR
  (+0.04); slightly behind it on LongMemEval oracle (−0.03, and recall 0.61
  vs 0.76).
- **Loses to full context** on LoCoMo-10 (−0.08) and DMR (−0.18). Full
  context is an upper bound only while the history fits in the window,
  which it does on these subsets.
- **LoCoMo-10 by category** (R20c, passed/12): Campy wins temporal (6 vs
  full-context 3) and adversarial (3 vs 1); loses multi-hop (**0 vs 6**) and
  single-hop (8 vs 10). Multi-hop is the clearest gap.
- **Retrieval at scale is the biggest gap.** LongMemEval s (~500 turns per
  question): evidence recall 0.139 against 0.61 on oracle. The same ranking
  problem as LoCoMo-10, much sharper.

### 3.3 The failure modes, in order of size

1. **Ranking depth.** R8: on LoCoMo-10 the evidence turn's median rank is
   ~28 while the conversation stage keeps 6. Not the similarity floor. R9:
   raising the limit to 12 or 20 raised recall (0.40 → 0.48 → 0.51) but not
   accuracy, halved correct abstentions and doubled latency. **More slots
   is not the fix; better ranking is.**
2. **Answer selection from a correct bundle.** R24/R26: on DMR the right
   turn is in the bundle (often first) and the 8b model still answers from
   a near-duplicate turn by the same speaker in the same session. More
   turns hurt here; fewer helped. (R26's "top 3" was really "oldest 3" —
   see §6 — so the exact cause is being measured in R27.)
3. **Multi-hop needs evidence from several turns combined.** Nothing in
   the read path assembles a chain; the graph, which should, carried mostly
   noise (§4).
4. **Write-path mismatch.** Campy's consolidation (gist classes,
   schema.org routing, engineering relations like REPLACES/CHOSEN_OVER) was
   built for engineering decisions. Benchmarks feed it personal chat, so it
   stored chit-chat as noise and invented engineering relations ("Mustang
   ALTERNATIVE_TO my car"). B472/B473 address this.
5. **Judge noise.** Pronoun flips ("You used to work in…" for "I used to…")
   are judged wrong; identical answers are judged differently across runs.
   About 2 of 6 DMR losses in R24 are judge, not memory.

---

## 4. The graph audit (B472 Phase 0) and what cleaned it

`diag_graph_audit.py` over kept stores showed what consolidation actually
stores from benchmark chat:

| | DMR R20a (50 stores) | LoCoMo-10 R20c |
|---|---|---|
| Concepts | 2,047 | 148 |
| Untyped (no gist class) | 87% | 96% |
| Time phrases as Concepts ("9:55 am", "20 July") | 25% | 28% |
| Harness-prefix junk ("Speaker", "1, 7 days") | 79 | 0 |
| ALTERNATIVE_TO / CHOSEN_OVER / EXTENDS edges | 943 / 233 / 162 | 76 / 38 / 79 |
| Same entity split into variants | – | "Caroline", "Caroline!", "Congrats Caroline", "Wow Caroline" |

Causes and fixes:

| Cause | Fix | Effect (audit) |
|---|---|---|
| Speaker and date were written into the message text by the harness, so they became entities | B472 Phase 1: `notify_turn(speaker, occurred_at)` fields; stored text stays clean | prefix junk 79 → 0; time phrases 25% → 10% (DMR), 28% → 8% (L10) |
| spaCy spans included greetings, punctuation, possessives; dedup was exact text | B472 Phase 2: surface normalization, label lookup, SKOS alt labels, named speakers seeded as Persons | Caroline unsplit; alt labels recorded |
| Step 3b's LLM was asked about every sentence and its endpoint strings became bare Concepts | B473: ask only with a relation cue; LLM relations only between existing Concepts | L10 Concepts 215 → 57, untyped 178 → 7; ALT/CHO/EXT 62/14/90 → 0/0/0 |

Side effect of B473: the semantic section of the bundle became nearly empty
on DMR (present for 12/50 questions). R26 showed this did not cost accuracy
— the semantic section had not been what carried R20.

One fixture regression from B473: `p6_cache_engine` lost its "Redis"
Concept, because Step 1b's "replace X with Y" pattern missed a parse where
spaCy hangs "with Y" off the object. Fixed in #296.

**Lesson:** audit what the write path stores before tuning the read path.
Most of the graph was noise, and no ranking change could have fixed that.

---

## 5. Fixes that moved the numbers (and by how much)

| Change | Measured effect |
|---|---|
| Harness scorer rewrite | Old scores were not comparable; first trustworthy baseline |
| B458 `current_truth` exact-identifier match | MemoryGym fixture 25% → 100% (wrong-episode recall fixed) |
| B459 lexical anchor for superseding statements | fixture deprecation probes recovered |
| B460 passive/move relations, B464 stated values become Concepts, B465 repair, B466 replace-with | fixture 28/28 judge, 0 INVERTED supersession edges |
| B470 drop query words found in >20% of messages from FTS | LoCoMo-10 0.347 → 0.389 (mean of 3 each side, ranges don't overlap) |
| B471 recall what the assistant said | LongMemEval oracle 0.400 → 0.571; single-session-assistant 0.2 → 1.0 |
| DMR harness: ask as the right speaker (framing 3) | DMR 0.500 → 0.620 |
| B473 relation noise | LoCoMo-10 0.354 → 0.396 (with B472 P1–2), adversarial 0.083 → 0.167 |
| B472 Phase 1b embed speaker with the turn | DMR 0.420 → 0.500, recall 0.401 → 0.580; LoCoMo-10 recall 0.388 → 0.496 |

Changes that did **not** help:

| Change | Result |
|---|---|
| Conversation limit 6 → 12 / 20 (R9) | recall up, accuracy flat, abstention halved, latency doubled |
| B472 Phase 1 alone (speaker removed from the embedded text) | **regression**: DMR 0.620 → 0.420, LoCoMo-10 0.396 → 0.354. Questions name the speaker; the right turns fell under the 0.30 similarity floor (cosine 0.219 unprefixed vs 0.539 prefixed). Fixed by Phase 1b. |

---

## 6. Process lessons (the expensive ones)

1. **Retrieval-affecting changes get a benchmark run before merging, not
   after.** B472 Phase 1 merged on unit tests and cost a full cycle (R21)
   to find a 20-point DMR regression. Unit tests cannot see that removing a
   word from an embedding changes what clears a similarity floor.
2. **Know the noise floor before reading a delta.** At 50–60 questions, one
   question is ~2 points; a single run's change under ~6 points is
   direction, not size. Repeat runs (`--repeat 3`) settled B470; single runs
   misled elsewhere (adversarial 3/12 → 0/12 is near noise).
3. **Compare per question, not only per suite.** "Lost 6, gained 0" plus
   reading the six bundles found the R24 cause in minutes; the suite mean
   alone would have suggested retrieval.
4. **Separate retrieval from answering.** Evidence recall (did the right
   turn reach the model?) and accuracy (did the model use it?) moved in
   opposite directions in R24. Report both, always.
5. **Replay instead of re-ingesting.** Ingestion is the slow part (hours).
   `--keep-store` plus offline replay (`diag_lme_fusion.py`,
   `diag_answer_replay.py`) tests a read-path change on frozen stores in
   under an hour, deterministically (temperature 0; R26 reproduced 99/99
   answers verbatim).
6. **Check the diagnostic's own semantics.** R26's `top3` sliced the first
   three turns of a list that the stage sorts *oldest first*, so it measured
   the oldest three, not the best three. Caught before anything was built
   on it, but only because the code was read against the result. Test a
   diagnostic's variants on a fake with known order (as #33 now does).
7. **Tuning on the evaluation set overfits.** B454 was tuned on the same
   34 fixture probes it was scored on; R26's "top 3 helps" came from the
   same 50 DMR questions it would be applied to. Any rule must hold on a
   second suite (LoCoMo-10) and, ideally, a held-out split.
8. **Long chains stall when every step waits for a person.** Work stopped
   after each phase until the user said "go". The local agent twice missed
   requests through its own comment-filter bugs (header level; cutoff time).
   What kept things moving: numbered requests, exact commands, explicit
   queues, scheduled check-ins, and standing permission to merge.
9. **Hand-off quality matters.** Local commands had to be zsh-safe (no `#`
   comment lines), pinned (`git switch --detach origin/<branch>`), and
   isolated (`--isolated`). Never touch `~/.campy` except through approved,
   backed-up steps.
10. **A clean graph is not the same as useful memory.** B473 removed most
    noise, and the semantic section then contributed almost nothing.
    Cleaning is necessary; Phase 3 (observations) is what should give the
    graph something worth retrieving.

---

## 7. Tools built (campy-benchmarks), and when to use them

| Tool | Use |
|---|---|
| `run_all.py --isolated --keep-store --turn-metadata fields` | every counted run |
| `--baselines no_memory,full_context,naive_rag` | same-model comparison |
| `diag_graph_audit.py <stores or results.json>` | what consolidation stored: types, junk, variants, edges |
| `diag_supersession_edges.py <store>` | fixture deprecation probes: right / INVERTED / missing |
| `diag_locomo10_fusion.py`, `diag_lme_fusion.py` | replay the conversation stage with variants; evidence rank per question |
| `diag_answer_replay.py` (was `diag_dmr_answer.py`) | re-ask through `run_ask` on copies of kept stores with bundle variants (`asis`, `nosem`, `convonly`, `oldest3`, `limit3/4`, `rankorder`); DMR and LoCoMo-10 |
| `diag_bundle.py`, `diag_conversation_stage.py` | inspect one question's bundle |
| `check_*.py` | self-checks for scorers, judge, suites, report, turn metadata |

---

## 8. State at the end of this record (2026-10-10 12:30 UTC)

- hippocampy main `0a7a888`: B472 Phases 0–2 + 1b, B473, #296.
- campy-benchmarks master `a201a3e`.
- Running locally: **R27** (corrected answer replay on R20a/R24b DMR and
  R20c/R24a LoCoMo-10 stores). Then **R20d** (LongMemEval s, 30 questions,
  with baselines and the fusion diagnostic), ~15 h.
- Designed, not built: **B472 Phase 3** (Observation table, dedicated
  worker, shipped disabled, user turns only) —
  `backlog/plans/B-472-phase3-observations.md`.
- Scorecard (claude.ai artifact) updated through R24 with the baseline chart.

## 9. Open questions

- Is the DMR answer-selection loss about turn count, turn order or position
  bias? (R27 decides.)
- Why does evidence rank so deep (median 28) on LoCoMo-10, and would a
  cross-encoder reranker over the fused candidates fix it?
- Can a session-level prefilter recover LongMemEval s recall (the `sess3`,
  `sess5` and `gold` variants of `diag_lme_fusion.py` — pending R20d)?
- How much of the gap to published systems is the 8b answering model?
  A model ablation on frozen stores would separate memory from model.
- Do observations (Phase 3) give multi-hop the cross-turn facts it lacks?
