# The adversarial-scoring fix, and the 2026-10-18/19 round (closed: #318, #319)

All gates are `eval_gate.py` replays on golden stores, judge gemma4:26b with 3
votes, McNemar on gained/lost. LoCoMo numbers here are re-scored with the
corrected adversarial scorer (below).

## The scoring bug (campy-benchmarks#41)

LoCoMo-10 category 5 (adversarial: the answer was never said) is scored by a
regex that detects an abstention. Since B475 (cite-or-abstain prompt) Campy
abstains with "I don't have that information", which no pattern matched, so a
correct abstention scored WRONG. On recent gate answers, recognised
abstentions went from 97/445 to 301/445 after the fix; 1 of 2135 judge-correct
ordinary answers is newly treated as a non-answer.

Consequences:
- Every LoCoMo number before the fix under-counts Campy. Re-score with
  `~/campy-lead/rescore5.py` (gate JSONs) or the fixed harness.
- The Observations gain (#305) was an artefact: corrected 66 gained / 63 lost,
  adversarial abstention 124 → 112. #320 turned Observations off by default.
- The B475 prompt's adversarial benefit was larger than measured.

## Corrected held-out baseline table (LoCoMo-10 conv-30, main before observations)

| | Categories 1–4 (judge) | Adversarial | All 60 |
|---|---|---|---|
| Campy | 0.364 (16/44) | 11/16 | **0.450** |
| Full history | 0.386 (17/44) | 6/16 | 0.383 |
| Naive RAG | 0.318 (14/44) | 5/16 | 0.317 |
| No memory | 0.068 (3/44) | 11/16 | 0.233 |

One conversation; indicative. Campy leads overall through abstention and is
within one question of full history on answerable questions.

## Closed this round

| PR | Change | Result (corrected) |
|---|---|---|
| #318 | One-hop observation expansion (M4.1) + fix (expand only on a strong first-pass match) | original 46/48 pooled; fix 25/28; held-out conv-44 5/9; multi-hop never moved |
| #319 | Read-time observation quality filter | conv-42 8/23 (p=0.011): tidier but less relevant observations |

## Lessons

- **Check the scorer against the system's own phrasing.** A prompt change
  (B475) changed how Campy abstains, and the scorer silently stopped
  recognising it. Any change to answer wording needs a scorer check.
- **Precision of retrieved items is not answer quality.** #319 doubled the
  hand-labelled precision of observations and lost accuracy.
- **Dev category patterns don't transfer reliably.** #318 helped factual
  questions on dev (29/11) and hurt them on held-out conv-44 (5/11).
