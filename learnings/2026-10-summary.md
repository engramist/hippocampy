# Summary: what the 2026-09/10 benchmark campaign taught us

The short version of `2026-10-benchmark-campaign.md` (read that for the
evidence, the run numbers and the commits). Written 2026-10-10.

## Seven things we learned

1. **At first the benchmark was mostly measuring itself.** The scorers
   passed "I don't know" and failed correct answers; the suites were
   hand-written lookalikes of the published benchmarks; there was no
   baseline; and runs wrote into the personal `~/.campy` store. Fixing the
   instrument came before anything else: a scorer self-test that must
   reject deliberately broken scorers, isolated stores, the real datasets
   (LoCoMo-10, LongMemEval, DMR), an LLM judge checked against hand labels,
   same-model baselines, and per-question records with provenance.

2. **Long runs found real daemon bugs.** The Consolidation Loop froze the
   daemon, memory blew up (CO_OCCURS_WITH doubling), cold start took
   minutes, tests killed the live daemon, and benchmark data leaked into
   the personal store. These had to be fixed (B448–B468) before any score
   could be trusted. A memory benchmark doubles as a soak test.

3. **Where Campy stands (same model, llama3.1:8b; same judge):**

   | | Campy | No memory | Naive RAG | Full history |
   |---|---|---|---|---|
   | LoCoMo-10 | 0.396 | 0.021 | 0.375 | 0.479 |
   | LongMemEval oracle | 0.600 | – | 0.629 | 0.571 |
   | DMR | 0.620 (text mode) / 0.500 (fields mode) | 0.120 | 0.580 | 0.800 |

   Campy beats naive RAG on LoCoMo-10 and DMR and trails it slightly on
   LongMemEval oracle. Reading the whole history still wins on LoCoMo-10
   and DMR. Campy's three biggest gaps:
   - **Long histories:** on LongMemEval s (~500 turns), only 14% of the
     turns that hold the answer reach the model (61% on oracle).
   - **Multi-hop:** 0–2 of 12 on LoCoMo-10, against 6 for full history.
   - **Answer selection:** the right turn reaches the model and it answers
     from a different, similar turn (DMR after B472 Phase 1b).

4. **The memory graph was mostly noise on chat data.** 87–96% of Concepts
   had no type; about a quarter were time stamps ("9:55 am"); the harness's
   own speaker prefixes became entities; the LLM invented engineering
   relations ("Mustang ALTERNATIVE_TO my car": 943 such edges on DMR); one
   person was split four ways ("Caroline", "Caroline!", "Congrats
   Caroline"…). B472 Phases 1–2 and B473 cleaned this up. But once clean,
   the graph's section of the bundle contributed almost nothing to
   answers. Source-grounded observations (B472 Phase 3) are what should
   give it something worth retrieving.

5. **More turns in the context is not the fix; better ranking is.** On
   LoCoMo-10 the turn holding the answer ranks around 28th while the stage
   keeps 6. Raising the limit to 12 or 20 raised recall but not accuracy,
   halved correct "can't answer" responses and doubled latency. On DMR,
   extra near-duplicate turns actively confuse the small model.

6. **The fixes that worked:** B470 (ignore query words that appear in most
   messages): LoCoMo-10 +0.04 over three runs each side; B471 (recall what
   the assistant said): LongMemEval oracle 0.40 → 0.57; DMR asked as the
   right speaker: 0.50 → 0.62; B473 (no invented relations): LoCoMo-10
   0.354 → 0.396; B472 Phase 1b (embed the speaker's name with the turn):
   DMR 0.42 → 0.50 and recall up on both suites. The one that hurt:
   B472 Phase 1 alone removed the speaker from the embedded text and cost
   DMR 20 points until 1b restored it.

7. **The process lessons that cost the most:**
   - Benchmark every retrieval-affecting change **before** merging; unit
     tests cannot see a similarity floor move.
   - Know the noise floor: at ~50 questions one question is 2 points; a
     single run's change under ~6 points is direction, not size.
   - Compare question by question ("lost 6, gained 0"), not only means.
   - Report retrieval (evidence recall) and answering (accuracy)
     separately; they can move in opposite directions.
   - Replay on kept stores instead of re-ingesting: it reproduced 99/99
     answers verbatim and takes under an hour instead of many.
   - Test the diagnostic itself: a replay variant labelled "top 3"
     actually measured "oldest 3".
   - Don't tune on the questions you score on: use a held-out set and a
     second suite.
   - Work stalled between phases waiting for a "go"; numbered requests,
     exact commands, queues, check-ins and standing merge permission kept
     it moving. That is why the plan (`e2e-improvement-plan.md`) writes
     its decision rules down in advance.

## Where things stand (2026-10-10)

- hippocampy main `0a7a888`; campy-benchmarks master `a201a3e`.
- Running on the local machine: R27 (corrected answer replay), then R20d
  (LongMemEval s at 30 questions with baselines), about 15 hours.
- Next: milestone M0 of the plan (evaluation infrastructure), then M1
  (use the evidence that already arrives).
