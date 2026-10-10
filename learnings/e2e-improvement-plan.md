# End-to-end plan: improving Campy and its benchmark scores

**Why this exists.** Work so far has advanced one phase at a time and
stopped after each, waiting for a "go". This plan describes the whole path
from where Campy is now to where it should be. It fixes the order and the
gates, and states the decision rules in advance, so work can keep running
without a stop between steps. It builds on `2026-10-benchmark-campaign.md`
(read that first).

**Owner of the loop:** the cloud agent drives and merges; the local agent
runs everything that needs real models; the user sets direction and can
interrupt at any point. Standing permission to merge when a gate passes is
assumed (already granted).

---

## 1. The goal, stated as numbers

Campy's claim is that memory beats stuffing the context and beats naive
retrieval. The end state proves that on public benchmarks with the same
model:

| Suite | Now | Milestone target | End target | Why that target |
|---|---|---|---|---|
| LoCoMo-10 (judge) | 0.396 | 0.45 | ≥ full context (0.48) | match the model reading everything |
| LoCoMo-10 multi-hop | 0–2 / 12 | 4 / 12 | 6 / 12 | full context gets 6 |
| LoCoMo-10 adversarial abstain | 0.00–0.25 | 0.25 | ≥ 0.33 | Campy's one clear category win must hold |
| DMR (judge) | 0.500 (fields) | 0.62 | ≥ 0.70 | recover text-mode, then close half the full-context gap (0.80) |
| LongMemEval oracle | 0.600 | 0.63 | ≥ 0.66 | beat naive RAG (0.629) clearly |
| LongMemEval s (recall) | 0.139 | 0.40 | ≥ 0.55 | close to oracle recall (0.61) |
| LongMemEval s (accuracy, 30 q) | n/a (0.429 on 7) | baseline set | > full context | where memory should beat stuffing |
| Fixture regression | 28/28, 0 INVERTED | hold | hold | never regress |

The headline the project wants to publish: **"With the same small model,
Campy beats naive RAG everywhere and beats full context on long
histories."** Every milestone moves toward that sentence.

---

## 2. The target architecture (what "end to end" means)

The pipeline has five stages. Most past work tuned one stage in isolation;
the plan treats them as one system, with a measurement at every boundary.

```
WRITE                                                 READ
turn ──► 1 Capture ──► 2 Consolidate ──► store ──► 3 Retrieve ──► 4 Pack ──► 5 Answer
         speaker,       entities,                    candidates,     evidence     prompt,
         occurred_at,   observations,                rerank,         order,       cite or
         session,       supersession                 session-aware   dedup,       abstain
         turn index     edges                                        budget
   measured by:  graph audit        evidence recall@k      bundle recall   accuracy, abstention
```

1. **Capture** (done, B472 Phase 1/1b): clean text plus speaker,
   occurred_at and session as fields; the speaker embedded with the text.
   Add a **turn ordinal within the session**, so turns that share a
   timestamp (DMR) can be told apart and ordered.
2. **Consolidate** (B472 Phase 2, B473 done; Phase 3 next): entities
   resolved, no invented relations, and **source-grounded observations**:
   who did/said/decided what, when, with a pointer to the evidence turn.
   This is what the semantic section and multi-hop should draw on.
3. **Retrieve**: candidates from three planes — turns (vector + FTS, as
   now), observations (new), and graph neighbours of the entities the
   question names (new, for multi-hop). Then **rerank** the fused
   candidates with a cross-encoder or LLM scorer instead of relying on
   reciprocal rank alone. For long histories, a **session prefilter**
   (choose the few sessions most likely to hold the answer, then rank
   within them).
4. **Pack**: decide which evidence the model sees and how. Best-first or
   chronological within a clear structure; near-duplicates collapsed; an
   adaptive cutoff (stop when scores drop off) instead of a fixed six; each
   item stamped `[speaker, date, session n, turn k]`.
5. **Answer**: a prompt that asks the model to quote the evidence it uses
   and to abstain when none supports an answer. Calibrate the "sections are
   NOT empty" instruction, which currently pushes the model to answer
   adversarial questions.

---

## 3. The evaluation system (built first, used by everything after)

The plan only runs unattended if every change has an automatic, cheap,
trustworthy verdict.

