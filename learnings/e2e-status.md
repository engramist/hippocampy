# E2E plan status

Live state of `e2e-improvement-plan.md`. One entry per step result; earlier history is in git and the dated notes.

_Last updated: 2026-11-17 14:30 (run 5 killed on its category-5 line; +6.3 points on the 809)_

## Scoreboard (one test set, one measure)

Every row is the same 809 questions (LoCoMo categories 1-4, five conversations), answered by the 8B answer model and
scored by the 26B judge. **Accuracy** is the share answered correctly. **Change** is in percentage points against the
run's own control (the same stores without the change). Noise is ±1.7 points; a change counts as a gain only above
+1.9 points (15 questions).

| Run | Accuracy | Change against its control | Verdict |
|---|---|---|---|
| `main` profile | 52.7% (426) | reference | |
| `principled` profile | 53.4% (432) | +0.7 against `main` | inside noise |
| Re-captured stores, capture flags off | 53.9% (436) | reference for the re-capture | |
| Re-captured stores, capture flags on | 53.6% (434) | -0.2 | no change; the control for the three rows below |
| Graph facts in the prompt, first build (2026-11-14) | 51.7% (418) | -1.7 against 53.4% | killed |
| Graph facts in the prompt, re-measured (2026-11-16) | 52.3% (423) | -1.4 | killed |
| Graph facts with object-text matching (2026-11-16) | 51.2% (414) | -2.5 | killed |
| Baseline: no memory (2026-11-17) | 2.6% (21) | -51.0 against 53.6% | reference |
| Baseline: naive retrieval (2026-11-17) | 36.1% (292) | -17.5 against 53.6% | reference |
| Baseline: full history | not run: the timing probe was stopped by the memory guard before its first answer | | held for the user |
| Fact sentences next to their source turn | not run, stopped at the faithfulness check (6 of 50 wrong; line 5) | | stopped |
| Changed abstain instruction (2026-11-17) | 60.0% (485) | +6.3 against 53.6% | killed: refusals on the 222 adversarial questions fell 27.1 points (line 10) |

In every arm about 3 points are answers that open with an abstention and then give the key; the judge fails them by its written rule. The arms differ by at most 0.6 points on this, so no comparison changes.

Two other measures, which are not accuracy and are never mixed with it:

- **Query hits:** the share of the 809 questions where a graph query finds a fact from the right turn. 13.7% before
  this plan; 14.7% on the re-captured stores; 23.5% with the role edges; 34.5% with object-text matching. Hits rose
  20 points and accuracy did not move.
- **Evidence in view:** on 64.8% of questions every source turn is in the prompt, and those are answered 71.0%
  correctly. On the other 34.7%, accuracy is 21.0%.

Reporting rule (user, 2026-11-16): every result is given as accuracy in percent on the 809 and its change in
percentage points against its control, with the noise band; raw counts once, in brackets. A number on any other set
of questions says so in the same sentence.

## Run queue (order ruled by the user 2026-11-17)

One GPU job at a time, under the guards (12% free; 8% while judging; 30 GB swap). Each run has its lines written
before it starts and gets a lessons entry when it ends.

