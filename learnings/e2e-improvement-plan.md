# Plan, 2026-11-10: put the facts in the graph, then answer from it

Approved 2026-11-10. Revised several times since; the latest is "Revision, 2026-11-18" below, and the revisions read in date order. Replaces the plan last touched 2026-10-21 (in git history).

## Goal

Raise LoCoMo categories 1-4 by making capture write subject-relation-object facts (P8) and answering from them by query (P2). The score is the verdict (P1). The leading check is **query hits**: of the 809 questions, how many a subject-anchored named query answers with rows whose source turn (`EVIDENCED_BY`) is a gold turn. It has no noise and needs no GPU. Shares of facts with an edge are reported, never gated: a share can rise while no question becomes answerable.

## Where we start

| Number | Today | Source |
|---|---|---|
| LoCoMo cat 1-4, `principled` vs `main` | 0.480 vs 0.480 | replay, 300 questions |
| Facts linked to an object entity | 21.6% (503 of 2,325) | latest gate store |
| Questions answered by a graph query | 0 of 300 | graph count fired on none |
| LoCoMo cat 1-4 on all 809 questions, `principled` vs `main` | 0.517 vs 0.514 (noise about ±14 questions) | step 0 replay |
| Evidence recall, graph-aware | 0.748 both | step 0 replay |
| Query hits | not measured yet | step Q sets it |
| Relation types in use | 9; "did" and "has_attribute" hold 54% of facts | latest gate store |

## Paused until step 4

Retrieval and answer-stage levers, prompt layout, cap tuning, replay ablations, the parked LongMemEval runs. The concept walk stays off; it gets retested in step 4, when the edges it reads exist.

## Steps

Each step is one PR, designed and reviewed against `skills/campy-graph/SKILL.md` before code. Order since 2026-11-16 (ruled by the user; see the revision below): 0, 0b-0e, Q, 1 (form 3, the "we" anchor, the full re-capture) done; then object-text matching by vector (built behind a flag, then OT-1), then 3 re-measured with it (S3-OT) and as built (S3-asbuilt), then the baselines on the 809 as a reference, then 4.

