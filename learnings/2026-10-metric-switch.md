# Gates now score the benchmark's own metric (2026-10-19)

## What changed

Until today every LoCoMo-10 gate counted all five categories and required
McNemar p < 0.05, with held-out as a separate hurdle. The published LoCoMo
headline (and every comparison we would make with other memory systems)
counts categories 1–4 only; category 5 (adversarial, scored by abstaining)
is not in it.

New rule (user decision; plan C.5 and Part F updated):

- Score on the published metric: LoCoMo cat 1–4, LongMemEval overall, DMR
  accuracy. Track adversarial abstention as a separate number.
- Pool dev and held-out conversations as one sample.
- Merge when pooled gained > lost and the change points the same way in most
  conversations, with no other suite dropping beyond noise. No p threshold:
  changes are flags and reversible.
- Keep every measurement-correctness check (those, not significance tests,
  caught the real problems: the category-5 scorer, the judge reply cap, the
  `full_history` marker).
- Run the full benchmark every few merges to confirm the total moves.

## Why

The all-category gate hid the biggest gain since the token budget. B487
neighbour expansion (#322), N=1, re-scored on categories 1–4:

| Conversation | main | neighbours | gained | lost |
|---|---|---|---|---|
| conv-42 (dev) | 69/199 | 84/199 | 25 | 10 |
| conv-30 (held-out) | 17/44 | 20/44 | 5 | 2 |
| conv-44 (held-out) | 51/123 | 67/123 | 22 | 6 |
| **pooled** | **0.374** | **0.467** | **52** | **18** |

Adversarial abstention fell 83/112 → 62/112, which is why the all-category
gate read it as noise. #322 merged with N=1 on by default.

## Earlier closed gates, re-scored on categories 1–4

Pooled over the gate files still on disk (older ones were lost to /tmp cleanup):

| Change | gained / lost | conversations up | now |
|---|---|---|---|
| Observations (#305, off by default since #320) | 53 / 38 | 4 of 4 | re-gate on top of neighbours (R66) |
| Observation dates (#316) | 14 / 7 | 2 of 3, 1 flat | merged; matters only with observations on |
| Observation graph expansion (#318) | 36 / 24 | 3 of 4 | re-gate after R66 |
| #318 fix attempt | 21 / 15 | 3 of 4 | same |
| Observation quality filter (#319) | 7 / 17 | 0 of 1 | stays closed |
| Budget "fill" mode (#315) | 19 / 27 | 0 of 1 | stays closed |

The "Observations were a scoring artefact" correction in
`2026-10-m3-observations.md` holds for all categories; on the published
metric they are a modest, consistent gain.

## Recurring pattern

More context (neighbours, observations, expansion) helps answerable questions
and costs adversarial abstentions with the 8b answer model. Under the new
metric that trade is worth taking; abstention work (B489 verify, #326) is now
secondary and matters mainly for LongMemEval's abstention questions.

## Follow-up the same night (2026-10-19/20)

**Neighbour count (R64).** Against no neighbours, pooled cat 1–4 over conv-42/30/44:
N=1 0.467 (52/18), N=2 0.484 (60/20). Directly, N=2 vs N=1: conv-42 16/9, conv-30
4/4, conv-44 7/8 — pooled 27/21 but up on only 1 of 3 conversations, so the
default stays N=1. conv-43 gets a direct N=1 vs N=2 gate (R67).

**conv-43 hang (B494).** Both conv-43 neighbour gates died: one question made the
answer model generate until the 3-minute Ollama timeout, retried 4×, aborting the
replay. LLM calls had no output cap. B494 (#330) caps output at 2048 tokens and
logs a warning naming the question when the cap is hit.

**Observations back on (R66, #331).** On top of neighbours, golden stores
ingested with observations on, cat 1–4:

| Conversation | main | observations | gained | lost | adversarial |
|---|---|---|---|---|---|
| conv-42 (dev) | 0.422 | 0.472 | 18 | 8 | 36 → 43 /61 |
| conv-30 (held-out) | 0.455 | 0.545 | 6 | 2 | 8 → 10 /16 |
| conv-44 (held-out) | 0.545 | 0.569 | 8 | 5 | 17 → 18 /35 |
| **pooled** | **0.467** | **0.514** | **32** | **15** | **61 → 71 /112** |

Unlike neighbours, observations also improve adversarial abstention. Merged as
the default (revert of #320).

**Harness (B491, campy-benchmarks#42).** Gate JSONs now carry each side's SHA,
dirty flag and `CAMPY_*` env, plus every model call and `meta` per question.
First used on R66; it worked.

## Final numbers for the night (2026-10-20)

**Observations, all four conversations (R66).** conv-43 (run last, after B494)
came in at 0.500 → 0.522 (17/13), adversarial 29 → 33. Pooled over conv-42/30/44/43:
cat 1–4 0.478 → 0.517, 49 gained / 28 lost, up on 4 of 4; adversarial 90 → 104 /176.

**The runaway question.** conv-43 q66 (a Star Wars book recommendation): the answer
model loops on "'The Essential Atlas' is not a book, so I'll suggest…" on both
sides. With B494 it stops at ~7.5k characters; the replay completes.

**Neighbour count (R67, conv-43).** N=0 vs N=1: cat 1–4 0.483 → 0.500 (15/12),
adversarial 43 → 29 — neighbours are up on 4 of 4 conversations. N=1 vs N=2
directly: 0.500 → 0.556 (15/5), adversarial 29 → 32. With R64, N=2 vs N=1 over four
conversations: 16/9, 4/4, 7/8, 15/5 — pooled 42/26. Default changed to N=2 (#333).
These neighbour gates ran with observations off; R69 (fresh ingest on the six
unseen conversations, main `8c38d23`) checks the combination.