| # | Run | What it tests | State | Lines (strict accuracy on the 809 unless said) |
|---|---|---|---|---|
| 1 | Baselines job: no memory, naive retrieval, timing probe | where 53.6% stands against no memory and plain retrieval | done: no memory 2.6% (-51.0 points), naive retrieval 36.1% (-17.5 points), both reference; the probe was stopped by the memory guard (free 9-10% against the 12% line, answer model at 21.2 GB) before its first answer, so there is no projection | reference, no line; predictions 2-6% and 30-42% |
| 2 | Second score, agreement check | whether the second pass agrees with 25 hand-read answers | closed by the user 2026-11-17: failed its line (2 of 5 partial answers passed; line 1); the second score is dropped | at least 18 of 20 full answers pass, at most 1 of 5 partial ones |
| 3 | Second score, six stored arms | a second column: an opening refusal ignored | closed by the user 2026-11-17: not run; the second score is dropped | no line; expected +2.5 to +3.5 points on every arm, gaps unchanged |
| 4 | Fact sentences by rule, next to their source turn | whether plain sentences built from the graph's facts help the reader | closed by the user 2026-11-17: stopped at the faithfulness check (6 of 50 wrong; line 5), left stopped; code kept on its branch, not merged | pass above +1.9 points; kill at 0 or below; prediction -0.5 to +1.5 |
| 5 | Changed abstain instruction | whether the reader stops declining with the evidence in view | killed: 809 at 60.0% (+6.3 points, pass); category-5 refusals 58.6% → 31.5% (-27.1 points, over the 10-point kill line) | pass above +1.9 points with correct refusals on the 222 adversarial questions falling by at most 5 points; kill at 0 or below, or refusals falling by more than 10; prediction +0.5 to +2.5 |
| 6 | Full history baseline | the reader with every turn in view | held: decided by the user after run 5 (the probe could not run under the 12% line) | reference, no line; prediction 45-62% |

Not queued, and the user's to schedule: the rebuilt capture lane (B542).

## Waiting for the user

Ruled by the user 2026-11-17 (morning), on the review session's recommendations:
1. **Fact sentences (run 4): left stopped.** About a third of stored facts are wrong (35 of 100, range 21-56%), so
   plain sentences would state those errors next to true turns. The code stays on its branch and is not merged.
2. **Second score (runs 2-3): dropped.** Only the strict score is reported. Every arm loses about 3 points to answers
   that decline and then state the key; the arms differ by at most 0.6 points on this, so no comparison changes.
3. **Full history (run 6): decided after run 5.** It needs either a lower line for that run or an otherwise idle
   machine, and may take a day or more.
4. **Capture rebuild (B542): the main direction question.** The review session gives a recommendation once run 5's
   result is in.

**Baselines judging under a lower guard line (ruled by the user 2026-11-16, about 22:15, in the plan lead's
session: "Lower line for judging").** As applied:
- The memory guard keeps 12% free at all times except during a judging phase, which marks itself with a flag file;
  while the flag exists the line is 8%. The user named no number; 8% is the plan lead's choice (the judge settles at
  11-12%), and the user can change it. The earlier guard script is kept as a backup.
- A second guard, added at the review session's request, stops the job if swap stays above 30 GB for three checks.
  It only adds a stop.
- The personal daemon is stopped for the whole job. Answering phases, the timing probe and full history stay at 12%.
- Observed in the first hour of judging: free 11-16%, swap rising from 2.1 GB to a band of 12-16 GB and levelling
  there; neither guard fired; judging runs at about half its usual speed.

The full trail of trials is in `lessons-learned.md`; every test or trial is appended there with its result.

Ruled by the user 2026-11-16 (night), on the review session's recommendations:
1. **Graph facts as a prompt section: the kill is accepted.** Both re-measurements lost (414 and 423 against 434),
   and even firing only on gold rows would gain under the +15 line. `graph_facts` and `object_text_match` stay off
   and in no profile. No new lever starts until the baselines on the 809 are in; the next direction is then the
   user's, read against the full-history baseline and the coverage table (every gold turn in view 0.71; otherwise 0.21).
2. **Baselines judging: requeue as it is, keep the guard.** The guard's line stays at 12% and no app is closed. The
   job is requeued unchanged; if the guard stops it a third time it comes back to the user.

Ruled by the user 2026-11-16:
1. **Action word:** dropped, as the 2026-11-14 ruling says (21 of 100 written words wrong; object-text matching
   reaches 57 of its 61 gained hits). The `roles` flag stays off and in no profile; no code is deleted yet.
2. **Place line:** judged by the whole turn (4 of 30 wrong). The place role is kept.
3. **Object-text matching by vector at cosine 0.75:** built next, behind a flag (off, in no profile), design first.
   Step 3 is then re-measured on top of it, as its own pre-registered run; then step 4.

