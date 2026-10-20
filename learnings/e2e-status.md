# E2E plan status

Live state of `e2e-improvement-plan.md`. Update after every step; keep it
short and current (history goes in dated `learnings/` notes).

_Last updated: 2026-10-20 06:25 UTC_

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

- **Gate rule changed (2026-10-19):** score on the published metric (LoCoMo
  categories 1–4; adversarial separate), pool dev + held-out, merge on
  gained > lost with no p threshold. Re-score with `~/campy-lead/rescore5.py`.
  See `2026-10-metric-switch.md`.
- **On main (`030303a`):** B482 token budget; B487 neighbours N=1; **Observations
  on (#331)**; B494 output cap 2048. Cat 1–4 vs the pre-neighbours main: neighbours
  +9 points (R64), observations a further +4.7 (R66).
- **Open:** #326 B489 verify (secondary); #318 expansion rebuilt on main
  (`claude/e2e-m4-1-expansion`, gate R68).
- **GPU queue:** R66 conv-43 → R67 conv-43 neighbours N=0/1/2 → R68 #318
  expansion on top of observations → R61 LongMemEval s on main `030303a` → R65
  B489 verify.
- **Next R-number:** R69.

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

None.

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

- dev: `r24b` DMR 0–49, `r24a` LoCoMo-10 conv-26
- dev-large: `r44a` DMR 100–299 (200 stores); `r44-conv-42`, `r44-conv-43`
  LoCoMo-10 (all questions; ingested with observations on)
- held-out: `r30a` DMR 50–99, `r30b` LoCoMo-10 conv-30
- other: `r20a`, `r20c` (text mode), `r35` (conv-26 with observations), `r39` (turn_index)

## Noise floor

Not measured yet (R31). Assume ±4 points at n=50–60.

## Next three actions

1. Re-score every baseline (full_context, naive_rag) and Campy run with the
   fixed scorer; publish one corrected table.
2. Next lever from the full-history analysis: neighbour expansion (±2 turns
   around each retrieved turn in the same session; evidence turns are often
   replies that do not repeat the question's words).
3. If observations are revisited: keep their ordinary-question gain without
   the abstention loss (e.g. show observations only for non-adversarial-looking
   questions, or tell the answer step that observations are not proof).
