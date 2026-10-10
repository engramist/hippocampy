# M2.1 cross-encoder reranker: better retrieval, worse answers (closed)

2026-10-10. hippocampy#301 (card B477), closed after its one fix attempt.
Branch `claude/e2e-m2-1-reranker` kept for a re-test after the
answer-model ablation (R40).

## What was tried

After RRF fusion in `GraphGateway._bundle_conversation`, the best 50
candidates were re-scored by a small MS MARCO cross-encoder (fastembed ONNX,
`Xenova/ms-marco-MiniLM-L-6-v2`, ~90 MB, ~240 ms per 50 pairs on CPU)
before the top-6 cut.

## Numbers

Offline (campy-benchmarks#36, `diag_locomo10_fusion.py --variant rerank`,
R24a store): LoCoMo-10 evidence-turn recall at limit 6 went from 0.327 to
0.469 (questions with any evidence turn in the bundle: 15 → 21 of 36).

T0 gates (`eval_gate.py`, golden R24 stores, judge gemma4:26b, 3 votes):

| gate | suite | main | branch | gained | lost |
|---|---|---|---|---|---|
| R34: replace order, turns scored as "Speaker N: text" | DMR dev | 0.520 | 0.400 | 2 | 8 |
| | LoCoMo-10 dev | 0.317 | 0.383 | 7 | 3 |
| R38: bare text, RRF blend with the fused rank, vs main with the cite prompt | DMR dev | 0.600 | 0.540 | 2 | 5 |
| | LoCoMo-10 dev | 0.350 | 0.283 | 2 | 6 |

## What we learned

- **The speaker label misleads the cross-encoder.** DMR questions read
  "Speaker 2 asks Speaker 1 … what Speaker 1 said". Scored against
  "Speaker 2: …", the other speaker's turns won. In every R34 DMR loss the
  right speaker's turn was replaced by the other speaker's.
- **Better recall did not become better answers.** This is the campaign's
  lesson 5 again (more or better turns ≠ accuracy). With the cite prompt
  (#299) the 8b model already uses what it gets. Changing which 6 turns it
  gets moved about as many answers each way, and lost on balance.
- **A one-off variant win is not a code win.** R34's LoCoMo-10 gain
  disappeared against main with the cite prompt (R38).

## Open

R40 replays both trees with gemma4:26b answering. If a stronger answer
model turns the recall gain into accuracy, the reranker comes back paired
with that model, or with an answer step that reads more candidates. Otherwise
it stays closed.
