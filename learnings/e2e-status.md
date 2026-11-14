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
- **Step 1 (capture writes the roles): stopped 2026-11-13 on the sense line; the contract question is held for the
  user.** Flag `[observations] roles`, default off. Design: `learnings/step1-capture-roles.md`.
  - **First form (free spans in the fact prompt, PR 410): killed 2026-11-11.** Anchored 47.3% and shared 34.2%, both
    under their kill lines; only 168 of 389 facts matched flag-off.
  - **Second form (a closed choice in a separate call, PR 411, draft): measured 2026-11-13 on conv-26** (store s1on2,
    control s1off):
    - Query hits (the gated measure): 21 against step Q's 14, net **+7** (8 gained, 1 lost). Pass (line +5).
      - Gained: q0, q5, q28, q29, q33, q39, q113, q128.
      - Lost: q70, which became too broad (its term "events" names event.n.01, above 63 facts).
    - Facts equal flag-off: 389/389. Pass.
    - Facts shown action options that got `HAS_ACTION`: 90/101 (89%). Pass.
    - Senses: **16 of 50 hand-checked are wrong (32%; 24% at the most lenient reading). Kill line (over 20%) hit.** The
      replay was not run.
    - Coverage (reported): anchored 57.6%, shared 51.7% (flag-off 34.7% and 21.9%).
  - **What the 8 gains rested on:**
    - None needed the sense: every role target matched the action Concept's own label, and no `BROADER` step was
      used.
    - Six came through an action label: support (q0), race (q5), adoption (q28, q113), workshop (q29), parade (q33),
      walk (q128).
    - Two came through the partner role: "LGBTQ" (q0 also; q39 only).
    - Where the 16 wrong senses sit:
      - None of them is the action behind an action-path gain.
      - One (union.n.11 for "joined a mentorship program") is on a gold row of q39, but q39's hit came through the
        partner edge.
      - The adoption hits (q28, q113) rest on a sense that is right for "to adopt" and doubtful for "a council meeting
        for adoption" (the event there is the meeting).
  - **The contract question, held for the user: what the action role writes.**

    | Option | Writes to the graph | Gains kept | Expected net on conv-26 | Cost |
    |---|---|---|---|---|
    | A: drop the action role | `HAS_PARTICIPANT` and `HAS_PLACE` only | 2 (q0, q39, through "LGBTQ") | about +2 (q70 is not lost: no broad action kind), inside the "+2 to +4 is not a pass" band | none beyond removing the action pick |
    | B: word-level action kinds | `HAS_ACTION` to a Concept per lemma (kind_scheme `action`, no sense, no `BROADER`); no sense line | all 8, if the lemma is the head noun or its nominalization ("adopt" -> "adoption"); q70 likely kept | about +7 to +8 | a roles.py change and one conv-26 re-capture (about 1 h GPU); the `BROADER` chain moves to step 2 |
    | C: rule-picked senses | `HAS_ACTION` to a WordNet sense chosen by rule (the most frequent event sense), with `BROADER` | all 8 (same labels) | about +7 (q70 lost again through event.n.01) | a re-capture (about 1 h) and a new 50-sense check; close to a third form, so it needs the user's explicit yes |
- **Step 0d (always-missed questions): done 2026-11-12** (`learnings/step0d-always-missed.md`). 337 of 809 questions are
  wrong in every one of 16 replay arms:
  - 303 real misses;
  - 29 with the key or label wrong;
  - 5 whose answer is not in the conversation;
  - 24 more flagged as possible judge errors.
  The 34 test-fault ids are reported next to every later score.
- **Step 0c (one store per conversation): done 2026-11-13.** Each of the five conversations was captured into its own
  store, for principled (walk off) and for main, and its questions were replayed on that store.
  - Prompts carrying another conversation's turns: 0 of 809 in both arms (240 and 266 on the shared store).
  - Restated 809 baseline: principled 432 (0.534), main 426 (0.527); without the 34 test faults, 430/775 and 423/775.
    By category, principled: cat 1 38/153, cat 2 86/171, cat 3 21/51, cat 4 287/434.
  - Against the shared store: +14 and +10, inside the ±14 noise, so no measurable change.
