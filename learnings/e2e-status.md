# E2E plan status

Live state of `e2e-improvement-plan.md`. Update after every step; keep it
short and current (history goes in dated `learnings/` notes).

_Last updated: 2026-10-10 14:00 UTC_

## Current position

- **Milestone:** M0 — evaluation infrastructure.
- **In flight (local agent):** R27, the corrected answer replay
  (`diag_answer_replay.py` variants on R20a/R24b DMR and R20c/R24a LoCoMo-10
  stores; started 12:14 UTC). Then R20d, LongMemEval s at 30 questions
  with baselines and `diag_lme_fusion.py` (~15 h; paused for R27, restarts
  automatically).
- **Next R-number to use:** R28 (check #278 first).

## Pins

| Repo | Commit | What it contains |
|---|---|---|
| hippocampy main | `0a7a888` | B472 Phases 0–2 + 1b, B473, #296 (Step 1b replace-with fix) |
| campy-benchmarks master | `a201a3e` | baselines with retry, turn-metadata fields, `diag_answer_replay.py`, `diag_graph_audit.py` |

## Latest numbers (fields mode unless noted)

| Suite | Accuracy | Evidence recall | Run |
|---|---|---|---|
| LoCoMo-10 conv-26 (60) | 0.396 | 0.496 | R24a, `9c5c9d8` |
| DMR (50) | 0.500 | 0.580 | R24b, `9c5c9d8` |
| DMR (50), text mode | 0.620 | 0.531 | R20a, `402c96c` |
| LongMemEval oracle (35) | 0.600 | 0.613 | R20b, `402c96c` |
| LongMemEval s (7) | 0.429 | 0.139 | `98ec223` |
| Fixture | 28/28, 0 INVERTED | – | R23c, `e78ac3b` |

Baselines (R20, `402c96c`): LoCoMo-10 no-memory 0.021 / naive RAG 0.375 /
full 0.479; DMR 0.120 / 0.580 / 0.800; LME oracle – / 0.629 / 0.571.

## Golden stores

Not yet preserved (M0.1). Known paths on the local machine (volatile,
`/tmp`):

- R24a LoCoMo-10: `/tmp/campy-bench-_g7_nemi`
- R20c LoCoMo-10: `/tmp/campy-bench-8ku42y31`
- R24b and R20a DMR: one store per question, listed in each result JSON's
  `store` fields (`results/r24b-dmr-q50-fields.json`, R20a's DMR results).

## Noise floor

Not measured yet (M0.3). Assume ±4 points at n=50–60 until then.

## Open PRs

- engramist/hippocampy#297 — this `learnings/` folder (docs only).

## Next three actions

1. Process R27 when posted → decide M1.1 (see plan Part E, M1.1).
2. Post R28: preserve golden stores (M0.1) and run the noise-floor repeats
   (M0.3) after R20d, or before it if R20d is not yet restarted.
3. Implement M0.2 (held-out selection flags) and M0.4 (branch replay +
   `eval_gate.py`) in campy-benchmarks.
