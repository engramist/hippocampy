# E2E plan status

Live state of `e2e-improvement-plan.md`. One entry per step result; earlier history is in git and the dated notes.

_Last updated: 2026-11-10 (step 0 result)_

- **Step 0 (fix the test): done.** All 809 category 1-4 questions of conv-26/41/48/49/50, replayed on the kept
  stores with the gate's answer model, judge (3 votes) and settings. Working files: `~/campy-lead/scratch/step0/`.

  | | `main` (R107 store) | `principled`, walk off (R111 store) |
  |---|---|---|
  | Accuracy, cat 1-4 | **0.514** (416 of 809) | **0.517** (418 of 809) |
  | single-hop (434) | 0.638 | 0.634 |
  | temporal (171) | 0.509 | 0.532 |
  | multi-hop (153) | 0.222 | 0.222 |
  | open-domain (51) | 0.353 | 0.353 |
  | Non-answers (auto-failed / abstention regex) | 61 / 192 | 50 / 191 |
  | Evidence recall, text (harness) | 0.656 | 0.666 |
  | Evidence recall, graph-aware | **0.748** | **0.748** |

  - **Noise.** The replay repeats exactly: on the 300 questions also in the earlier replays, 300 of 300 answers,
    prompts and verdicts match for both arms. What is left is sampling noise: ±0.018 (±14 questions) at one standard
    error on 809, against ±0.029 on 300. Paired, `principled` against `main` gains 31 and loses 29 (net +2); the
    paired standard deviation is about ±8 questions, so a step-4 gain needs more than about 15 questions net.
  - **Graph-aware recall** also counts a gold turn as found when a fact in the prompt has that turn as its
    `EVIDENCED_BY` source. Fact lines are matched back to Observations on store copies by speaker, date and quote
    (0 unmatched; the 2% that match several Observations credit nothing). About 110 questions per arm have a gold
    turn reached only through a fact. By category (text to graph-aware), `main`: multi-hop 0.37 to 0.51, temporal
    0.72 to 0.82, open-domain 0.34 to 0.49, single-hop 0.77 to 0.83.
  - **Evidence labels.** The harness now splits labels written with `;` or spaces and fixes two typos
    (campy-benchmarks PR 45). Two published ids name no turn and stay unresolved.
  - **Known limit of the replay.** The kept store holds all five conversations, but the live gate asks each
    conversation's questions before the next one is ingested. In the replay, 266 (`main`) and 240 (`principled`) of
    809 prompts carry turns from another conversation. Both arms carry it, but the replay is not the live gate.
    Left as it is (decided 2026-11-10); raise it again before step 3 is measured.
  - `scripts/drift_report.py`: "watch: score flat while code landed" (28 commits in 7 days, 4 with a gate result).
- **Step 0b (fact contract): done.** `docs/fact-contract.md`, approved 2026-11-10: keep the 9 predicates and add action,
  with and place roles; text objects allowed but flagged; action kinds from an independent source.
- **Step 1 (capture writes the roles): design approved 2026-11-10, with a shared-node measure, a sense-accuracy gate and a
  side-effect guard** (`learnings/step1-capture-roles.md`). Building, flag `[observations] roles`, default off.
- Steps 2-4: not started.

Before this plan: the whole `principled` profile was gated on 300 questions (2026-11-07) and tied `main` on
replay (0.480 vs 0.480). 21.6% of facts in that store link to an object entity; no question was answered by a
graph query.
