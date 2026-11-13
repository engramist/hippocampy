# E2E plan status

Live state of `e2e-improvement-plan.md`. One entry per step result; earlier history is in git and the dated notes.

_Last updated: 2026-11-12 (plan revised; rulings table added)_

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
- **Step 1 (capture writes the roles).**
  - **First form killed 2026-11-11.** It added free-span fields to the fact prompt. On re-captured conv-26:
    - anchored 47.3% and shared 34.2%, both under their kill lines;
    - `HAS_ACTION` on 25 of 135 did/plans facts, 5 of the 25 with the wrong sense;
    - only 168 of 389 (quote, object_text) pairs equal to flag off.
  - **Corrected conv-26 baseline:** under one definition (a fact counts only with a subject), anchored 35.1% and shared
    16.0%.
  - **Second form (closed choice in a separate call, fact prompt untouched): built on `claude/step1-form2` (PR 411),
    paused by the 2026-11-12 revision** until step Q's baseline and query-hit line exist. Design:
    `learnings/step1-capture-roles.md` section 8.
- **Plan revised 2026-11-12:** steps 0c (per-conversation replay stores), 0d (always-missed questions), 0e (predictions in
  CI) and Q (a thin graph query, whose hits become the measure for steps 1 and 2) come before step 1 continues. None
  started.
- Steps 2-4: not started.

## Rulings

One row per measured result. "Proposed" rows are the lead's recommendation and wait for the user.

| Result | Measured | Ruling |
|---|---|---|
| Walk turns merged into the conversation section (B563) | 0.440-0.447 against 0.480 with the walk off, 300 questions | Stopped; not built |
| A stronger model as the reader | 0.463 against 0.470, 300 questions; abstains on a third | Stopped |
| Roles as free spans in the fact prompt (first form, PR 410) | conv-26: anchored 47.3%, shared 34.2%, both under their kill lines; only 43% of facts matched flag-off | Stopped 2026-11-11; its fields come out with the second form |
| LongMemEval runs R108, R109 | not run | Parked until step 4 |
| Concept walk (store-wide and anchored, B556-B560) | lowers accuracy on 300 questions; about 2% of its rows hold gold | Not ruled. Proposed: off until step 4, then retested once or deleted |
| Graph vote and question analysis | neutral on accuracy; recall up, non-answers down | Not ruled. Proposed: kept |
| Graph count | fired on 0 of 300 questions | Not ruled. Proposed: folded into step Q's queries or deleted |
| The other `principled` switches | not measured one by one | Not ruled; each is on by default or deleted at step 4 |

Before this plan: the whole `principled` profile was gated on 300 questions (2026-11-07) and tied `main` on
replay (0.480 vs 0.480). 21.6% of facts in that store link to an object entity; no question was answered by a
graph query.
