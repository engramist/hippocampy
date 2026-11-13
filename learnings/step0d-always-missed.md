# Step 0d: the questions no arm has answered

_2026-11-12. Plan step 0d. Ids and counts only; no answer-key values. Working files: `~/campy-lead/scratch/step0d/`._

## What was read

**Arms.** The stored verdicts of 16 replay arms:
- the two 809-question arms of step 0 (`main` on R107, `principled` with the walk off on R111);
- 14 arms on the 300-question subset: the B563 ablation (every member-off arm), the walk-merge arms, and both profiles
  with the stronger reader.

**Always-missed.** A question is always-missed when every arm that asked it judged it wrong.

**How each was classed.** Each always-missed question was read with its gold turns (2 turns either side, session dates),
the answer key and two arms' answers. The conversation was searched in full before a question was classed "not in the
conversation". The lead spot-checked the classes.

## Result

337 of 809 questions are always-missed. 122 of them are in the 300 that all 16 arms asked.

| Category | Always-missed | Real miss | Key or label wrong | Not in the conversation |
|---|---|---|---|---|
| 1 multi-hop (153) | 109 | 96 | 10 | 3 |
| 2 temporal (171) | 65 | 56 | 9 | 0 |
| 3 open-domain (51) | 29 | 27 | 0 | 2 |
| 4 single-hop (434) | 134 | 124 | 10 | 0 |
| **All (809)** | **337** | **303** | **29** | **5** |

- **Key or label wrong (29).**
  - Value (18): the key contradicts the turns. Examples: a date resolved against the wrong weekday or year, a country
    that belongs to the other speaker, the question naming the wrong person.
  - Label (11): the evidence ids point to turns that do not hold the answer, while the answer is elsewhere in the
    conversation.
- **Not in the conversation (5).** The answer appears only in image metadata, or nowhere.
- **Flags.**
  - Judge doubt (24): an arm's answer matches the key in substance but was judged wrong. These are scorer cases (P6),
    not pipeline misses.
  - Ambiguous question (55): the question admits more than one fair reading.

**Size of the test faults.** 34 questions (4.2% of 809) are test faults (key, label or evidence). Another 24 are
possible judge errors. The 809 denominator does not change. These ids are reported next to every later score, so a
change that "gains" them can be read for what it is.

## The ids

- **Key wrong, value (18):** `conv-26_q138`, `conv-26_q5`, `conv-41_q48`, `conv-41_q62`, `conv-48_q123`, `conv-48_q155`, `conv-48_q174`, `conv-48_q179`, `conv-48_q87`, `conv-49_q24`, `conv-49_q54`, `conv-49_q74`, `conv-49_q80`, `conv-50_q137`, `conv-50_q151`, `conv-50_q19`, `conv-50_q50`, `conv-50_q88`
- **Key wrong, label (11):** `conv-26_q43`, `conv-26_q70`, `conv-26_q72`, `conv-41_q44`, `conv-41_q49`, `conv-48_q105`, `conv-48_q78`, `conv-49_q105`, `conv-49_q28`, `conv-50_q11`, `conv-50_q27`
- **Not in the conversation (5):** `conv-26_q23`, `conv-26_q56`, `conv-48_q75`, `conv-50_q1`, `conv-50_q39`
- **Judge doubt (24):** `conv-26_q136`, `conv-26_q149`, `conv-26_q5`, `conv-26_q57`, `conv-41_q147`, `conv-41_q74`, `conv-41_q93`, `conv-48_q12`, `conv-48_q120`, `conv-48_q150`, `conv-48_q151`, `conv-48_q155`, `conv-48_q159`, `conv-48_q166`, `conv-48_q18`, `conv-48_q189`, `conv-48_q5`, `conv-48_q51`, `conv-48_q68`, `conv-48_q7`, `conv-48_q98`, `conv-49_q154`, `conv-49_q19`, `conv-50_q125`

The 303 real misses are the pipeline's own work list. They are not listed here; `classes.json` in the working folder
holds them with their reasons.