### 3.1 Three tiers

| Tier | What | Time | When |
|---|---|---|---|
| **T0 replay** | Read-path changes evaluated on **frozen golden stores** with `diag_answer_replay.py` (and the fusion replays), judged | 30–90 min | every read-path PR, before merge |
| **T1 fixtures** | LoCoMo fixture 28/28, 0 INVERTED; unit tests; spaCy tests | minutes (CI) | every PR |
| **T2 full runs** | Fresh ingestion: DMR 50, LoCoMo-10 60, LME oracle 35, LME s 30, with `--keep-store` and graph audit | 3–15 h | every write-path PR before merge; nightly on main |

Read-path changes (retrieval, rerank, pack, prompt) need only T0 + T1.
Write-path changes (capture, consolidation, observations) need T2.

### 3.2 Golden stores and splits

- Freeze the kept stores from R24 (DMR 50 + LoCoMo-10 conv-26) and from the
  next LME s run as **golden stores**. Regenerate them only when a
  write-path change merges (the new T2 run's stores become the new golden
  set).
- **Dev / held-out split.** Tune only on the dev split; a change merges
  only if the held-out split does not regress.
  - DMR: dev = the current 50; held-out = 50 more (questions 50–99).
  - LoCoMo-10: dev = conv-26; held-out = a second conversation.
  - LongMemEval: oracle stays a check; s is the scale test.

### 3.3 The gate (applied automatically)

A change passes when, on the held-out split and the other suites:

- no suite drops by more than its **noise floor** (measured once: 3 repeat
  runs on main; expected ~±4 points at n=50–60); and
- the paired per-question comparison shows more gained than lost on the
  targeted suite; and
- the fixtures stay 28/28 with 0 INVERTED.

The verdict is posted as a table on #278 and the scorecard is updated.

### 3.4 Answer-model ablation (once, early)

Re-ask the golden stores with a stronger answering model (same bundles) to
learn how much of the gap is the 8b model. If a stronger model closes most
of the gap, prioritise pack/answer work; if not, retrieval and
consolidation.

---

## 4. The milestones, in order

Each milestone lists its work items, the tier that gates it, and the exit
criterion. A milestone starts as soon as the previous one's exit criterion
is met; nothing waits for a separate "go".

### M0 — Evaluation infrastructure (start now; ~2 days)

- 0.1 Golden stores: copy R24's kept stores to a durable path; record
  their commits. Same for each new T2 run.
- 0.2 Held-out sets: DMR questions 50–99 and a second LoCoMo-10
  conversation, run once on main (`9c5c9d8`+) to set baselines.
- 0.3 Noise floor: `--repeat 3` on main for DMR and LoCoMo-10.
- 0.4 One command per tier: `make eval-read` (T0 replay on golden stores,
  judged, paired diff vs main) and `make eval-write` (T2), both producing a
  standard summary table.
- 0.5 Answer-model ablation (§3.4).
- 0.6 Finish R27 and R20d (in progress).

**Exit:** the gate table can be produced for any branch with one command
per tier.

### M1 — Pack and answer: use the evidence that already arrives (~3 days)

Retrieval now often brings the right turn (DMR recall 0.58); the model
does not use it.

- 1.1 Evidence order and count from R27's result: `rankorder`, a real
  top-k, or an adaptive score cutoff.
- 1.2 Turn ordinal in the stamp (`[Speaker 1, 2022-12-14, s3 t5]`); collapse
  near-duplicate turns by the same speaker in the same session.
- 1.3 Answer prompt: quote the supporting line, abstain if none; revisit
  the "NOT empty" instruction (LoCoMo-10 adversarial fell to 0/12).
