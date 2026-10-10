# E2E plan status

Live state of `e2e-improvement-plan.md`. Update after every step; keep it
short and current (history goes in dated `learnings/` notes).

_Last updated: 2026-10-10 16:30 UTC_

## Who is running this

- **Lead:** the local Claude session "Hippocampy learnings folder
  integration" on the user's machine (took over from the cloud agent
  `user-bd` on 2026-10-10). Implementation is delegated to subagents, one
  at a time.
- **Local benchmark agent:** the peer session "B463: ask reaches the current
  value…" (stable id `ccb12e37-1a8b-4231-b243-40d40f14b1bd`). Requests now
  go by direct session message; R-numbers continue. Results land in
  `/tmp/cb-q27/results/` and its `local/results` branch.

## Current position

- **Milestone:** M0 nearly done; M1 and M2.1 in progress in parallel (code
  is cheap, the GPU is the bottleneck).
- **GPU queue:** R32 (rejudge, running) → R33 (gate #299) → R30 (held-out
  baselines + golden copies) → R20d (LME s, ~15 h) → R31 (noise repeats).
- **Next R-number:** R34.

## Pins

| Repo | Commit | What it contains |
|---|---|---|
| hippocampy main | `2b22bed` | + B474 `[retrieval] conversation_order` (default "time") |
| campy-benchmarks master | `2af2ccc` | + held-out selection, `--hippocampy`/`--llm-model` replay, `eval_gate.py` (#34), DMR persona judge rule, `--judge-votes`, `rejudge.py` (#35) |

## Gate results

| Item | PR | suite | main | branch | gained | lost | verdict | outcome |
|---|---|---|---|---|---|---|---|---|
| M1.1 rank order | hippocampy#298 | DMR dev (R24b) | 0.500 | 0.500 | 3 | 3 | within noise | merged as opt-in flag, default "time" |
| | | LoCoMo-10 dev (R24a) | 0.300 | 0.333 | 3 | 1 | within noise | |

R27 (bundle-variant replay) had shown rank order +5/−1 (DMR) and +5/−2
(LoCoMo-10) on R24 stores and −4 on the text-mode R20 stores; the real
implementation (R29) also changed the section description and did not
reproduce the gain. Lesson: a variant replay that changes one thing is not
the same as code that changes two.

Judge change (R32, persona rule + 3 votes): R24b 0.50 → 0.52 (1 flip),
R20a 0.62 → 0.62 (0 flips). Judge noise was small.

## Open PRs

- hippocampy#299 — M1.3 cite-or-abstain prompt (`[ask] answer_style`), gate R33 queued.
- hippocampy#300 — M1.2 `Message.turn_index` (write path, needs T2) + near-duplicate collapse (read path); stacked on #299.
- hippocampy#301 — M2.1 cross-encoder reranker (`[retrieval] reranker`, off by default; `CAMPY_RETRIEVAL_RERANKER` env override). Offline: LoCoMo-10 evidence recall at limit 6, 0.327 → 0.469.
- campy-benchmarks#36 — `rerank` variant in `diag_locomo10_fusion.py`.

## Latest numbers (fields mode unless noted)

| Suite | Accuracy | Evidence recall | Run |
|---|---|---|---|
| LoCoMo-10 conv-26 (60) | 0.396 | 0.496 | R24a, `9c5c9d8` |
| DMR (50) | 0.500 (0.52 rejudged) | 0.580 | R24b, `9c5c9d8` |
| DMR (50), text mode | 0.620 | 0.531 | R20a, `402c96c` |
| LongMemEval oracle (35) | 0.600 | 0.613 | R20b, `402c96c` |
| LongMemEval s (7) | 0.429 | 0.139 | `98ec223` |
| Fixture | 28/28, 0 INVERTED | – | R23c, `e78ac3b` |

## Golden stores (M0.1 done, R28)

`~/campy-golden/` on the local machine (477 MB):

- `r24a/r24a-locomo10-q60-fields.golden.json`, store `r24a/stores/campy-bench-_g7_nemi`
- `r24b/r24b-dmr-q50-fields.golden.json` (50 stores)
- `r20c/r20c-locomo10-q60-baselines.golden.json`, store `r20c/stores/campy-bench-8ku42y31`
- `r20a/r20a-dmr-q50-baselines.golden.json` (50 stores)
- held-out `r30a` (DMR offset 50) and `r30b` (LoCoMo-10 conv-30): pending R30

## Noise floor

Not measured yet (M0.3, R31). Assume ±4 points at n=50–60.

## Next three actions

1. R33 result → merge or close #299.
2. Gate #301 (reranker on, and reranker + rank order) on DMR and LoCoMo-10 dev, then held-out once R30 lands.
3. Gate #300's read-path half; schedule a T2 run for its write-path half.