| # | Step | Measure | Passes when | Killed when |
|---|---|---|---|---|
| 0 | **Fix the test.** Ask all 809 cat 1-4 questions of the five gate conversations, not 300. Replay `main` on its kept store as the new baseline. Fix the 8 unparseable evidence labels. Recall also counts a fact in the prompt whose source turn (`EVIDENCED_BY`) is a gold turn, so an answer from the graph is visible to the measure. | Noise on the score | Noise falls from about ±9 of 300 to about ±15 of 809 (±0.03 to ±0.018) | — |
| 0b | **Write the fact contract.** One page: what Campy hands any consumer. A fact is subject, relation, object, date and source turn (`HAS_SUBJECT`, `HAS_OBJECT`, `INSTANCE_OF`, `EVIDENCED_BY`). A computed result (count, list, latest) is marked as computed and keeps its source turns. Design only, no code. | The contract names every edge capture must write | You approve it; it is the target for steps 1-3 | A question type in LoCoMo cat 1-4 that the contract cannot express: revise before step 1 |
| 0c | **Make the replay match the gate.** Capture each of the five conversations into its own store (flag-off `principled`, and `main`), and replay each conversation's questions on its own store. Today 240 to 266 of 809 replay prompts carry turns from another conversation, which the live gate never does. | Prompts holding another conversation's turns; the 809 baseline re-stated | 0 such prompts; the new baseline for both arms is in `e2e-status.md` and replaces the step-0 figures | — |
| 0d | **Review the questions no arm has answered.** From the stored answers of every replay arm (both profiles, every member-off arm, the stronger reader), list the questions wrong in all of them. Read each with its gold turns and class it: answer key or label wrong, evidence not in the conversation, or a real miss. No answer-key values go in the repo; ids and counts only. | Always-missed questions, by class | The list is classed and the key-fault ids are reported next to every later score (the 809 denominator does not change) | — |
| 0e | **Predictions enforced.** The `pr-score-effect` check requires a `Prediction:` line (expected measure and size) on PRs that touch capture, retrieval or answering. `scripts/drift_report.py` also counts how many merged changes moved a measure. | — | Both are live in CI | — |
| Q | **A thin answer-from-the-graph query, now.** One or two named query shapes on edges capture already writes (`HAS_SUBJECT`, `HAS_OBJECT`, `EVIDENCED_BY`, `INSTANCE_OF`, `BROADER`), anchored on the question's subject. Measured offline on the step-0c stores; nothing is added to the prompt yet. Its misses, classed by the edge that was absent, are the work list for steps 1 and 2. | Query hits on 809, per category; misses by missing edge | The baseline and the miss list are in `e2e-status.md`. The lines for steps 1 and 2 are set from it, in `RUNS.md`, and approved before either is built | The query cannot be anchored on a subject for more than half the questions: fix subject resolution first |
| 1 | **Capture writes the roles.** Read 50 unlinked facts and classify why (done: `learnings/step1-capture-roles.md`). Forms tried: free spans in the fact prompt (killed 2026-11-11), a closed choice (option B, killed 2026-11-14), and form 3, a rule proposing candidate words with a closed choice (the last form). After the full re-capture of the five conversations (2026-11-16): **the action role (`HAS_ACTION`) is dropped** (21 of 100 words wrong) and the model-chosen partner was dropped on 2026-11-15. **Kept:** place (`HAS_PLACE`), the rule-written partner (`HAS_PARTICIPANT`) and the rule-written "we" anchor (`HAS_SUBJECT` to the speaker, flag `group_anchor`). The 9 predicates stay. | **Query hits** on the five re-captured conversations against flag-off. Mechanism checks: facts match flag-off; hand-checked words, places, "we" facts and partner links; the 809 replayed flag on against flag off | Query hits rise by the line set from step Q, and every mechanism check holds (20% or fewer wrong; replay within the line) | Query hits do not rise: stop, and bring it as a contract question. A mechanism check over its line drops that role (as the action role was) |
| 2 | **Kinds and places.** Only the kinds and chains that step Q's miss list shows a query needs: a kind for an object entity (`INSTANCE_OF`, `BROADER`), a kind for a common-noun place or partner, a `LOCATED_IN` chain. From a rule or an independent source, not from the extractor (P3). Nothing is written that no named query reads. | **Query hits** against the step-1 result. Reported, not gated: share of object entities with a kind | Query hits rise by the line set from step Q | The source can't type activities and places without per-dataset rules (P4); or query hits do not rise |
| 3 | **Answer from the graph.** Step Q's queries, widened to list, count, latest and which-kind questions, run anchored on the subject. Its rows go in the prompt in the contract's compact fixed-shape rendering for `ask`. | Questions where the query returns rows; accuracy on those | 100 or more of 809 fire, and accuracy on them beats the same questions on `main` | Fewer than 30 fire: the edges from steps 1-2 are still missing; go back |
| 4 | **Whole gate.** Fresh ingest, 809 questions, `principled` vs `main`. Then LongMemEval as the held-out check. | LoCoMo cat 1-4, LongMemEval overall | Net gain above noise (more than 15 questions) | — |

At step 4 every one of the 15 `principled` switches is either on by default or deleted. No third state.

**After step 4:** the contract's second rendering, structured output from the MCP tools plus a short skill for outside agents on how to read it. It gets its own measure before it is built, or it is not built.

## How I work under this plan

