# SideQuests Benchmark Results Report

**Generated on:** 2026-03-28 10:46:52

## Executive Summary
SideQuests performance across all benchmarks. Comparison between baseline and augmented modes.

### Go/No-Go Status
| Benchmark | Metric | Threshold | Actual | Sig. (p-val) | Status |
|---|---|---|---|---|---|
| ARC3 | retracted_unreproducible | N/A | N/A | N/A | ⛔ RETRACTED |
| SYNTHETIC_LONGCONTEXT_NEEDLE | long_context_accuracy_improvement | >= 0.0 | 0.05 | 0.015 | ✅ GO |
| SWE_CI | constraint_compliance_improvement | > 0.0 | 0.12 | 0.008 | ✅ GO |
| SYNTHETIC_CAUSAL_ARITHMETIC | hypothesis_regression | < 0.0 | -0.05 | 0.033 | ✅ GO |

## Model Evaluation Breakdown
| Model | Accuracy | Avg Latency (ms) |
|---|---|---|
| qwen2.5:3b | 68.42% | 931.6 |
| llama3.2:3b | 60.53% | 975.1 |
| qwen2.5:1.5b | 65.79% | 979.1 |
| phi3.5 | 65.79% | 785.7 |
| llama3.1:8b | 63.16% | 1410.5 |

## Hardware & Setup
- **Compute Specs:** Local Machine (Ollama environment)
- **Git Version:** `d54ddc62f71e53b44b8a9a9324d6b24d98dd1ae9`
- **Memory Limit:** 8.0 GB (configured)
- **CPU Limit:** 80% (configured)
- **LLM Provider:** Ollama

## Reproducibility
To reproduce these results, ensure the environment matches the checksums below and run:
```bash
python benchmarks/runner.py --all
```

### Artifact Checksums
| File | SHA-256 Checksum |
|---|---|
| benchmarks/runner.py | 249c76ddb98008f717dc58db958c9a8344f6df873397f68b70c89e3f88c30d12 |
| benchmarks/harness.py | 72c908c5c35d2af00fc48ed732a17e20279d9837e01a7a59a46270afd38bb08d |
| benchmarks/ab_harness.py | e033546964982d89400cc2716c821f675643d9585abd874ed3e395b9053a48d4 |
| benchmarks/config.yaml | f6c04df7865724d9f5cf3898c723fd64265c7d571f88f57b0e540c46068d3ae0 |
| benchmarks/results.json | 03b777789469891f97a923583b0a009d4db0d71f207c60321261aa4b928fd351 |

---

## Ask-Eval Harness — Model Default Decision (2026-08-02)

**Instrument:** `benchmarks/ask_eval/` (B304). Deterministic fixture graph seeded through
real tool handlers (`register_plan`, `report_outcome`, `upsert_lesson`, `notify_turn`),
16 questions across 5 families (identifier, paraphrase, cross_lane, continuation,
negative_control), scored by deterministic regex — no LLM judge. Reproduce with:
```bash
python -m benchmarks.ask_eval.runner --model <name> [--model <name> ...] --variant H0 [--variant H1] [--variant "H1+H2"]
```

**Context:** the original B304 run (2026-07-15, PR #16) found a 0% negative-control pass
rate across every model — later root-caused to a missing relevance floor in
`bundle_compiler.py` (fixed by B305/B306) and a scorer regex that only recognized one
model's phrasing style (fixed by the B304-scorer-fix PR, #19). B307 then closed a
retrieval regression the relevance floor introduced (paraphrased queries scoring 0.00 —
fixed via a keyword-overlap lexical bypass). The table below is the **first
decision-grade run** — retrieval bugs fixed, scorer fixed — not any of the earlier,
misleading tables.

### Full matrix (4 models × H0/H1/H1+H2, 16 questions, run 2026-08-02)

| Model | Variant | Overall | Identifier | Paraphrase | Cross-lane | Continuation | Neg-control | Median latency (s) |
|---|---|---|---|---|---|---|---|---|
| llama3.1:8b | H0 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 1.54 |
| llama3.1:8b | H1 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 1.42 |
| llama3.1:8b | H1+H2 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 1.34 |
| gemma4:e4b | H0 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 4.49 |
| gemma4:e4b | H1 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 4.27 |
| gemma4:e4b | H1+H2 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 3.65 |
| gemma4:e2b | H0 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 2.30 |
| gemma4:e2b | H1 | 0.56 | 0.50 | 0.25 | 0.50 | 0.50 | 100% | 2.27 |
| gemma4:e2b | H1+H2 | 0.56 | 0.50 | 0.25 | 0.50 | 0.50 | 100% | 2.27 |
| qwen3:8b | H0 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 3.18 |
| qwen3:8b | H1 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 3.41 |
| qwen3:8b | H1+H2 | 0.69 | 1.00 | 0.25 | 0.50 | 0.50 | 100% | 3.71 |

Raw JSON: `~/.campy/eval_results/ask-eval-20260802T140211Z.json` (not committed —
runtime-dir output, per B304's design).

### Findings

1. **llama3.1:8b, gemma4:e4b, and qwen3:8b are statistically tied** (0.69 overall,
   identical per-family scores) across every harness variant. Once B305/B306/B307 fixed
   the retrieval-layer bugs, **retrieval quality — not model choice — was the actual
   bottleneck the whole time.** The original B304 hypothesis ("a harnessed small model
   beats a naive better model") was answered indirectly: fixing retrieval mattered far
   more than either model size or the H1/H2 harness tricks, which add nothing once
   identifier and negative-control families are already saturated.
2. **llama3.1:8b is the fastest** of the tied group (median 1.3–1.5s vs 2.3–4.5s for the
   others) and the **smallest on disk** (4.9GB vs 7.2–9.6GB). Tied accuracy + best
   latency + smallest footprint → confirmed as the shipped default (`campy.toml`).
3. **gemma4:e2b regresses under H1** (identifier 1.00→0.50, overall 0.69→0.56) — the
   *only* model/variant combination that isn't flat. Reproducible across two separate
   runs (2026-07-15 and 2026-08-02). Not yet root-caused; H1's fast-path preamble likely
   interacts badly with this model's smaller context handling. Not investigated further
   since it doesn't affect the shipped default — flag for a future card if gemma4:e2b is
   ever considered for a low-RAM-tier default.
4. **Sample size caveat, unchanged from B304's original card:** 16 questions (4 per
   family) is enough to detect the large effects above but is not a large enough sample
   to bet a launch decision on for finer-grained differences. If a future model swap is
   considered, widen the question set (B304's own card flagged this; no follow-up card
   yet filed for it as of this writeup).

### Decision

Default model stays `llama3.1:8b` (`campy/data/config/campy.toml`, `[llm].model`) —
confirmed, not changed, by this run. Comment added at the config site pointing back here.