Done 2026-11-16: object-text matching is built behind `[retrieval] object_text_match` (off, in no profile; it acts
only with `graph_facts` on). **Run OT-1 passed every line:**
- the build gives 279 hits on the flags-on stores and 275 on the flags-off stores, the same as the offline
  reference (vecq-4), with 0 question ids different;
- flag off gives 123 and 119, unchanged;
- 3 of 50 sampled new matches are wrong (3 to 5 on the borderline calls; the line is at most 10).

Next: S3-OT (step 3 with object text, one GPU replay arm against the stored 434), then S3-asbuilt, then the baselines
on the 809 as a reference measurement.

Ruled by the user 2026-11-15:
1. **Partner role:** the model-chosen partner is dropped (29 of 30 hand-checked links were wrong). The action word
   (form 3) and place stay. A co-participant edge is written only by a rule.
2. **Subject change:** the "we"/group part only, anchored by rule on facts the model already proposes, with the
   extraction prompt untouched (measured offline: 56 facts, 5 hits, 3 of 18 wrong). The relation part ("my ...") stays
   out (6 of 12 wrong). The prompt wording is not tried again.

Done 2026-11-15: the "we" anchoring is on main behind `group_anchor` (off); form 3 without the model-chosen partner
is on main behind `roles` (off); the conv-26 confirming capture met its lines. Next: the paired full re-capture of the five conversations on the approved lines;
then step 3 re-measured; then step 4.

Earlier rulings, 2026-11-14 (the decisions page, `~/campy-lead/reports/2026-11-14-decisions-for-the-user.md`):
1. **Step 3:** option C. The flag stays off. The section as built is re-measured after the capture work and one full
   re-capture; there is no new fire rule.
2. **The action word:** one new form (form 3). A rule proposes candidate words from the fact's own text, and a closed
   choice picks one or "none". This is the last form: if its word line is hit, the action role is dropped and partner
   and place go forward alone.
3. **Who a fact may be about:** option A only. "we" and people named by relation ("my kids") may be subjects; the
   nine predicates stay.
4. **Step 0c:** kept. The per-conversation stores are the replay baseline.

