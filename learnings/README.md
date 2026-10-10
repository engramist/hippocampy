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
| [e2e-status.md](e2e-status.md) | Live state of the plan: current milestone, pins, latest numbers, golden stores, open PRs, next actions. Updated after every step |

## Adding a note

- One file per campaign or milestone, named `YYYY-MM-<topic>.md`.
- Lead with the numbers and the commits they came from.
- Record what did *not* work as carefully as what did.
- Name the tool or run (R-number on engramist/hippocampy#278) that produced
  each claim, so it can be re-checked.
