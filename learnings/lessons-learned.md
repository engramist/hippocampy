# Lessons learned: every trial, why we ran it, and what it showed

The full trail of the benchmark work, oldest first. One entry per test or trial: why we tried it, what we tried, the
result, and the decision that followed. `e2e-status.md` is the current-state page; this file is the history. The dated
notes in this folder hold the longer evidence for each period and are linked from the section headings.

Conventions: results are given as accuracy in percent on the 809 questions and the change in percentage points against the run's own control (noise ±1.7 points; a gain needs more than +1.9), with raw counts once in brackets; a number on any other question set says so. Ids and counts only, no answer-key values; models are named by role and size (the 8B answer model, the
26B judge); "g / l" means questions gained / lost against the comparison arm on the same questions.

## Adding an entry (required after every test or trial)

Append to the last section, in the same PR as the status-file update. If the result changes direction (a step added,
dropped, reordered or redefined), update `e2e-improvement-plan.md` in that PR too, under a dated "Revision" heading.
A result PR without its entry here is not merged.

```
### <date> <short name> (<run id, PR or card>)
- **Why:** the observation or miss that prompted it.
- **What:** the change or measurement; the graph edges it reads and writes; flags; stores; what it was compared with.
- **Lines:** the prediction, the pass line and the kill line, written before the run.
- **Result:** the numbers, including what was lost.
- **Decision:** kept, stopped, parked or held, by whom, and what it changes next.
- **Lesson:** only if it taught something that applies beyond this run.
```

## Lessons that kept recurring

1. **Test the measuring instrument first.** Broken scorers, an abstention pattern that missed our own wording, a judge
   reply cap, a replay that mixed conversations, and wrong answer keys each produced false results for days.
2. **More or better evidence in the prompt did not become better answers** with the 8B answer model: a larger turn
   limit, a reranker, a graph walk, gathered turns and graph facts without a gold row all raised recall and lowered or
   tied accuracy. Extra loosely related lines make it abstain.
3. **A share or a count can rise while no question becomes answerable.** Shares of facts with an edge, link counts and
   precision of retrieved items all moved without the score. Since 2026-11-12 capture changes are judged by query
   hits, and a role is hand-checked.
4. **Prompt wording swings results by itself.** Two sentence replacements in the extraction prompt lost 58 of 76
   stable facts; reordering same-timestamp turns flipped 6 of 50 answers.
5. **A model's closed choice is not a rule.** The model-chosen partner was wrong 29 times in 30, senses 32%, action
   words 21-34%. What a rule wrote from the text (places, "we" anchors, "X and I" partners) held up.
6. **Know the noise before reading a difference.** ±5 of 110 questions, ±9 of 300, ±14 of 809. Several "findings"
   were reversed within days because one measurement was believed.
7. **Per-lever gates on a mixed pipeline are checkpoints, not verdicts.** Capture was dropping most entities while
   graph stages were being judged one by one on top of it.
8. **Predictions catch design errors.** Step 3 predicted 100-115 firings and got 413; the gap was the finding.

---

## 1. Vetting the benchmark, 2026-09-28 to 2026-10-10 ([campaign](2026-10-benchmark-campaign.md), [summary](2026-10-summary.md))

| Trial | Why | What | Result | Decision |
|---|---|---|---|---|
| Harness audit | Reported scores looked too good | Read every scorer and suite | Scorers wrong in both directions ("I don't know" passed; correct answers failed); the suites were hand-written lookalikes; no baseline; runs wrote into the personal store | Scorer rewrite with a self-test that must reject broken scorers; isolated store per run; real LoCoMo-10, LongMemEval and DMR; same-model baselines; per-question records |
| Reliability under long runs | Runs hung or blew up | Long ingests on the real daemon | Consolidation froze the daemon; an edge upsert doubled on every rewrite (43 GB); cold start 4-7 min; tests killed the live daemon; benchmark data in the personal store | Fixed as B448-B468 before any score was counted |
| First real baselines (R20) | No number meant anything alone | Campy against no memory, naive RAG and full history, same model and judge | LoCoMo-10: 0.396 against 0.021 / 0.375 / 0.479. LongMemEval oracle: 0.600 against 0.629 naive RAG. DMR: 0.620 against 0.580 / 0.800 | Position recorded; gaps named: long histories, multi-hop (0-2 of 12), answer selection |
| Evidence rank (R8) | Low recall on LoCoMo | Rank of the gold turn in the fused candidates | Median rank about 28; the stage keeps 6 | Ranking, not the similarity floor, is the gap |
| Turn limit 6 to 12 and 20 (R9) | Gold turn ranks deep | Raise the conversation limit | Recall 0.40 to 0.48 to 0.51; accuracy flat; correct abstentions halved; latency doubled | Not adopted |
| Graph audit (B472 phase 0) | Graph section added nothing | Audit of what capture stored | 87-96% of Concepts untyped; about a quarter were time phrases; speaker prefixes stored as entities; hundreds of invented engineering relations; one person split into variants | Clean-up below |
| Speaker and date as fields (B472 phase 1) | They were being stored as entities | `notify_turn(speaker, occurred_at)`; stored text clean | Junk entities gone, but DMR 0.620 to 0.420 and LoCoMo-10 0.396 to 0.354: questions name the speaker and the turns fell under the similarity floor | Regression; fixed by phase 1b |
| Embed the speaker with the turn (phase 1b) | The regression above | Speaker name in the embedded text only | DMR 0.420 to 0.500, recall 0.401 to 0.580; LoCoMo-10 recall 0.388 to 0.496 | Kept |
| Surface normalisation, alt labels (phase 2) | Entity variants | Normalise spans, label lookup, speakers seeded as persons | Variants merged | Kept |
| No invented relations (B473) | Engineering relations on personal chat | Ask the model only on a relation cue, only between existing Concepts | LoCoMo-10 0.354 to 0.396; invented edges to 0; the semantic section nearly empty, at no accuracy cost | Kept. Lesson: a clean graph is not yet useful memory |
| Common query words dropped from keyword search (B470) | Frequent words swamped matches | Drop words found in over 20% of messages | LoCoMo-10 0.347 to 0.389, three runs a side, ranges apart | Kept |
| Recall what the assistant said (B471) | Assistant turns were not recalled | Index assistant turns | LongMemEval oracle 0.400 to 0.571 | Kept |
| DMR asked as the right speaker | Harness framing | Question framed from the right speaker | 0.500 to 0.620 | Kept (harness) |
| "Top 3 turns" answer replay (R26) | Answer picked from a near-duplicate turn | Replay with fewer turns | The variant measured the oldest 3, not the best 3 | Caught before use. Lesson: test a diagnostic on a fake with known order |

## 2. Answer-stage and ranking gates, 2026-10-10 to 2026-10-13 ([gates](2026-10-m1-m2-gates.md), [reranker](2026-10-m2-reranker.md))

Replays on kept stores (DMR 50, LoCoMo-10 conv-26 60), 26B judge with 3 votes.

