# Lessons learned: every trial, why we ran it, and what it showed

The full trail of the benchmark work, oldest first. One entry per test or trial: why we tried it, what we tried, the
result, and the decision that followed. `e2e-status.md` is the current-state page; this file is the history. The dated
notes in this folder hold the longer evidence for each period and are linked from the section headings.

Conventions: ids and counts only, no answer-key values; models are named by role and size (the 8B answer model, the
26B judge); "g / l" means questions gained / lost against the comparison arm on the same questions.

## Adding an entry (required after every test or trial)

Append to the last section, in the same PR as the status-file update:

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
