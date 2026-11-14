# E2E plan status

Live state of `e2e-improvement-plan.md`. One entry per step result; earlier history is in git and the dated notes.

_Last updated: 2026-11-13 (user rulings: step 3 first, roles option B)_

## Waiting for the user

1. **Who a fact may be about, and the predicate set:** "we" and unnamed others ("my kids"), and verbs outside the nine.
   These are the largest capture-recall losses, and they are a contract and prompt change.
2. **The step 0c ruling:** keep the per-conversation stores as the replay baseline (proposed).

Ruled by the user 2026-11-13: step 3 runs first, on today's 111 hits; roles are option B (a word-level action kind,
with form 2's partner and place roles kept).

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
- **B565 (2026-11-13, PR 422): closed-class words are never Concepts.** On cleaned copies of the five step-0c
  principled stores, 31 pronoun Concepts were archived. Step Q's table is restated:
  - hits: 111 (unchanged, none gained or lost);
  - object is text: 216 (from 291);
  - question names no object Concept: 224 (from 117);
  - object not reached: 81 (from 113);
  - no subject edge 90, no fact on a gold turn 79, subject unresolved 8: unchanged.
  59 facts are left without a live subject. Follow-up: B566.
- **Step 2 (kinds and places): stopped 2026-11-13 before build; held for the user with step 1's roles.**
  - The line was restated and approved 2026-11-13 (review session, delegated), scoped to step 2's own 77 targets: on the
    809, against 111, pass +31 net, kill under +10.
  - Pre-build check on the cleaned copies (whether each rule's trigger occurs in the target questions' gold turns):

    | Rule | Targets | What the gold turns hold | Estimated reach |
    |---|---|---|---|
    | (a) kind for an untyped object entity | 8 | "another cat named Bailey" (WordNet has no path from cat to pet); "his name is Kyle" (no kind noun) | 0 to 2 |
    | (b) BROADER between existing kinds | 5 | each names a context word, not the answer's kind; no hypernym exists | about 0 |
    | (c) LOCATED_IN "X in Y" | 20 | "in Y" in 4 gold turns, X an event or common noun (a show in Tokyo): step 1's HAS_PLACE | 0 to 1 |
    | (d) head-noun kind for non-event objects | 44 | the head is the named label on 4; a WordNet hypernym on 6 | +4 to +10 |

    Total: **+4 to +13**, against kill under +10 and pass +31.
- **Held for the user: which roles capture writes (steps 1 and 2 together).** Of the 297 misses left after B565, the
  questions name:
  - an event's partner: 113;
  - an activity: 61;
  - a kind or place where the gold facts are events only: 46;
  - something within step 2's own rules: 77.

  | Option | Writes | Questions it can reach | Expected net on 809 | GPU |
  |---|---|---|---|---|
  | A: partner and place roles only (form 2 without the action pick) | `HAS_PARTICIPANT`, `HAS_PLACE` | partner 113, event places | about +10 (conv-26 +2, scaled) | five re-captures, about 5 h |
  | B: A plus a word-level action kind (lemma, no sense), which also types did/plans object phrases | A plus `HAS_ACTION` to a lemma kind | A plus activity 61 and event-only 46 | about +35 to +40 (conv-26 +7 to +8, scaled) | about 5 h |
  | C: A plus a rule-picked WordNet sense with `BROADER` | A plus `HAS_ACTION` to a sense | the same as B | about +35 (conv-26 about +7, scaled) | about 5 h, plus a 50-sense check |
  | Step 2's own rules (a-d), with any option | kinds and LOCATED_IN | 77 | +4 to +13 | none beyond the option's |

  Scaling conv-26 to 809 is rough: conv-26 is one conversation of five. For the user to answer in one line: A, B or C,
  and whether step 2's rules are dropped or folded in.
- **Capture recall, diagnosed 2026-11-13** (re-run of the extractor on the 57 substantive gold turns with no fact, and
  60 control turns; it reproduced the original capture):

  | Stage | Gold (57) | Control (60) |
  |---|---|---|
  | Called, proposed nothing | 27 (47%) | 41 (68%) |
  | Proposals all rejected by a rule | 23 (40%) | 17 (28%) |
  | Reply malformed | 7 (12%) | 2 (3%) |
  | Not called, or written then archived | 0 | 0 |

  - Of the 27 gold "proposed nothing" turns, 12 are about "we" or third persons, which the prompt leaves out. That is a
    contract question (waiting list item 2).
  - The rejections are right by the rules (verbs outside the nine, no object, an ungrounded subject), except "prefer"
    for "prefers" on 3 turns. That is fixed as B567.
  - 8 of the 9 malformed replies are cut at the output limit with 7-8 complete facts before the cut. A parser salvage
    design is in review.
  - About 140 misses are capture recall: 62 substantive gold turns with no fact, 75 where no fact carries the
    question's words, and 13 short turns. No roles option touches them.
- **"you" facts anchored on the other speaker (probe): closed.** 55 facts rewired: hits 111, none gained; 1 of 90
  moved; 17 of 20 point at the right person, but 12 of 20 are compliments or questions.
- **What a query hit is worth today (stored step-0c replays):**
  - the 111 hit questions are answered 65 (59%) by principled and 62 (56%) by main;
  - the 698 others are answered 53% and 52%.
  - Hits by category (n / principled / main): cat 1 22/7/8, cat 2 29/15/15, cat 3 4/2/2, cat 4 56/41/37.
  - So hits barely move the score until step 3 puts the rows in the prompt. 46 hit questions are answered wrong today.
- Steps 3-4: not started. The step 3 design is ready for the order ruling (waiting list item 4).

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
| Kinds and places (step 2, rules a-d) | pre-build check estimates +4 to +13 | Stopped 2026-11-13 before build; held for the user with step 1's roles |
| Order: step 3 before steps 1 and 2 | a query hit is worth about 0.06 of a correct answer today (59% against 53%) | Ruled by the user 2026-11-13: step 3 runs first on today's 111 hits |
| Roles (steps 1 and 2) | options A, B, C under step 1 | Ruled by the user 2026-11-13: option B (word-level action kind; partner and place roles kept); step 2 folded into step 1 where it is the same construction |
| Closed-class Concepts (B565, PR 422) | hits 111 unchanged; miss table restated (216 / 224 / 81) | Kept 2026-11-13 (review session, delegated) |
| LongMemEval runs R108, R109 | not run | Parked until step 4 |
| Concept walk (store-wide and anchored, B556-B560) | lowers accuracy on 300 questions; about 2% of its rows hold gold | Parked 2026-11-13: off until step 4, then retested once or deleted |
| Graph vote and question analysis | neutral on accuracy; recall up, non-answers down | Kept 2026-11-13 |
| Graph count | fired on 0 of 300 questions | Stopped as a separate lever 2026-11-13: folded into step Q's queries or deleted |
| The other `principled` switches | not measured one by one | Parked 2026-11-13: each is on by default or deleted at step 4 |

Before this plan: the whole `principled` profile was gated on 300 questions (2026-11-07) and tied `main` on
replay (0.480 vs 0.480). 21.6% of facts in that store link to an object entity; no question was answered by a
graph query.