- **Step Q (query hits): done 2026-11-13** (PR 418, `query_hits.*` NamedQueries and their CI test). Baseline on the
  five principled per-conversation stores from step 0c:
  - Subject resolved on 801 of 809.
  - Query hits: 111 of 809 (13.7%): cat 1 22/153, cat 2 29/171, cat 3 4/51, cat 4 56/434. conv-26 alone: 14 of 152.
  - Misses, by the first missing edge:
    - object is text (no `HAS_OBJECT` to a Concept): 291
    - the question names no object Concept: 117
    - object not reached by `INSTANCE_OF` / `BROADER`: 113
    - gold fact without the subject edge: 90
    - no fact on a gold turn: 79
    - subject unresolved: 8
  - Hits among the 34 test faults: 6. Among the 337 always-missed: 38 (the graph holds the gold row, but answering missed
    it; a step-4 input).
  - Noise: 0. A rerun is identical, and the conv-26 re-capture gives the same count.
  - Lines approved 2026-11-13 (review session, delegated by the user):
    - Step 2 (809): pass +45 net hits, kill under +15.
    - Step 1 (conv-26, baseline 14): pass +5 net, kill under +2. Three conditions:
      - The role reads (`facts.by_action_kind` / `with_participant` / `at_place`) count as hits only under the same rule:
        a question term names the action kind, partner or place Concept (exact label, in SPARQL), the fact is the
        subject's, a gold turn is among the rows, and there are at most 25 facts.
      - Net is gained minus lost; the baseline hits lost on the re-captured store are listed.
      - +2 to +4 is not a pass. It is reported, with no third form.
      The plan row's mechanism checks are reported alongside.
- **Plan revised 2026-11-12:** steps 0c (per-conversation replay stores), 0d (always-missed questions), 0e (predictions in
  CI) and Q (a thin graph query, whose hits become the measure for steps 1 and 2) come before step 1 continues. 0c, 0d
  and Q done; 0e in review (PR 419).
- Step 2: design in review (it does not depend on the action role). Steps 3-4: not started.

## Rulings

One row per measured result. Rulings dated 2026-11-13 were approved by the user on that day.

| Result | Measured | Ruling |
|---|---|---|
| Walk turns merged into the conversation section (B563) | 0.440-0.447 against 0.480 with the walk off, 300 questions | Stopped; not built |
| A stronger model as the reader | 0.463 against 0.470, 300 questions; abstains on a third | Stopped |
| Roles as free spans in the fact prompt (first form, PR 410) | conv-26: anchored 47.3%, shared 34.2%, both under their kill lines; only 43% of facts matched flag-off | Stopped 2026-11-11; its fields come out with the second form |
| Always-missed review (step 0d) | 337 always-missed; 34 test faults (29 key or label, 5 not in the conversation), 24 judge doubts | Kept: the ids are reported next to every later score; the denominator stays 809 |
| One store per conversation (step 0c) | foreign-turn prompts 0 of 809 in both arms; principled 0.534, main 0.527 (+14, +10, inside noise) | Not ruled. Proposed: kept; these stores are the replay baseline and step Q is measured on them |
| Query hits baseline (step Q) | 111 of 809 hits; subject resolved 801; largest miss: object is text (291) | Kept 2026-11-13 (review session, delegated): the measure for steps 1 and 2, with the approved lines above |
| Closed-choice roles (form 2, PR 411) | query hits +7 net (pass); senses 32% wrong (kill line hit) | Stopped 2026-11-13; held for the user (options A, B, C under step 1) |
| LongMemEval runs R108, R109 | not run | Parked until step 4 |
| Concept walk (store-wide and anchored, B556-B560) | lowers accuracy on 300 questions; about 2% of its rows hold gold | Parked 2026-11-13: off until step 4, then retested once or deleted |
| Graph vote and question analysis | neutral on accuracy; recall up, non-answers down | Kept 2026-11-13 |
| Graph count | fired on 0 of 300 questions | Stopped as a separate lever 2026-11-13: folded into step Q's queries or deleted |
| The other `principled` switches | not measured one by one | Parked 2026-11-13: each is on by default or deleted at step 4 |

Before this plan: the whole `principled` profile was gated on 300 questions (2026-11-07) and tied `main` on
replay (0.480 vs 0.480). 21.6% of facts in that store link to an object entity; no question was answered by a
graph query.
