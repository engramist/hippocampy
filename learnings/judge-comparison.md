# Our LoCoMo judge against the published ones

Compared on 2026-11-17 at the user's request. Nothing about our judge changes: any change is a user decision with its own pre-registered re-scoring.

## Sources (read from the released code at a pinned commit, not from memory)
- **Mem0:** `evaluation/metrics/llm_judge.py`, `ACCURACY_PROMPT`, in mem0ai/mem0 at commit b3ede5b7. The folder was removed from `main` in the next commit, 9315e303. The paper (arXiv 2504.19413) prints the same template in Appendix A and reports the mean of 10 runs, ± 1 standard deviation.
- **Zep:** `kg_architecture_agent_memory/locomo_eval/zep_locomo_eval.py`, `locomo_grader`, in getzep/zep-papers at commit 4434662f.
- **MemOS:** `evaluation/scripts/locomo/locomo_eval.py`, `locomo_grader`, in MemTensor/MemOS at commit e8204062.
- **Ours:** `locomo10/scoring.py` `JUDGE_TEMPLATE` and `judge_one`, in the campy-benchmarks harness, as used by every arm on the scoreboard.

**The three published judges are one prompt.** Zep and MemOS reuse Mem0's instructions word for word: Zep adds a one-line system prompt and MemOS copies Zep's. So there is one published judge to compare against.

## Settings

| | Published (Mem0 / Zep / MemOS) | Ours |
|---|---|---|
| Judge model | one small hosted model, temperature 0 | the local 26B judge, temperature 0 |
| Calls per answer | 1. Mem0 repeats the whole evaluation 10 times and averages; MemOS's run count is configurable, default 1 | 2 calls with the fields in different orders; a third decides if they disagree |
| Output | one sentence of reasoning, then the label (Mem0 asks for JSON; Zep uses structured output) | one word |
| Before the judge | none | a pure abstention fails without a judge call |
| Category 5 | skipped | scored separately by the abstention rule, never judged |

## Rules that can move a verdict

| Case | Published | Ours |
|---|---|---|
| Default leaning | Be generous: a longer answer that "touches on the same topic as the gold answer" is CORRECT | CORRECT only if it states the key information and nothing in it contradicts the gold |
| An answer that says the information is unavailable, then gives it | Not addressed. Under the generosity rule it would usually pass, since it touches the topic | WRONG: the template names "says the information is unavailable" as a reason |
| A partial answer or partial list | Not addressed; the generosity rule leans CORRECT | WRONG: "only partly answers" is a reason, and a list "must contain the gold items" |
| Hedging between alternatives | Not addressed | WRONG |
| Dates | CORRECT if the answer refers to the same date or period, in any format, relative references included | CORRECT if it refers to the same date or period in any format, including a relative form that resolves to it. In practice, about the same |
| Vague dates ("a few days ago", "around then") | Generosity, plus "same time period", leans CORRECT | Must resolve to the gold date or period, otherwise WRONG |

## What this means for comparing numbers
- Our judge is stricter on every case where the two differ. On LoCoMo, a score from our judge is a lower bound on what the published judge would give the same answers.
- The size of the difference is not measured. It would take re-scoring stored answers with the published template: a user decision, pre-registered, with its own judging time.
- The known size of one piece: in every arm about 3 points are answers that decline and then give the key (counted 2026-11-17). Under the published wording these would mostly pass.