| Trial | Why | What | Result | Decision |
|---|---|---|---|---|
| Rank order instead of oldest-first (#298) | Position of the gold turn | Order turns by rank | DMR 3/3, LoCoMo 3/1 | Merged off by default |
| Cite-or-abstain prompt (#299, B475) | Right turn in the bundle, answer from another | Instruction to cite a line or abstain | DMR 0.520 to 0.600 (5/1); LoCoMo 0.317 to 0.350; adversarial 0 to 3 of 12 | Merged. The only gain of the round |
| Cross-encoder reranker (#301) | Gold turn ranks 28th | Re-score the best 50 fused candidates | Recall at 6 turns 0.33 to 0.47; DMR 0.520 to 0.400 (2/8). Second form (bare text, blended): DMR 2/5, LoCoMo 2/6 | Closed. The speaker label misled the cross-encoder; better recall was not better answers |
| Near-duplicate collapse (#300) | R26's "near-duplicates" | Collapse similar same-speaker turns | Never fired: the highest same-speaker cosine was 0.69 | Removed; the premise was wrong |
| Turn number in each stamp; turn index as tiebreak (#300) | Ordering of same-time turns | Two variants | 0/3 and 1/5; 45 of 50 prompts changed | Closed. Lesson: presentation noise is about ±5 of 110 |
| Speaker and date boosts (#307) | Questions name speaker and date | Boost 0.5 and 1.0 | DMR 1/4 and 1/3; LoCoMo 3/5 | Closed |
| Select-then-answer (#310) | Answer selection | Two model steps | DMR 2/4, LoCoMo 5/8; re-tested later (R70), closed again | Closed |
| The 26B as the answer model (R40) | Is the reader the limit? | Same prompts, larger reader | DMR 0.600 to 0.592; LoCoMo 0.350 to 0.283; ignores the abstain instruction; 4 times slower | No |
| Larger dev sets and McNemar | Gates could not see 3-5 points | DMR 100-299; LoCoMo conv-42/43 (502 questions) | Power to see about 3 points | Adopted |
| Recall fixes (#312) | Low recall | Retrieval changes | DMR 34/28 but LoCoMo down on both conversations; pooled 70/97 | Closed. The keyword channel matters on LoCoMo |
| Conversation token budget (#313, B482) | Full history scored 0.825 on DMR with 3.4k tokens while Campy showed 6 turns | Show the whole history when it fits 3,500 tokens | DMR 0.531 to 0.633 (43/23); pooled 59/30 | Merged, on by default. Lesson: look at what the strongest baseline does differently |
| Budget "fill" mode (#315) | Extend the budget idea to large stores | Fill the budget by rank | 19/27; timeouts on LoCoMo | Closed |

## 3. Observations, scoring fix and the metric switch, 2026-10-18 to 2026-10-21 ([observations](2026-10-m3-observations.md), [scoring fix](2026-10-scoring-fix-and-round5.md), [metric switch](2026-10-metric-switch.md), [freeze](2026-10-20-freeze-and-drift-controls.md), [R61](2026-10-21-r61-longmemeval-s.md))

| Trial | Why | What | Result | Decision |
|---|---|---|---|---|
| Observations (#305) | Give the graph something worth retrieving | One model call per user turn extracts source-grounded facts; shown when the history does not fit | LoCoMo 65/39 over three conversations | Merged, then found to be an artefact (next row) |
| Adversarial scorer check (campy-benchmarks#41) | Abstention counts looked low | Compare the abstention pattern with Campy's own wording | Correct abstentions scored wrong since the cite prompt: recognised 97 of 445, then 301 of 445. Observations re-scored: 66/63 | Scorer fixed; Observations turned off (#320). Lesson: any change to answer wording needs a scorer check |
| First rule for when Observations show (R56) | Redundant when the whole history is shown | Rule in three row builders | Held-out replay byte-identical to main: the rule marked every conversation as full history | Fixed (R57). Lesson: "identical to main" is a signal to check |
| Observation dates (#316) | Relative dates in facts | Rule resolves "yesterday", "last Saturday" against the turn date | 18/14 overall; temporal 11/3 | Merged |
| One-hop observation expansion (#318) and its fix | Multi-hop | Expand from matched Observations | 46/48, fix 25/28; held-out 5/9; multi-hop never moved. Re-gated on top of Observations (R68): 5/5 and 0/1 | Closed twice |
| Read-time quality filter (#319) | Half of sampled Observations were low quality | Filter at read time | 8/23: tidier but less relevant | Closed. Lesson: precision of retrieved items is not answer quality |
| Metric switch (user decision, 2026-10-19) | The all-category gate read a real gain as noise | Gate on the published metric (LoCoMo categories 1-4), pooled, merge on net gain, no p threshold | Neighbours re-scored 52/18 | Adopted |
| Neighbour turns (#322, B487) | A gold turn's neighbours carry the answer | Add N turns either side of each kept turn | N=1: 0.374 to 0.467 (52/18). N=2 against N=1 over four conversations: 42/26 | Merged; default N=2 (#333) |
| Output cap (B494) | One question made the answer model run to the timeout and killed two gates | Cap output at 2,048 tokens and log the question | Replays complete | Merged |
| Observations on top of neighbours (R66) | Re-test under the new metric | Stores ingested with Observations on | 0.478 to 0.517 over four conversations (49/28, 4 of 4 up); adversarial 90 to 104 | Back on by default (#331) |
| Abstention verify step (#326, B489, R65) | Abstention with evidence present | A verify call before abstaining | Pooled 5/118 | Closed |
| LongMemEval s, fresh ingest (R61) | Position check at about 500 turns per question | 30 questions with baselines | First attempt froze the machine (two models and two daemons in memory). Rerun: 10 of 30 against naive RAG 12; recall 0.526 against 0.529. Ran in text mode, so every memory was stamped with the ingest date | Memory guard and judge-swap scripts; harness default changed to fields mode. The first reading ("answering throws evidence away") was wrong: 14 of 20 misses lacked evidence |
| Drift controls (B495) | Agents drift to paperwork and prompt tweaks | Principles in the file every agent reads; CI requires a score effect; drift report | Live | Kept |

## 4. Graph-structure foundation and the failure breakdown, 2026-10-21 to 2026-10-27

| Trial | Why | What | Result | Decision |
|---|---|---|---|---|
| Supersession by string keys (B499, R72) | Knowledge-update questions pick the old value | Supersede by attribute key | 0/0 on LongMemEval oracle | Invalid test: oracle histories fit the budget, so the Observation and graph stages are skipped. Lesson: check the gate exercises the lever |
| First-person statements ending in "?" (B501, R75) | Such user turns were filtered out | Keep them | LoCoMo pooled 22/10 (3 of 4 up); LongMemEval 10/2 | Merged; on by default from B514 |
| Gathered turns (B502, R77/R78) | Set-valued questions | Gather related turns | Oracle run identical to main (invalid); replay 17/40 | Closed (#346) |
| SHACL shapes, SKOS kinds, OWL properties, concept linking (B503-B509, #356; R95, R96, R93) | The graph had no enforced structure | Full stack behind flags | Full stack with the walk: 0.467 against main 0.525 (7/14); walk off: 0.517 (7/8); SHACL gate 1/1 | Merged flags-off, then on by default without the walk (B514). The 12-item walk section diluted answers |
| Walk v2 (B510, R97) | The walk's noise | A narrower walk | Result not kept in the notes | Not merged; replaced by the anchored walk (B560) |
| Attribute facts reach OWL properties (B511, R98) | 7.8% of attribute facts linked to a property | Structured attribute field and rule fallbacks | Linked 7.8% to 59.3%; accuracy 5/4 | Merged; neutral on score |
| Aggregate count in Python (B505 v2, R99) | Count questions | Count items of a kind | Identical to the baseline (0/0); fired on 1 of 4 count questions and counted every item of the kind, not the subject's | Closed. The user called it drift: an answer a query can compute is a query anchored on the subject. Principles P2 and P8 and the campy-graph skill follow from this |
| Ownership and count stack (B522-B525, R100/R102) | Count and list by a subject-anchored query | Roles on Observations, possession rule, graph count, kind hygiene | 0.317 against 0.317 (3/3); the count fired on 0 of 12 count questions | Not a gain; pieces merged later behind flags |
| Failure breakdown (2026-10-25) | Three weeks of levers chosen from anecdotes | 180 failed questions of 300 labelled by cause | Retrieval 106, answering 51 (20 date arithmetic, 19 abstained with evidence), key or scorer 13, presentation 10, capture 0 | Levers re-ranked. "Capture 0" was later shown wrong (section 5) |
| Reply pairing (B536) and seed variants (B537) | Top two re-ranked levers | Replay screens | 5/9; best seed variant net +2 | Both closed |
| Relative dates resolved at capture (B538, R104) | 20 temporal failures | A rule writes the resolved date inline | 0.450 to 0.503 on five unseen conversations (28/12, 5 of 5 up); temporal 36 to 50 of 84. The replay had predicted +3 | Merged, on by default. Lesson: a replay is a strict proxy; a lever with large reach still deserves a gate |
| Non-answer re-judge (B539) | The harness failed answers the judge never saw | Send non-answers to the judge | Applied to both arms | Kept (harness) |
| Typed objects, offline screen (B540) | Objects are text | Screen on a kept store | Closed with its screen; the cause was upstream (next row) | Closed |
| Capture root cause (2026-10-27) | Capture gaps kept appearing | Read what the early Loop gates drop | Two gates left from the original decision tracker dropped correctly recognised entities: places 1 of 22, organisations 0 of 16, titles 1 of 9 stored on one conversation | User: rebuild capture (B542: the model reads every turn with closed questions, a rule writes); the old tracker becomes a side branch that never gates storage (B543) |

## 5. The principled profile and its whole-pipeline gate, 2026-11-04 to 2026-11-09

| Trial | Why | What | Result | Decision |
|---|---|---|---|---|
| Profile switch and its members (B543-B549, B554, B559, B560) | User, 2026-11-05: judge the pipeline as a whole once it follows the principles, not lever by lever | `principled` profile: entity admission, typed objects, question analysed once, graph vote in fusion, entity standing by rule, Observation-to-entity links, subject-anchored walk | Built behind flags | Gated as a whole (next row) |
| Whole-profile gate (R106, R107, R110, R111; 2026-11-07) | The assembled pipeline against main | Fresh ingest of five unseen conversations, 300 questions | main 0.503; principled with the store-wide walk 0.427 (8/31); walk off 0.487 (7/12); anchored walk 0.447 (9/26). Recall rose in every arm (to 0.660); non-answers 19 to 43 and 33 | Not passed. The walk section is in nearly every loss |
| Walk turns merged into the conversation section (B563) | Is the walk's layout the cause? | Answer replay on the kept store | Separate 0.437; merged 0.447 and 0.440; walk off 0.480. 36 of 1,684 walk rows hold gold (2%) | Stopped, not built. The noise is the cause, not the layout |
| Member-by-member replay (2026-11-08) | Which member costs or earns | Each member off in turn, walk off | Baseline 0.480; vote off 0.483; analysis off 0.480; count off 0.480; main replayed 0.480 | Principled with the walk off ties main. Vote and analysis kept (recall up, non-answers down); the count is a no-op |
| The 26B as the reader (2026-11-09) | Is the reader the ceiling? | Same prompts, larger reader | 0.463 and 0.470; abstains on a third | Stopped |
| Accuracy by gold evidence in the bundle | Where the ceiling is | Bucket questions by evidence present | All evidence: about 0.75; some: 0.22; none: 0.14-0.23 | Recall of whole evidence is the ceiling |
| Zero-recall review (2026-11-09) | The 95 questions with no gold turn | Read each | About half are artefacts of the key or the recall measure; gold turns mostly share no word with the question | Fed the plan: count facts by their source turn; capture typed edges |
| Drift audit (user, 2026-11-10) | A month of flat score; work kept moving away from the graph | Audit of repo and chat | Causes: recall counted only turn text, so every diagnosis said "more text"; net-gain merging favours same-day text tweaks; conclusions flipped within three days | New plan (section 6); rules: name the edge before a proposal, pre-register every run, no conclusion until two measurements agree |

## 6. The 2026-11-10 plan: facts into the graph, then answer by query ([plan](e2e-improvement-plan.md), [status](e2e-status.md))

### 2026-11-10 Step 0: fix the test (PR 409)
- **Why:** 300 questions gave ±9 noise, and recall could not see an answer that came from a graph fact.
- **What:** all 809 category 1-4 questions of the five gate conversations replayed on the kept stores; recall also counts a fact in the prompt whose `EVIDENCED_BY` turn is gold.
- **Result:** main 0.514, principled (walk off) 0.517; graph-aware recall 0.748 both; the replay repeats exactly (300 of 300); noise ±14 questions. 240-266 prompts carried another conversation's turns.
- **Decision:** baseline adopted; the mixed-conversation fault fixed later as step 0c.

### 2026-11-10 Step 0b: fact contract (`docs/fact-contract.md`)
- **Why:** capture, query and prompt had no shared target.
- **What:** a fact is subject, relation, object, date and source turn; nine predicates kept; action, partner and place roles added; text objects allowed but flagged.
- **Decision:** approved by the user.

### 2026-11-11 Step 1, first form: roles as free spans in the fact prompt (PR 410)
- **Why:** 54% of facts are "did" or "has attribute" with the verb phrase in text and no structure.
- **What:** the extraction prompt asked for action, partner and place spans; conv-26 re-captured.
- **Result:** anchored 47.3% and shared 34.2%, both under their kill lines; only 168 of 389 facts matched the flag-off capture.
- **Decision:** killed. **Lesson:** changing the fact prompt changes the facts; later forms leave it untouched.

### 2026-11-12 Plan revised
- **Why:** the step-1 lines had to be re-derived twice, and a share of facts can rise while no question becomes answerable; a review of a similar project said the same.
- **What:** steps 0c, 0d, 0e and Q added before step 1 continues; steps 1 and 2 judged by query hits; every result gets a ruling.

### 2026-11-12 Step 0d: always-missed questions ([note](step0d-always-missed.md))
- **Why:** doubt the answer key before the pipeline (P6).
- **What:** questions wrong in all 16 replay arms, each read with its gold turns.
- **Result:** 337 always missed: 303 real misses, 29 with the key or label wrong, 5 whose answer is not in the conversation; 24 more possible judge errors.
- **Decision:** the 34 test-fault ids are reported next to every later score; the denominator stays 809.

### 2026-11-13 Step 0c: one store per conversation
- **Why:** the replay mixed conversations; the live gate never does.
- **What:** each conversation captured into its own store for both profiles and replayed there.
- **Result:** foreign-turn prompts 0 of 809; principled 432 (0.534), main 426 (0.527); +14 and +10 against the shared store, inside noise.
- **Decision:** kept (user, 2026-11-14): these stores are the replay baseline.

### 2026-11-13 Step Q: query hits (PR 418)
- **Why:** a measure with no noise and no GPU for what capture lets a query answer.
- **What:** a subject-anchored query over `HAS_SUBJECT`, `HAS_OBJECT`, `INSTANCE_OF`, `BROADER`, `EVIDENCED_BY`; a hit is at most 25 facts with a gold turn among them. Writes nothing.
- **Result:** 111 of 809 (13.7%); subject resolved on 801. Misses by first missing edge: object is text 291, question names no object Concept 117, object not reached 113, no subject edge 90, no fact on a gold turn 79.
- **Decision:** kept as the measure for steps 1 and 2. The 111 hit questions were answered only 59% against 53% elsewhere, so hits alone barely move the score.

### 2026-11-13 Closed-class words are never Concepts (B565, PR 422)
- **Why:** pronouns were stored as Concepts and matched as objects.
- **Result:** 31 pronoun Concepts archived; hits 111 unchanged; miss table restated (object is text 216; names no object Concept 224; not reached 81).
- **Decision:** kept.

### 2026-11-13 Capture-recall diagnosis (rerun62)
- **Why:** 79 questions have no fact on a gold turn.
- **What:** the extractor re-run on 57 such gold turns and 60 control turns.
- **Result:** proposed nothing 47% (control 68%); all proposals rejected by a rule 40%; reply malformed 12%. 12 of the 27 "nothing" turns are about "we" or third persons, which the prompt leaves out.
- **Decision:** two fixes below; the "we" question went to the user.

### 2026-11-13 Predicate normalisation (B567) and cut-reply salvage (B568)
- **Why:** "prefer" for "prefers" was rejected on 3 gold turns; 8 of 9 malformed replies were cut at the output limit with 7-8 complete facts before the cut.
- **Result:** B567: facts on 2 gold turns; hits 111 to 111; "no fact on a gold turn" 79 to 76. B568: facts on 4 of 6 cut gold turns; hits 111; 76 to 69.
- **Decision:** both merged; inside their predictions; no hit gain.

### 2026-11-13 "you" facts anchored on the other speaker (probe)
- **Why:** 90 questions lack the subject edge.
- **Result:** 55 facts rewired; hits 111, none gained; 12 of 20 are compliments or questions, not facts.
- **Decision:** closed.

### 2026-11-13 Step 1, second form: roles by closed choice in a separate call (PR 411)
- **Why:** keep the fact prompt untouched.
- **What:** per fact, the model picks an action sense (WordNet, with `BROADER`), partner and place from numbered options; writes `HAS_ACTION`, `HAS_PARTICIPANT`, `HAS_PLACE`.
- **Result:** conv-26 hits 14 to 21 (+7 net; pass); facts 389 of 389; **16 of 50 senses wrong (kill)**. None of the 8 gains needed the sense: each matched the action Concept's own label.
- **Decision:** stopped; options A, B, C to the user, who chose B (a word-level action kind).

### 2026-11-13 Step 2: kinds and places (pre-build check)
- **Why:** 77 misses fall in step 2's own rules.
- **What:** before building, checked whether each rule's trigger occurs in the target questions' gold turns.
- **Result:** estimated +4 to +13 hits against a kill line of +10 and a pass line of +31.
- **Decision:** stopped before build; folded into step 1 where it is the same construction. **Lesson:** a cheap reach check before the build saved a build.

### 2026-11-14 Step 3: graph facts in the prompt (PR 428, step3g)
- **Why:** hits do not help unless the rows reach the answer model. The user ruled step 3 first, on the 111 hits.
- **What:** the query's rows rendered as a prompt section, flag `CAMPY_GRAPH_FACTS`; replay of the 809.
- **Lines:** pass = 100 or more fire and firing accuracy beats main by 8; kill = under 30 fire or firing accuracy at or below main.
- **Result:** fired on 413, not the predicted 100-115 (the section fires on any subject with a named object Concept; hits are a subset). On the 413: 204 against main 216. With a gold row (111): 75 against 62 (+13). Without (302): 129 against 154 (-25), mostly new non-answers. Overall 418 against 432 and 426.
- **Decision:** kill line hit; flag off. User: no new fire rule; re-measure as built after the capture work.
- **Lesson:** a gold row in the section helps; rows without the answer cost twice as much as the others gain.

### 2026-11-14 Step 1, option B: action word by rule (run s1onB)
- **What:** the rule picks the action word from the fact's own text (head, or its nominalisation); no sense, no `BROADER`.
- **Result:** hits 14 to 27 (+13); facts identical; **17 of 50 action words wrong (kill)**: phrasal verbs cut to the head, light or aspectual verbs kept for the activity, a noun chosen.
- **Decision:** stopped. User: one last form (form 3); if its word line is hit the action role is dropped.

### 2026-11-14 Step 1, form 3: candidate words by rule, closed choice with "none" (run s1onF3)
- **Result:** hits 14 to 28 (+14, none lost); facts identical; 10 of 50 words wrong (at the line).
- **Decision:** pass at the edge; the line not moved. The choice barely filters: "none" on 3 of 109 facts.

### 2026-11-14 Partner hand-check (not pre-registered)
- **Why:** partner links fell from 138 to 100 between forms, with no change meant to cause it.
- **Result:** 29 of 30 partner links are not a co-participant by the quote; 73 of 100 name one of the two speakers. Only 4 of 170 event quotes on conv-26 name a co-participant at all.
- **Decision:** user, 2026-11-15: the model-chosen partner is dropped; co-participant edges by rule only.
- **Lesson:** the counts had passed three times. A role is hand-checked from now on, with wrong-rates over edges actually written.

### 2026-11-14 Who a fact may be about, by prompt change (PR 432, `group_subjects`)
- **Why:** 12 of 27 no-proposal gold turns are about "we" or people named by relation.
- **What:** two sentences of the extraction prompt replaced; the extractor re-run three times (off, on, off).
- **Result:** gold turns gaining a fact 11 of 57 (as predicted), but 36 of 40 fact-bearing turns lost a fact; 58 of 76 stable facts lost. Re-run alone, the model replies with nothing under the new wording.
- **Decision:** kill line hit; flag off. **Lesson:** a wording effect, not the rule; the prompt is not touched again before step 4.

### 2026-11-15 "We" facts anchored by rule (PR 441, `group_anchor`)
- **Why:** get the "we" facts without touching the prompt.
- **What:** on facts the model already proposes with a "we" subject, a rule writes `HAS_SUBJECT` to the `SPOKEN_BY` speaker, marks `group_subject`, and writes `HAS_PARTICIPANT` only to a person who is X in "X and I" or the object of "with".
- **Result (offline, before build):** "we" part 56 facts, 5 hits, 3 of 18 wrong; relation part ("my ...") 6 of 12 wrong, left out. Partner by "any person named in the quote" 4 of 6 wrong, so narrowed.
- **Decision:** built behind the flag (off).

### 2026-11-15 Confirming capture after the partner line was removed (s1onF3np)
- **Why:** removing the partner from the call might shift the action picks.
- **Result:** hits 26 (line: within 2 of 26); facts 389 of 389; no wrong word changed; 10 of the 47 written words wrong.
- **Decision:** prerequisite met as pre-registered; not counted as evidence the words are under 20% wrong.

### 2026-11-16 Full re-capture, five conversations, flags on against off
- **Why:** conv-26 is one conversation of five; the role lines needed 100 words and all 809 questions.
- **What:** ten captures (`roles` and `group_anchor` on, and both off), step Q on each, hand-checks, and a replay of the 809.
- **Result:** hits 190 against 119 (+73 gained, 2 lost); facts 6 of 2,731 missing; **action words 21 of 100 wrong (line: 20)**; places 4 of 30 wrong by the turn (14 by the quote alone); "we" facts 6 of 30 wrong; rule-written partner links 61, 4 of 30 wrong; replay 434 against 436. The action role carries 61 of the 73 gains; without it +16.
- **Decision:** hits, facts, "we", partner and replay pass. Action word and place wording held for the user (ruled below).
- **Lesson:** +71 hits did not move the replay (434 against 436): hits are not answers until the rows reach the prompt.

### 2026-11-16 Question words resolved by vector, offline (vecq-1, vecq-2, vecq-3)
- **Why:** the user asked why matching is by exact label when vectors are captured. 216 misses are "object is text".
- **What:** reading A: question terms against entity label vectors. Reading B: question terms against the object text of the subject's own facts, embedded in memory. Thresholds 0.65, 0.75, 0.85 fixed in advance; 50 matches hand-checked per reading. A lemma match with no vectors as the control. Nothing written to any store.
- **Result:**
  - A: +17 net at 0.65 with 20 of 50 wrong; +10 at 0.75 with 18 of 50 wrong. Killed.
  - B: 0.65 +151 with 11 of 50 wrong; **0.75 +116 net, 1 lost, 5 of 50 wrong**; 0.85 +81, 1 of 50 wrong. Passes at 0.75 and 0.85.
  - Lemma control: +161, 5 lost, 11 of 50 wrong, 6.8 rows per new hit against 4.6. Killed on its wrong-rate line.
  - Of the action role's 61 gains, 57 are reached with no action read. Flags off plus B at 0.75: 275 hits against 119; flags on without the action read: 285; with it: 306.
- **Decision (user, 2026-11-16):** see the next entry.
- **Lesson:** entity labels are too short to match by meaning; the object phrase of a fact carries the meaning. The vectors buy precision, not reach.

### 2026-11-16 Rulings on the re-capture and the vector measurement (user)
- **Action word:** dropped, as ruled on 2026-11-14. It hit its line, costs a model call per turn, and object-text matching reaches 57 of its 61 gains. The `roles` flag stays off; no code deleted yet.
- **Place:** judged by the whole turn (4 of 30 wrong); the place role is kept.
- **Object-text matching at 0.75:** build it as the next step, behind a flag, design first; then re-measure step 3 on top of it.
- **Open caveat:** the match reads a fact's text at question time. It does not turn that text into a graph entity, so capture still leaves most objects unlinked.

### 2026-11-16 Reference numbers for the object-text build (vecq-4)
- **Why:** the build must reproduce a number fixed before it is written, so its first run can only show it right or wrong.
- **What:** offline on the recap store copies, CPU only, nothing written. Exact object Concepts plus object-text matches at 0.75 (top 3 per term, vecq-1's term filter), with no role reads, since the `graph_facts` section reads none. Also counted: which questions the section would fire on (subject resolved, 1 to 25 distinct facts) and whether a gold turn is among the rows.
- **Lines:** no lever line. The script is wrong if the flags-off stores do not give vecq-3's 275.
- **Result:**
  - Flags-off stores: exact 119, with object text 275 (reproduced).
  - Flags-on stores: exact 123, with object text 279.
  - Firings 415 to 631: 156 more with a gold row, 60 more without one; 4.15 rows per firing.
  - Embedding: 11,553 distinct texts in 5.8 s on CPU; at most 289 per subject.
- **Decision (review session, 2026-11-16):** design approved; the build's line (OT-1) is 279 ± 3 and 275 ± 3.
- **Lesson:** applying step 3's per-group rates to these counts projects about +25 from the gold-row firings and about -28 from the no-gold firings. More hits can still net zero answers while the section fires without a gold row.

### 2026-11-16 Object-text matching built, run OT-1 (branch `claude/object-text-match`, flag `object_text_match`)
- **Why:** reading B at 0.75 passed offline, and the user ruled to build it before step 3 is re-measured.
- **What:**
  - **The match:** at question time, each question word that is not a Concept label is matched by vector against the distinct object text of the subject's own live facts. Up to 3 texts per word at cosine 0.75 or above are kept; both numbers are constants.
  - **The read:** the four `query_hits.facts*` queries take the matched texts as a second branch beside the exact-label objects. Count, latest and exists are computed over both together, and nothing is written.
  - **Edges read:** `HAS_SUBJECT` (or the subject literal), the fact's object text, `HAS_OBJECT`, `INSTANCE_OF`, `BROADER` and `EVIDENCED_BY`.
  - **Scope:** the flag is off, in no profile, and acts only inside the `graph_facts` section.
  - **The run:** measured with step Q's script on fresh copies of the re-capture stores.
- **Lines:**
  - 279 ± 3 and 275 ± 3, with at most 5 ids differing from vecq-4;
  - flag off unchanged (123 and 119);
  - at most 10 of 50 sampled new matches wrong (seed 20261127, drawn before the hits).
- **Result:**
  - 279 and 275, with 0 ids different on either arm;
  - flag off 123 and 119;
  - 1,862 new-candidate matches, of which 3 of 50 sampled are wrong (3 to 5 on the borderline calls): a boot camp read as a camping trip, an LGBTQ conference as LGBTQ rights, and a guitar style as "individual styles".
- **Decision:** passed; merged with the flag off. Step 3 with object text (S3-OT) runs next, then step 3 as built (S3-asbuilt).

### 2026-11-16 Step 3 re-measured with object-text matching (S3-OT)
- **Why:** the user ruled to build object-text matching at 0.75 and then re-measure step 3 on top of it. OT-1 had shown the build lifts gold-row firings from 123 to 279.
- **What:**
  - **Replay:** all 809 questions on copies of the five recapture flags-on stores, from main b82ded76.
  - **Flags:** `graph_facts` and `object_text_match` on; walk off; linking limit 0.
  - **Graph reads:** the section reads `HAS_SUBJECT`/`subject_id`, `HAS_OBJECT` and `object_text`, and `EVIDENCED_BY` → Message. Nothing is written.
  - **Judging:** the same judge, 3 votes and the same cache.
  - **Baseline:** the stored replay with both flags off (434).
  - **Firing groups:** from the section's own code path, run offline on the same copies.
- **Lines (pre-registered):**
  - PASS: net at least +15, and the fired-no-gold-row group loses at most 10 net.
  - KILL: net 0 or less, or the no-gold group loses more than 24.
  - Prediction: net -10 to +15.
- **Result:**
  - **Overall:** 414 vs 434, **net -20** (+41 / -61); -17 without the 34 test faults. Non-answers 44 against 48.
  - **Fired with a gold row:** 279, +9 (32 / 23).
  - **Fired with no gold row:** 361, **-29** (9 / 38).
  - **Not fired:** 169, 0.
  - **By source** (gold-row group / no-gold group):
    - exact labels only: +2 on 47 / -7 on 106;
    - exact labels plus matched text: +5 on 139 / -15 on 130;
    - matched text only: +2 on 93 / -7 on 125.
  - **By category:** 1: -1, 2: +4, 3: -2, 4: -21.
  - **Size:** 8.1 lines (4.16 facts) per firing.
- **Breakdown of the stored records** (no new run; a gold turn is "in the prompt" when the first 60 normalised characters of its text are in the conversation section):
  - **Ceiling:** gold-row questions score 177 of 279 against 168 without the section. A rule that fired only on gold rows, which no rule can know, would gain at most +9, under the +15 line. The fire rule is not the whole story: where the section is right, it adds little.
  - **Gold turn already in view:** 249 of the 279 gold-row questions had a gold turn in the conversation section already (rcon right 160 of 168, rcon wrong 89 of 111). The section mostly repeats what retrieval had supplied.
  - **The 102 gold-row questions still wrong:**
    - the gold shows as a turn and as a fact row in 84, as a fact row only in 18;
    - 11 are non-answers;
    - 27 are date questions and 5 arithmetic;
    - 10 are test faults and 6 judge doubts.
  - **What the lost answers became** (non-answer / quotes a section row / neither):
    - gold-row losses: 3 / 3 / 17;
    - no-gold losses: 3 / 7 / 28.
  - **No-gold firings:** a gold turn was elsewhere in the prompt in 254 of 361, and absent in 104.
- **Coverage of the conversation section, rcon on all 809:**
  - **Accuracy by bucket:** every gold turn present 0.71 (524); some 0.15 (94); none 0.24 (187); no gold text 4.
  - **Without the test faults:** 0.73, 0.16 and 0.25.
  - **Without every gold turn:** 0.21 (59 of 281). Category 1 has every gold turn in view on only 32 of 153.
  - **Caution:** the buckets are not randomly assigned. Questions whose gold turns are all retrieved may be easier ones.
- **Ruling (review session, 2026-11-16):** kill on both lines, accepted. The flag stays off. No fire rule or cap change is tried; held for the user.
- **Lesson:** more query hits did not become answers. Even with the gold among its rows, the section mostly repeats turns the reader already had, and when it fires without the gold it costs answers.

### 2026-11-16 Step 3 re-measured as built (S3-asbuilt, the control)
- **Why:** to separate the section's own effect from object-text matching's. Step 3 "re-measured as built after the re-capture" was an open item of the 2026-11-14 ruling.
- **What:** the same replay as S3-OT (same stores, commit, judge and baseline) with `object_text_match` off.
- **Lines (pre-registered):** KILL at net 0 or less. Prediction: -15 to 0.
- **Result:**
  - **Overall:** 423 vs 434, **net -11** (+26 / -37); -10 without the test faults. Non-answers 43.
  - **Fired with a gold row:** 123, +13.
  - **Fired with no gold row:** 299, -24.
  - **Not fired:** 387, 0.
  - **By category:** 1: 0, 2: +3, 3: -2, 4: -12.
  - **Paired against S3-OT:** +42 / -33, net +9 for as built.
- **Ruling:** kill as predicted; held for the user with S3-OT.
- **Lesson:** matching made the section fire more often (gold-row firings 123 to 279, no-gold firings 299 to 361) without raising its net where it holds the gold (+13 to +9). The gold-only ceiling is under +15 in both forms.

### 2026-11-16 Baselines on the 809, first attempt (stopped twice by the memory guard at judging)
- **Why:** a reference for the 809, approved by the review session as a measurement with no pass or kill line. The last baselines were on 44-60 questions in October. Full history is the arm the next direction will be read against.
- **What ran:**
  - **Harness and runs:** the evaluation harness (`baselines.py` via `run_all.py --baselines-only`), one run per conversation, categories 1-4.
  - **Settings:** pinned to the replay tree's config, so the answer model and the small embedder come from it, never the personal config.
  - **Answering:** native chat endpoint at temperature 0, with the context sized per prompt.
  - **Judging:** the replays' judge, 3 votes and cache (`judge_arm.py`), after a converter that checks the ids against the 809.
  - **Order:** no memory, naive retrieval (k=5), a 5-question timing probe, then full history. These ran as queue jobs under the memory guard.
  - **Graph:** no graph read or written.
- **Stop 1 (job 1000, 17:29):**
  - All five no-memory runs finished: 809 answers, about 2 s each, with no context overflow.
  - The guard stopped the job one minute into judging (free 11% for 3 checks).
  - **Cause:** the personal daemon was up. It reloaded the answer model at its own larger context while the judge loaded, so both were resident.
  - The same contention slowed the last conversation (21 min against about 5) and timed out one call, conv-50_q114. The harness scores it wrong; it was not re-run.
  - **The trap:** the judging script unloads the answer model once, at its start, and that does not hold while another client can reload it. The S3 replays' judging used the same script with the daemon up, and only timing kept it clear.
- **Stop 2 (job 1001, 17:56):**
  - **Set-up:** the daemon was stopped for the whole job, the answer model unloaded before judging, and the job resumed from the stored answers.
  - **What happened:** the judge alone (17.4 GB resident) took free memory from 84% to 20%, 15%, 12% and then 11%, with swap rising from 2.5 to 4.5 GB. The guard stopped the job again three minutes into judging.
  - **Cause:** no contention this time. The judge by itself now sits at the guard's line on this machine, with the user's other apps open. From 11-04 to 11-10 the judge sat at 13-14% free on most samples.
- **The guard was not running from 11-10 07:49 to 11-16 16:44.**
  - The machine rebooted at 11-10 07:50, and neither the guard nor the queue runner starts by itself.
  - So the recapture, vecq, S3-OT and S3-asbuilt judging ran unguarded, probably at the same memory level.
  - Both are running again since 11-16 16:44, as background processes that a reboot will end.
- **Stored:**
  - the five raw no-memory files;
  - the five converted answer files (`step0c/out/bl_no_memory_conv-*.answers.json`), with one timed-out question;
  - no verdicts.
- **Ruling (review session, 2026-11-16):** held for the user. The user chooses between freeing memory (closing apps) and a lower guard line for judging phases only. No retry, threshold change, smaller judge, other quantisation or other judging model until they answer.
- **Lesson:** a GPU job's memory budget includes every other client of the model server. Unloading at the start of a phase does not hold while another client can reload the model. The guard must be restarted after a reboot.

### 2026-11-16 (night) Rulings on step 3 and the baselines' memory (user)
- **Why:** both step 3 re-measurements hit their kill lines, and the baselines were stopped twice by the memory guard at judging.
- **Decision (user, on the review session's recommendations):**
  - The step 3 kill is accepted. Graph facts stay out of the prompt; `graph_facts` and `object_text_match` stay off. No new lever starts until the baselines are in.
  - The guard's 12% line is kept. No app is closed; the baselines job is requeued as it is, and a third guard stop comes back to the user.
- **Plan:** revised the same night ("Revision, 2026-11-16 (night)"): step 4 waits, and the next direction is the user's once the baselines are reported.
- **Lesson:** three measurements of the same section (418, 423, 414 against 426 to 434) agree. Putting the right fact in front of the 8B answer model adds little when the source turn is already in view, and a section without the answer costs answers.

### 2026-11-16 Baselines judging, third memory-guard stop (job 1001 requeued as it was)
- **Why:** the user chose to requeue the job unchanged: no app closed, guard line at 12%.
- **What:**
  - Job 1001, unchanged: the personal daemon was stopped for the whole job, the answer model unloaded before judging, and the job resumed from the stored no-memory answers.
  - The guard and the runner were both confirmed running first.
- **Result:**
  - 82% free at the start, at 21:24.
  - The judge alone settled at **12%** (four samples from 21:25 to 21:26), then **11%** (three samples).
  - Swap went from 1.4 GB to 4.1 GB in those three minutes and was still rising.
  - The guard stopped the job at 21:28.
  - Nothing new is stored: no verdicts for any arm, and naive retrieval and the probe never started. The five no-memory answer files remain.
- **Ruling:** no retry; back to the user (closing apps, or a lower line for judging phases only).
- **Lesson:** with today's apps open, the judge by itself sits at or below the 12% line on this 32 GB machine. Removing the other model clients does not change that.

### 2026-11-16 Baselines judging, fourth attempt under a lower guard line (job 1001, started 22:21)
- **Why:** the judge alone sits at 11-12% free on this machine, at the guard's 12% line, and stopped the job three times. The user chose "Lower line for judging" over closing apps.
- **What:**
  - **Guard:** 12% free at all times except while a judging phase holds a flag file, when the line is 8%. The user gave no number; 8% is the plan lead's choice, three to four points under the judge's steady state.
  - **Second guard:** added at the review session's request after swap was seen climbing: the job stops if swap stays above 30 GB for three checks (the highest ever logged before was 26.8 GB). It only adds a stop.
  - **Job:** unchanged otherwise. The personal daemon is stopped for the whole job; the answer model is unloaded before judging and the judge after; it resumes from the stored no-memory answers, then naive retrieval, the timing probe, and full history if the probe projects under 40 hours.
- **Result so far (first hour):** free memory 11-16%; swap rose from 2.1 GB to 13.9 GB in twelve minutes, then held in a band of 12-16 GB; neither guard fired. Judging is about half its usual speed (one conversation in about 55 minutes against about 25). The baselines' numbers are entered when the job ends.
- **No-memory judging, full curve (22:21 to 00:39, 270 samples):**
  - Free memory held at 11-14% (11%: 26 samples, 12%: 95, 13%: 107, 14%: 25).
  - Swap went from 2.7 GB at the start to a peak of 16.7 GB at 23:26, then down to 2.4 GB at the end.
  - Neither guard fired, and the 30 GB ceiling was never approached.
  - Judging took 22-36 min per conversation, 2 h 17 min in all.
- **No-memory result:** 2.6% on the 809 (21), -51.0 points against the 53.6% control; a reference, with no line. The prediction was 2-6%. Non-answers: 36. One question timed out during the first attempt's answering and is scored wrong; it was not re-run.
- **Lesson:** a free-memory line alone does not see memory pressure. The system held free memory at 12% by swapping, so the pressure showed only in swap; a guard needs both.


### 2026-11-17 Why answers are wrong with every gold turn in view (offline classification)
- **Why:** the user asked why questions with every source turn in the prompt are still answered wrong, and whether the evidence is presented badly.
- **What:**
  - **Data:** the stored records of the control run (re-captured stores, capture flags on, 53.6% on the 809). Its conversation section holds every gold turn on 524 questions. Of these, 152 are wrong, which is 18.8 points of the 809.
  - **Reading:** each of the 152 was read by hand (question, key, answer, gold turns with their preceding turn, Observation lines) and given one label. Test-fault and judge-doubt ids are class 1. An answer opening with an abstention is class 2. Both rules are checked in code.
  - **Graph:** nothing read or written, and no GPU.
  - **Lines:** none; a description, not a lever.
- **Result** (share of 152, points of the 809):

  | Class | Share of 152 | Points of 809 |
  |---|---|---|
  | Abstained with the evidence in view | 44% | **8.3** |
  | Test fault or judge doubt | 18% | 3.5 |
  | Answered from another turn or line | 14% | 2.6 |
  | Partial list | 10% | 1.9 |
  | Other | 7% | 1.2 |
  | Date reading wrong | 5% | 1.0 |
  | Needs inference | 2% | 0.4 |
  | Neighbouring turn not in view | 0% | 0.0 |

  - Of the abstentions, 25 state the key after abstaining (3.1 points).
  - "Other" includes 4 where the key is only in the gold turn's image caption (7 in all classes) and 3 answers that give the key but are judged wrong.
  - Neighbouring turn: 32 of the 152 lack the gold turn's preceding turn, but none was judged to turn on it.
- **Presentation:** gold position (median 11 of 24), prompt length (about 2,100 tokens) and an Observation line for the gold fact (42% wrong against 40% right) are the same for the 152 wrong and the 372 right.
- **Ruling:** none. It informs the user's choice of direction after the baselines. Report: `~/campy-lead/reports/2026-11-17-all-in-view-wrong.md`; labels: `scratch/allin/labels.txt`.
- **Lesson:** with every gold turn in view, the largest loss is the reader declining to answer (8.3 points), not where or how the evidence is placed. The coverage buckets are not random, so these questions may differ from the others in difficulty.

### 2026-11-17 Scorer and prompt check on the abstentions (stored records only)
- **Why:** the classification found 67 abstentions with every gold turn in view (8.3 points of the 809). 25 of them abstain and then state the key (3.1 points). The user asked whether this is the scorer (P6) or the prompt.
- **What:**
  - The scoring path of the 25: the harness's pure-abstention filter, or the judge's votes from the cache.
  - The same pattern counted in five arms: an answer that opens with an abstention but is not a pure abstention.
  - The answer prompt's abstain instruction and its git history.
  - Two rule counts over the 67: no shared content word, and a date needed from a relative phrase.
  - No graph read or written, no GPU, no lines (a description).
- **Result:**
  - **The 25:**
    - 1 failed by the filter: its date sat inside a second abstention clause, which the filter reads as the abstention's topic.
    - 17 failed by the judge with both votes WRONG.
    - 7 failed by the judge on a 1-1 split, with the third vote WRONG.
    - The judge's prompt says an answer that "says the information is unavailable" is WRONG, so it follows its own written rule.
    - By reading, 20 of the 25 state the full key (2.5 points). By rule (every key word present), 15.
  - **The pattern in every arm:**

    | Arm | Accuracy | Pattern | Judged right | Wrong but with every key word |
    |---|---|---|---|---|
    | Step-0 replay, `main` (shared store) | 51.4% | 126 | 2 | 27 (3.3 pts) |
    | Step-0 replay, `principled` (shared store) | 51.7% | 135 | 2 | 30 (3.7 pts) |
    | Control (re-captured, flags on) | 53.6% | 117 | 1 | 25 (3.1 pts) |
    | Graph facts as built | 52.3% | 129 | 1 | 27 (3.3 pts) |
    | Graph facts with object text | 51.2% | 128 | 3 | 28 (3.5 pts) |

  - **The instruction's history:**
    - The answer prompt's "cite" instruction (answer only from the lines, quote one, otherwise say the information is not there) was added on 2026-10-10 (B475, PR 299). It made the reader abstain on the adversarial category 5, which the 809 does not include.
    - The system prompt's "say so explicitly" line dates from 2026-06-14.
  - **The 67:**
    - 5 share no content word with any gold turn (0.6 points).
    - 27 need a date from a relative phrase (3.3 points; 25 are category 2). **24 of those 27 already showed the gold turn with the phrase resolved inline.**
- **Ruling (review session, 2026-11-17):** accepted. No scorer change and no prompt change; both are the user's call and have been taken to them.
- **Lesson:** about 3 points in every arm are answers the judge fails for opening with an abstention while giving the key. The level is shared, so no comparison between arms changes. And a resolved date shown inline does not stop the reader from abstaining.

### 2026-11-17 Reading the results with the user: rulings, and why the triples are still thin
- **Why:** the user asked why questions with all their evidence in view still fail, proposed giving the answer model plain sentences built from the graph's facts, and asked what became of the capture work that was meant to enrich the triples.
- **What was established (all on the 809, control 53.6%):**
  - Evidence in view: on 64.8% of questions every source turn is in the prompt (71.0% correct); on the other 34.7% accuracy is 21.0%. Wrong answers with all evidence in view cost 18.8 points; wrong answers with evidence missing cost 27.4.
  - Of the 18.8 points, 8.3 are the reader declining to answer with the evidence in view. The instruction that tells it to decline was added on 2026-10-10 for the adversarial category, which is outside the 809.
  - In every arm about 3 points are answers that decline and then state the key; the judge fails them by its written rule. The arms differ by at most 0.6 points on this.
  - A resolved date printed next to the turn did not stop the declining (24 of 27 relative-date cases already had it).
  - Position, prompt length and an existing fact line did not separate right answers from wrong ones.
- **Why the triples are still thin (what happened to the capture work):**
  - **Built and on main (flags, mostly in the `principled` profile):** every named entity of a user turn becomes a Concept (B544), the object of a fact can be a typed entity (B546), an entity's standing is decided by rule (B549), a fact is linked to the entities its evidence names (B554), the speaker edge (B560), the dependency-parse rules of step 1 (place, the "X and I" partner, the "we" anchor). These fixed what they aimed at: named entities are no longer dropped (the 2026-10-27 root cause).
  - **Not built:** the rebuilt capture lane (B542: the model answers closed questions per turn, choosing the relation from a vocabulary and the object as an exact span with a kind). Its card is still open at the design phase. The 2026-11-10 fact contract kept the nine predicates and added roles instead.
  - **Tried and dropped:** every model-chosen role (senses 32% wrong, action words 21-34%, partner 29 of 30).
  - **So today:** a fact is a subject, one of nine predicates (two of them, "did" and "has attribute", hold over half the facts) and an object that is usually a free-text phrase, because what people say they did is mostly not a named entity. Only 32 of the 152 all-evidence failures have a matching fact by exact label.
- **Rulings (user, 2026-11-17):**
  1. Fact sentences built by rule from the graph, with no model call, attached to their source turn: approved by the review session to build behind a flag; run after the baselines. Prediction -0.5 to +1.5 points.
  2. A second score is reported beside the strict one: the same judging with an opening refusal ignored (a pure refusal still fails). The strict score stays the headline; the second is applied to every arm.
  3. A changed abstain instruction is tested as one pre-registered replay after the baselines, measured on the 809 and on the adversarial questions together.
- **Lesson:** "the evidence is there and the answer is wrong" had three different causes under it (declining, a strict scorer, and real misreadings), and none of them was where the evidence sat in the prompt. Classify the failures by reading them before choosing a lever.

### 2026-11-17 Three designs approved and the run order (before any of them runs)
- **Why:** the user ruled yes to a second score and to testing the abstain instruction, liked fact sentences built by rule, and ruled that the short runs go before the long full-history baseline.
- **Fact sentences (design approved to build):**
  - **What:** the subject's matching facts are rendered as plain sentences by one fixed template per predicate and polarity, with no model call. "I", "my" and "we" become the person's name; a resolved date replaces a relative phrase; place and partner are added when their edges exist; facts of one kind across turns become one list sentence (at most 6 items). Each sentence is a line right after its source turn. Exact labels only; object-text matching stays off.
  - **Edges:** reads `HAS_SUBJECT`, the predicate, `HAS_OBJECT` or the object text, polarity, the time phrase and its resolved date, `EVIDENCED_BY`, `HAS_PLACE`, the rule-written partner, `group_subject`. Writes nothing.
  - **Lines:** a faithfulness check of 50 sentences before any GPU (at most 5 wrong); pass above +1.9 points on the 809 with the group fired without a gold fact losing at most 1.0 point; kill at 0 or below, or that group losing more than 2.0. Prediction -0.5 to +1.5: only 32 of the 152 all-evidence failures have a matching fact.
  - **Known overlap:** about 40% of prompts already carry a model-written fact line for the gold fact, with no effect on outcome. The sentence is still added; the report splits duplicate against new.
- **Second score (design approved):** only answers the strict pass failed and that open with a refusal are re-judged on the text after the refusal, by fixed rules in the harness that its self-test holds. A pure refusal still fails. It must first agree with 25 hand-read answers (at least 18 of 20, at most 1 of 5). The strict score stays the headline and decides every line.
- **Abstain instruction (design approved):** one changed wording, written once: if a line answers the question, even when a date must be worked out, give the answer; only otherwise say the information is missing. Measured on the 809 and on the 222 adversarial questions, each against its own control. Pass above +1.9 points with correct refusals falling by at most 5 points; kill at 0 or below, or a fall of more than 10. Prediction +0.5 to +2.5. Closed if it fails. Caution: the wording was written after reading the 809's failures.
- **Order (user):** the running baselines job, then the second score, fact sentences and the abstain replay as each is ready, then full history.
- **Lesson:** none yet; results are entered as each run ends.


### 2026-11-17 Fact sentences built by rule; FS-0; faithfulness check (stopped)
- **Why:** the user asked for the subject's facts to be rendered by rule as plain sentences, next to the turn the reader already reads (placement A, exact-label objects only). It was approved by the review session on 2026-11-17 behind `[retrieval] fact_sentences` (default off, in no profile).
- **What:**
  - **Build:** branch `claude/fact-sentences` (pushed, not merged).
    - One grouped NamedQuery, `fact_sentences.rows`, reads HAS_SUBJECT/subject_id, the predicate, HAS_OBJECT (label and kind) or object_text, polarity, time and its resolved date, EVIDENCED_BY → Message, HAS_PLACE, the rule-written partner and group_subject. It writes nothing.
    - The query computes the join to the shown turns, the lists, the 6-item cap and the over-cap exclusion.
    - Python fills a fixed template per predicate and polarity, rewrites first-person words to the subject, and applies the declared per-turn (2) and per-prompt (6) caps.
    - 90 tests; the full suite passes.
  - **FS-0:** a compile-only replay of the 809 with the built path on copies of the five re-captured flags-on stores, with no answer model.
  - **Faithfulness check:** 50 sentences sampled from all 639 (seed 20261117, before any outcome existed), each read by hand against its source turn.
- **Lines (pre-registered):**
  - FS-0 goes on only with at least 25 gold-fact firings among the 152.
  - Faithfulness: at most 5 of 50 wrong; 6 or more stops the step.
- **Result:**
  - **FS-0 reproduces the control exactly:** the conversation sections are identical on all 809 once the fact lines are removed, and all 457 prompts with no firing are byte-identical.
  - **Firings:** 352 (99 with a sentence on a gold turn, 253 without), 1.82 sentences per firing.
  - **Reach:**
    - among the 152 wrong with every gold turn in view: 77 firings, **30 gold-fact firings** (line 25: passed);
    - among the 281 missing-evidence questions: 13;
    - among the 372 already right: 163 firings.
  - **Duplicates:** 60% of sentences (382 of 639) repeat a fact already shown as an Observation line.
  - **Faithfulness: 6 of 50 wrong (line 5): stopped.** By cause:
    - wrong person: 1;
    - a future stated as past: 2;
    - a present fact stored as a plan: 2;
    - a non-place stored as the place: 1.
    - The 6 are 4 distinct facts, all in one conversation. Every one renders a stored fact as stored; the rendering rules produced no wrong sentence in the sample.
- **Ruling (review session, 2026-11-17):** the stop is accepted as pre-registered. The line is not moved and nothing is discounted after the fact. Fact sentences are not run; held for the user. The code stays on its branch.
- **Lesson:** a sentence built by rule states its fact plainly next to a true turn, so a capture error becomes a confident false claim. The sentences exposed the stored facts' error rate rather than the rendering's.

### 2026-11-17 How often a stored fact is wrong (FACT-ACC, offline, hand-read)
- **Why:** every error the fact-sentence check found was in the stored fact, not the rendering. This sizes the capture error for the user's decision on the capture rebuild (B542).
- **What:**
  - **Sample:** 100 live facts, 20 per conversation, from fresh copies of the five re-captured flags-on stores (seed 20261118 over sorted observation ids, drawn before reading).
  - **Reading:** each fact (subject, predicate, polarity, object, place, partner, time) was read by hand against its source turn and given one label, with borderline calls marked.
  - **Graph reads:** Observation literals, HAS_SUBJECT/subject_id, HAS_OBJECT, HAS_PLACE, HAS_PARTICIPANT, EVIDENCED_BY → Message text. Nothing written; no GPU and no model.
  - **Lines:** none (pre-registered in `scratch/factacc/RUNS.md`). Prediction: 15-30% wrong.
- **Result:**
  - **35 of 100 wrong:** 21 clear and 14 borderline.
    - If every borderline call went the other way, the count runs from 21 to 56, since 21 facts judged right were also borderline.
    - The point estimate is above the prediction.
  - **By label:**

    | Label | n |
    |---|---|
    | Not a fact about anyone (a question, small talk, an opinion with no subject) | 14 |
    | Wrong object or place | 9 |
    | Wrong person | 5 |
    | Wrong tense or polarity | 4 |
    | Wrong predicate | 3 |

  - **By predicate (wrong of sampled):** has_attribute 11/19, is_a 7/13, prefers 5/17, did 5/30, plans 4/15, relates_to 2/4, owns 1/2.
  - **By conversation:** 9, 7, 6, 9 and 4 of 20.
  - **No subject:** 10 facts have no subject edge or literal, and all 10 are wrong.
  - **Shown to the reader:** 13 of the 35 wrong facts already appear as an Observation line in at least one control prompt (67 prompts); 10 of the 21 clear-wrong ones do. Of the 65 right facts, 39 appear.
- **Ruling:** none; for the user's decision on B542.
- **Lesson:** about a third of stored facts are not true statements about a person. The error is concentrated in has_attribute and is_a, and in facts with no subject. "did" facts are the most reliable (5 of 30). The reader already sees some of these wrong facts as Observation lines today.

### 2026-11-17 Baselines: naive retrieval, and the full-history timing probe (job 1001)
- **Why:** to place the 53.6% control between no memory (2.6%) and plain retrieval, and to size the full-history run before it is queued.
- **What:**
  - Naive retrieval: the harness `naive_rag` baseline (embedding retriever) on the 809, with the same answer model and the same judge (3 votes, cache), and the daemon stopped.
  - Probe: the `full_context` baseline on 5 questions, to time one answer.
  - Lines: none (reference). Predictions: naive retrieval 30-42%; full history only if the probe projects under 40 h.
- **Result:**
  - **Naive retrieval: 36.1% (292), -17.5 points against 53.6%; reference.** By conversation: 42.1, 42.8, 30.4, 34.6 and 32.3%. Non-answers: 10. No errors or overflow; largest prompt 769 tokens. Inside the prediction.
  - Memory during naive judging (8% judging line): free 14-15%, swap 2.3-6.1 GB.
  - **Probe: stopped by the memory guard.** At full-history context the answer model took 21.2 GB, and free memory fell to 9-10% against the 12% line. The guard stopped the job 6 minutes in, before the first answer. There was no retry, and no projection.
- **Ruling:** none; full history is held for the user.
- **Lesson:** Campy's memory adds 17.5 points over plain retrieval of turns at the same reader. The full-history reference cannot be measured on this machine under the guards as they stand.

### 2026-11-17 Second-score agreement check (job 1002)
- **Why:** before rescoring six arms with a second column that ignores an opening refusal, check that the second pass agrees with 25 hand-read answers.
- **What:** `second_score.py` on the 25 agreement ids of `rcon`: refusal stripped, then judged by the same judge with 2 votes. Line set before the run: at least 18 of the 20 full-key answers right, and at most 1 of the 5 not-full ones.
- **Result:**
  - Full key: 18 of 20 right (pass). conv-26_q80 gets no second pass, as known beforehand; conv-48_q143's stripped remainder is only a partial sentence.
  - **Not full: 2 of 5 right: FAIL.** Both are dates worked out or left vague ("the week of 2023-02-27" from "last week"; "a few days ago, according to his conversation on 2023-12-17"), which the judge credits.
  - Strict 0 of 25, second 20 of 25, 172 s.
- **Ruling:** stopped as pre-registered; the six-arm pass (run 3) is not run.
- **Lesson:** once the refusal is stripped, the judge is lenient on derived and vague dates. A second column would raise partial answers as well as complete ones, so it is not a clean measure of the abstention cost.

### 2026-11-17 (morning) Rulings on the held runs (user)
- **Why:** three of the six queued runs ended held: fact sentences stopped at the faithfulness check (6 of 50 wrong; line 5), the second score failed its agreement check (2 of 5 partial answers passed; line 1), and the full-history probe was stopped by the memory guard (the answer model took 21.2 GB at full-history context).
- **Decision (user, on the review session's recommendations):**
  - Fact sentences are left stopped; the line is not moved. The code stays on its branch and is not merged.
  - The second score is dropped; only the strict score is reported. The scoreboard notes that every arm loses about 3 points to answers that decline and then give the key.
  - Full history is decided after the abstain replay.
  - The capture rebuild (B542) is the next direction question; the review session recommends after the abstain replay.
- **Lesson:** both stops were caught by checks set before any GPU time (a faithfulness sample and an agreement sample), at a cost of minutes, not hours. The fact-sentence stop also measured something larger than itself: the stored facts' own error rate.


### 2026-11-17 Run 5: the changed abstain instruction (cite_answer)
- **Why:** 67 of the 152 wrong answers with every gold turn in view were declines. The current instruction tells the reader to say it lacks the information, and the changed one tells it to answer whenever a line answers, a worked-out date included.
- **What:**
  - Tree at main 4b1404fa. Re-captured flags-on store copies, linking limit 0 (the control's flags).
  - Changed arm on the 809 (`CAMPY_ANSWER_STYLE=cite_answer`), judged by the same judge (3 votes) and cache against the stored control (53.6%).
  - Control and changed arms on the 222 category-5 (adversarial) questions, scored judge-free by the harness `abstained` / `abstained_strict` rule.
  - Check before the run: with the flag off, the tree gave byte-identical prompts to the stored control (30 of 30).
  - Lines: PASS above +1.9 points with category-5 refusals falling by at most 5 points. KILL at 0 or below, or refusals falling by more than 10. Prediction: +0.5 to +2.5 points; refusals down 3 to 8.
- **Result:**
  - **809: 60.0% (485), +6.3 points against 53.6%.** Gained 67, lost 16. Without the 34 test faults: 55.6% → 61.9%.
  - By category: 1 -2, 2 +23, 3 +8, 4 +22. Non-answers 168 → 58.
  - 39 of the 67 declines with gold in view are now right.
  - **Category 5: refusals 58.6% → 31.5%, -27.1 points: KILL.** abstained_strict 0.9% in both arms. 61 stopped refusing and 1 started. Only 1 of the 61 is a refusal worded so the rule misses it; 60 give a real answer, usually the other speaker's fact for a speaker-swapped question.
- **Ruling:** killed as pre-registered; the flag stays off. Held for the user.
- **Lesson:** the instruction fixes the declines it targets, but the reader cannot tell a line about the asked person from a line about someone else. So permission to answer also answers the trap questions. Wording moves both sides together; separating them needs a structural check on the subject (P5).

### 2026-11-17 LoCoMo's own F1 beside the judge score, and our judge against the published ones
- **Why:** user request (2026-11-17), so our numbers can be set beside the LoCoMo paper's and beside the memory papers' judge scores.
- **What:**
  - Token F1 for every arm on the scoreboard, from the stored answers, with the harness's `locomo10.scoring.locomo_f1` unchanged. Stemming was on. All ten arms have every answer text stored (one no-memory answer is empty and scores 0).
  - The published judge prompts, read from released code at pinned commits (Mem0, Zep, MemOS), compared rule by rule with ours (`learnings/judge-comparison.md`).
  - No GPU and no pipeline change. Lines: none (a measurement and a reading).
- **Result:**
  - F1 runs from 11.6 to 13.3 across the memory arms, against 52-60% judge accuracy. No memory: 3.0. Naive retrieval: 10.3, only 2.4 below the control, against 17.5 points by the judge.
  - The run-5 instruction gains +0.6 F1.
  - Our answers have a median of 37 words against a 4-word key, because the cite instruction adds the quoted line. The baselines' answers are short. So F1 here mostly measures answer length, and is not comparable to systems told to answer in a few words.
  - The three published judges share one prompt (Mem0's, reused by Zep and MemOS). It leans generous ("touches on the same topic"), and says nothing about answers that decline then answer, partial lists or hedging. Ours fails all three explicitly. Dates are treated about the same.
- **Ruling:** none; reported to the user. No change to our judge.
- **Lesson:** our judge accuracy is a lower bound against the published judge, and our F1 is depressed by the cite format. Neither number can be set beside a paper's without saying so.

### 2026-11-17 Would a speaker rule have stopped run 5's category-5 answers? (offline count, no design)
- **Why:** the input to the user's choice between accepting run 5's kill and designing a subject check by rule (review session request).
- **What:**
  - From the stored run-5 records, with no GPU.
  - **The rule:** the question names exactly one speaker, A; the line the answer quotes was spoken by the other speaker, B, and does not mention A.
  - **Speaker of a line:** the dataset turn's speaker, which capture writes as SPOKEN_BY.
  - **The quoted line:** the answer's quoted text, matched to its turn. Otherwise the answer's `[Speaker, date]` label. If the answer quotes nothing, the shown turn with the most word overlap with the answer, chosen without the gold.
  - Script: `scratch/cite/speaker_rule.py` in the plan lead's working area.
- **Result:**
  - **(a) Category 5, the 60 answers that now answer: the rule stops 16.** conv-26 q169, q171, q181, q183, q194; conv-41 q161; conv-48 q194, q202, q210, q212, q217, q230, q232, q238; conv-49 q163; conv-50 q175.
    - Not stopped: 25 quote a line the asked person spoke; 16 quote the other speaker in a line that names the asked person; 3 questions name neither or both speakers.
  - **(b) The 809, the 67 gained: the rule wrongly stops 1** (conv-48 q36). 60 quote the asked person, and 6 questions name both speakers. Across all 485 right answers in the changed arm, it fires on 3.
  - **(c) The rule can apply** to 727 of the 809 (89.9%) and 219 of the 222 (98.6%): those name exactly one speaker.
  - **Derived:** with the rule, category-5 refusals would be about 86 of 222 (38.7%; 70 now plus the 16 stopped), against the control's 58.6%. That is still about 20 points down, so the rule as specified does not bring run 5 inside its 10-point line.
  - **The first count (14 of 60, a 23 / 16 / 7 split)** left 7 answers unchecked. The gold-free best-matching shown turn, for answers that quote nothing, settled 4 of them (2 stopped, 2 quoting the asked person). The 3 that name neither or both speakers stay outside the rule.
- **Ruling:** none; counts only, for the user.
- **Lesson:** a speaker rule is nearly free on the 809, but stops only about a quarter of the category-5 answers. Most of them answer from the asked person's own line, or from a line that names them, so a check on who spoke cannot see the trap.

### 2026-11-17 Rulings after run 5 (user)
- **Why:** run 5, the speaker-rule counts, the F1 column and the judge comparison were in. Four decisions were with the user.
- **What:** the user ruled "go with your recommendations" on the plan lead's four recommendations:
  - run 5's kill is kept;
  - full history gets one more probe at an 8% answering line, with the full run only under 40 hours;
  - the control and run 5 are re-scored with the published judge prompt, as a separate column;
  - the capture rebuild (B542) is next, design first.
- **Result:** the probe and the re-score were pre-registered (`scratch/baselines/RUNS.md`, `scratch/pubjudge/RUNS.md`) and queued.
- **Lesson:** the run-5 kill stands even though it is the largest gain on the 809. The adversarial side is the held-out check, and it failed.

### 2026-11-17 Full-history probe at the 8% line (run 6, second probe)
- **Why:** user ruling (2026-11-17 afternoon): probe full history once more with the answering line lowered to 8% (the judging line) for the probe only, and run in full only if it projects under 40 hours.
- **What:** five questions on one conversation (`run_all.py --baselines-only --baselines full_context --locomo10-max-questions 5`), with the judge flag set so the memory guard used 8%, the daemon and the judge model stopped, and the 30 GB swap ceiling. Pre-registered in `scratch/baselines/RUNS.md` (plan lead's working area).
- **Lines set before the run:** none on accuracy. A projection under 40 hours allows the full run (after a check with the review session). A guard stop means no retry, and it goes back to the user.
- **Result:** stopped by the memory guard before its first answer. Free memory fell from 52% to 5-6% within 80 seconds of the answer model loading (20.9 GB at full-history context), and swap rose from 4.1 to 8.2 GB. No answer and no projection.
- **Ruling:** held for the user (review session): run 6 has been stopped twice by the guard, at 12% and at 8%.
- **Lesson:** at full-history context, the answer model alone takes the machine below any guard line we would accept. Lowering the line again would trade a baseline number for the risk of a swap storm. Full history cannot run on this machine as built.

### 2026-11-18 Re-score with the published judge prompt
- **Why:** user ruling (2026-11-17 afternoon): re-score the control and run 5 with the judge prompt the memory papers publish, as a separate column, so our numbers can be set beside theirs.
- **What:**
  - Mem0's ACCURACY_PROMPT, read from the released file at mem0ai/mem0 b3ede5b7 (deleted from main later; Zep and MemOS reuse it verbatim).
  - One call per answer, temperature 0, a JSON label, on our local 26B judge model. The model is the only difference from the papers' setup.
  - The stored answers of the control (re-captured stores, capture flags on) and of run 5, on the 809. No pre-filter. No GPU beyond the judge, and no pipeline change.
  - Script: `scratch/pubjudge/pub_judge.py` in the plan lead's working area.
- **Lines set before the run:** control expected 62-75%; run 5's change expected +2 to +5 points (smaller than our +6.3, since this prompt already passes many decline-then-answer replies). No pass or kill line. A judge error rate above 2% voids the result.
- **Result:**
  - Control: 69.8% (565), inside the prediction. Our judge: 53.6%.
  - Run 5: 75.4% (610), +5.6 points (gained 61, lost 16). Just above the predicted range; our judge gave +6.3.
  - Judge errors: 1 of 809 on run 5, none on the control. The result stands.
  - Answer by answer, the published judge passes every answer ours passes. It also passes 131 more on the control and 125 more on run 5.
- **Ruling:** a measurement only. Our judge stays the headline, and run 5's kill stands, since the published judge skips category 5.
- **Lesson:** the published prompt is a strict superset of ours on these answers: about 16 points more generous and never stricter. So a paper's judge score is roughly our accuracy plus 16 points on our answers, and run 5's gain survives the change of judge almost unchanged. My prediction that this prompt would shrink the gain was wrong: run 5 mostly turned refusals into full answers, which both judges pass.

### 2026-11-18 B542 step 1: do parse rules on the closed-question lane make stored facts more accurate? (paired, blinded, no GPU)
- **Why:** the user approved the B542 capture-rebuild design ("go with your recommendations"). Step 1 screens it before any GPU time.
- **What:**
  - **Lane:** the earlier B542 lane's saved replies from the 8B reader, for the five conversations of the 809, put through frozen parse rules:
    - not a question;
    - the subject a person on a closed list;
    - the subject decided by rule from the object's clause;
    - a whole, specific object from the turn's own text;
    - tense and polarity from the main verb;
    - is_a only as a copular complement.
    Answers that fail a rule are candidates. Nothing was written to any store, and no model was called.
  - **llm-1:** fresh facts from copies of the control stores, with FACT-ACC's 100 left out.
  - **Sample:** one seed, 20 facts per conversation from each source. The 200 were shuffled, rendered in one form, and read with FACT-ACC's six labels. The source key was opened only after the last label.
  - Scripts and pre-registration: `scratch/b542s1/` in the plan lead's working area (rules frozen by sha256 before the draw).
- **Lines set before the run:**
  - continue if the lane has at least 10 fewer wrong of 100 and at least 60% of llm-1's right facts per 100 turns;
  - stop if it is no better, or under 60%;
  - in between, to the user.
  - Prediction: lane 18-30 wrong, llm-1 28-40, coverage 40-80%.
- **Result:**
  - **Wrong of 100:** lane 52 (range 35-69), llm-1 53 (range 43-76). No accuracy gain.
  - **Coverage: stopped.** Right facts per 100 turns: lane 15.5 (32.2 confirmed × 48% right), llm-1 41.0 (87.2 × 47%), or 38%, against the 60% line.
  - **By label:**

    | Label | lane | llm-1 |
    |---|---|---|
    | wrong object | 24 | 26 |
    | not a fact about anyone | 15 | 12 |
    | wrong predicate | 7 | 7 |
    | wrong tense or polarity | 3 | 1 |
    | wrong person | 3 | 7 |

  - **Candidates per rule** (2,643 answers):
    - the rule-decided subject 759;
    - malformed answers 408;
    - object checks 303;
    - question sentences 207;
    - tense 46;
    - is_a 3;
    - the closed subject list 1.
  - **Overlap:** of llm-1's right facts that could be matched to a dataset turn, the lane confirms the same turn and subject on 19 of 33.
  - **Blinding leak, found at reading:** 30 of the 100 llm-1 items showed a stored date and the image caption, so they were recognisable as llm-1. The lane items never were.
  - **Step 1b** (the larger reader's saved replies, conv-48 and conv-49) was drawn but not read, per the stop rule. Its screen confirms 91% of llm-1's fact count there.
- **Ruling:** stopped as pre-registered. Held for the user: whether to read step 1b, and whether B542 continues.
- **Lesson:**
  - With the 8B reader, the parse rules cut wrong-person errors (7 → 3) but not the main error: an object that is a fragment or the wrong noun ("make", "go", "a ton"). The rules also cost about 60% of the right facts. Better gates on a weak reader's answers do not make the stored facts more accurate.
  - The same labels read blind gave llm-1 53 wrong, against FACT-ACC's 35 read unblinded. So one reading of 100 facts is not a stable baseline. Only a paired reading supports a comparison.

### 2026-11-18 B542 step 1b: the same screen on the larger reader's saved replies (paired, blinded, no GPU)
- **Why:** step 1 stopped with the 8B reader. The user asked for step 1b to be read, to see whether a stronger reader changes the picture.
- **What:**
  - The same frozen rules and method as step 1, on the larger, judge-class model's saved lane replies for conv-48 and conv-49.
  - 20 + 20 facts per conversation (40 lane, 40 fresh llm-1, with step 1's and FACT-ACC's facts left out), seed 20261120. One shuffled list, with the key opened after the last label.
- **Lines set before the run:** at least 4 fewer wrong of 40, and at least 60% of llm-1's right facts per 100 turns. Informs the reader choice only; it does not start step 2.
- **Result:**
  - **Wrong of 40:** lane 15 (37.5%; range 9-23), llm-1 19 (47.5%; range 12-30). Difference -4, exactly the line.
  - **Coverage:** right facts per 100 turns, lane 43.6 against llm-1's 40.4 (108%).
  - **By label:**

    | Label | lane | llm-1 |
    |---|---|---|
    | wrong object | 8 | 3 |
    | not a fact about anyone | 6 | 8 |
    | wrong predicate | 1 | 4 |
    | wrong person | 0 | 3 |
    | wrong tense or polarity | 0 | 1 |

  - **Blinding leak:** 13 of the 40 llm-1 items were recognisable by a stored date and caption.
  - **Weight:** about 0.9 standard errors on 40 facts per source.
- **Ruling:** meets its lines. Held for the user: whether to make larger-reader replies for the other three conversations (one GPU job, near the memory guard), then a full paired 100 + 100 reading, or to close B542.
- **Lesson:** the reader matters more than the rules. With the larger reader, the same rules remove the wrong-person and wrong-predicate errors and keep coverage. With the 8B reader, they only cost coverage. The object choice is the remaining error for both readers.

### 2026-11-18 B542 step 1c: the larger reader on the other three conversations (GPU job 1006)
- **Why:** step 1b met its lines on a weak sample. The user approved one GPU job ("Run the GPU job") to make the larger reader's replies for conv-26, conv-41 and conv-50, so that a full paired, blinded 100 + 100 reading could follow.
- **What:**
  - The earlier lane's runner for the larger reader, unchanged, from the same base store copies, writing only reply files.
  - The daemon and the 8B model stopped first.
  - The standing guards: 12% free, since this is not judging; 30 GB swap.
  - Pre-registered in `scratch/b542s1/RUNS.md`, including that a guard stop means no retry. The leak fix for the reading (dataset text and dates for every item) was set before any draw.
- **Result:** stopped by the memory guard 78 seconds in. The model loaded at 18.1 GB, and free memory fell from 74% to 10% within 30 seconds and held there for three checks; swap rose from 2.9 to 7.2 GB. 3 windows of conv-26 were written. Nothing was drawn or read.
- **Ruling:** held for the user. There was no retry, and no lower line.
- **Lesson:** the reader that made step 1b look better does not fit on this machine under the 12% line. The earlier run held 12-13% free, under a looser scratch guard. So a larger-reader capture arm (B542 step 2) is not runnable as built either: it would need the same model for about 3-5 hours of capture.

### 2026-11-18 ND-1 and ND-2: how far would subject-anchored turn retrieval reach? (offline, no GPU)
- **Why:** sizing for the next-direction options note (review session request). Of the 809, the control prompt held no gold turn on 187 questions (23.1%, answered 24% right) and only some on 94 (11.6%).
- **What:**
  - Read-only SPARQL on fresh copies of the control stores, with no model and no embeddings.
  - **Anchor:** the speaker the question names, when it names exactly one.
  - **Question terms:** named entities, noun chunks and noun lemmas, matched exactly to Concept labels.
  - **ND-1, query A:** turns `SPOKEN_BY` the subject that `MENTIONS` a question term, ranked by terms matched, then by date. Query B adds turns that mention the subject.
  - **ND-2:** the same query A, with `MENTIONS` simulated for every name and noun of each turn (the same term rule on the dataset text). A what-if of an edge capture could write.
  - Pre-registered in `scratch/nd1/RUNS.md` in the plan lead's working area.
- **Lines:** none (sizing). Predictions: ND-1 top-10 reach on the 187 at 15-30%; ND-2 at 15-30% with result sizes over 50 at the 90th percentile.
- **Result:**
  - **ND-1:**
    - The top 10 holds a gold turn on 18 of the 187 (9.6%), below the prediction. B: 15.
    - Misses: no question word matches a Concept 77; matched but no gold turn 57; no single-speaker anchor 22; gold below the top 10 16.
    - Capture writes about 3 MENTIONS per turn. Check on the 524 questions with all gold in view: 27.7%.
  - **ND-2:**
    - The top 10 holds a gold turn on 46 of the 187 (24.6%), by category 1: 9, 2: 11, 3: 3, 4: 23.
    - Result size median 11, p90 40.
    - On the 94 partly-covered questions: 44, an upper bound that counts gold turns already shown.
  - **Worth on the 809:**
    - ND-1: about +1.0 point, under the +1.9 bar.
    - ND-2: a ceiling of about +2.7 points, if the 46 were answered at the all-in-view rate (71%) and the added turns cost nothing.
- **Ruling:** not ruled; input to the user's next-direction decision (`~/campy-lead/reports/2026-11-18-next-direction-options.md`).
- **Lesson:** the subject-anchored path through SPOKEN_BY is there today, but capture's MENTIONS are too sparse to carry it. About 3 per turn leaves most question words with no Concept. Writing a mention for every name and noun is the capture fix that would make the query worth gating (P8: fix capture first). ND-2 is a simulation on clean dataset text, so the real number needs the rule written into store copies first.

### 2026-11-18 Step 4, the whole gate: `principled` against `main` on fresh captures (GPU jobs 1007 and 1008)
- **Why:** the plan's closing gate. Four default-on capture fixes (B565, B567, B568, B570) had landed in both profiles since step 0c, so step 0c's +0.7 points needed a second measurement before the 15 principled switches are ruled on. Run on the user's "follow the plan".
- **What:**
  - Fresh captures of conv-26/41/48/49/50 for each profile, on a tree detached at main 949d6353, with step 0c's recipe unchanged.
  - The 809 replayed on each store (principled with the concept walk off; main with `CAMPY_PROFILE=main`), judged by the 26B judge under the 8% judging line.
  - Pre-registered in `scratch/step4/RUNS.md` in the plan lead's working area.
- **Lines:** pass if principled beats main by more than 15 questions net. No kill line. Prediction -0.5 to +2.0 points. LongMemEval only after a pass.
- **Result:**
  - principled 54.1% (438) against main 53.9% (436): **+0.2 points**, net +2 questions (gained 25, lost 23). Without the 34 test faults: 56.1% against 55.9%, +0.3 points.
  - By category: 1 +2.6 points (net +4 of 153), 2 +0.6 (+1 of 171), 3 -2.0 (-1 of 51), 4 -0.5 (-2 of 434).
  - Step 0c beside it: +0.7 points (net +6). Same-arm repeatability: principled moved +0.7 points between the two captures (769 of 809 same verdict), main +1.2 points (779 of 809).
  - No guard stops, 0 judge errors. Captures took 10.3 h, replay and judging 3.9 h.
- **Ruling:** no pass. LongMemEval stays parked. The 15 principled switches go to the user: on by default or deleted.
- **Lesson:** two measurements agree that the profiles tie: the principled switches neither help nor hurt the score at this capture quality. Between two fresh captures the same profile moves about 1 point, so the step-to-step drift is the size of the effect being looked for.

### 2026-11-18 ND-0 and ND-3: subject-anchored turns ranked by vector (offline, no GPU)
- **Why:** the review session's correction to the ND-1/ND-2 drop. ND-1 and ND-2 ranked anchored turns by term match; the direction asked for a vector rank within the subject's turns.
- **What:**
  - ND-0: the edge check on copies of the control stores (SPOKEN_BY, MENTIONS into the speakers' Concepts).
  - ND-3: for each question naming one speaker, the Messages SPOKEN_BY or MENTIONing that speaker (one anchored SPARQL query), ranked by the cosine between the raw question and each Message's stored vector (the store's own embedding model, on the CPU). R mode replaces the control's conversation section with the top N (N = the control's own turn count, median 24); A mode adds the anchored top 5 not already shown.
  - Run after the step-4 result was sent, with the queue empty, at 90% free memory. Pre-registered in `scratch/nd1/RUNS.md`.
- **Lines:** stop if under 25% of the 187 "none" questions gain a gold turn, or if the net estimate is under +15 questions; the direction continues only if one mode clears both. Prediction: 30-50% of "none" gain; 15-30% of "all" lose a gold turn under R.
- **Result:**
  - ND-0: every Message has SPOKEN_BY; 47-83% of Messages per store MENTION a person; on 727 of the 809 questions (89.9%) the subject resolves to a Concept with MENTIONS into it.
  - R: 50 of the 187 "none" gain a gold turn (26.7%), 30 gain all their missing ones. But 154 of the 524 "all" lose a gold turn (29.4%). Net estimate 25.9 - 86.2 = **-60.4 questions**.
  - A: 23 of the 187 gain (12.3%); net estimate **+10.2 questions**. Median 125 added tokens (p90 230).
  - "some" (94): R gains for 39.4%, mostly category 1 (29 of 74), and loses a shown gold turn for 39.4%.
- **Ruling:** stopped. R clears the reach line but not the net line; A clears neither. The vector-ranked anchored variant is dropped with no GPU time.
- **Lesson:** the anchor edges are there (P8 holds for this query), but a subject anchor plus the question's vector is a worse selector than the existing retrieval: it finds a missing gold turn on a quarter of the "none" questions only by dropping a found one on almost a third of the "all" questions. Added as extra turns, it finds too few.

### 2026-11-18 ND-4: where the category-1 "some" questions' missing gold turns rank (offline, no GPU)
- **Why:** the direction's pre-named fallback: whether a larger turn budget would bring every gold turn into view for the multi-turn questions that already show some.
- **What:** the 74 category-1 questions in the "some" bucket. The stored records hold no retrieval ranks, so each dataset turn was ranked by the store's own vector score (cosine of the raw question against every Message vector, one vector per turn). Near-duplicate crowding: turns ranked above the worst missing gold turn, by the same speaker in the same session, with cosine at least 0.9 to a shown turn.
- **Lines:** stop if under 25 of the 74 have every gold turn in the top 30. Prediction 20-35, with most missing gold turns just below the budget.
- **Result:**
  - Every gold turn in the top 15, 20 and 30: **9, 11 and 12 of the 74**.
  - The 164 missing gold turns (1 more has no vector) rank at a median of 89.5 (25th percentile 27, 75th 209); 43 are within 30, 88 within 100.
  - Of the 12,376 non-gold turns ranked above the worst missing gold turn, 3 are near-duplicates of a shown turn.
- **Ruling:** stopped, under the line and below the prediction. The fallback is dropped; the next direction is the review session's to pick.
- **Lesson:** the missing gold turns of multi-turn questions are not just over the budget's edge, and they are not crowded out by duplicates. The question's vector ranks them far down, so a larger budget recovers few of them. A lever for these questions has to reach them by something other than similarity to the question.

### 2026-11-18 ND-5: a cross-encoder reranks the candidate turns (offline, CPU, no GPU)
- **Why:** the review session's direction after ND-3/ND-4. The missing gold turns are mostly in a 100-turn candidate set, but the question's vector ranks them low, so the question is whether a stronger scorer over the same set puts them in the prompt.
- **What:**
  - Scorer: a small public MS MARCO cross-encoder (about 92 MB), downloaded on the user's OK, pinned to a commit and checked by sha256, then run through the installed fastembed on the CPU.
  - Candidates per question: the control prompt's turns plus the top 100 dataset turns by the store's own vector score (one vector per turn). Each candidate is scored as "speaker: turn text" against the raw question, then cut to the control's own turn count (replace mode).
  - Run on the same five control stores and records as ND-3, with the queue empty and free memory 62% at the start. It never went under 63% during the run.
  - Pre-registered in `scratch/nd1/RUNS.md` in the plan lead's working area.
- **Lines:**
  - Stops: under 25% of the "none" questions gain a gold turn; a net estimate under +15 questions; more than 10% of the "all" questions lose a gold turn.
  - "Close" (set before the run): a stop is hit, but "none" gain is at least 20% or the net estimate is at least +8. Close would allow the larger base model.
  - Prediction: "none" gain 15–25%, "all" losses 15–30%, net estimate −20 to +5, so a STOP.
- **Result:**
  - "none" (187): **86 gain a gold turn (46.0%)**, and 58 gain every missing one (31.0%). None lose one. Gains by category: 1: 31, 2: 11, 3: 8, 4: 36.
  - "some" (94): 52 gain (55.3%) and 16 lose a shown gold turn (17.0%).
  - "all" (524): **36 lose a gold turn (6.9%)**, against 29.4% for ND-3's vector rank.
  - Net estimate **+23.9 questions** (by category: 1 +12.6, 2 +4.1, 3 +0.8, 4 +6.3).
  - Two checks before believing it. 29 prompt items across the 809 do not map to a distinct turn, so replace mode hands those slots to turns; negligible. Two questions counted as gaining every missing gold turn also lost a shown one (−1.1). Corrected: **about +22.8 questions, about +2.8 points**. This is a ceiling, since it assumes the all-in-view rate.
- **Ruling:** passes all three stops; the prediction was wrong. "Close" does not apply, so the base model is not fetched. Next: a design for a reranking stage in the retrieval path behind a flag, reviewed against the graph skill, then one GPU gate (pass above +1.9 points; kill at 0 or below, or if category-5 refusals fall more than 5 points). Both wait for the review session.
- **Lesson:** the retrieval gap is a ranking problem, not a reach problem. The candidate set already holds the gold turns, and a scorer that reads the question and the turn together keeps the gold turns already shown far better than a vector score (6.9% lost against 29.4%). Only one of two measurements so far, so no memory entry until the GPU gate agrees.
