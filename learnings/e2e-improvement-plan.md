# Plan, 2026-11-10: put the facts in the graph, then answer from it

Approved 2026-11-10. Revised 2026-11-12 (see "Revision, 2026-11-12" below). Replaces the plan last touched 2026-10-21 (in git history).

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

Each step is one PR, designed and reviewed against `skills/campy-graph/SKILL.md` before code. Order since 2026-11-13 (ruled by the user): 0c, 0d, Q done; then 3 on today's query hits, then 1 (roles option B), then 2 folded into 1 where it is the same construction, then 3 re-measured, then 4. Step 0e is done.

| # | Step | Measure | Passes when | Killed when |
|---|---|---|---|---|
| 0 | **Fix the test.** Ask all 809 cat 1-4 questions of the five gate conversations, not 300. Replay `main` on its kept store as the new baseline. Fix the 8 unparseable evidence labels. Recall also counts a fact in the prompt whose source turn (`EVIDENCED_BY`) is a gold turn, so an answer from the graph is visible to the measure. | Noise on the score | Noise falls from about ±9 of 300 to about ±15 of 809 (±0.03 to ±0.018) | — |
| 0b | **Write the fact contract.** One page: what Campy hands any consumer. A fact is subject, relation, object, date and source turn (`HAS_SUBJECT`, `HAS_OBJECT`, `INSTANCE_OF`, `EVIDENCED_BY`). A computed result (count, list, latest) is marked as computed and keeps its source turns. Design only, no code. | The contract names every edge capture must write | You approve it; it is the target for steps 1-3 | A question type in LoCoMo cat 1-4 that the contract cannot express: revise before step 1 |
| 0c | **Make the replay match the gate.** Capture each of the five conversations into its own store (flag-off `principled`, and `main`), and replay each conversation's questions on its own store. Today 240 to 266 of 809 replay prompts carry turns from another conversation, which the live gate never does. | Prompts holding another conversation's turns; the 809 baseline re-stated | 0 such prompts; the new baseline for both arms is in `e2e-status.md` and replaces the step-0 figures | — |
| 0d | **Review the questions no arm has answered.** From the stored answers of every replay arm (both profiles, every member-off arm, the stronger reader), list the questions wrong in all of them. Read each with its gold turns and class it: answer key or label wrong, evidence not in the conversation, or a real miss. No answer-key values go in the repo; ids and counts only. | Always-missed questions, by class | The list is classed and the key-fault ids are reported next to every later score (the 809 denominator does not change) | — |
| 0e | **Predictions enforced.** The `pr-score-effect` check requires a `Prediction:` line (expected measure and size) on PRs that touch capture, retrieval or answering. `scripts/drift_report.py` also counts how many merged changes moved a measure. | — | Both are live in CI | — |
| Q | **A thin answer-from-the-graph query, now.** One or two named query shapes on edges capture already writes (`HAS_SUBJECT`, `HAS_OBJECT`, `EVIDENCED_BY`, `INSTANCE_OF`, `BROADER`), anchored on the question's subject. Measured offline on the step-0c stores; nothing is added to the prompt yet. Its misses, classed by the edge that was absent, are the work list for steps 1 and 2. | Query hits on 809, per category; misses by missing edge | The baseline and the miss list are in `e2e-status.md`. The lines for steps 1 and 2 are set from it, in `RUNS.md`, and approved before either is built | The query cannot be anchored on a subject for more than half the questions: fix subject resolution first |
| 1 | **Capture writes the roles.** Read 50 unlinked facts and classify why (done: `learnings/step1-capture-roles.md`). Then capture writes action, with and place roles (`HAS_ACTION` to a WordNet action kind, `HAS_PARTICIPANT`, `HAS_PLACE`) next to the object, behind one flag. The 9 predicates stay. The first form (free spans in the fact prompt) was killed on 2026-11-11; the second form is a closed choice in a separate call, with the fact prompt untouched. | **Query hits** on re-captured conv-26 against step Q's baseline for that conversation. Mechanism checks: flag-on facts match flag-off exactly; of the facts shown options, the share that gets an edge; sense accuracy on 50 hand-checked actions; conv-26's 152 questions replayed flag on vs flag off. Reported, not gated: anchored share and shared share | Query hits rise by the line set from step Q, and every mechanism check holds (20% or fewer wrong senses; replay within 6 questions) | Query hits do not rise: stop, and bring it as a contract question, not a third form. Facts differ from flag-off, more than 20% wrong senses, or a replay drop of more than 6 questions: the step stops |
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

## Revision, 2026-11-12

What changed, and why. The reasons come from the first step-1 run and from a review of a similar project.

1. **Steps 1 and 2 are judged by query hits, not by a share of facts.** The step-1 lines had to be re-derived twice, and a share of facts can rise while no question becomes answerable. Step Q builds the thin query first so each capture change is measured by what it lets a query answer.
2. **Step 2 builds only what a query reads.** Kinds and chains written ahead of any reader are cost with no measure.
3. **The replay is fixed now (0c), not before step 3.** A known gap between the measured path and the real one should not sit under the headline number.
4. **The always-missed questions are reviewed (0d).** Doubt the answer key before the pipeline (P6).
5. **Every result gets a ruling**, so measured results do not sit undecided.
6. **Predictions are enforced in CI (0e)**, not kept by convention.

## Not known yet

- The query-hit lines for steps 1 and 2 do not exist until step Q's baseline is in.
- Step 1 needs GPU time to re-capture one conversation (about 1 hour a pass). Step 0c needs about ten captures once (five conversations, two profiles).
- No LoCoMo conversation is still unseen. LongMemEval is the only held-out set.