- Before any proposal, I state which graph edge the change reads or writes. If the answer is none, it is not in this plan.
- Before each run, one line: the hypothesis, the expected size, the result that kills it.
- A conclusion goes to memory only after two measurements agree.
- Cards are filed with their fix, except blockers.
- I report results, not progress checks.
- One session per step. Each starts from this file, not from a summary of an earlier chat.
- `python scripts/drift_report.py` runs at each step's result, and its verdict goes in the report.
- If a step's graph number moves and the score doesn't, I say so and stop before starting another lever.
- Every result ends in a ruling, recorded in the Rulings table of `e2e-status.md`: kept, stopped, parked (needs the user to restart), or not ruled. A result is not left without one past the next step's start.
- A gain is claimed only from a replay on stored stores or when it exceeds the noise. Otherwise the report says "no measurable change".
- **After every test or trial, two documents are updated in the same PR as the result** (ruled by the user 2026-11-16):
  1. `lessons-learned.md` gets a detailed entry: why we ran it, what we did (edges read and written, flags, stores, what it was compared with), the lines set before the run, the result with its numbers, and the decision.
  2. This plan is updated if the result changes direction: a step added, dropped, reordered or redefined. The change is dated under a "Revision" heading with its reason. A change of direction is the user's ruling; the plan records it, it does not make it.
  A result PR without its lessons entry is not merged. `e2e-status.md` stays the current-state page.

## Revision, 2026-11-12

What changed, and why. The reasons come from the first step-1 run and from a review of a similar project.

1. **Steps 1 and 2 are judged by query hits, not by a share of facts.** The step-1 lines had to be re-derived twice, and a share of facts can rise while no question becomes answerable. Step Q builds the thin query first so each capture change is measured by what it lets a query answer.
2. **Step 2 builds only what a query reads.** Kinds and chains written ahead of any reader are cost with no measure.
3. **The replay is fixed now (0c), not before step 3.** A known gap between the measured path and the real one should not sit under the headline number.
4. **The always-missed questions are reviewed (0d).** Doubt the answer key before the pipeline (P6).
5. **Every result gets a ruling**, so measured results do not sit undecided.
6. **Predictions are enforced in CI (0e)**, not kept by convention.

## Revision, 2026-11-16

What changed, and why. Every change below was ruled by the user (2026-11-15 and 2026-11-16).

1. **The action role is dropped.** Form 3 was the last form, and its word line was hit on the full re-capture (21 of 100 written action words wrong). Offline, object-text matching reaches 57 of the action role's 61 gained hits with no action read. The `roles` flag stays off and in no profile; its code is removed by a later cleanup card.
2. **The model-chosen partner is dropped (2026-11-15).** 29 of 30 hand-checked links were wrong. A co-participant edge is written only by a rule.
3. **Kept:** place (`HAS_PLACE`, 4 of 30 wrong judged by the whole turn); the rule-written partner (61 written, 4 of 30 wrong); and the rule-written "we" anchor (flag `group_anchor`, 6 of 30 wrong), with the extraction prompt untouched.
4. **New step before step 3 is re-measured: object-text matching by vector.**
   - At question time, the question's words are matched against the object text of the subject's own live facts (cosine 0.75, top 3 per word; constants, not settings).
   - The matched facts are read by the same subject-anchored queries. Nothing is written.
   - Measured offline first (vecq-1: +116 net hits, 5 of 50 wrong; vecq-4: 279 and 275, the reference for the build).
   - Built behind `[retrieval] object_text_match`, default off. Run OT-1 checks that the build reproduces the reference.
5. **Step 3 is re-measured twice:** with object-text matching (S3-OT), then as built (S3-asbuilt), against the stored flag-off replay of the re-captured stores. S3-asbuilt is the control that isolates object text's own effect.
6. **Baselines on the 809 are added as a reference measurement, not a step:** no memory, naive retrieval and full history, with the same answer model, judge and settings as the step-0c replays. They run after S3-asbuilt, with no pass or kill line. The last baselines were on 44-60 questions in October.

## Revision, 2026-11-16 (evening)

Step 3 is killed in both forms re-measured on the re-captured stores: with object-text matching (net -20) and as
built (net -11), against the stored flag-off replay. The gold-only ceiling (+9 and +13) is under the +15 line, so the
fire rule alone would not rescue it; the section mostly repeats turns already in the conversation section (249 of
279). Step 4 does not start on top of step 3. What comes next is held for the user. The baselines on the 809 run
meanwhile as the reference the next direction will be read against.