Order: form 3, then the subjects change, then one full re-capture of the five conversations, then step 3
re-measured, then step 4. One GPU job at a time.

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
- **Step 1 (capture writes the roles): form 3 passed its lines 2026-11-14 (the word line at its edge); the next step is
  with the user.** Flag `[observations] roles`, default off. Design: `learnings/step1-capture-roles.md`.
  - **Form 3 (candidate words by rule, closed choice with "none" in the partner/place call; branch
    `claude/step1-form3`, run s1onF3; the last form).**

    | Line | Result | |
    |---|---|---|
    | query hits on conv-26 against 14: pass +5, kill under +2 | 28 (+14 net; 14 gained, 0 lost) | pass |
    | facts 389 of 389 | identical to s1off | pass |
    | action facts with a candidate that get HAS_ACTION: kill under 50% | 104-105 of 109 (96%) | pass |
    | 50 written action words, hand-checked (sample drawn before the hits): at most 20% wrong | 10 of 50 (20%) | pass at the edge (±2 items on borderline readings; ruled a pass, the line not moved) |
    | replay of the 152, flag on against flag off: within 6 | running | |

    - The rule's new candidates fix the phrasal verbs (look after, hang out, look into, sign up) and the aspectual
      complement (started playing -> playing). Option B's 17 wrong words: right 5, none 0, no candidate 4, still
      wrong 8.
    - The choice barely filters: "none" on 3 of 109 facts; the first candidate taken in 102 of 105 picks. Writing the
      first candidate without a choice would change 7 words: the sample would read 11 of 50, and hits would be 27.
    - What is left wrong: the complement of a light verb (have a good time, have fun, had a blast, make a difference,
      start a chapter) and nouns that name a thing or place. The complement rule holds 5 of the 10 sampled wrong
      words; no single existing check separates them.
    - Partners: 138 links under option B, 100 under form 3. With the action line in the same call, the model answers
      "none" for the partner far more often. By their quotes, none of the 58 lost links is a real co-participant:
      54 name the other speaker with no support in the quote, 4 are junk names.
    - **Partner hand-check (2026-11-14, not pre-registered, not gated): 29 of 30 random form 3 partner links are not
      a co-participant by the quote.** 73 of the 100 links name one of the two conversation speakers; most of the rest
      are a modifier ("an LGBTQ art show") or a junk name. Without any partner edge the hits are 26 (form 3: 28). The
      two that go (q0, q39) rested on "LGBTQ" as a modifier, not on a co-participant.
    - Only 4 of 170 event quotes on conv-26 name a co-participant ("with the kids" ×2, "with the gang", "with my
      dad"), and none by a name.
    - Places: 10 written, all by the parse fallback; 9 are where the fact happened by the quote, and 1 is right by the
      turn but not named in the quote.
    - Known weakness, not acted on: the complement rule (the word after a light or aspectual verb) holds 5 of the 10
      sampled wrong words.
    - Calls per turn are unchanged (114). Capture time was 67 min against 56.
  - **Option B (word-level action kind by rule, partner and place by closed choice; PR 411 draft, run s1onB):
    kill line hit 2026-11-14.** conv-26 capture on the pinned tree (f2133c58, the s1off capture code), measured on a copy.

    | Line | Result | |
    |---|---|---|
    | query hits on conv-26 against 14: pass +5, kill under +2 | 27 (+13 net; 13 gained, 0 lost) | pass |
    | facts equal s1off | 389 of 389, identical (predicate, object, quote) | pass |
    | did/plans facts with HAS_ACTION: kill under 50% | 109 of 177 (62%) | pass |
    | 50 action words, hand-checked (sample drawn before the hits): at most 20% wrong | 17 wrong (34%); 13 (26%) counting four borderline as right | **kill** |
    | replay of the 152, flag on against flag off | not run: the step stopped | |

    - The 17 wrong words: a phrasal verb cut to its head 4 (look after, hang out, look into, sign up); an aspectual or
      light verb kept for the activity 8 (start, finish, try, had a blast, a good time, a great time, me-time, make it
      happen); a noun or the wrong verb chosen 5 (make some art, a support group, kids who need it, let them know, up
      for the challenge).
    - Gains by role: action 10, partner 2, both 1, place 0. Three gains rest on a word that is wrong or not an action
      (support, sign, class); without them +10. 2 of the 17 wrong and 2 of the 33 right sample words sit on a fact
      behind a gain.
    - Of the 10 action gains, 8 come through a word that is the fact's head noun or main verb with no light, aspectual
      or phrasal construction (lost: sign up, had a picnic); 7 if "class" (in "made it in pottery class") is also
      counted as not an action.
    - Outcomes: written 110; no head 12; head not in quote 10; no event word 23; second word dropped 8; no subject 24.
      77 action Concepts, 22 shared by two or more facts; 6 action labels equal a non-action Concept's label
      (adoption, event, painting, support, work, workshop).
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
  - Corrected by step 3 (2026-11-14): with the rows in the prompt, a question whose gold turn is among the rows goes
    from 62 to 75 of 111 against main (the step-Q hits; all 111 have a gold turn among their rows).
- **Step 3 (graph facts section, PR 428, flag `CAMPY_GRAPH_FACTS`): kill line hit 2026-11-14; flag off.** Replay of
  the 809 on the B565-cleaned per-conversation stores, against the stored principled flag-off arm and main.
  It fired on 413 questions, not the predicted 100-115: the prediction counted hits (a gold turn among at most 25 rows),
  but the section fires on any subject with a named object Concept and 1-25 facts, so hits are a subset (all 111 fired).
  On the 413 it answered 204, against 218 (principled) and 216 (main): the kill line (at or below main) is hit.

  | | n | step 3 | principled | main | step 3 - main | non-answers (step 3 / principled / main) |
  |---|---|---|---|---|---|---|
  | fired, gold turn among the rows | 111 | 75 | 65 | 62 | +13 | 7 / 18 / 24 |
  | fired, no gold row | 302 | 129 | 153 | 154 | -25 | 97 / 71 / 71 |
  | not fired | 396 | 214 | 214 | 210 | +4 | 72 / 72 / 73 |
  | all | 809 | 418 | 432 | 426 | -8 | |

  - Gold among the rows is read from the rows' EVIDENCED_BY turns (the live queries re-run on the same store copies).
  - Without the 34 test-fault ids: gold among the rows 73 of 105 against main 60; no gold row 129 of 292 against 154.
  - On the no-gold-row questions, 36 are lost against principled and 12 gained; 26 of the 36 losses are non-answers.
    In 29 of the 36 the gold turn is elsewhere in the same prompt (the instruction to answer only from the lines is
    the existing answer prompt, B475, in every arm).
  - Not fired: 0 changed against principled, so the cleaned stores do not confound the result.

  | Shape (fired) | n | step 3 | principled | main | step 3 - main | test faults |
  |---|---|---|---|---|---|---|
  | fact | 237 | 119 | 133 | 134 | -15 | 6 |
  | list | 64 | 23 | 23 | 18 | +5 | 5 |
  | dated | 92 | 49 | 48 | 51 | -2 | 4 |
  | exists | 15 | 10 | 11 | 11 | -1 | 0 |
  | latest | 0 | - | - | - | - | - |
  | count | 5 | 3 | 3 | 2 | +1 | 1 |

  | Category | fired n | step 3 | principled | main | step 3 - main | test faults | not fired n | step 3 | main |
  |---|---|---|---|---|---|---|---|---|---|
  | 1 | 64 | 20 | 15 | 14 | +6 | 6 | 89 | 23 | 23 |
  | 2 | 91 | 49 | 47 | 49 | 0 | 5 | 80 | 39 | 38 |
  | 3 | 18 | 7 | 9 | 9 | -2 | 0 | 33 | 12 | 12 |
  | 4 | 240 | 128 | 147 | 144 | -16 | 5 | 194 | 140 | 137 |

- **Item 3 (who a fact may be about; PR 432, flag `[observations] group_subjects`): kill line hit 2026-11-14; flag
  off.** The fact extractor alone was re-run three times (flag off, on, off again) on 57 gold turns with no fact,
  60 control turns and 40 turns with facts (their facts archived in the copy first), on the cleaned stores.
  - Fact-bearing turns: 36 of 40 lost a fact that both flag-off runs wrote; 58 of 76 stable facts were lost. The two
    flag-off runs were identical. Line: more than 2 turns.
  - Cause, checked on 3 lost turns re-run alone: with the flag on the model replies `[]`, where the flag-off prompt gets
    3-4 proposals. The only difference is the two sentence replacements. A wording effect, not the anchoring rule.
  - Gold: 11 of 57 turns gained a fact (prediction 8-15); control: 2 of 60. On the flag-on arm the rule wrote 14
    group-subject facts and 1 relation fact without error.
- Step 4: not started.

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
| Graph facts section (step 3, PR 428) | fired on 413; gold among rows 75 vs main 62 of 111 (+13); no gold row 129 vs 154 of 302 (-25); overall 418 vs 432 and 426 | Kill line hit 2026-11-14; flag off; held for the user |
| Roles, option B (word-level action kind, PR 411) | query hits 14 to 27 (+13 net, pass); action words 34% wrong (kill line hit) | Stopped 2026-11-14; held for the user |
| Step 3 decision | the decisions page, 2026-11-14 | Ruled by the user 2026-11-14: option C, flag off; re-measured as built after the capture work and one full re-capture; no new fire rule |
| Action word decision | option B 34% wrong | Ruled by the user 2026-11-14: form 3 (candidates by rule, closed choice with "none"); the last form, after which the action role is dropped if its line is hit |
| Who a fact may be about | 12 of 27 no-proposal gold turns about "we" or third persons | Ruled by the user 2026-11-14: option A ("we" and people named by relation); the nine predicates stay |
| One store per conversation (step 0c), ruling | as above | Ruled by the user 2026-11-14: kept; the per-conversation stores are the replay baseline |
| Roles, form 3 (candidates by rule, closed choice; branch claude/step1-form3) | conv-26 query hits 14 to 28 (+14); action words 10 of 50 wrong | Pass at the edge 2026-11-14 (review session; the line not moved); partner links fell 140 to 100; next step with the user |
| Partner by closed choice (forms 2, B, 3) | counts passed; option B's 138 links include 54 to the other speaker with no support in the quote; form 3 hand-check 29 of 30 wrong | Hand-check 2026-11-14; not to be written as built; held for the user. Roles are hand-checked like the action word from now on (a gated line of at most 20% wrong at the full re-capture) |
| Group and relation subjects by prompt change (item 3, PR 432) | gold +11 turns; 58 of 76 stable facts lost on fact-bearing turns | Kill line hit 2026-11-14; flag off; held for the user |
| LongMemEval runs R108, R109 | not run | Parked until step 4 |
| Concept walk (store-wide and anchored, B556-B560) | lowers accuracy on 300 questions; about 2% of its rows hold gold | Parked 2026-11-13: off until step 4, then retested once or deleted |
| Graph vote and question analysis | neutral on accuracy; recall up, non-answers down | Kept 2026-11-13 |
| Graph count | fired on 0 of 300 questions | Stopped as a separate lever 2026-11-13: folded into step Q's queries or deleted |
| The other `principled` switches | not measured one by one | Parked 2026-11-13: each is on by default or deleted at step 4 |
| Partner role by closed choice | 29 of 30 hand-checked links wrong | Dropped by the user 2026-11-15; co-participant edges by rule only |
| Subject change, anchor only | "we" part 5 hits, 17% wrong; relation part 2 hits, 50% wrong | User 2026-11-15: build the "we" part, prompt untouched; relation part left out |
| "We" anchor design (review session, 2026-11-15) | pre-build check: partner by "PERSON named in the quote" 4 of 6 wrong; narrowed to "X and I" or object of "with": 1 link, right | Approved to build behind `group_anchor` (off): speaker as subject, `group_subject` true, partner by the narrowed rule only, PERSON only. Under 10 partner links in the re-capture is "too few to judge", not a pass |
| Confirming capture, partner line removed (conv-26, 2026-11-15) | hits 26 (line: within 2 of 26); facts 389/389; same 50 words: 3 right words now unwritten, no wrong word changed; 10 of 50 wrong (10 of the 47 written, 21.3%); invalid or missing action answers 10 against 1 | Review session: prerequisite met as pre-registered (the picks did not shift). Not counted as evidence the words are under 20% wrong; the re-capture's 100 written words decide the action role, wrong-rates over written edges only |
| Question words resolved to entities by vector (user, 2026-11-15) | not measured; step Q matches exact labels only | User: measure offline on store copies after the full re-capture result. A measurement only; no code on main until its result has a ruling. It does not change the order (step 3 re-measured, then step 4) |
| Full re-capture, five conversations, flags on against off (2026-11-16) | query hits 190 against 119 (+73, 2 lost; +79 against 111); facts 6 of 2,731 missing; action words 21 of 100 wrong; places 4 of 30 wrong by the turn (14 by the quote alone); "we" facts 6 of 30 wrong; rule-written partner links 61, 4 of 30 wrong; replay 434 against 436 | Hits, facts, "we" facts, partner links and replay pass. The action-word line is hit: held for the user. The place wording: held for the user |
| Vector-resolution design (review session, 2026-11-15) | not yet run | Approved as a measurement: readings A (entity vectors), B (object text) and C (role labels), thresholds 0.65/0.75/0.85 fixed in advance, 50 hand-checked matches per reading. C waits for the action ruling. A pass is a result for the user, not a go-ahead to build |
| Vector resolution, reading A: question words to entity vectors (2026-11-16) | 0.65: +17 net, 20 of 50 wrong; 0.75: +10, 18 of 50 wrong; 0.85: +3 | Killed by its lines (every threshold over 20% wrong). Not re-run with another term filter |
| Vector resolution, reading B: question words to the object text of the subject's facts (2026-11-16) | 0.65: +151 net, 11 of 50 wrong; 0.75: +116, 1 lost, 5 of 50 wrong; 0.85: +81, 1 lost, 1 of 50 wrong; rows per new hit 4.6 against 4.8 | Passes at 0.75 and 0.85. A result for the user; nothing built |
| Lexical control: lemma match on object text, no vectors (2026-11-16) | +161 net, 5 lost, 11 of 50 wrong; 6.8 rows per new hit | Killed on its wrong-rate line. Reaches 65 hits the vectors do not; the vectors reach 16 it does not |
| What the action role adds beyond object-text matching (2026-11-16) | of its 61 gained hits, 57 are reached with no action read (40 by vectors at 0.75, 52 by lemmas); 4 by neither. Flags off plus vectors at 0.75: 275 hits against 119 | Reported to the user with ruling 1. Reading C (role labels) stays deferred |
| Action word, place line, object-text matching (user, 2026-11-16) | as the three rows above and the full re-capture row | User: action word dropped; places judged by the turn and kept; object-text matching at 0.75 built next behind a flag, design first, then step 3 re-measured |
| Lessons file (user, 2026-11-16) | `lessons-learned.md` written back to 2026-09-28 | User: every test or trial is appended to it (why, what, result, decision) in the same PR as its status update |
| Object-text matching design (review session, 2026-11-16) | reference measured before the build (vecq-4, exact object Concepts plus object text at 0.75, no role reads): 279 hits on the flags-on stores, 275 on the flags-off stores; exact only 123 and 119 | Approved to build behind `object_text_match` (off, in no profile): reads the subject's live facts, their object text and `EVIDENCED_BY`; writes nothing; threshold 0.75 and 3 texts per term fixed as constants. Run OT-1: the build reproduces 279 and 275 within 3, at most 10 of 50 sampled matches wrong. Run S3-OT (graph facts with object text, against the stored 434): pass net +15 or more with the no-gold-row group losing at most 10; kill at net 0 or below, or that group losing more than 24; between is the user's call. Prediction: near 0, because the fire rule is unchanged. The as-built step 3 arm also runs, as the control and to close the 2026-11-14 ruling |
| Object-text matching build, run OT-1 (2026-11-16) | built path: 279 (flags on) and 275 (flags off), 0 ids differing from vecq-4; flag off 123 and 119; 3 of 50 new matches wrong (range 3-5) | Passed every line; merged with the flag off. S3-OT next |
| Step 3 with object-text matching, S3-OT (2026-11-16) | 414 vs 434 (net -20); gold row +9 on 279, no gold row -29 on 361 (line: >24); without the 34 test faults -17 | Kill on both lines; flag stays off; held for the user |
| Step 3 as built, S3-asbuilt (2026-11-16) | 423 vs 434 (net -11); gold row +13 on 123, no gold row -24 on 299 | Kill as predicted (line: net <= 0); held for the user with S3-OT |
| Baselines on the 809 (design, 2026-11-16) | design approved by the review session 2026-11-16: per-conversation runs, same answer model, judge, votes and cache as rcon; no pass or kill line; predictions no memory 0.02-0.06, naive retrieval 0.30-0.42, full history 0.45-0.62 | Approved; stopped twice by the memory guard at judging; held for the user |
| Step 3 kill and the baselines' memory (user, 2026-11-16 night) | S3-OT net -20, S3-asbuilt net -11; the judge alone at the guard's 12% line | User: the kill is accepted, graph facts stay out of the prompt, no new lever until the baselines are in; the guard stays at 12%, no app is closed, and the job is requeued as it is; a third guard stop comes back to the user |
| Baselines judging, guard line (user, 2026-11-16 about 22:15) | three guard stops with the judge alone at 11-12% free | User: a lower line for judging phases only. Applied as 8% while a judging phase holds its flag (the plan lead's number), 12% otherwise; a 30 GB swap ceiling added as a second stop. Job requeued 22:21 |
| Fact sentences by rule (user, 2026-11-17) | the 152 all-evidence failures cost 18.8 points; 32 have a matching fact by exact label | User likes sentences built by rule, no model call. Review session: design approved to build behind a flag (off), a line attached to its source turn, exact labels only; faithfulness check of 50 sentences (at most 5 wrong) before any GPU; replay after the baselines; pass above +1.9 points, kill at 0 or below; prediction -0.5 to +1.5 |
| Second score (user, 2026-11-17) | about 3 points in every arm are answers that decline and then give the key | User: report a second score beside the strict one, with an opening refusal ignored; strict stays the headline; applied to every arm. Design first |
| Abstain instruction (user, 2026-11-17) | declining with the evidence in view costs 8.3 points; the instruction dates from 2026-10-10 and serves the adversarial category | User: test a changed instruction as one pre-registered replay after the baselines, measured on the 809 and the adversarial questions together. Design first |
| Second-score design (review session, 2026-11-17) | detection and stripping rules fixed in the harness and self-tested; only strict-wrong answers that open with a refusal get a second pass on the stripped text, same judge and votes | Approved. The agreement check gates reporting. The strict column decides every pass and kill |
| Abstain-instruction design (review session, 2026-11-17) | one changed wording, written once; flag `answer_style = cite_answer`; the 809 and the 222 adversarial questions, each against its own control | Approved with the lines in the run queue. One arm, no second wording; closed if it fails. The wording was written after reading the 809's failures, so a pass is not a held-out result |
| Run order (user, 2026-11-17) | full history may take 14-34 hours | User: the three short runs go before full history; the current baselines job finishes first |
| Fact sentences, second score, full history (user, 2026-11-17 morning) | run 4 stopped at its faithfulness check; run 2 failed its agreement line; run 6's probe stopped by the guard; 35 of 100 stored facts wrong | User: fact sentences left stopped (code not merged); the second score dropped, strict only; full history decided after run 5; the capture rebuild (B542) is the next direction question, with the review session's recommendation after run 5 |
| Baseline: naive retrieval (2026-11-17) | 36.1% (292), -17.5 points against 53.6% | Reference; no line |
| Full-history timing probe (2026-11-17) | stopped by the memory guard before its first answer: free 9-10% against the 12% line, answer model at 21.2 GB | Held for the user (review session, 2026-11-17): run 6 cannot run under the 12% line as built; no fix, variant or retry without the user |
| Second-score agreement check (2026-11-17) | 18 of 20 full answers right (line 18); 2 of 5 partial answers right (line 1): failed | Held for the user (review session, 2026-11-17): run 3 is not queued and no second column is reported; no fix, variant or retry without the user |
| Changed abstain instruction, run 5 (2026-11-17) | 809: 60.0% (485), +6.3 points (gained 67, lost 16); category 5: refusals 58.6% → 31.5%, 60 of the 61 now answer for real | Killed as pre-registered (category-5 line); the flag stays off. Held for the user: any follow-up (for example a subject check before answering) is a new design |

Before this plan: the whole `principled` profile was gated on 300 questions (2026-11-07) and tied `main` on
replay (0.480 vs 0.480). 21.6% of facts in that store link to an object entity; no question was answered by a
graph query.
