# Plan, 2026-11-10: put the facts in the graph, then answer from it

Approved 2026-11-10. Replaces the plan last touched 2026-10-21 (in git history).

## Goal

Raise LoCoMo categories 1-4 by making capture write subject-relation-object facts (P8) and answering from them by query (P2). The score is the verdict (P1). Two graph numbers are the leading checks, because they have no noise and need no GPU.

## Where we start

| Number | Today | Source |
|---|---|---|
| LoCoMo cat 1-4, `principled` vs `main` | 0.480 vs 0.480 | replay, 300 questions |
| Facts linked to an object entity | 21.6% (503 of 2,325) | latest gate store |
| Questions answered by a graph query | 0 of 300 | graph count fired on none |
| Relation types in use | 9; "did" and "has_attribute" hold 54% of facts | latest gate store |

## Paused until step 4

Retrieval and answer-stage levers, prompt layout, cap tuning, replay ablations, the parked LongMemEval runs. The concept walk stays off; it gets retested in step 4, when the edges it reads exist.

## Steps

Each step is one PR, designed and reviewed against `skills/campy-graph/SKILL.md` before code.

| # | Step | Measure | Passes when | Killed when |
|---|---|---|---|---|
| 0 | **Fix the test.** Ask all 809 cat 1-4 questions of the five gate conversations, not 300. Replay `main` on its kept store as the new baseline. Fix the 8 unparseable evidence labels. | Noise on the score | Noise falls from about ±9 of 300 to about ±15 of 809 (±0.03 to ±0.018) | — |
| 1 | **Capture writes the object.** Read 50 unlinked facts and classify why each has no object entity. Then change capture so every fact has an object entity or is flagged unanchored. Review whether 9 relation types are enough. | Object-linked share, on one re-captured conversation | 60% or more (estimate; reset after reading the 50) | Under 40%: stop and rethink the extraction form, don't patch |
| 2 | **Kinds and places.** Each object entity gets a kind (`INSTANCE_OF`, `BROADER`), and places get a `LOCATED_IN` chain, from a rule or an independent source, not from the extractor (P3). | Share of object entities with a kind | 70% or more (estimate) | The source can't type activities and places without per-dataset rules (P4) |
| 3 | **Answer from the graph.** List, count, latest and which-kind questions run a query anchored on the subject. Its rows, with their source turns, go in the prompt. | Questions where the query returns rows; accuracy on those | 100 or more of 809 fire, and accuracy on them beats the same questions on `main` | Fewer than 30 fire: the edges from steps 1-2 are still missing; go back |
| 4 | **Whole gate.** Fresh ingest, 809 questions, `principled` vs `main`. Then LongMemEval as the held-out check. | LoCoMo cat 1-4, LongMemEval overall | Net gain above noise (more than 15 questions) | — |

At step 4 every one of the 15 `principled` switches is either on by default or deleted. No third state.

## How I work under this plan

- Before each run, one line: the hypothesis, the expected size, the result that kills it.
- A conclusion goes to memory only after two measurements agree.
- Cards are filed with their fix, except blockers.
- I report results, not progress checks.
- If a step's graph number moves and the score doesn't, I say so and stop before starting another lever.

## Not known yet

- The 60% and 70% targets are estimates.
- Step 1 needs GPU time to re-capture one conversation (about 1.5 hours a pass).
- No LoCoMo conversation is still unseen. LongMemEval is the only held-out set.
