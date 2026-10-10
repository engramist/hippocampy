# E2E plan status

Live state of `e2e-improvement-plan.md`. Update after every step; keep it
short and current (history goes in dated `learnings/` notes).

_Last updated: 2026-10-10 22:00 UTC_

## Who is running this

- **Lead:** the local Claude session "Hippocampy learnings folder
  integration" on the user's machine (took over from the cloud agent
  `user-bd` on 2026-10-10). Implementation is delegated to subagents, one
  at a time.
- **Local benchmark agent:** the peer session "B463: ask reaches the current
  value…" (stable id `ccb12e37-1a8b-4231-b243-40d40f14b1bd`). Requests go by
  direct session message; R-numbers continue. Results land in
  `/tmp/cb-q27/results/`.
- **Rule:** never touch a worktree that a queued or running R-request
  references (gate replays start a fresh subprocess per store and import
  whatever is on disk). Update PR branches from a throwaway worktree with
  `git push origin HEAD:<branch>`.
- **Rule:** an import check (`python -c "import campy; print(campy.__file__)"`)
  run from inside a hippocampy checkout lies: `-c` puts the current directory
  ahead of `PYTHONPATH`. Run it from the harness worktree.

## Current position

- **Milestones:** M0 done except the noise floor (R31) and held-out baselines
  (R30). M1: M1.1 flag merged (opt-in), M1.3 merged (gain), M1.4 merged,
  M1.2 reduced to the turn ordinal (T2 in R39). M2.1 reranker on its one fix
  attempt (R38). M2.3 built (#307), not yet gated. M3a merged; 3b/3c built,
  T2 in R35, gate in R36.
- **GPU queue:** R38 (running) → R39 (T2 DMR with turn_index + stamp gate) →
  R30 (held-out baselines) → R35 (T2 LoCoMo-10 with observations) → R36
  (observation retrieval gate + nosem) → R20d (LME s) → R31 (noise repeats).
- **Next R-number:** R40.

## Pins

| Repo | Commit | What it contains |
|---|---|---|
| hippocampy main | `485e1b5` | + B474 `conversation_order` (default "time"), B475 cite-or-abstain prompt, B472 3a Observation schema, B478 de-dup on (speaker, text) |
| campy-benchmarks master | `96bbe24` | + `eval_gate.py`, held-out selection, `--hippocampy`/`--llm-model`, DMR persona judge rule, `--judge-votes`, `rejudge.py`, judge survives errors (no reply cap), "judge problems" count |

## Gate results (T0 replay on golden R24 stores, judge gemma4:26b)

| Item | PR | suite | main | branch | gained | lost | verdict | outcome |
|---|---|---|---|---|---|---|---|---|
| M1.1 rank order | #298 | DMR dev | 0.500 | 0.500 | 3 | 3 | within noise | merged as opt-in flag |
| | | LoCoMo-10 dev | 0.300 | 0.333 | 3 | 1 | within noise | |
| M1.3 cite or abstain | #299 | DMR dev | 0.520 | 0.600 | 5 | 1 | **real** | **merged** |
| | | LoCoMo-10 dev | 0.317 | 0.350 | 5 | 3 | within noise; adversarial 0/12 → 3/12 | |
| M2.1 reranker (replace, speaker-prefixed) | #301 | DMR dev | 0.520 | 0.400 | 2 | 8 | **regression** | fix attempt: bare text + RRF blend (R38) |
| | | LoCoMo-10 dev | 0.317 | 0.383 | 7 | 3 | real | |
| M1.2 near-duplicate collapse | #300 | both | = | = | 0 | 0 | no-op (never fired) | collapse removed |

Notes:
- The DMR reranker losses: the cross-encoder scored "Speaker 2: …" turns
  against questions framed "Speaker 2 asks Speaker 1 …" and promoted the
  other speaker's turns.
- The collapse never fired: max same-speaker same-session cosine on a golden
  DMR store is 0.69 (median 0.34). R26's "near-duplicates" were same-topic
  neighbours, not paraphrases.
- Judge change (persona rule + 3 votes, R32): at most 2 verdicts per file
  changed, baselines included.
- A 256-token judge cap (#37) made the reasoning judge reply empty and cost
  4/26 correct verdicts on identical answers (first R34a); removed in #38.
  Every report now carries a "judge problems" count.

## Open PRs

- hippocampy#300 — M1.2 `Message.turn_index` + `turn N` stamp (collapse removed); T2 + gate in R39.
- hippocampy#301 — M2.1 reranker, fix attempt (bare text, blend); gate R38.
- hippocampy#304 — M3b Observation extraction worker (off; `CAMPY_OBSERVATIONS_ENABLED`); T2 in R35.
- hippocampy#305 — M3c observation-fed semantic section (off; `CAMPY_OBSERVATIONS_RETRIEVAL`); stacked on #304; gate R36.
- hippocampy#307 — M2.3 speaker/time cue boosts (off; `CAMPY_RETRIEVAL_SPEAKER_BOOST`, `CAMPY_RETRIEVAL_TIME_BOOST`); not yet gated.

## Latest numbers (fields mode)

| Suite | Accuracy | Run |
|---|---|---|
| DMR dev (50), main with cite prompt, replay | 0.600 | R33/R37 |
| LoCoMo-10 dev (60, all categories), main with cite prompt, replay | 0.350 (adversarial 3/12) | R33/R37 |
| LoCoMo-10 conv-26 (judge accuracy, cat 1–4) | 0.396 | R24a, `9c5c9d8` |
| LongMemEval oracle (35) | 0.600 | R20b, `402c96c` |
| Fixture | 28/28, 0 INVERTED | R23c |

Replay numbers count all questions in the file (LoCoMo-10 includes
category 5) and are not directly comparable to run_all's judge accuracy.

## Golden stores (`~/campy-golden/`, local machine)

- `r24a/` LoCoMo-10 dev, store `stores/campy-bench-_g7_nemi`
- `r24b/` DMR dev (50 stores)
- `r20a/`, `r20c/` text-mode references
- pending: `r30a`/`r30b` (held-out), `r35` (observations on), `r39` (turn_index)

## Noise floor

Not measured yet (R31). Assume ±4 points at n=50–60.

## Next three actions

1. R38 → merge or close #301 (one fix attempt used).
2. R39 → decide #300; R30 → held-out check of #299.
3. Gate #307 (speaker/time boosts) and R35/R36 → #304/#305.
