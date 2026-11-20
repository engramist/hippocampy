# E2E plan status

Live state of `e2e-improvement-plan.md`. One entry per step result; earlier history is in git and the dated notes.

_Last updated: 2026-11-20 (LME probe: light capture 3.54 s per turn, so a 100-question sign check with default capture, queued after ND-12)_

## Scoreboard (one test set, one measure)

Every row is the same 809 questions (LoCoMo categories 1-4, five conversations), answered by the 8B answer model and
scored by the 26B judge. **Accuracy** is the share answered correctly. **Change** is in percentage points against the
run's own control (the same stores without the change). Noise is ±1.7 points; a change counts as a gain only above
+1.9 points (15 questions).

| Run | Accuracy | Change against its control | Verdict | F1 (LoCoMo's own metric) | F1 change against the same control |
|---|---|---|---|---|---|
| `main` profile | 52.7% (426) | reference | | 12.5 | reference |
| `principled` profile | 53.4% (432) | +0.7 against `main` | inside noise | 12.3 | -0.2 |
| Step 4, `main` profile, fresh captures (2026-11-18) | 53.9% (436) | reference | | | |
| Step 4, `principled` profile, fresh captures (2026-11-18) | 54.1% (438) | +0.2 against step 4's `main` | no pass (line: more than +15 questions); a tie, agreeing with the row above | | |
| Re-captured stores, capture flags off | 53.9% (436) | reference for the re-capture | | 12.7 | reference |
| Re-captured stores, capture flags on | 53.6% (434) | -0.2 | no change; the control for the three rows below | 12.7 | +0.1 |
| Graph facts in the prompt, first build (2026-11-14) | 51.7% (418) | -1.7 against 53.4% | killed | 11.8 | -0.5 |
| Graph facts in the prompt, re-measured (2026-11-16) | 52.3% (423) | -1.4 | killed | 12.0 | -0.7 |
| Graph facts with object-text matching (2026-11-16) | 51.2% (414) | -2.5 | killed | 11.6 | -1.1 |
| Baseline: no memory (2026-11-17) | 2.6% (21) | -51.0 against 53.6% | reference | 3.0 | -9.8 |
| Baseline: naive retrieval (2026-11-17) | 36.1% (292) | -17.5 against 53.6% | reference | 10.3 | -2.4 |
| Baseline: full history | not run: both timing probes were stopped by the memory guard, at the 12% and at the 8% line | | skipped (user, 2026-11-18) | | |
| Fact sentences next to their source turn | not run, stopped at the faithfulness check (6 of 50 wrong; line 5) | | stopped | | |
| B578 gate control: step 4 stores, reranker off (2026-11-19) | 54.1% (438) | reference | | | |
| B578 turn reranker on (2026-11-19) | 51.9% (420) | -2.2 against the row above | **killed** (line: 0 or below); gained 57, lost 75 | | |
| B578 add mode on (2026-11-19) | 48.8% (395) | -5.3 against 54.1% (the control above) | **killed** (lines: 0 or below; "all" bucket -13.0); gained 48, lost 91; truncated 0 | | |
| B578 window mode on (2026-11-19) | 56.5% (457) | +2.3 against 54.1% (the control above) | **pass** (line: more than +1.9); gained 61, lost 42; truncated 0; one measurement | | |
| B578 rcon control: re-captured stores, reranker off (2026-11-19 reuse) | 53.6% (434) | reference | | | |
| B578 window mode on, rcon stores (job 1012, 2026-11-19) | 56.5% (457) | +2.8 against the row above | **confirmed by the lines** (own > 0, pooled +2.6 > +1.9); 682 of 809 prompts identical to 1011, so 127 new questions | | |
| **Control from 2026-11-19: window mode on (the default), step 4 stores** | **56.5% (457)** | reference for later gates | default since the review session's ruling; memory entry waits for an independent sample | | |
| Changed abstain instruction (2026-11-17) | 60.0% (485) | +6.3 against 53.6% | killed: refusals on the 222 adversarial questions fell 27.1 points (line 10) | 13.3 | +0.6 |

The judge score is the headline because token F1 fails correct paraphrases and long answers. Our cite answers add the quoted line (median 37 words against a 4-word key), so F1 here mostly measures answer length. F1 is shown so these numbers can be set beside the LoCoMo paper's. It was computed from the stored answers with the harness's `locomo10.scoring.locomo_f1`, unchanged. That function mirrors the official evaluation: it lowercases, drops commas, punctuation and a/an/the/and, Porter-stems, and takes token-overlap F1. Category 1 scores each gold item against the best of the comma-split answer, and category 3 uses the first gold alternative. F1 changes are within the F1 column only. How our judge differs from the published judges: `learnings/judge-comparison.md`.

In every arm about 3 points are answers that open with an abstention and then give the key; the judge fails them by its written rule. The arms differ by at most 0.6 points on this, so no comparison changes.

**Published judge (a separate measure, 2026-11-18).** The same stored answers, judged by the prompt the memory papers publish (Mem0's, reused verbatim by Zep and MemOS; read from released code at mem0ai/mem0 b3ede5b7), on our local judge model with one call at temperature 0. It is shown only so our numbers can be set beside those papers'. It never decides a pass or kill, and its changes are within this table only.

| Run | Published-judge accuracy | Change against the same control |
|---|---|---|
| Re-captured stores, capture flags on (the control) | 69.8% (565) | reference |
| Changed abstain instruction (killed) | 75.4% (610) | +5.6 (gained 61, lost 16) |

Judge errors: 1 of 809 on run 5, none on the control (void line 2%). Answer by answer, the published judge passes every answer ours passes. It also passes 131 more on the control and 125 more on run 5, so our judge is about 16 points stricter and never the more generous one.

Two other measures, which are not accuracy and are never mixed with it:

- **Query hits:** the share of the 809 questions where a graph query finds a fact from the right turn. 13.7% before
  this plan; 14.7% on the re-captured stores; 23.5% with the role edges; 34.5% with object-text matching. Hits rose
  20 points and accuracy did not move.
- **Evidence in view:** on 64.8% of questions every source turn is in the prompt, and those are answered 71.0%
  correctly. On the other 34.7%, accuracy is 21.0%.

Reporting rule (user, 2026-11-16): every result is given as accuracy in percent on the 809 and its change in
percentage points against its control, with the noise band; raw counts once, in brackets. A number on any other set
of questions says so in the same sentence.

## Run queue (order ruled by the user 2026-11-17)

One GPU job at a time, under the guards (12% free; 8% while judging; 30 GB swap). Each run has its lines written
before it starts and gets a lessons entry when it ends.

| # | Run | What it tests | State | Lines (strict accuracy on the 809 unless said) |
|---|---|---|---|---|
| 1 | Baselines job: no memory, naive retrieval, timing probe | where 53.6% stands against no memory and plain retrieval | done: no memory 2.6% (-51.0 points), naive retrieval 36.1% (-17.5 points), both reference; the probe was stopped by the memory guard (free 9-10% against the 12% line, answer model at 21.2 GB) before its first answer, so there is no projection | reference, no line; predictions 2-6% and 30-42% |
| 2 | Second score, agreement check | whether the second pass agrees with 25 hand-read answers | closed by the user 2026-11-17: failed its line (2 of 5 partial answers passed; line 1); the second score is dropped | at least 18 of 20 full answers pass, at most 1 of 5 partial ones |
| 3 | Second score, six stored arms | a second column: an opening refusal ignored | closed by the user 2026-11-17: not run; the second score is dropped | no line; expected +2.5 to +3.5 points on every arm, gaps unchanged |
| 4 | Fact sentences by rule, next to their source turn | whether plain sentences built from the graph's facts help the reader | closed by the user 2026-11-17: stopped at the faithfulness check (6 of 50 wrong; line 5), left stopped; code kept on its branch, not merged | pass above +1.9 points; kill at 0 or below; prediction -0.5 to +1.5 |
| 5 | Changed abstain instruction | whether the reader stops declining with the evidence in view | killed: 809 at 60.0% (+6.3 points, pass); category-5 refusals 58.6% → 31.5% (-27.1 points, over the 10-point kill line) | pass above +1.9 points with correct refusals on the 222 adversarial questions falling by at most 5 points; kill at 0 or below, or refusals falling by more than 10; prediction +0.5 to +2.5 |
| 6 | Full history baseline | the reader with every turn in view | stopped twice by the guard, at 12% and at 8%; **skipped by the user 2026-11-18** (second probe: free memory fell from 52% to 5-6% within 80 seconds of the 20.9 GB answer model loading; swap 4.1 → 8.2 GB; no projection, no retry) | reference, no line; prediction 45-62% |

| 7 | B542 capture rebuild, step 1: paired, blinded fact screen (no GPU) | whether parse rules on the closed-question lane make stored facts more accurate without losing right facts | stopped on the coverage line: lane 52 wrong of 100, llm-1 53 (blinded, same reading); right facts per 100 turns 15.5 against 41.0 (38%, line 60%); step 1b (larger reader, conv-48 and conv-49), read at the user's request: lane 15 wrong of 40 against llm-1 19, coverage 108%, meets its scaled lines on a weak sample (about 0.9 standard errors); step 1c (larger-reader replies for the other three conversations, GPU job 1006) stopped by the memory guard 78 seconds in (free 10% against 12%, model at 18.1 GB), no retry; **closed by the user 2026-11-18 ("Close B542")** | continue at 10 or more fewer wrong and coverage at least 60%; stop if no better or coverage under 60%; prediction lane 18-30 wrong, llm-1 28-40, coverage 40-80% |

| 8 | Step 4, the whole gate: fresh captures, `principled` against `main` (jobs 1007 and 1008) | whether the principled profile beats main with the four capture fixes since step 0c | **no pass:** 54.1% against 53.9%, +0.2 points, net +2 questions (gained 25, lost 23); by category 1 +2.6, 2 +0.6, 3 -2.0, 4 -0.5 points; without the 34 test faults +0.3 points; no guard stops, 0 judge errors | pass above +15 questions net; no kill line; prediction -0.5 to +2.0 points |

B542 is closed (user, 2026-11-18); step 2 was never queued.

## Waiting for the user

**Open now (2026-11-18, night):**
1. **Step 4 did not pass** (54.1% against 53.9%, +0.2 points, net +2 questions against the +15 line). With step 0c's +0.7 points, two measurements agree: `principled` ties `main`. LongMemEval stays parked. **For the user:** each of the 15 principled switches goes on by default or is deleted, with no third state.
   - **Ruled (review session, under the user's delegation):** 14 switches on by default and the concept walk deleted (B575, code PR). Subject-anchored turn retrieval has no surviving variant (ND-1/ND-2 lexical, ND-3 vector-ranked, ND-4 the category-1 fallback all stopped offline).
2. **Next direction: reranking the candidate turns, sized offline as ND-5** (review session, 2026-11-18). The user approved the downloads ("Both, as needed").
   - **B578 gate killed (2026-11-19):** 51.9% against 54.1%, -2.2 points. Coverage rose as ND-5 said ("none" questions +12.4 points), but on questions that kept every gold turn accuracy fell 7.1 points: replace mode drops the evidence turns' neighbours. The flag stays off; the next step is the review session's.
   - **B578 add mode killed (2026-11-19):** 48.8% against 54.1%, -5.3 points; the "all" bucket -13.0. No prompt truncated. More context made the answer model refuse: 63 of the 91 lost answers are refusals. Both modes are killed; the next direction is the review session's.
   - **B578 window mode passed (2026-11-19):** 56.5% against 54.1%, +2.3 points (net +19); every category up (cat 4 +3.0). "none" bucket +15.1 points, "all" bucket -2.3 (line -3). Category-5 abstention -1.4; refusals on the 809 fell 167 → 153. No prompt truncated. One measurement: the flag stays off until the review session rules on a default flip or a second measurement.
   - **Job 1012 met the confirmed line (2026-11-19):** 56.5% against 53.6% on the rcon stores, +2.8 points; pooled +2.6. But the rcon and s4p stores give byte-identical prompts on 682 of 809 questions, so only 127 questions are a new sample. On those 127, both runs gain (+10 and +12 net). The flip waits on the review session's ruling.
   - **Window mode is the default (review session, 2026-11-19):** `turn_rerank = true`, `turn_rerank_mode = "window"`. The new control for gates is window mode on, 56.5%. No memory entry until an independent sample (a fresh capture, or LongMemEval when unparked) agrees. The model on the personal daemon is the user's call. Nothing goes on the GPU until the review session picks the next direction.
   - **Next: ND-8 (review session, 2026-11-19)**, an offline miss analysis of the new control (1011's on arm) to choose the next stage by counts; CPU only.
   - **ND-8 result (2026-11-19):** of 352 misses, gold not in view 159 (45.2%), refusal with every gold turn in view 83 (23.6%), misreading 57 (16.2%), key/judge artefacts 33 (9.4%), aggregation 13 (3.7%), date arithmetic 7 (2.0%). Among the 173 in-view misses, refusals are 48.0%. Hand check: 33 of 40 agree (82.5%). 32 of the 83 in-view refusals give the key after an opening refusal. By the decision rule the next lever is the answer stage; the design waits on the review session.
   - **ND-9 killed (2026-11-19):** the hedge rule cut category-5 correct abstention from 55.9% to 25.2% (-30.6 points; 1012: -30.2), against a 5-point line. The model hedges in the same shape on adversarial questions (79 of 222 changed, against 63 of 809). No GPU used. The next direction is the review session's.
   - **ND-10 killed (2026-11-19); the hedge line is closed:** gating the hedge rule on SPOKEN_BY by the question's subject still cut category-5 abstention by 13.1 points (1012: 11.7), against a 5-point line. The gate separates ("spoken by another" 54% of adversarial hedges against 8% of answerable ones) but about 40% of adversarial hedges rest on the subject's own turn. No GPU used.
   - **ND-11 stopped (2026-11-19):** adding every Message SPOKEN_BY the resolved subject to window mode's candidates (median 332 candidates against 112) gains a gold turn in context on 17.8% of the "none" questions (line 20%); "all" loss 3.5%, chars +2.1%, scoring 2.2 s. Reach is not the limit: 154 of the 159 no-gold-in-view misses have a gold turn spoken by the subject, yet the cross-encoder still ranks it out. The next direction is the review session's.
   - **ND-5 passed offline, on the small cross-encoder:** "none" questions gaining a gold turn 46.0% (line 25%); "all" questions losing one 6.9% (line 10%); net estimate about +22.8 questions, about +2.8 points (line +15; a ceiling).
   - The base model is not needed. **Next, for the review session:** design a reranking stage behind a flag, then one GPU gate.
3. **Full history (run 6): skipped** (user, 2026-11-18). The guard is not lowered.
4. **Direction and GPU authority delegated** (user, 2026-11-18: "you can do these 'pick a new direction, start a GPU experiment,' just have good reasons for why you did them"). The review session now picks directions and approves GPU experiments, and records its reasons in the Rulings table and the plan before anything runs. The guard lines and the other standing constraints are unchanged. The first pick is in the plan's 2026-11-18 revision: retrieval coverage, by subject-anchored turn retrieval.

### Settled rulings (kept for the trail)

Ruled by the user 2026-11-17 (afternoon), in the plan lead's session ("go with your recommendations"), on the plan lead's four recommendations:
1. **Run 5 (abstain instruction): the kill is kept.** The flag stays off and in no profile.
2. **Full history (run 6): one more probe** with the answering line at 8% (the judging line) for the probe only, and the 30 GB swap ceiling. The full run only if the probe projects under 40 hours. The full run also needs a check with the review session first.
3. **Published judge: re-score** the stored control and run-5 answers with the published LoCoMo judge prompt (Mem0's, reused by Zep and MemOS), on our local judge. This is a separate column; our judge stays the headline.
4. **Capture rebuild (B542): the next direction.** A design comes first; no GPU until the user approves it. The design names the edges it writes. Its measures include the hand-read fact accuracy on a fresh 100-fact sample against FACT-ACC's 35% (same labels and reader rules), query hits and the 809 replay. The speaker rule is not pursued.

Ruled by the user 2026-11-17 (morning), on the review session's recommendations:
1. **Fact sentences (run 4): left stopped.** About a third of stored facts are wrong (35 of 100, range 21-56%), so
   plain sentences would state those errors next to true turns. The code stays on its branch and is not merged.
2. **Second score (runs 2-3): dropped.** Only the strict score is reported. Every arm loses about 3 points to answers
   that decline and then state the key; the arms differ by at most 0.6 points on this, so no comparison changes.
3. **Full history (run 6): decided after run 5.** It needs either a lower line for that run or an otherwise idle
   machine, and may take a day or more.
4. **Capture rebuild (B542): the main direction question.** The review session gives a recommendation once run 5's
   result is in.

**Baselines judging under a lower guard line (ruled by the user 2026-11-16, about 22:15, in the plan lead's
session: "Lower line for judging").** As applied:
- The memory guard keeps 12% free at all times except during a judging phase, which marks itself with a flag file;
  while the flag exists the line is 8%. The user named no number; 8% is the plan lead's choice (the judge settles at
  11-12%), and the user can change it. The earlier guard script is kept as a backup.
- A second guard, added at the review session's request, stops the job if swap stays above 30 GB for three checks.
  It only adds a stop.
- The personal daemon is stopped for the whole job. Answering phases, the timing probe and full history stay at 12%.
- Observed in the first hour of judging: free 11-16%, swap rising from 2.1 GB to a band of 12-16 GB and levelling
  there; neither guard fired; judging runs at about half its usual speed.

The full trail of trials is in `lessons-learned.md`; every test or trial is appended there with its result.

Ruled by the user 2026-11-16 (night), on the review session's recommendations:
1. **Graph facts as a prompt section: the kill is accepted.** Both re-measurements lost (414 and 423 against 434),
   and even firing only on gold rows would gain under the +15 line. `graph_facts` and `object_text_match` stay off
   and in no profile. No new lever starts until the baselines on the 809 are in; the next direction is then the
   user's, read against the full-history baseline and the coverage table (every gold turn in view 0.71; otherwise 0.21).
2. **Baselines judging: requeue as it is, keep the guard.** The guard's line stays at 12% and no app is closed. The
   job is requeued unchanged; if the guard stops it a third time it comes back to the user.

Ruled by the user 2026-11-16:
1. **Action word:** dropped, as the 2026-11-14 ruling says (21 of 100 written words wrong; object-text matching
   reaches 57 of its 61 gained hits). The `roles` flag stays off and in no profile; no code is deleted yet.
2. **Place line:** judged by the whole turn (4 of 30 wrong). The place role is kept.
3. **Object-text matching by vector at cosine 0.75:** built next, behind a flag (off, in no profile), design first.
   Step 3 is then re-measured on top of it, as its own pre-registered run; then step 4.

Done 2026-11-16: object-text matching is built behind `[retrieval] object_text_match` (off, in no profile; it acts
only with `graph_facts` on). **Run OT-1 passed every line:**
- the build gives 279 hits on the flags-on stores and 275 on the flags-off stores, the same as the offline
  reference (vecq-4), with 0 question ids different;
- flag off gives 123 and 119, unchanged;
- 3 of 50 sampled new matches are wrong (3 to 5 on the borderline calls; the line is at most 10).

Next: S3-OT (step 3 with object text, one GPU replay arm against the stored 434), then S3-asbuilt, then the baselines
on the 809 as a reference measurement.

Ruled by the user 2026-11-15:
1. **Partner role:** the model-chosen partner is dropped (29 of 30 hand-checked links were wrong). The action word
   (form 3) and place stay. A co-participant edge is written only by a rule.
2. **Subject change:** the "we"/group part only, anchored by rule on facts the model already proposes, with the
   extraction prompt untouched (measured offline: 56 facts, 5 hits, 3 of 18 wrong). The relation part ("my ...") stays
   out (6 of 12 wrong). The prompt wording is not tried again.

Done 2026-11-15: the "we" anchoring is on main behind `group_anchor` (off); form 3 without the model-chosen partner
is on main behind `roles` (off); the conv-26 confirming capture met its lines. Next: the paired full re-capture of the five conversations on the approved lines;
then step 3 re-measured; then step 4.

Earlier rulings, 2026-11-14 (the decisions page, `~/campy-lead/reports/2026-11-14-decisions-for-the-user.md`):
1. **Step 3:** option C. The flag stays off. The section as built is re-measured after the capture work and one full
   re-capture; there is no new fire rule.
2. **The action word:** one new form (form 3). A rule proposes candidate words from the fact's own text, and a closed
   choice picks one or "none". This is the last form: if its word line is hit, the action role is dropped and partner
   and place go forward alone.
3. **Who a fact may be about:** option A only. "we" and people named by relation ("my kids") may be subjects; the
   nine predicates stay.
4. **Step 0c:** kept. The per-conversation stores are the replay baseline.

Order: form 3, then the subjects change, then one full re-capture of the five conversations, then step 3
re-measured, then step 4. One GPU job at a time.

Ruled by the user 2026-11-13: step 3 runs first, on today's 111 hits; roles are option B (a word-level action kind,
with form 2's partner and place roles kept).

- **Step 0 (fix the test): done.** All 809 category 1-4 questions of conv-26/41/48/49/50, replayed on the kept
  stores with the gate's answer model, judge (3 votes) and settings. Working files: `~/campy-lead/scratch/step0/`.

  | | `main` (R107 store) | `principled`, walk off (R111 store) |
  |---|---|---|
  | Accuracy, cat 1-4 | **0.514** (416 of 809) | **0.517** (418 of 809) |
  | single-hop (434) | 0.638 | 0.634 |
  | temporal (171) | 0.509 | 0.532 |
  | multi-hop (153) | 0.222 | 0.222 |
  | open-domain (51) | 0.353 | 0.353 |
  | Non-answers (auto-failed / abstention regex) | 61 / 192 | 50 / 191 |
  | Evidence recall, text (harness) | 0.656 | 0.666 |
  | Evidence recall, graph-aware | **0.748** | **0.748** |

  - **Noise.** The replay repeats exactly: on the 300 questions also in the earlier replays, 300 of 300 answers,
    prompts and verdicts match for both arms. What is left is sampling noise: ±0.018 (±14 questions) at one standard
    error on 809, against ±0.029 on 300. Paired, `principled` against `main` gains 31 and loses 29 (net +2); the
    paired standard deviation is about ±8 questions, so a step-4 gain needs more than about 15 questions net.
  - **Graph-aware recall** also counts a gold turn as found when a fact in the prompt has that turn as its
    `EVIDENCED_BY` source. Fact lines are matched back to Observations on store copies by speaker, date and quote
    (0 unmatched; the 2% that match several Observations credit nothing). About 110 questions per arm have a gold
    turn reached only through a fact. By category (text to graph-aware), `main`: multi-hop 0.37 to 0.51, temporal
    0.72 to 0.82, open-domain 0.34 to 0.49, single-hop 0.77 to 0.83.
  - **Evidence labels.** The harness now splits labels written with `;` or spaces and fixes two typos
    (campy-benchmarks PR 45). Two published ids name no turn and stay unresolved.
  - **Known limit of the replay.** The kept store holds all five conversations, but the live gate asks each
    conversation's questions before the next one is ingested. In the replay, 266 (`main`) and 240 (`principled`) of
    809 prompts carry turns from another conversation. Both arms carry it, but the replay is not the live gate.
    Left as it is (decided 2026-11-10); raise it again before step 3 is measured.
  - `scripts/drift_report.py`: "watch: score flat while code landed" (28 commits in 7 days, 4 with a gate result).
- **Step 0b (fact contract): done.** `docs/fact-contract.md`, approved 2026-11-10: keep the 9 predicates and add action,
  with and place roles; text objects allowed but flagged; action kinds from an independent source.
- **Step 1 (capture writes the roles): form 3 passed its lines 2026-11-14 (the word line at its edge); the next step is
  with the user.** Flag `[observations] roles`, default off. Design: `learnings/step1-capture-roles.md`.
  - **Form 3 (candidate words by rule, closed choice with "none" in the partner/place call; branch
    `claude/step1-form3`, run s1onF3; the last form).**

    | Line | Result | |
    |---|---|---|
    | query hits on conv-26 against 14: pass +5, kill under +2 | 28 (+14 net; 14 gained, 0 lost) | pass |
    | facts 389 of 389 | identical to s1off | pass |
    | action facts with a candidate that get HAS_ACTION: kill under 50% | 104-105 of 109 (96%) | pass |
    | 50 written action words, hand-checked (sample drawn before the hits): at most 20% wrong | 10 of 50 (20%) | pass at the edge (±2 items on borderline readings; ruled a pass, the line not moved) |
    | replay of the 152, flag on against flag off: within 6 | running | |

    - The rule's new candidates fix the phrasal verbs (look after, hang out, look into, sign up) and the aspectual
      complement (started playing -> playing). Option B's 17 wrong words: right 5, none 0, no candidate 4, still
      wrong 8.
    - The choice barely filters: "none" on 3 of 109 facts; the first candidate taken in 102 of 105 picks. Writing the
      first candidate without a choice would change 7 words: the sample would read 11 of 50, and hits would be 27.
    - What is left wrong: the complement of a light verb (have a good time, have fun, had a blast, make a difference,
      start a chapter) and nouns that name a thing or place. The complement rule holds 5 of the 10 sampled wrong
      words; no single existing check separates them.
    - Partners: 138 links under option B, 100 under form 3. With the action line in the same call, the model answers
      "none" for the partner far more often. By their quotes, none of the 58 lost links is a real co-participant:
      54 name the other speaker with no support in the quote, 4 are junk names.
    - **Partner hand-check (2026-11-14, not pre-registered, not gated): 29 of 30 random form 3 partner links are not
      a co-participant by the quote.** 73 of the 100 links name one of the two conversation speakers; most of the rest
      are a modifier ("an LGBTQ art show") or a junk name. Without any partner edge the hits are 26 (form 3: 28). The
      two that go (q0, q39) rested on "LGBTQ" as a modifier, not on a co-participant.
    - Only 4 of 170 event quotes on conv-26 name a co-participant ("with the kids" ×2, "with the gang", "with my
      dad"), and none by a name.
    - Places: 10 written, all by the parse fallback; 9 are where the fact happened by the quote, and 1 is right by the
      turn but not named in the quote.
    - Known weakness, not acted on: the complement rule (the word after a light or aspectual verb) holds 5 of the 10
      sampled wrong words.
    - Calls per turn are unchanged (114). Capture time was 67 min against 56.
  - **Option B (word-level action kind by rule, partner and place by closed choice; PR 411 draft, run s1onB):
    kill line hit 2026-11-14.** conv-26 capture on the pinned tree (f2133c58, the s1off capture code), measured on a copy.

    | Line | Result | |
    |---|---|---|
    | query hits on conv-26 against 14: pass +5, kill under +2 | 27 (+13 net; 13 gained, 0 lost) | pass |
    | facts equal s1off | 389 of 389, identical (predicate, object, quote) | pass |
    | did/plans facts with HAS_ACTION: kill under 50% | 109 of 177 (62%) | pass |
    | 50 action words, hand-checked (sample drawn before the hits): at most 20% wrong | 17 wrong (34%); 13 (26%) counting four borderline as right | **kill** |
    | replay of the 152, flag on against flag off | not run: the step stopped | |

    - The 17 wrong words: a phrasal verb cut to its head 4 (look after, hang out, look into, sign up); an aspectual or
      light verb kept for the activity 8 (start, finish, try, had a blast, a good time, a great time, me-time, make it
      happen); a noun or the wrong verb chosen 5 (make some art, a support group, kids who need it, let them know, up
      for the challenge).
    - Gains by role: action 10, partner 2, both 1, place 0. Three gains rest on a word that is wrong or not an action
      (support, sign, class); without them +10. 2 of the 17 wrong and 2 of the 33 right sample words sit on a fact
      behind a gain.
    - Of the 10 action gains, 8 come through a word that is the fact's head noun or main verb with no light, aspectual
      or phrasal construction (lost: sign up, had a picnic); 7 if "class" (in "made it in pottery class") is also
      counted as not an action.
    - Outcomes: written 110; no head 12; head not in quote 10; no event word 23; second word dropped 8; no subject 24.
      77 action Concepts, 22 shared by two or more facts; 6 action labels equal a non-action Concept's label
      (adoption, event, painting, support, work, workshop).
  - **First form (free spans in the fact prompt, PR 410): killed 2026-11-11.** Anchored 47.3% and shared 34.2%, both
    under their kill lines; only 168 of 389 facts matched flag-off.
  - **Second form (a closed choice in a separate call, PR 411, draft): measured 2026-11-13 on conv-26** (store s1on2,
    control s1off):
    - Query hits (the gated measure): 21 against step Q's 14, net **+7** (8 gained, 1 lost). Pass (line +5).
      - Gained: q0, q5, q28, q29, q33, q39, q113, q128.
      - Lost: q70, which became too broad (its term "events" names event.n.01, above 63 facts).
    - Facts equal flag-off: 389/389. Pass.
    - Facts shown action options that got `HAS_ACTION`: 90/101 (89%). Pass.
    - Senses: **16 of 50 hand-checked are wrong (32%; 24% at the most lenient reading). Kill line (over 20%) hit.** The
      replay was not run.
    - Coverage (reported): anchored 57.6%, shared 51.7% (flag-off 34.7% and 21.9%).
  - **What the 8 gains rested on:**
    - None needed the sense: every role target matched the action Concept's own label, and no `BROADER` step was
      used.
    - Six came through an action label: support (q0), race (q5), adoption (q28, q113), workshop (q29), parade (q33),
      walk (q128).
    - Two came through the partner role: "LGBTQ" (q0 also; q39 only).
    - Where the 16 wrong senses sit:
      - None of them is the action behind an action-path gain.
      - One (union.n.11 for "joined a mentorship program") is on a gold row of q39, but q39's hit came through the
        partner edge.
      - The adoption hits (q28, q113) rest on a sense that is right for "to adopt" and doubtful for "a council meeting
        for adoption" (the event there is the meeting).
  - **The contract question, held for the user: what the action role writes.**

    | Option | Writes to the graph | Gains kept | Expected net on conv-26 | Cost |
    |---|---|---|---|---|
    | A: drop the action role | `HAS_PARTICIPANT` and `HAS_PLACE` only | 2 (q0, q39, through "LGBTQ") | about +2 (q70 is not lost: no broad action kind), inside the "+2 to +4 is not a pass" band | none beyond removing the action pick |
    | B: word-level action kinds | `HAS_ACTION` to a Concept per lemma (kind_scheme `action`, no sense, no `BROADER`); no sense line | all 8, if the lemma is the head noun or its nominalization ("adopt" -> "adoption"); q70 likely kept | about +7 to +8 | a roles.py change and one conv-26 re-capture (about 1 h GPU); the `BROADER` chain moves to step 2 |
    | C: rule-picked senses | `HAS_ACTION` to a WordNet sense chosen by rule (the most frequent event sense), with `BROADER` | all 8 (same labels) | about +7 (q70 lost again through event.n.01) | a re-capture (about 1 h) and a new 50-sense check; close to a third form, so it needs the user's explicit yes |
- **Step 0d (always-missed questions): done 2026-11-12** (`learnings/step0d-always-missed.md`). 337 of 809 questions are
  wrong in every one of 16 replay arms:
  - 303 real misses;
  - 29 with the key or label wrong;
  - 5 whose answer is not in the conversation;
  - 24 more flagged as possible judge errors.
  The 34 test-fault ids are reported next to every later score.
- **Step 0c (one store per conversation): done 2026-11-13.** Each of the five conversations was captured into its own
  store, for principled (walk off) and for main, and its questions were replayed on that store.
  - Prompts carrying another conversation's turns: 0 of 809 in both arms (240 and 266 on the shared store).
  - Restated 809 baseline: principled 432 (0.534), main 426 (0.527); without the 34 test faults, 430/775 and 423/775.
    By category, principled: cat 1 38/153, cat 2 86/171, cat 3 21/51, cat 4 287/434.
  - Against the shared store: +14 and +10, inside the ±14 noise, so no measurable change.
- **Step Q (query hits): done 2026-11-13** (PR 418, `query_hits.*` NamedQueries and their CI test). Baseline on the
  five principled per-conversation stores from step 0c:
  - Subject resolved on 801 of 809.
  - Query hits: 111 of 809 (13.7%): cat 1 22/153, cat 2 29/171, cat 3 4/51, cat 4 56/434. conv-26 alone: 14 of 152.
  - Misses, by the first missing edge:
    - object is text (no `HAS_OBJECT` to a Concept): 291
    - the question names no object Concept: 117
    - object not reached by `INSTANCE_OF` / `BROADER`: 113
    - gold fact without the subject edge: 90
    - no fact on a gold turn: 79
    - subject unresolved: 8
  - Hits among the 34 test faults: 6. Among the 337 always-missed: 38 (the graph holds the gold row, but answering missed
    it; a step-4 input).
  - Noise: 0. A rerun is identical, and the conv-26 re-capture gives the same count.
  - Lines approved 2026-11-13 (review session, delegated by the user):
    - Step 2 (809): pass +45 net hits, kill under +15.
    - Step 1 (conv-26, baseline 14): pass +5 net, kill under +2. Three conditions:
      - The role reads (`facts.by_action_kind` / `with_participant` / `at_place`) count as hits only under the same rule:
        a question term names the action kind, partner or place Concept (exact label, in SPARQL), the fact is the
        subject's, a gold turn is among the rows, and there are at most 25 facts.
      - Net is gained minus lost; the baseline hits lost on the re-captured store are listed.
      - +2 to +4 is not a pass. It is reported, with no third form.
      The plan row's mechanism checks are reported alongside.
- **Plan revised 2026-11-12:** steps 0c (per-conversation replay stores), 0d (always-missed questions), 0e (predictions in
  CI) and Q (a thin graph query, whose hits become the measure for steps 1 and 2) come before step 1 continues. 0c, 0d
  and Q done; 0e in review (PR 419).
- **B565 (2026-11-13, PR 422): closed-class words are never Concepts.** On cleaned copies of the five step-0c
  principled stores, 31 pronoun Concepts were archived. Step Q's table is restated:
  - hits: 111 (unchanged, none gained or lost);
  - object is text: 216 (from 291);
  - question names no object Concept: 224 (from 117);
  - object not reached: 81 (from 113);
  - no subject edge 90, no fact on a gold turn 79, subject unresolved 8: unchanged.
  59 facts are left without a live subject. Follow-up: B566.
- **Step 2 (kinds and places): stopped 2026-11-13 before build; held for the user with step 1's roles.**
  - The line was restated and approved 2026-11-13 (review session, delegated), scoped to step 2's own 77 targets: on the
    809, against 111, pass +31 net, kill under +10.
  - Pre-build check on the cleaned copies (whether each rule's trigger occurs in the target questions' gold turns):

    | Rule | Targets | What the gold turns hold | Estimated reach |
    |---|---|---|---|
    | (a) kind for an untyped object entity | 8 | "another cat named Bailey" (WordNet has no path from cat to pet); "his name is Kyle" (no kind noun) | 0 to 2 |
    | (b) BROADER between existing kinds | 5 | each names a context word, not the answer's kind; no hypernym exists | about 0 |
    | (c) LOCATED_IN "X in Y" | 20 | "in Y" in 4 gold turns, X an event or common noun (a show in Tokyo): step 1's HAS_PLACE | 0 to 1 |
    | (d) head-noun kind for non-event objects | 44 | the head is the named label on 4; a WordNet hypernym on 6 | +4 to +10 |

    Total: **+4 to +13**, against kill under +10 and pass +31.
- **Held for the user: which roles capture writes (steps 1 and 2 together).** Of the 297 misses left after B565, the
  questions name:
  - an event's partner: 113;
  - an activity: 61;
  - a kind or place where the gold facts are events only: 46;
  - something within step 2's own rules: 77.

  | Option | Writes | Questions it can reach | Expected net on 809 | GPU |
  |---|---|---|---|---|
  | A: partner and place roles only (form 2 without the action pick) | `HAS_PARTICIPANT`, `HAS_PLACE` | partner 113, event places | about +10 (conv-26 +2, scaled) | five re-captures, about 5 h |
  | B: A plus a word-level action kind (lemma, no sense), which also types did/plans object phrases | A plus `HAS_ACTION` to a lemma kind | A plus activity 61 and event-only 46 | about +35 to +40 (conv-26 +7 to +8, scaled) | about 5 h |
  | C: A plus a rule-picked WordNet sense with `BROADER` | A plus `HAS_ACTION` to a sense | the same as B | about +35 (conv-26 about +7, scaled) | about 5 h, plus a 50-sense check |
  | Step 2's own rules (a-d), with any option | kinds and LOCATED_IN | 77 | +4 to +13 | none beyond the option's |

  Scaling conv-26 to 809 is rough: conv-26 is one conversation of five. For the user to answer in one line: A, B or C,
  and whether step 2's rules are dropped or folded in.
- **Capture recall, diagnosed 2026-11-13** (re-run of the extractor on the 57 substantive gold turns with no fact, and
  60 control turns; it reproduced the original capture):

  | Stage | Gold (57) | Control (60) |
  |---|---|---|
  | Called, proposed nothing | 27 (47%) | 41 (68%) |
  | Proposals all rejected by a rule | 23 (40%) | 17 (28%) |
  | Reply malformed | 7 (12%) | 2 (3%) |
  | Not called, or written then archived | 0 | 0 |

  - Of the 27 gold "proposed nothing" turns, 12 are about "we" or third persons, which the prompt leaves out. That is a
    contract question (waiting list item 2).
  - The rejections are right by the rules (verbs outside the nine, no object, an ungrounded subject), except "prefer"
    for "prefers" on 3 turns. That is fixed as B567.
  - 8 of the 9 malformed replies are cut at the output limit with 7-8 complete facts before the cut. A parser salvage
    design is in review.
  - About 140 misses are capture recall: 62 substantive gold turns with no fact, 75 where no fact carries the
    question's words, and 13 short turns. No roles option touches them.
- **"you" facts anchored on the other speaker (probe): closed.** 55 facts rewired: hits 111, none gained; 1 of 90
  moved; 17 of 20 point at the right person, but 12 of 20 are compliments or questions.
- **What a query hit is worth today (stored step-0c replays):**
  - the 111 hit questions are answered 65 (59%) by principled and 62 (56%) by main;
  - the 698 others are answered 53% and 52%.
  - Hits by category (n / principled / main): cat 1 22/7/8, cat 2 29/15/15, cat 3 4/2/2, cat 4 56/41/37.
  - So hits barely move the score until step 3 puts the rows in the prompt. 46 hit questions are answered wrong today.
  - Corrected by step 3 (2026-11-14): with the rows in the prompt, a question whose gold turn is among the rows goes
    from 62 to 75 of 111 against main (the step-Q hits; all 111 have a gold turn among their rows).
- **Step 3 (graph facts section, PR 428, flag `CAMPY_GRAPH_FACTS`): kill line hit 2026-11-14; flag off.** Replay of
  the 809 on the B565-cleaned per-conversation stores, against the stored principled flag-off arm and main.
  It fired on 413 questions, not the predicted 100-115: the prediction counted hits (a gold turn among at most 25 rows),
  but the section fires on any subject with a named object Concept and 1-25 facts, so hits are a subset (all 111 fired).
  On the 413 it answered 204, against 218 (principled) and 216 (main): the kill line (at or below main) is hit.

  | | n | step 3 | principled | main | step 3 - main | non-answers (step 3 / principled / main) |
  |---|---|---|---|---|---|---|
  | fired, gold turn among the rows | 111 | 75 | 65 | 62 | +13 | 7 / 18 / 24 |
  | fired, no gold row | 302 | 129 | 153 | 154 | -25 | 97 / 71 / 71 |
  | not fired | 396 | 214 | 214 | 210 | +4 | 72 / 72 / 73 |
  | all | 809 | 418 | 432 | 426 | -8 | |

  - Gold among the rows is read from the rows' EVIDENCED_BY turns (the live queries re-run on the same store copies).
  - Without the 34 test-fault ids: gold among the rows 73 of 105 against main 60; no gold row 129 of 292 against 154.
  - On the no-gold-row questions, 36 are lost against principled and 12 gained; 26 of the 36 losses are non-answers.
    In 29 of the 36 the gold turn is elsewhere in the same prompt (the instruction to answer only from the lines is
    the existing answer prompt, B475, in every arm).
  - Not fired: 0 changed against principled, so the cleaned stores do not confound the result.

  | Shape (fired) | n | step 3 | principled | main | step 3 - main | test faults |
  |---|---|---|---|---|---|---|
  | fact | 237 | 119 | 133 | 134 | -15 | 6 |
  | list | 64 | 23 | 23 | 18 | +5 | 5 |
  | dated | 92 | 49 | 48 | 51 | -2 | 4 |
  | exists | 15 | 10 | 11 | 11 | -1 | 0 |
  | latest | 0 | - | - | - | - | - |
  | count | 5 | 3 | 3 | 2 | +1 | 1 |

  | Category | fired n | step 3 | principled | main | step 3 - main | test faults | not fired n | step 3 | main |
  |---|---|---|---|---|---|---|---|---|---|
  | 1 | 64 | 20 | 15 | 14 | +6 | 6 | 89 | 23 | 23 |
  | 2 | 91 | 49 | 47 | 49 | 0 | 5 | 80 | 39 | 38 |
  | 3 | 18 | 7 | 9 | 9 | -2 | 0 | 33 | 12 | 12 |
  | 4 | 240 | 128 | 147 | 144 | -16 | 5 | 194 | 140 | 137 |

- **Item 3 (who a fact may be about; PR 432, flag `[observations] group_subjects`): kill line hit 2026-11-14; flag
  off.** The fact extractor alone was re-run three times (flag off, on, off again) on 57 gold turns with no fact,
  60 control turns and 40 turns with facts (their facts archived in the copy first), on the cleaned stores.
  - Fact-bearing turns: 36 of 40 lost a fact that both flag-off runs wrote; 58 of 76 stable facts were lost. The two
    flag-off runs were identical. Line: more than 2 turns.
  - Cause, checked on 3 lost turns re-run alone: with the flag on the model replies `[]`, where the flag-off prompt gets
    3-4 proposals. The only difference is the two sentence replacements. A wording effect, not the anchoring rule.
  - Gold: 11 of 57 turns gained a fact (prediction 8-15); control: 2 of 60. On the flag-on arm the rule wrote 14
    group-subject facts and 1 relation fact without error.
- Step 4: not started.

## Rulings

One row per measured result. Rulings dated 2026-11-13 were approved by the user on that day.

| Result | Measured | Ruling |
|---|---|---|
| Walk turns merged into the conversation section (B563) | 0.440-0.447 against 0.480 with the walk off, 300 questions | Stopped; not built |
| A stronger model as the reader | 0.463 against 0.470, 300 questions; abstains on a third | Stopped |
| Roles as free spans in the fact prompt (first form, PR 410) | conv-26: anchored 47.3%, shared 34.2%, both under their kill lines; only 43% of facts matched flag-off | Stopped 2026-11-11; its fields come out with the second form |
| Always-missed review (step 0d) | 337 always-missed; 34 test faults (29 key or label, 5 not in the conversation), 24 judge doubts | Kept: the ids are reported next to every later score; the denominator stays 809 |
| One store per conversation (step 0c) | foreign-turn prompts 0 of 809 in both arms; principled 0.534, main 0.527 (+14, +10, inside noise) | Not ruled. Proposed: kept; these stores are the replay baseline and step Q is measured on them |
| Query hits baseline (step Q) | 111 of 809 hits; subject resolved 801; largest miss: object is text (291) | Kept 2026-11-13 (review session, delegated): the measure for steps 1 and 2, with the approved lines above |
| Closed-choice roles (form 2, PR 411) | query hits +7 net (pass); senses 32% wrong (kill line hit) | Stopped 2026-11-13; held for the user (options A, B, C under step 1) |
| Kinds and places (step 2, rules a-d) | pre-build check estimates +4 to +13 | Stopped 2026-11-13 before build; held for the user with step 1's roles |
| Order: step 3 before steps 1 and 2 | a query hit is worth about 0.06 of a correct answer today (59% against 53%) | Ruled by the user 2026-11-13: step 3 runs first on today's 111 hits |
| Roles (steps 1 and 2) | options A, B, C under step 1 | Ruled by the user 2026-11-13: option B (word-level action kind; partner and place roles kept); step 2 folded into step 1 where it is the same construction |
| Closed-class Concepts (B565, PR 422) | hits 111 unchanged; miss table restated (216 / 224 / 81) | Kept 2026-11-13 (review session, delegated) |
| Graph facts section (step 3, PR 428) | fired on 413; gold among rows 75 vs main 62 of 111 (+13); no gold row 129 vs 154 of 302 (-25); overall 418 vs 432 and 426 | Kill line hit 2026-11-14; flag off; held for the user |
| Roles, option B (word-level action kind, PR 411) | query hits 14 to 27 (+13 net, pass); action words 34% wrong (kill line hit) | Stopped 2026-11-14; held for the user |
| Step 3 decision | the decisions page, 2026-11-14 | Ruled by the user 2026-11-14: option C, flag off; re-measured as built after the capture work and one full re-capture; no new fire rule |
| Action word decision | option B 34% wrong | Ruled by the user 2026-11-14: form 3 (candidates by rule, closed choice with "none"); the last form, after which the action role is dropped if its line is hit |
| Who a fact may be about | 12 of 27 no-proposal gold turns about "we" or third persons | Ruled by the user 2026-11-14: option A ("we" and people named by relation); the nine predicates stay |
| One store per conversation (step 0c), ruling | as above | Ruled by the user 2026-11-14: kept; the per-conversation stores are the replay baseline |
| Roles, form 3 (candidates by rule, closed choice; branch claude/step1-form3) | conv-26 query hits 14 to 28 (+14); action words 10 of 50 wrong | Pass at the edge 2026-11-14 (review session; the line not moved); partner links fell 140 to 100; next step with the user |
| Partner by closed choice (forms 2, B, 3) | counts passed; option B's 138 links include 54 to the other speaker with no support in the quote; form 3 hand-check 29 of 30 wrong | Hand-check 2026-11-14; not to be written as built; held for the user. Roles are hand-checked like the action word from now on (a gated line of at most 20% wrong at the full re-capture) |
| Group and relation subjects by prompt change (item 3, PR 432) | gold +11 turns; 58 of 76 stable facts lost on fact-bearing turns | Kill line hit 2026-11-14; flag off; held for the user |
| LongMemEval runs R108, R109 | not run | Parked until step 4 |
| Concept walk (store-wide and anchored, B556-B560) | lowers accuracy on 300 questions; about 2% of its rows hold gold | Parked 2026-11-13: off until step 4, then retested once or deleted |
| Graph vote and question analysis | neutral on accuracy; recall up, non-answers down | Kept 2026-11-13 |
| Graph count | fired on 0 of 300 questions | Stopped as a separate lever 2026-11-13: folded into step Q's queries or deleted |
| The other `principled` switches | not measured one by one | Parked 2026-11-13: each is on by default or deleted at step 4 |
| Partner role by closed choice | 29 of 30 hand-checked links wrong | Dropped by the user 2026-11-15; co-participant edges by rule only |
| Subject change, anchor only | "we" part 5 hits, 17% wrong; relation part 2 hits, 50% wrong | User 2026-11-15: build the "we" part, prompt untouched; relation part left out |
| "We" anchor design (review session, 2026-11-15) | pre-build check: partner by "PERSON named in the quote" 4 of 6 wrong; narrowed to "X and I" or object of "with": 1 link, right | Approved to build behind `group_anchor` (off): speaker as subject, `group_subject` true, partner by the narrowed rule only, PERSON only. Under 10 partner links in the re-capture is "too few to judge", not a pass |
| Confirming capture, partner line removed (conv-26, 2026-11-15) | hits 26 (line: within 2 of 26); facts 389/389; same 50 words: 3 right words now unwritten, no wrong word changed; 10 of 50 wrong (10 of the 47 written, 21.3%); invalid or missing action answers 10 against 1 | Review session: prerequisite met as pre-registered (the picks did not shift). Not counted as evidence the words are under 20% wrong; the re-capture's 100 written words decide the action role, wrong-rates over written edges only |
| Question words resolved to entities by vector (user, 2026-11-15) | not measured; step Q matches exact labels only | User: measure offline on store copies after the full re-capture result. A measurement only; no code on main until its result has a ruling. It does not change the order (step 3 re-measured, then step 4) |
| Full re-capture, five conversations, flags on against off (2026-11-16) | query hits 190 against 119 (+73, 2 lost; +79 against 111); facts 6 of 2,731 missing; action words 21 of 100 wrong; places 4 of 30 wrong by the turn (14 by the quote alone); "we" facts 6 of 30 wrong; rule-written partner links 61, 4 of 30 wrong; replay 434 against 436 | Hits, facts, "we" facts, partner links and replay pass. The action-word line is hit: held for the user. The place wording: held for the user |
| Vector-resolution design (review session, 2026-11-15) | not yet run | Approved as a measurement: readings A (entity vectors), B (object text) and C (role labels), thresholds 0.65/0.75/0.85 fixed in advance, 50 hand-checked matches per reading. C waits for the action ruling. A pass is a result for the user, not a go-ahead to build |
| Vector resolution, reading A: question words to entity vectors (2026-11-16) | 0.65: +17 net, 20 of 50 wrong; 0.75: +10, 18 of 50 wrong; 0.85: +3 | Killed by its lines (every threshold over 20% wrong). Not re-run with another term filter |
| Vector resolution, reading B: question words to the object text of the subject's facts (2026-11-16) | 0.65: +151 net, 11 of 50 wrong; 0.75: +116, 1 lost, 5 of 50 wrong; 0.85: +81, 1 lost, 1 of 50 wrong; rows per new hit 4.6 against 4.8 | Passes at 0.75 and 0.85. A result for the user; nothing built |
| Lexical control: lemma match on object text, no vectors (2026-11-16) | +161 net, 5 lost, 11 of 50 wrong; 6.8 rows per new hit | Killed on its wrong-rate line. Reaches 65 hits the vectors do not; the vectors reach 16 it does not |
| What the action role adds beyond object-text matching (2026-11-16) | of its 61 gained hits, 57 are reached with no action read (40 by vectors at 0.75, 52 by lemmas); 4 by neither. Flags off plus vectors at 0.75: 275 hits against 119 | Reported to the user with ruling 1. Reading C (role labels) stays deferred |
| Action word, place line, object-text matching (user, 2026-11-16) | as the three rows above and the full re-capture row | User: action word dropped; places judged by the turn and kept; object-text matching at 0.75 built next behind a flag, design first, then step 3 re-measured |
| Lessons file (user, 2026-11-16) | `lessons-learned.md` written back to 2026-09-28 | User: every test or trial is appended to it (why, what, result, decision) in the same PR as its status update |
| Object-text matching design (review session, 2026-11-16) | reference measured before the build (vecq-4, exact object Concepts plus object text at 0.75, no role reads): 279 hits on the flags-on stores, 275 on the flags-off stores; exact only 123 and 119 | Approved to build behind `object_text_match` (off, in no profile): reads the subject's live facts, their object text and `EVIDENCED_BY`; writes nothing; threshold 0.75 and 3 texts per term fixed as constants. Run OT-1: the build reproduces 279 and 275 within 3, at most 10 of 50 sampled matches wrong. Run S3-OT (graph facts with object text, against the stored 434): pass net +15 or more with the no-gold-row group losing at most 10; kill at net 0 or below, or that group losing more than 24; between is the user's call. Prediction: near 0, because the fire rule is unchanged. The as-built step 3 arm also runs, as the control and to close the 2026-11-14 ruling |
| Object-text matching build, run OT-1 (2026-11-16) | built path: 279 (flags on) and 275 (flags off), 0 ids differing from vecq-4; flag off 123 and 119; 3 of 50 new matches wrong (range 3-5) | Passed every line; merged with the flag off. S3-OT next |
| Step 3 with object-text matching, S3-OT (2026-11-16) | 414 vs 434 (net -20); gold row +9 on 279, no gold row -29 on 361 (line: >24); without the 34 test faults -17 | Kill on both lines; flag stays off; held for the user |
| Step 3 as built, S3-asbuilt (2026-11-16) | 423 vs 434 (net -11); gold row +13 on 123, no gold row -24 on 299 | Kill as predicted (line: net <= 0); held for the user with S3-OT |
| Baselines on the 809 (design, 2026-11-16) | design approved by the review session 2026-11-16: per-conversation runs, same answer model, judge, votes and cache as rcon; no pass or kill line; predictions no memory 0.02-0.06, naive retrieval 0.30-0.42, full history 0.45-0.62 | Approved; stopped twice by the memory guard at judging; held for the user |
| Step 3 kill and the baselines' memory (user, 2026-11-16 night) | S3-OT net -20, S3-asbuilt net -11; the judge alone at the guard's 12% line | User: the kill is accepted, graph facts stay out of the prompt, no new lever until the baselines are in; the guard stays at 12%, no app is closed, and the job is requeued as it is; a third guard stop comes back to the user |
| Baselines judging, guard line (user, 2026-11-16 about 22:15) | three guard stops with the judge alone at 11-12% free | User: a lower line for judging phases only. Applied as 8% while a judging phase holds its flag (the plan lead's number), 12% otherwise; a 30 GB swap ceiling added as a second stop. Job requeued 22:21 |
| Fact sentences by rule (user, 2026-11-17) | the 152 all-evidence failures cost 18.8 points; 32 have a matching fact by exact label | User likes sentences built by rule, no model call. Review session: design approved to build behind a flag (off), a line attached to its source turn, exact labels only; faithfulness check of 50 sentences (at most 5 wrong) before any GPU; replay after the baselines; pass above +1.9 points, kill at 0 or below; prediction -0.5 to +1.5 |
| Second score (user, 2026-11-17) | about 3 points in every arm are answers that decline and then give the key | User: report a second score beside the strict one, with an opening refusal ignored; strict stays the headline; applied to every arm. Design first |
| Abstain instruction (user, 2026-11-17) | declining with the evidence in view costs 8.3 points; the instruction dates from 2026-10-10 and serves the adversarial category | User: test a changed instruction as one pre-registered replay after the baselines, measured on the 809 and the adversarial questions together. Design first |
| Second-score design (review session, 2026-11-17) | detection and stripping rules fixed in the harness and self-tested; only strict-wrong answers that open with a refusal get a second pass on the stripped text, same judge and votes | Approved. The agreement check gates reporting. The strict column decides every pass and kill |
| Abstain-instruction design (review session, 2026-11-17) | one changed wording, written once; flag `answer_style = cite_answer`; the 809 and the 222 adversarial questions, each against its own control | Approved with the lines in the run queue. One arm, no second wording; closed if it fails. The wording was written after reading the 809's failures, so a pass is not a held-out result |
| Run order (user, 2026-11-17) | full history may take 14-34 hours | User: the three short runs go before full history; the current baselines job finishes first |
| Fact sentences, second score, full history (user, 2026-11-17 morning) | run 4 stopped at its faithfulness check; run 2 failed its agreement line; run 6's probe stopped by the guard; 35 of 100 stored facts wrong | User: fact sentences left stopped (code not merged); the second score dropped, strict only; full history decided after run 5; the capture rebuild (B542) is the next direction question, with the review session's recommendation after run 5 |
| Baseline: naive retrieval (2026-11-17) | 36.1% (292), -17.5 points against 53.6% | Reference; no line | 10.3 | -2.4 |
| Full-history timing probe (2026-11-17) | stopped by the memory guard before its first answer: free 9-10% against the 12% line, answer model at 21.2 GB | Held for the user (review session, 2026-11-17): run 6 cannot run under the 12% line as built; no fix, variant or retry without the user |
| Second-score agreement check (2026-11-17) | 18 of 20 full answers right (line 18); 2 of 5 partial answers right (line 1): failed | Held for the user (review session, 2026-11-17): run 3 is not queued and no second column is reported; no fix, variant or retry without the user |
| Changed abstain instruction, run 5 (2026-11-17) | 809: 60.0% (485), +6.3 points (gained 67, lost 16); category 5: refusals 58.6% → 31.5%, 60 of the 61 now answer for real | Killed as pre-registered (category-5 line); the flag stays off. Held for the user: any follow-up (for example a subject check before answering) is a new design |
| Full-history probe at the 8% line (2026-11-17) | stopped by the memory guard: free 5-6% against the 8% line within 80 seconds of the answer model loading (20.9 GB); swap 4.1 → 8.2 GB; no answer, no projection | Held for the user (review session, 2026-11-17): run 6 is stopped twice by the guard, at 12% and at 8%; no retry, and the plan lead recommends against a lower line |
| Published-judge re-score (2026-11-18) | control 69.8% (565); run 5 75.4% (610), +5.6 points; 1 judge error in 809 | A measurement for comparison with the papers, with no pass or kill line; inside the predicted 62-75% for the control, just above +2 to +5 for the change. Our judge stays the headline; run 5's kill stands (the published judge skips category 5) |
| B542 design (user, 2026-11-18) | closed-question lane, parse rules confirm, candidates tagged with `fact_status`, replaces llm-1 behind a flag; paired blinded screen first | User, "go with your recommendations": replace, tag candidates, the 8B reader, the lines as revised by the review session |
| B542 step 1, fact screen (2026-11-18) | lane 52 wrong of 100 against llm-1 53, blinded; coverage 38% of llm-1's right facts per 100 turns, against a 60% line | Stopped as pre-registered (coverage line). Held for the user: whether to read step 1b (the larger reader, 91% of llm-1's fact count) and whether B542 continues |
| B542 step 1b, larger reader (2026-11-18) | lane 15 wrong of 40 against llm-1 19, blinded; coverage 108% of llm-1's right facts per 100 turns | Meets the scaled lines (4 fewer; 60%), at the margin and on 40 facts per source. Informs the reader choice only. Held for the user: larger-reader replies for the other three conversations (one GPU job, near the memory guard) and a full paired reading, or close B542 |
| B542 step 1c, GPU job 1006 (2026-11-18) | stopped by the memory guard 78 seconds in: free 10% against the 12% line, the larger model at 18.1 GB, swap 2.9 → 7.2 GB; 3 windows of one conversation written | No retry (standing rule). Held for the user: the larger reader cannot run on this machine under the 12% line as it stands, so step 1c's reading cannot run |
| B542 closure (user, 2026-11-18) | 8B arm stopped on its coverage line with no accuracy gain; larger reader met its lines on 40 facts but does not fit under the 12% memory line | User, "Close B542": closed as built, no code merged; the guard is not lowered |
| Full history, run 6 (user, 2026-11-18) | stopped twice by the guard, at 12% and at 8% | User: "skip full history". Not run, and the guard is not lowered |
| Direction and GPU authority (user, 2026-11-18) | B542 closed; step 4 running; no direction ruled | User: the review session may pick a new direction and start GPU experiments, "just have good reasons for why you did them". Every such pick gets a Rulings row with its reasons before it runs. Guards unchanged, one GPU job at a time |
| Next direction (review session, 2026-11-18) | coverage on the control: all gold turns in the prompt for 64.8% of questions (71.0% right), some for 11.6% (14.9%), none for 23.1% (24.1%); stored facts 35-53% wrong; graph facts in the prompt killed three times; run 5 shows answer-stage gains trade against category 5 | Picked: **retrieval coverage by subject-anchored turn retrieval.** The graph picks the turns (a query anchored on the question's subject through the edges capture writes); the reader sees the verbatim turns, never the stored facts. Order: edge check, then offline sizing on store copies (no GPU), then a reviewed design with pre-registered lines, then one GPU gate after step 4 ends. Reasons in the plan's 2026-11-18 revision |
| ND-1 and ND-2, subject-anchored turn reach (2026-11-18, offline) | today's edges: top 10 holds a gold turn on 18 of the 187 no-gold questions (9.6%); with a MENTIONS edge for every name and noun (simulated): 46 (24.6%), a ceiling of about +2.7 points | Not ruled: input to the next-direction options note for the user |
| ND-1 / ND-2 against the direction's stop (review session, 2026-11-18) | subject-anchored turns reach a gold turn in the top 10 on 9.6% of the 187 "none" questions with today's edges (ND-1), and 24.6% with MENTIONS simulated for every name and noun (ND-2, a ceiling about +2.7 points before any loss); with ND-2, only 63.5% of the "all" questions reach a gold turn that vector retrieval already finds | **Dropped before any GPU time,** on the stop set when the direction was picked (fewer than 25% of the "none" questions). Option A (write MENTIONS for every name and noun) is not taken: its ceiling, measured on dataset text rather than built edges, already sits under 25%, and its realistic gain straddles the +1.9 line. Reason: the missed gold turns mostly share no word with the question, so a lexical anchor cannot find what vector retrieval missed. Next, offline: ND-3 sizes the pre-named fallback, the 74 category-1 questions with only some gold turns in view |
| Correction to the ND-1/ND-2 ruling (review session, 2026-11-18) | ND-1 and ND-2 rank the anchored turns by lexical term match; the measure asked for ranks them by vector score within the subject's turns | The drop in the row above applies only to the lexical-anchored variant and to option A. The vector-ranked anchored variant has not been measured yet. It is pre-registered as ND-3, with two stops: under 25% of the "none" questions gain a gold turn, or a net estimate under +15 questions on the 809. It has a replace mode and an add-5 mode. The category-1 fallback is ND-4. Both are offline and wait for an empty queue and free memory above 40% |
| Step 4, the whole gate (2026-11-18) | principled 54.1% (438) against main 53.9% (436): +0.2 points, net +2 questions (gained 25, lost 23); category 1 +2.6, 2 +0.6, 3 -2.0, 4 -0.5 points; without the 34 test faults +0.3 points | **No pass** (line: more than +15 questions; no kill line). Inside the prediction (-0.5 to +2.0). Agrees with step 0c (+0.7): the profiles tie. LongMemEval stays parked. The 15 principled switches go to the user: on by default or deleted |
| ND-0 and ND-3, vector-ranked subject-anchored turns (2026-11-18, offline) | anchor edges exist (SPOKEN_BY on every Message; 89.9% of questions resolve to a subject Concept with MENTIONS into it). R: 26.7% of the 187 "none" questions gain a gold turn, but 29.4% of the 524 "all" lose one, net estimate -60.4 questions. A (add 5): 12.3% gain, net estimate +10.2 | **Stopped** on the pre-registered lines: no mode clears both (25% of "none"; net above +15). The vector-ranked anchored variant is dropped with no GPU time |
| ND-4, category-1 "some" fallback (2026-11-18, offline) | every gold turn in the store's vector top 30 for 12 of the 74 (top 15: 9; top 20: 11); missing gold turns rank at a median of 89.5; 3 of 12,376 turns ranked above them are near-duplicates of a shown turn | **Stopped** (line: under 25 of the 74 at 30; prediction 20-35). The missing turns are far down the vector ranking, not crowded out. The fallback is dropped; the next direction is the review session's to pick |
| B542 steps 1 and 2 (user, 2026-11-18, relayed by the review session) | the B542 design, with the paired blinded screen first | User: "Approve steps 1 and 2". Superseded the same day: step 1 stopped on its coverage line, step 1c was stopped by the memory guard, and the user closed B542 before step 2 was queued |
| The 15 principled switches (review session, 2026-11-18, under the user's delegation) | two whole-profile ties: step 0c +0.7, step 4 +0.2 points; cost check from step 4's records: principled capture 1.03× main's time (312 against 303 min), stores 1.06× main's size (133 against 125 MB), against limits of 1.5× and 2× | **14 on by default:** loop entity_admission, entity_standing, tracker_side_branch, spoken_by; observations object_roles, ownership_rule, kind_hygiene, wordnet_kinds, vocab_steward, typed_objects, evidence_entity_links; retrieval graph_count, question_analysis, graph_vote. **Deleted:** graph_linking_limit 12 (the concept walk), which was off in both measured arms and lost alone (R95, 7 / 14); its code goes under B576. Reasons: no score case either way (P6), so the principles decide: the capture members write the edges the graph needs (P8) and the current direction's measures read; graph_count and graph_vote are subject-anchored queries (P2); gated with no harm, so the default flips (P7). Code: B575 |
| Next direction (review session, 2026-11-18, under the user's delegation) | ND-3/ND-4: the anchor edges exist and the budget is not the limit; the question's vector ranks the missing gold turns low (median rank 89.5; 43 of 164 within 30) | Picked: **better ranking of the candidate turns (a reranking stage), sized offline first as ND-5.** Reasons: the gap is still retrieval (71% right with every gold turn in view, 24% with none); ND-3 and ND-4 show a ranking-quality problem over a candidate set that already holds the gold turns, which a stronger scorer fixes directly, while anchors and bigger budgets displace turns that are already right; the reader still sees only verbatim, source-linked turns (P3), vectors.db stays an index, it is a structural retrieval change (P5), measured offline first (P6, P7). ND-5 runs only after this row is on main |
| B578 GPU gate: the turn reranker, off against on (job 1009, main 457d8d1a, step 4's s4p stores, walk 0) | Pass above +1.9 points; kill at 0 or below, or category-5 refusals down more than 5 points. Prediction +0.5 to +2.5 | 51.9% (420) against 54.1% (438), **-2.2 points**; gained 57, lost 75; without the 34 faults -2.1; cat 1 +3.9, cat 2 -2.9, cat 3 0.0, cat 4 -4.4; category-5 refusals 57.2% → 60.8% (+3.6). **Killed**; the flag stays off. Coverage moved as ND-5 predicted (none→all 55, all→none 18), and the off arm's "none" questions rose 22.7% → 35.1%. But on the 484 questions that kept every gold turn, accuracy fell 73.6% → 66.5%: only 33% of the off arm's turns survive replace mode, so the evidence turns' neighbours are lost. ND-5 and the gate disagree, so no memory entry. The next construction is the review session's to rule |
| B578 additive mode (review session, 2026-11-19, under the user's delegation) | The gate killed replace mode (-2.2 points). "none" bucket +12.4 points (185 questions, about +23); the loss came from neighbours dropped on questions with every gold turn in view (73.6% → 66.5%) | **Approved:** an additive mode, sized offline first, then gated. Construction fixed in advance (P4): add k = 5 reranked turns not already in the section, from ND-5's candidate set, for every question (not only "none": the bucket is unknown at run time, and gating on gold coverage would leak the answer key). Each added turn comes with the section's own neighbour window, in the section's time order; vote turns stay pinned. Offline stops: "none" gold gain under 25%; median prompt growth over 50%, or past the answer model's context; any "all" question losing a gold turn is a bug (0 by construction). GPU gate on the s4p stores: the control b8off is reused only if flag-off bundles at the new commit match 457d8d1a's byte for byte on 20 or more questions, otherwise both arms run. Pass above +1.9 points; kill at 0 or below, or category-5 refusals down more than 5 points; early kill if the "all" bucket falls more than 3 points. Prediction +0.5 to +2.5. Reasons: keeps the one gain the gate showed and removes the measured cause of the loss (no turn the section builds today is dropped); verbatim, source-linked Message nodes, vote turns pinned, nothing stored, no new edge (P2, P3); one structural lever behind the same flag (P5, P7) Then (review session, 2026-11-19): measure the context bound, don't pin it (P7); more than 2% truncated on the on arm means confounded. `prompt_eval_count` (the server's prompt token count) is recorded for every answer call in both arms; per arm, report prompts over 3,900 tokens and prompts truncated (at or near the slot size), with the num_ctx of each answer-model load from the server log. 2% or less truncated: the lines apply, and the truncated questions are reported separately |
| ND-6: B578 add mode sized offline (K = 5, window ±2, nothing dropped; CPU) | Stops: "none" gain under 25%; median prompt growth over 50%; any prompt over 4,096 tokens; any "all" loss is a bug. Prediction: none gain 30–45%, growth 35–60%, net +15 to +25 | "none" gain 44.4% (83 of 187), every missing gold turn 35.3%; "all" loss 0; turns added median 23; growth median 41.7% (p90 53.8%); prompt after median 2,954 tokens, max 3,842 (chars/4), none over 4,096; transition net +43.7 (a ceiling). **No stop hit.** Accepted by the review session; next the code PR, then the GPU gate |
| B578 add-mode GPU gate (job 1010, main c4036c9c, s4p stores, walk 0; control b8off reused after 25/25 and 20/20 byte-identical bundles) | Pass above +1.9 points; kill at 0 or below, category-5 refusals down more than 5, or the "all" bucket down more than 3; confounded at 17 or more truncated (slot and ratio detectors, union). Prediction +0.5 to +2.5 | 48.8% (395) against 54.1% (438), **-5.3 points**; gained 48, lost 91; without faults -5.3; cat 1 +4.6, cat 2 -12.3, cat 3 -5.9, cat 4 -6.0; category-5 refusals 57.2% → 72.1%; buckets none +11.9, some +4.1, all **-13.0**; truncated 0 by both detectors (all prompts at slot 32,768). **Killed** on two lines; not confounded. Refusals on the 809 rose 167 → 242; 63 of the 91 lost answers are refusals. Both B578 modes killed; the gates agree the reranker loses with this answer model. The next direction is the review session's |
| ND-7: budget-neutral window replacement, the last reranker construction (review session, 2026-11-19, under the user's delegation) | Add mode killed (-5.3 points; "all" bucket -13.0; refusals 167 → 242, 63 of 91 lost answers). Replace mode killed (-2.2; the evidence turns' neighbours dropped). In both, the "none" bucket rose about 12 points | **Approved, offline first:** the reranker picks seeds; each seed brings its ±2 session window; seeds in reranker order until the control section's own turn count N is reached; vote turns pinned; session order. The prompt keeps today's length and every seed keeps its neighbours. Measure "context coverage": a gold turn is in view only if it and its ±1 neighbours are all in the section. Stops: "none" gain in context under 25%; "all" questions losing context coverage on any gold turn over 10% (against the control); median prompt chars more than 10% above the control's. Bucket-move estimate reported as a ceiling with no weight. Prediction: "none" gain 20–35%, "all" context loss 10–25%; a stop is likely. If it clears: one GPU gate with job 1010's lines (the "all" -3 kill included) plus the truncation union. If it stops: B578 and the reranker line are closed and the next direction is at a different stage. Reasons: the one construction that removes both measured causes, neighbour loss and length, at once; fixed by those mechanisms, not by the score, with nothing to tune (P4); the third and last try on these 809, with no fourth variant, to keep the forking paths in check (P6)  Result (2026-11-19): "none" context gain 36.9%, "all" context loss 4.2%, prompt chars +1.1%; **no stop hit**. Measure check: the killed replace mode scores 78.4% "all" context loss under the same harness (two stops), so the measure stops both killed modes. Next: the window-mode code PR, then the gate |
| B578 window-mode GPU gate (job 1011, main 45a1abe1, s4p stores, walk 0; control b8off/b8c5off reused after 25/25 and 20/20 byte-identical bundles at 45a1abe1) | Pass above +1.9 points; kill at 0 or below, category-5 refusals down more than 5, or the "all" bucket down more than 3; confounded at 17+ truncated (both detectors). Prediction (review session) +0.5 to +2.5. Diagnostic: refusals on the 809 | 56.5% against 54.1%, **+2.3 points**, net +19 (gained 61, lost 42); cat 1 +2.0, cat 2 +1.2, cat 3 +2.0, cat 4 +3.0; without faults +2.7. "none" +15.1, "some" +4.1, "all" -2.3. Category-5 abstention 55.9% against 57.2% (-1.4). Truncation union 0. Refusals 153 against 167 (15 of the 42 lost). **Pass; not ruled on the default** (one measurement; the review session decides a flip or a second measurement) |
| B578 window mode: confirm before the default flip (review session, 2026-11-19, under the user's delegation) | Job 1011 passed: +2.3 points (net +19); all four categories up; abstention line clear; refusals -14 | **One confirming measurement, job 1012**: window mode on the control's rcon stores (a fresh capture of the same conversations, at a different commit and profile; LoCoMo has no held-out conversations left), both arms at main 45a1abe1, the rcon off arm reused only if 20+ flag-off bundles are byte-identical to its recorded prompts. Confirmed if its own change is above 0 and the pooled change over 1011 and 1012 is above +1.9; kill at 0 or below, category-5 refusals down more than 5, or the "all" bucket down more than 3; confounded at a truncation union of 17+. Prediction +0.5 to +2.5; refusal diagnostic reported. If confirmed: a code PR flips `turn_rerank = true`, `turn_rerank_mode = "window"` (a missing model path keeps today's behaviour with one warning), then the memory entry; the model on the personal daemon is the user's call. If killed: window mode stays off and 1011 is recorded as unconfirmed. Reasons: +2.3 against a +1.9 line with ±1.7 noise; the third construction on the same 809, each fixed by a measured mechanism but still forking paths (P4, P6); the "all" bucket 0.7 from its line; two agreeing measurements is the bar for memory too |
| B578 window-mode confirmation (job 1012, main 45a1abe1, rcon stores, walk 0; off arms rcon/r5c5ctl reused after 25/25 and 20/20 byte-identical bundles) | Confirmed if own change > 0 and pooled over 1011+1012 > +1.9; kill at 0 or below, category-5 refusals down more than 5, "all" down more than 3; confounded at 17+ truncated. Prediction +0.5 to +2.5 | 56.5% against 53.6%, **+2.8 points**, net +23 (gained 65, lost 42); cat 1 +4.6, cat 2 +0.6, cat 3 +2.0, cat 4 +3.2. "none" +14.6, "some" +7.4, "all" -1.9. Category-5 abstention -3.2. Truncation 0. Refusals 154 against 168. Pooled +2.6. **Confirmed by the lines.** Caveat found after scoring: 682 of 809 prompts are byte-identical to 1011 in both arms (identical answers, 2 verdict flips), so the new sample is 127 questions (1011 net +10, 1012 net +12 on them). **Flip not ruled**; reported to the review session |
| B578 window mode: default flip (review session, 2026-11-19, under the user's delegation) | Job 1011 +2.3 (pass, all 809); job 1012 +2.8 (confirmed by the lines). Review session's confirmation design assumed independent stores; 682/809 prompts were identical, so 1012 is an independent sample on 127 questions only | **(a) Flip the default, caveat recorded, no memory entry yet**: `turn_rerank = true`, `turn_rerank_mode = "window"`; a missing model path keeps today's behaviour with one warning per process. Window mode on becomes the control for later gates (56.5%). Reasons: 1011 passed its pre-registered line on all 809 (net +19); on the 127 differing questions the sign replicated (+10, +12); every category positive in both runs, refusals down in both, the "all" bucket inside its line both times; the flip is a reversible default behind a flag (P7). The memory bar (two independent measurements agree) is not met; it waits for a fresh capture or LongMemEval. The model on the personal daemon touches ~/.campy and is the user's call |
| ND-8: miss analysis of the new control, offline, before any lever (review session, 2026-11-19, under the user's delegation) | Window mode is the default (56.5%). On 1011's on arm about 31% of the questions with every gold turn in view are still wrong (about 160), more than the whole remaining "none" bucket | **Approved, CPU only:** the wrong answers on 1011's on arm, all four categories, each with its window-mode bucket. Rule tags: (a) refusal with every gold turn in view; (b) date or time arithmetic (category 2, gold a date or duration, evidence with a relative expression next to a session date); (c) aggregation a graph query could compute (count, list, latest, exists, before/after over several turns); (d) a wrong reading of one turn in view; (e) answer-key or judge artefacts (the 34 known faults plus any the hand check finds); (f) gold not in view (some/none). Hand check: a seeded random 40 of the "all"-bucket misses; agreement reported; under 80% the hand proportions replace the rule counts. Report per class count and share by category; ids and counts only in the repo. **Decision rule:** the next lever goes to the largest class with a P2/P8 construction ((b) dates resolved at capture onto a typed time edge; (c) a graph query anchored on the subject; (a) the answer stage, under P5 caution; (d), (e) no lever, recorded); a class counts only at 20% or more of the misses (about 30+); if none does, the review session rules between the top two. Prediction: (b)+(c) over 40% of the "all"-bucket misses, (a) 15–25%. Reasons: after B578 the largest miss pool has moved off retrieval, so the next stage is chosen by counts, not taste (P6)   Result (2026-11-19): misses 352; primary classes (all misses) f 159 (45.2%), a 83 (23.6%), d 57 (16.2%), e 33 (9.4%), c 13 (3.7%), b 7 (2.0%); "all"-bucket misses (173) a 48.0%, d 32.4%, e 8.1%, c 7.5%, b 4.0%. Hand check 33/40 (82.5%): rule counts stand. Prediction missed ((b)+(c) 11.5% by rule, 22.5% by hand; (a) 48%). 32 of 83 in-view refusals contain the key words after the refusal. **By the rule: (a), the answer stage**; design to the review session  Known undercount: the regex missed 4 (c) list questions in the hand sample ("who have", "which community activities", "where has ... been"); the hand proportions put (c) near 17% of the in-view misses. ND-8 prediction: missed |
| ND-9: the hedge rule, sized on the stored answers (review session, 2026-11-19, under the user's delegation) | ND-8: in-view refusals are 48% of in-view misses; 32 of 83 (35 of 152 overall) open with a refusal and then give a substantive answer. ND-8 prediction recorded as missed; (c) undercounted by its regex (hand proportions put it near 17% of the in-view misses) | **Approved:** trigger = the first sentence matches the judge-free abstention detector, followed by a continuation opening "However", "But" or "That said", of 20 characters or more; output = the continuation alone, connective removed, no wording added; no other threshold; every answer, all five categories. Applied to 1011's and 1012's on arms (809 and 222); changed 809 answers re-judged (same judge, 3 votes; one small GPU job); category 5 judge-free. Control: the window-on arm, 56.5% on both. Pass above +1.9 on 1011's 809 with 1012's change above 0 (the 127 differing questions reported apart). Kill: category-5 correct abstention down more than 5 on either run, or the 809 change at 0 or below. Prediction: +1.5 to +3.0; category-5 abstention -2 to -6. If it passes: a code PR behind `[answer] hedge_commit`, off, and this result stands as the gate. Reasons: the pattern is structural, the model has already answered and a rule decides the final form (P3, P5); keyed on the answer's shape, not a question (P4); deterministic over the same answers, so the stored-answer result is the gate itself (P6); category 5 is the deciding risk (run 5 died there)  Result (2026-11-19): changed 63 of 809 and 79 of 222 (1011), 66 and 78 (1012). Category-5 correct abstention 55.9% → 25.2% (-30.6 points) and 55.4% → 25.2% (-30.2). **Killed** (line: down more than 5). The 809 re-judge was not run |
| ND-10: a subject-anchored hedge gate, sized on the stored answers (review session, 2026-11-19, under the user's delegation) | ND-9 killed: the hedge shape carries the abstention signal (category-5 abstention -30.6/-30.2); P3 asks for a second, independent source | **Approved:** ND-9's trigger exactly; the evidence turn is the prompt turn with the highest cross-encoder score (the same pinned small model) against the continuation text; commit to the continuation only if that turn's SPOKEN_BY speaker (by graph query) is the question's resolved subject (question_analysis on the same store copies); unresolved or several subjects keep the abstention; nothing else changes, no threshold beyond 20 characters. First kill, judge-free: category-5 correct abstention down more than 5 on either run. If clear: re-judge only the changed 809 answers (same judge, 3 votes, a small GPU job). Pass above +1.9 on 1011 with 1012 above 0 (the 127 non-shared reported apart); kill at 0 or below. Also report the share of the 809's hedges that pass and their right/wrong split. Prediction: category-5 abstention -2 to -8; 809 +0.5 to +2.0. If it stops, the hedge line is closed for good, and the next direction is the 159 no-gold-in-view misses (73 category 1). Reasons: adversarial near-misses are about another person, and SPOKEN_BY plus the resolved subject is an independent, subject-anchored graph fact (P2, P3, P8); general for memory QA, an answer about X rests on evidence anchored on X (P4), with the stated risk that it fits how LoCoMo builds adversarial questions; deterministic over the stored answers, so cheap  Result (2026-11-19): hedges passing the gate: 809 42/63 (1011), 45/66 (1012); 222 34/79, 31/78. Spoken by another: 5 of 63 answerable, 43 of 79 adversarial. Category-5 correct abstention 55.9% → 42.8% (-13.1) and 55.4% → 43.7% (-11.7). **Killed** (line: down more than 5); no re-judge. **The hedge line is closed** |
| ND-11: subject-anchored candidates for the window reranker, offline (review session, 2026-11-19, under the user's delegation) | Hedge line closed. The largest pool is the 159 misses with no gold turn in view; ND-4 found the missing gold ranked far down by vector (median 89.5, many beyond the top 100), so window mode's candidates often never hold them | **Approved, CPU only, ND-7's context-coverage harness:** candidates = window mode's current set plus every Message whose SPOKEN_BY is a resolved subject of the question (analyse_for_bundle's subjects, a union when several; unresolved: unchanged); everything else is window mode exactly (same scorer against the question, "speaker: text", vote turns pinned, ±2 session windows, filled to N, session order). Known limit: turns about the subject spoken by the other person are not reached (no MENTIONS edges). Measured against the new control, 1011's window-on sections, buckets by context coverage. Stops: "none" context gain under 20%; "all" context loss over 5%; median prompt chars over the control's by more than 10%; median CPU scoring time above 5 s per question (candidates per question reported). Report the bucket-move estimate as a ceiling by category, and how many of the 159 have a gold turn spoken by the subject (the reach). Prediction: "none" gain 10–25%, "all" loss 3–8%; a stop is likely. If it clears: design review, code PR behind a flag, one GPU gate against 56.5% with job 1010's lines and the truncation union. Reasons: the cross-encoder cannot promote a turn it never sees; the P2/P8 way to widen the set is a subject-anchored graph query, not a bigger vector top-k; ND-3 failed through replacement, and now ranking and fill are the validated parts, so only the candidate source changes (P7); ND-7's harness stopped both killed constructions, so the offline answer can be trusted (P6)  Result (2026-11-19): "none" gain 44 of 247 (17.8%) → **stop**; "all" loss 16 of 455 (3.5%); chars +2.1%; scoring median 2.20 s; candidates median 332. Ceiling +7.2 questions (+0.89 points). Reach 154 of 159. Simulated control equals the real section on 582 of 809; lever alone "none" +34/-4, "all" +1/-12. **Stopped** |
| ND-12: a stronger scorer for window mode, offline (review session, 2026-11-19, under the user's delegation) | ND-11: reach is not the limit, ranking is: 154 of the 159 no-gold misses hold the gold turn in the subject-anchored pool, yet the small pair scorer ranks it below N | **Approved, CPU only, ND-7's harness:** primary arm = window mode exactly as shipped (prompt turns + vector top 100) with the scorer swapped for a base-size reranker (the second model of the user's "Both, as needed", pinned commit, sha256 checked, cached under ~/campy-lead/models/), "speaker: text" against the raw question; secondary (diagnostic, not a line) = the base scorer on ND-11's subject-anchored candidates. Against 1011's window-on sections, context-coverage buckets. Stops: "none" gain under 20%; "all" loss over 5%; median chars over the control's by more than 10%; median CPU scoring above 10 s per question. Report the bucket-move ceiling and the median gold rank before/after on the 159. Prediction: "none" gain 15–30%, "all" loss 2–6%. Download (about 1.13 GB) asked of the user directly before it starts: the ND-5 condition tying it to ND-5 coming close does not apply. If it stops: the cheap retrieval and answer-shape levers at this model size are spent, and the review session takes a stocktake to the user. Reasons: the one retrieval question left is whether a stronger scorer ranks implicit and multi-hop evidence higher; one lever, the scorer (P7); verbatim source-linked turns, nothing stored (P2, P3); no GPU |
| LongMemEval for window mode: light-capture probe first (review session, 2026-11-19, under the user's delegation, the user saying "go ahead with your recomendations") | Sizing: s is the only split that fits (oracle histories fit the budget, so the stage never ranks); 500 questions, median 491 turns; no LME store survives; principled capture runs about 50 min per question (all 500 about 19 days); noise band from 1011's discordance (12.7%) is ±4.8 at 100 questions, ±2.2 at 500 | **(c) first:** one LME-s question of median size, light capture (observation model reads off: `CAMPY_OBSERVATIONS_ENABLED=0 CAMPY_OBSERVATIONS_RETRIEVAL=0 CAMPY_OBSERVATIONS_ENTITIES=0`; Messages, embeddings, SPOKEN_BY and the Loop as default), measuring seconds per turn and peak memory. Decision rule: at 0.5 s per turn or less, (a) all 500, light capture, both arms at one commit, pass above +2.2, kill at 0 or below, refusals reported, single-session-assistant reported apart and kept in the total, truncation union as before; 0.5 to 2 s, (a) on the largest stratified sample fitting 4 days of capture, its pass line from the noise formula written before capture; above 2 s, (b) 100 questions stratified, a sign check (kill at 0 or below, pass above +4.8). Caveat: under light capture graph_vote has no facts, so there are no pinned turns; every result is labelled "light capture". Reasons: capture time is the only cost and the lever does not read most of what default capture spends it on; a one-hour probe decides whether the one confirming size is affordable; 19 GPU days blind would block everything else, and (b) blind buys only a sign check  Result (2026-11-19, job 1013): light capture 3.54 s per turn (1,714 s for 484 turns); capture minimum free memory 21%, judging 19%. **Rule: (b)** |
| LME sign check with default capture (review session, 2026-11-19, under the user's delegation) | Probe: light capture only about 2 times faster than default (3.54 against about 6.69 s per turn), so the trade it was meant to buy (all 500) is gone | **(b) with today's default capture**, not light: the 100-question stratified prefix (49,874 turns), the gate env plus the pinned model path, stores kept; window on against off replayed on the kept stores at one commit. Lines: kill at 0 or below, pass above +4.8 points, labelled a sign check. Checks: determinism 95%, truncation union under 2, the official single-vote judge plus a 3-vote re-judge of the discordant answers; single-session-assistant and abstention reported apart. Expected 6.69 s per turn (about 93 h); a watchdog stops the capture over 10.0 s per turn (1.5 times) and holds for the review session. Queued after ND-12. Reasons: at 100 questions default capture costs about 1.5 days more (about 3.5 against 2); the result is about the shipped system, with graph_vote pinning turns as in production, so no "light capture" caveat (P1); the kept default-capture stores become a reusable LME replay set, so later levers can be gated on LME in hours |
| ND-5 downloads (user, 2026-11-18, relayed by the review session and confirmed in the plan lead's session) | ND-5 held: no cross-encoder on disk | **"Both, as needed"**: fetch the small MS MARCO cross-encoder (about 92 MB, pinned commit, sha256 checked); fetch the base reranker (about 1.13 GB) only if the small one comes close to the stops, defined before the run |
| ND-5: cross-encoder rerank of the control's turns plus the top 100 by vector, cut to the control's budget (offline, CPU) | Stops: "none" gain under 25%; net under +15; "all" loss over 10%. Prediction: a STOP (net −20 to +5) | "none" gain 46.0%, "all" loss 6.9%, net estimate +23.9 (+22.8 corrected, about +2.8 points, a ceiling). **Passes; continues.** The base model is not fetched. Next: a reranking stage behind a flag, design reviewed first, then one GPU gate (pass above +1.9 points; kill at 0 or below, or category-5 refusals down more than 5 points) |
| B578 reranking stage, design and GPU gate (review session, 2026-11-18, under the user's delegation) | ND-5 passed offline; bucket-move estimate +20.5 questions, +2.5 points (an upper bound); design in the plan lead's reports, no code written | **Approved:** the design as sent, with graph-vote turns **pinned** (they keep their slots; the reranker fills the other N − pinned). Then one GPU gate once the code PR is merged: a retrieval-only replay on step 4's s4p_* stores, both arms at the same main commit with today's defaults, CAMPY_TURN_RERANK 0 against 1. Lines as registered: pass above +1.9 points on the 809; kill at 0 or below, or category-5 correct refusals down more than 5 points. Prediction +0.5 to +2.5 points, so the pass line is a real risk. Reasons: the gap is ranking, not reach (ND-5: 46.0% of "none" questions gain a gold turn, 6.9% of "all" lose one, against 29.4% for vector rank); the graph vote is a subject-anchored query, and a model's score does not override it (P2, P3); turns stay verbatim and source-linked, nothing is stored and there is no new edge (P2, P3); the construction is ND-5's, with nothing swept on the 809 (P4); a structural retrieval change behind a flag, off by default (P5, P7); same stores and commit in both arms, so only the lever differs (P6). Cost: about +4 minutes per arm on the CPU |
| Four decisions after run 5 (user, 2026-11-17 afternoon) | run 5's kill, full history, the published judge, the capture rebuild | User, "go with your recommendations": run 5's kill kept; full history probed again at an 8% answering line, the full run only under 40 hours; published-judge re-score of the control and run 5 as a separate column; capture rebuild (B542) next, design first |

Before this plan: the whole `principled` profile was gated on 300 questions (2026-11-07) and tied `main` on
replay (0.480 vs 0.480). 21.6% of facts in that store link to an object entity; no question was answered by a
graph query.
