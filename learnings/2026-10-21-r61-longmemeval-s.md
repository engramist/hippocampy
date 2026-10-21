# R61: LongMemEval s on main (2026-10-21)

**What ran:** `run_all.py --suite longmemeval --lme-variant s --lme-questions 30
--baselines no_memory,naive_rag --isolated`, hippocampy `8c38d23` (token
budget, neighbours N=2, observations on, output cap 2048), answer model
llama3.1:8b, judge gemma4:26b. Campy part took 19 h (about 500 turns per
question ingested fresh); 2 of 28,194 calls failed (q 852ce960 timed out
twice at 240 s and was scored wrong). Peak memory under the memory guard:
30% free, swap flat at ~570 MB. No freeze this time.

## Result

| Type | n | Campy | no_memory | naive_rag |
|---|---|---|---|---|
| abstention | 5 | 4 | 4 | 5 |
| knowledge-update | 5 | 2 | 0 | 3 |
| multi-session | 4 | 0 | 0 | 0 |
| single-session-assistant | 4 | 1 | 0 | 1 |
| single-session-preference | 4 | 0 | 1 | 2 |
| single-session-user | 4 | 1 | 0 | 1 |
| temporal-reasoning | 4 | 2 | 0 | 0 |
| **overall** | 30 | **10 (0.333)** | 5 (0.167) | 12 (0.400) |

Evidence recall is the same for both (Campy 0.526, naive_rag 0.529), so the
gap is in answering, not retrieval. Campy-only wins: 4; naive_rag-only wins: 6.

## Why Campy loses the 6

- **Over-abstention with the evidence in context (2):** 118b2229 and 89527b6b
  have recall 1.0; Campy answers "I don't have that information" (118b2229
  even quotes the 45-minute commute in its refusal). This is the failure
  R70 (select-then-answer, #310) and R65 (B489 verify) target.
- **Knowledge update picks the older value (1):** 6a1eabeb answers 27:12, the
  earlier personal best, not the later 25:50; recall 0.5, so the newer turn
  was not retrieved.
- **Preference questions (2):** 8a2466db, 06878be2 recall 0.0; the
  preference sits in an earlier session that the question's words do not
  match. naive_rag passes by answering generically.
- **Abstention (1):** 15745da0_abs answers about vintage cameras when asked
  about vintage films; it should have abstained.

## Reading

n=30 is small (±9 points); this is a position check, not a gate. It says
the same thing the LoCoMo gates say: retrieval is level with a plain
baseline, and the answer step throws away evidence it already has.
