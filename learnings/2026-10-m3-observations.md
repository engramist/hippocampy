# M3 Observations and M4.2 dates: merged (2026-10-18)

hippocampy #305 (B472 Phase 3b+3c, on by default) and #316 (B484, M4.2).
All gates are `eval_gate.py` replays, judge gemma4:26b with 3 votes,
McNemar on gained/lost.

## Observations (#305)

| Set | main | observations | gained / lost |
|---|---|---|---|
| LoCoMo-10 dev-large conv-42 (260 q) | 0.277 | 0.350 | 35 / 16 (p=0.011) |
| LoCoMo-10 dev-large conv-43 (242 q) | 0.417 | 0.430 | 22 / 19 |
| LoCoMo-10 held-out conv-30 (60 q) | 0.300 | 0.367 | 8 / 4 |
| **LoCoMo combined** | | | **65 / 39, p≈0.014** |
| DMR held-out (49 q), first version | 0.633 | 0.571 | 2 / 5 |
| DMR held-out, final rule | 0.640 | 0.640 | 0 / 0 |

- Removing the observation section on the branch cost 19 (conv-42) and 11
  (conv-43) questions; adversarial abstention 34 vs 11 of 125. The section
  earns its place (M3 exit criterion).
- **Rule:** observations feed the semantic section only when the
  conversation section cannot show the whole history (B482 fit_all). When
  the whole history is shown (all of DMR), observations derived from the
  same turns were redundant and slightly harmful.
- Extraction costs one LLM call per user turn and slows ingestion; a
  LoCoMo conversation with observations can take longer than the
  harness's old 1 h drain limit (campy-benchmarks#40 made it configurable).
- Roughly half of a sample of extracted observations were low quality
  ("Your day plans: enjoy"). Extraction precision is the next lever.
- A bug in the first version of the rule marked every conversation as
  full history (a replace across three row builders). Gate R56 caught it
  because the held-out LoCoMo replay came out byte-identical to main; R57
  re-verified the fix.

## Dates for observations (#316, M4.2)

Rule-based resolution of "yesterday", "last Saturday", "two days ago", etc.
against the turn's date. Overall neutral (18 / 14 over 562 LoCoMo
questions), temporal questions 11 / 3 (p≈0.06), the category it targets.

## Lessons

- Check a merge-candidate rule on a held-out set that actually exercises
  it: conv-30 (8k words) and DMR (fits the budget) test different paths.
  A large held-out conversation (conv-44) is now being ingested.
- A "byte-identical to main" result is a signal to check, not a pass, when
  the change was supposed to do something on that set.