## Revision, 2026-11-16 (night)

Ruled by the user. The kill of step 3 is accepted: graph facts are not fed to the answer model as a prompt section, in either form, and no fire rule is tried. Step 4 (the whole gate) has no candidate to gate, so it waits. No new lever starts until the baselines on the 809 are reported; the next direction is the user's ruling, read against the full-history baseline and the coverage table. What the capture work produced stays on main behind flags (place, the rule-written partner, the "we" anchor, object-text matching), unused by any profile.

## Revision, 2026-11-17

Ruled by the user after reading why answers fail with all their evidence in view (the reader declines: 8.3 points; a strict scorer: about 3 points in every arm; misreadings: the rest of 18.8). Three items are added after the baselines, each with a design approved before code and its own pre-registered run. None is step 4.

1. **Fact sentences built by rule.** The subject's matching facts are rendered as plain sentences by fixed templates, with no model call, each attached to its source turn in the conversation section. Behind a flag; exact labels only. It reads the same edges as step Q and writes none.
2. **A second score.** Beside the strict score, the same judging with an opening refusal ignored (a pure refusal still fails), applied to every arm. The strict score stays the headline.
3. **The abstain instruction.** One replay with a changed instruction, measured on the 809 and on the adversarial questions together, so the trade is visible. This is a wording change (P5): one arm, pre-registered, no tuning.

**Order (ruled by the user 2026-11-17):** the running baselines job (no memory, naive retrieval, the timing probe) finishes first; then the second score, fact sentences and the abstain-instruction replay, as each is ready; full history last. The run queue is kept at the top of `e2e-status.md`.

**Outcome (ruled by the user 2026-11-17 morning):** fact sentences stopped at their faithfulness check and are left stopped (the code is not merged); the second score is dropped after failing its agreement check, so only the strict score is reported; full history is decided after the abstain replay; the capture rebuild (B542) is the next direction question.

Still open and not scheduled: the rebuilt capture lane (B542), which is what would make the triples richer than nine predicates and a free-text object.

## Revision, 2026-11-17 (afternoon)

Ruled by the user in the plan lead's session ("go with your recommendations"), after run 5 and the speaker-rule counts.

1. **The abstain instruction (run 5) stays killed.** It gained +6.3 points on the 809, but category-5 refusals fell 27.1 points against a 10-point line. The flag stays off.
2. **The speaker rule is not pursued.** It would stop 16 of the 60 category-5 answers and leave refusals about 20 points down, still outside run 5's line.
3. **The capture rebuild (B542) is the next direction.** About a third of stored facts are wrong (FACT-ACC, 35 of 100), and every graph lever so far has run on those facts.
   - A design comes first, and no GPU until the user approves it.
   - The design names every edge it writes.
   - Its measures include: the hand-read fact accuracy on a fresh 100-fact sample against FACT-ACC's 35%, with the same labels and reader rules; query hits; and the 809 replay.
4. **Full history:** one more 5-question probe at an 8% answering line (the flag file, for the probe only), with the 30 GB swap ceiling. The full run needs the projection under 40 hours and a check with the review session first, since it takes a day or more on a machine the user also uses.
5. **The published judge:** the stored control and run-5 answers are re-scored with the published LoCoMo judge prompt (Mem0 @ b3ede5b7; Zep and MemOS reuse it), category 5 skipped as theirs. It is a separate column, and our judge stays the headline.

## Revision, 2026-11-18

Ruled by the user ("Close B542"), after the B542 screens.