- 1.4 Judge robustness: accept pronoun-flipped persona answers (a judge
  prompt note for DMR's "you" framing) and re-judge disagreements twice.

**Gate:** T0 + T1. **Exit:** DMR ≥ 0.62 in fields mode; LoCoMo-10 ≥ 0.42
with adversarial ≥ 0.25; held-out no worse.

### M2 — Retrieval ranking (~1 week)

- 2.1 Cross-encoder reranker over the top ~50 fused candidates (a small
  local model; measure latency). This targets R8's median evidence rank of
  28.
- 2.2 Session prefilter for long histories (`sess3`/`sess5`/`gold` from
  R20d tell how much it can win).
- 2.3 Query understanding: extract named speakers, entities and time
  expressions from the question and use them as filters or boosts (DMR
  names the speaker; LoCoMo-10 temporal questions name dates).
- 2.4 Re-tune the 0.30 similarity floor and RRF only after 2.1, on dev,
  checked on held-out.

**Gate:** T0 on DMR, LoCoMo-10 and LME s golden stores + T1. **Exit:**
LoCoMo-10 evidence recall ≥ 0.60; LME s recall ≥ 0.40; accuracy not down
anywhere.

### M3 — Observations (B472 Phase 3; ~1–2 weeks)

As designed in `backlog/plans/B-472-phase3-observations.md`: a new
Observation table, a dedicated worker, user turns only, shipped disabled.

- 3a schema and write API (no behaviour change);
- 3b extraction worker behind a flag;
- 3c observations as a retrieval plane (semantic section fed from them);
- 3d enable by default once the gate passes.

**Gate:** T2 for 3b–3d (the write path changes), plus T0 for 3c. **Exit:**
LoCoMo-10 multi-hop ≥ 4/12; LME oracle ≥ 0.63; the semantic section is
present for most questions again and helps (a `nosem` replay shows a loss
without it).

### M4 — Multi-hop and temporal reasoning (~1 week)

- 4.1 Graph expansion: from the question's entities to their observations
  and one hop further; pack the chain together.
- 4.2 Time normalisation: resolve relative phrases ("last Friday") against
  `occurred_at` at capture, so temporal questions compare dates.
- 4.3 Optional two-step answering for multi-hop questions: retrieve,
  extract intermediate facts, retrieve again.

**Gate:** T0 + T2 as applicable. **Exit:** multi-hop ≥ 6/12; temporal
holds ≥ 6/12.

### M5 — Scale, breadth and publication (~1 week, then continuous)

- 5.1 LoCoMo-10 on all ten conversations; DMR on all questions; LME s on
  ≥ 100 questions.
- 5.2 Three seeds per headline number, with ranges.
- 5.3 Publish `RESULTS.md` and the scorecard with baselines and the answer
  model named; write up the method.
- 5.4 Nightly T2 on main, posting regressions automatically.

**Exit:** the headline sentence in §1 is true and published with ranges.

---

## 5. Decision rules (so nothing waits for a person)

| Situation | Action |
|---|---|
| Gate passes | merge, update the scorecard, start the next item |
| Gate fails by more than the noise floor | do not merge; post the per-question diff; diagnose with replay; one fix attempt, else drop the item and record why in `learnings/` |
| Change is within noise either way | merge only if it simplifies or is a prerequisite; otherwise drop |
| A diagnostic's result looks surprising | verify the diagnostic on a fake with known answers before acting on it |
| Local agent silent for > 2 h with work queued | re-post the request with a fresh number; check the filter |
| A milestone exit is not met after its time box ×2 | stop, write a learnings note, and ask the user to re-plan |
| Anything touching `~/.campy` | only through an approved, backed-up step |

---

## 6. How the loop runs day to day

1. The cloud agent keeps a **queue** at the top of #278: the next 3–5 runs
   with exact commands. The local agent always has the next run ready, so
   the GPU never idles waiting for a reply.
2. Every PR states its tier and its gate result in the description.
3. Each result is processed within one check-in: gate verdict, scorecard
   update, next item queued.
4. Every finished milestone, and every dropped item, adds a dated note to
   `learnings/`.
5. The user is asked only about direction changes, never "should I
   continue".

---

## 7. Risks and how the plan handles them

| Risk | Mitigation |
|---|---|
| Overfitting to 50–60 questions | held-out splits, a second suite per change, repeat runs |
| The 8b model is the ceiling | the M0 ablation tells early; M1 prompt work still helps |
| Reranker or observations add latency | measure `ask` latency in every gate table; budget ≤ 2× today |
| Phase 3 raises LLM cost per turn | user turns only, cue-gated, worker off the event loop, flag |
| Benchmark-specific hacks creep in | every fix must be stated as a general rule about conversations (as #296 was), never a dataset id |
| Local agent misses requests | numbered requests, queue, re-post rule |
