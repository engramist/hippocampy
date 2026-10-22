# Learnings

Dated records of what we learned while building and measuring Campy: what
was tried, what the numbers showed, what worked, what didn't, and why.
Settled design lives in `docs/ARCHITECTURE.md`; work items live in
`backlog/`. This folder is the memory of the *process*: read it before
starting work that has been tried before. An agent picking up the
improvement work starts with `2026-10-summary.md`, then
`e2e-improvement-plan.md`, then `e2e-status.md`.

| File | What it covers |
|---|---|
| [2026-10-benchmark-campaign.md](2026-10-benchmark-campaign.md) | 2026-09-28 → 10-10: vetting campy-benchmarks, real datasets and baselines, every result through R24/R26, the graph audit, the fixes that moved scores, and the process lessons |
| [2026-10-summary.md](2026-10-summary.md) | One-page summary of the campaign: seven things we learned and where things stand |
| [e2e-improvement-plan.md](e2e-improvement-plan.md) | The end-to-end plan and runbook, written for an agent to execute without stopping: targets, repos and conventions, how to work with the local agent, the evaluation system and gate, the pipeline with code locations, milestones M0–M5 with concrete work items, decision rules, and known traps |
| [2026-10-m2-reranker.md](2026-10-m2-reranker.md) | M2.1 cross-encoder reranker: recall up (0.33 → 0.47 at limit 6), accuracy down on both suites; closed after one fix attempt |
| [2026-10-m1-m2-gates.md](2026-10-m1-m2-gates.md) | Every M1/M2 gate of 2026-10-10/11: the cite prompt won; reranker, collapse, turn ordinal, speaker/date boosts, select-then-answer and a bigger answer model did not; presentation noise ≈ ±5 of 110 questions |
| [2026-10-m3-observations.md](2026-10-m3-observations.md) | M3 Observations merged (LoCoMo 65/39, p≈0.014; used only when the whole history does not fit) and M4.2 observation dates (temporal 11/3) |
| [2026-10-scoring-fix-and-round5.md](2026-10-scoring-fix-and-round5.md) | The adversarial-abstention scoring bug and its consequences (Observations gain was an artefact), the corrected held-out baseline table (Campy 0.450 vs full history 0.383 on conv-30), and #318/#319 closed |
| [2026-10-metric-switch.md](2026-10-metric-switch.md) | Gates switched to the benchmark's published metric (LoCoMo categories 1–4, pooled, no p threshold); #322 neighbours merged (+9 points); earlier closed gates re-scored |
| [2026-10-20-freeze-and-drift-controls.md](2026-10-20-freeze-and-drift-controls.md) | R68 (#318 adds nothing on top of Observations), the LongMemEval freeze and the memory guard, drift controls (B495), old PRs cleared (B496) |
| [e2e-status.md](e2e-status.md) | Live state of the plan: current milestone, pins, latest numbers, golden stores, open PRs, next actions. Updated after every step |

## Adding a note

- One file per campaign or milestone, named `YYYY-MM-<topic>.md`.
- Lead with the numbers and the commits they came from.
- Record what did *not* work as carefully as what did.
- Name the tool or run (R-number on engramist/hippocampy#278) that produced
  each claim, so it can be re-checked.