1. **The capture rebuild (B542) is closed as built.**
   - With the 8B reader, parse rules on the closed-question lane gave no accuracy gain on a paired, blinded reading (52 wrong of 100 against llm-1's 53), and kept only 38% of llm-1's right facts.
   - The larger reader looked better on two conversations (15 wrong of 40 against 19), but it does not fit on this machine under the 12% memory line: the guard stopped its job 78 seconds in.
   - The flag, the `fact_status` property and the reader filter were never built.
2. **FACT-ACC's 35% is not a stable baseline.** Fresh llm-1 facts read blind came out 53 wrong of 100. A future capture change is measured by a paired, blinded reading against fresh llm-1 facts, not against a stored figure.
3. Capture stays llm-1. No next direction was ruled with this closure.
4. **Outcomes of the 2026-11-17 (afternoon) items:**
   - **Run 5's kill is kept.**
   - **Full history:** the second probe, at the 8% line, was stopped by the memory guard before its first answer (free 5-6%, answer model at 20.9 GB). Run 6 is held for the user. The review session recommends skipping it and not lowering the guard.
   - **The published judge:** recorded as a separate table in `e2e-status.md`. Control 69.8%, run 5 75.4% (+5.6 points). It never decides a pass or kill.

**Since then (user, 2026-11-18: "follow the plan"):** step 4, the whole gate, is running as written in the steps table. It is a fresh ingest of the 809, `principled` against `main`, on main 949d6353, which holds four default-on capture fixes made since step 0c. Pass above +15 questions net, with no kill line. Its result leads to the ruling on the 15 principled switches.

**Full history (run 6) is skipped** (user, 2026-11-18).

**Delegation (user, 2026-11-18).** The review session may pick a new direction and start GPU experiments, "just have good reasons for why you did them". The guard lines and the other standing constraints are unchanged.

**Next direction, picked by the review session (2026-11-18): retrieval coverage by subject-anchored turn retrieval.**
- **The gap is retrieval, not the reader.** On the control, a question with every gold turn in the prompt is right 71.0% of the time (64.8% of questions). With some gold turns it is right 14.9% (11.6% of questions), and with none 24.1% (23.1%). Moving the last two groups to the first group's rate is worth at most about 17 points on the 809. That is an upper bound, not a forecast, but no other gap we have measured comes close.
- **Turns, not facts.** Stored facts are 35-53% wrong, depending on the reading. Graph facts in the prompt were killed three times, and the capture rebuild did not make facts more accurate on the 8B. So the graph chooses which turns reach the reader (P2), and the reader sees the verbatim turns, each linked to its source (P3). A wrong fact can then only cost a slot, never state a falsehood.
- **Why not the answer stage now.** Run 5 showed that making the reader answer more trades directly against category 5. The reader model is fixed by the machine's memory.
- **The plan already pointed here.** Retrieval levers were paused "until step 4", and step 4 is running.
- **Order:**
  1. **Edge check (P8):** does capture write what an anchored query needs, such as Message `MENTIONS` to the subject's Concept and `SPOKEN_BY`, on the 809's stores? If an edge is missing, capture is fixed first.
  2. **Offline sizing on store copies (no GPU):** for each "none" or "some" question, does a query anchored on its subject reach a missing gold turn within the prompt's turn budget? This gives a kill line before any GPU time.
  3. **A design reviewed against `skills/campy-graph/SKILL.md`,** with lines pre-registered: pass above +1.9 points on the 809; kill at 0 or below, or category-5 refusals falling more than 5 points.
  4. **One GPU gate,** queued after step 4 (job 1008) ends.
- **What would change the pick:** if the edge check or the sizing shows that anchored queries reach few missing gold turns, this direction is dropped before any GPU time. The next candidate is then the "some" group's multi-turn questions (category 1).
- **Outcome (review session, 2026-11-18): dropped on that stop.**
  - ND-1: the anchored query reached a gold turn in the top 10 on 9.6% of the "none" questions.
  - ND-2: with every name and noun simulated as MENTIONS, it reached 24.6%, about +2.7 points at most.
  - Both are under the 25% stop. Even in ND-2 the lexical query missed a gold turn on 36.5% of the "all" questions, so it is a weaker selector than the vector retrieval already in place.
  - **Corrected the same night:** ND-1 and ND-2 ranked by term match, so the drop covers only the lexical-anchored variant and option A. The vector-ranked anchored variant is measured as ND-3. Its stops: under 25% of the "none" questions gain a gold turn, or a net estimate under +15 questions. It is read in a replace mode and in an add-5 mode.
  - Then ND-4, the fallback: for the 74 category-1 "some" questions, where the missing gold turns rank in the existing retrieval and why they are cut. Its stop: fewer than 25 of the 74 with every gold turn in view at a budget of 30.
  - **ND-3 and ND-4 outcome (2026-11-18, night): both stopped.** ND-3 replace mode reaches 26.7% of the "none" questions but its net estimate is -60.4 questions (29.4% of the "all" questions lose a gold turn); add mode reaches 12.3%, net +10.2. ND-4: 12 of the 74 have every gold turn in the vector top 30, against 25. The direction has no surviving variant and is closed.

**Step 4 result (2026-11-18, night): no pass.** `principled` 54.1% against `main` 53.9% on the 809, +0.2 points, net +2 questions against the +15 line. Step 0c measured +0.7: the two agree that the profiles tie. As written above, each of the 15 principled switches now goes on by default or is deleted, as the user rules; LongMemEval stays parked. The next direction is the review session's to pick under the delegation, with its reasons recorded before anything runs.
  - No GPU until a candidate clears its own stops. Both measures wait for step 4 to end.

## Not known yet

- The query-hit lines for steps 1 and 2 do not exist until step Q's baseline is in.
- Step 1 needs GPU time to re-capture one conversation (about 1 hour a pass). Step 0c needs about ten captures once (five conversations, two profiles).
- No LoCoMo conversation is still unseen. LongMemEval is the only held-out set.

## Revision, 2026-11-18 (night): the switches ruled; next, reranking (ND-5)

- **The 15 principled switches** (review session, under the user's delegation, after step 4 tied): 14 on by default, and the concept walk (graph_linking_limit 12) deleted, its code removed under B576. Reasons are in the Rulings table. Code: B575. The step-4 cost check passed: principled capture took 1.03× main's time and its stores are 1.06× main's size.
- **Next direction: better ranking of the candidate turns, sized offline as ND-5** (review session).
  - **Why:** ND-3 and ND-4 show the missing gold turns are in the candidate set, but the question's MiniLM vector ranks them low (median rank 89.5). The budget, duplicates and anchor edges are not the cause. A stronger scorer over that set is the direct fix, and it keeps the reader on verbatim, source-linked turns (P3).
  - **ND-5:**
    - **Candidates:** for every question of the 809, the control prompt's conversation turns plus the top 100 Messages by stored vector score.
    - **Scorer:** a cross-encoder or a stronger embedding model already on disk; nothing is downloaded without the user's OK.
    - **Cut:** rerank, then cut to the control's own turn budget for the question (replace mode).
    - **Measures:** gold reach on none / some / all, and ND-3's net estimate by category.
  - **Stops:** under 25% of the "none" questions gain a gold turn; a net estimate under +15 questions; more than 10% of the "all" questions lose a gold turn.
  - **Runs:** CPU only, with the queue empty and the same memory gate. The prediction is set in `scratch/nd1/RUNS.md` before the run.
  - **If it clears:** a design reviewed against `skills/campy-graph/SKILL.md`, then one GPU gate: pass above +1.9 points, kill at 0 or below, or category-5 refusals falling more than 5 points.
  - **Outcome (2026-11-18):** cleared on the small cross-encoder. "none" gain 46.0%, "all" loss 6.9%, net estimate about +22.8 questions (a ceiling). The design is next, then the GPU gate.
  - **Next (review session, 2026-11-18): B578, a reranking stage** in the conversation section, behind `[retrieval] turn_rerank`, off by default. Graph-vote turns are pinned, since a model score does not override a graph query (P2, P3). Otherwise it is ND-5's construction, with nothing swept. One GPU gate on step 4's stores, both arms at the same commit: pass above +1.9 points, kill at 0 or below, or category-5 refusals down more than 5 points. Predicted +0.5 to +2.5 points by bucket moves, so a pass is not expected to be easy. Reasons are in the Rulings row.
