# SideQuest Brain — Benchmark Sources

This document provides canonical links, citations, and license terms for the benchmarks used to evaluate the SideQuest Brain Daemon.

## ARC3
- **Status:** Unverified (not confirmed fabricated, not confirmed reproducible — see
  `backlog/B332.md`'s 2026-08-20 correction).
- **Reason:** `benchmarks/results/arc3.json`'s specific numbers (`solve_rate_improvement: 0.08`,
  `p_value: 0.042`) don't trace to any harness or run in *this* repo. A real ARC-AGI-3 A/B harness does
  exist in the sibling `ARC_AGI` repo (`benchmarks/arc3/harness.py` — "ARC-AGI-3 A/B Harness (Baseline
  vs SideQuests-Augmented)", wired to Campy over MCP via `sidequest_mcp_client`), and could plausibly
  produce a result in this shape — but a search of that repo's
  `benchmarks/results/regression_history.jsonl` found no matching run.
- **Current Action:** Treat this specific number as unverified, not established. Do not cite it in
  claims. Cross-repo reconciliation (locating or re-running the actual source of this number in
  ARC_AGI, or confirming conclusively it can't be found) is open work.

## SWE-CI (Internal Synthetic Sample)
- **Goal:** Constraint-compliance comparison between baseline and memory-assisted variants.
- **Source:** Internal sample dataset (`benchmarks/swe_ci/data/swe_ci_sample.json`).
- **Repository:** This repository only (no external benchmark repository linked).
- **License:** Project License.
- **Task Count:** 4 tasks (current checked-in dataset).
- **Notes:** Prior placeholder citation (`arxiv:2603.xxxxx`, `Repository: TBD`, and
	"100 tasks across 68 repositories") was removed as unverified.

## Synthetic Long-Context Needle Proxy
- **Goal:** Stress long-context retrieval behavior with synthetic needle-in-haystack prompts.
- **Source:** Internal generator in `benchmarks/longcontext/harness.py`.
- **Task Count:** 5 tasks per configured context size (`context_sizes`).
- **Notes:** Inspired by LoCoBench-style evaluation design but does not run the external
	8,000-scenario LoCoBench dataset.

## Synthetic Causal Arithmetic Proxy
- **Goal:** Multi-step arithmetic reasoning with shared constraints.
- **Source:** Internal generator in `benchmarks/causal/__init__.py::generate_ama_bench_tasks`.
- **Task Count:** Configurable synthetic tasks (default 10).
- **Notes:** Inspired by AMA-Bench themes; does not run the published AMA-Bench dataset.

## Synthetic Capacity-Constraints Proxy
- **Goal:** Interdependent state transitions with capacity/dependency constraints.
- **Source:** Internal generator in `benchmarks/causal/__init__.py::generate_memory_arena_tasks`.
- **Task Count:** Configurable synthetic tasks (default 10).
- **Notes:** Inspired by MemoryArena-style scenarios; does not run the published MemoryArena dataset.

## External Papers Referenced as Design Inspiration (Not Directly Executed Here)
- LoCoBench: [arxiv:2509.09614](https://arxiv.org/abs/2509.09614),
	[SalesforceAIResearch/LoCoBench](https://github.com/SalesforceAIResearch/LoCoBench)
- AMA-Bench: [arxiv:2602.22769](https://arxiv.org/abs/2602.22769),
	[AMA-Bench/AMA-Bench](https://github.com/AMA-Bench/AMA-Bench)
- MemoryArena: [arxiv:2602.16313](https://arxiv.org/abs/2602.16313),
	[MemoryArena/MemoryArena](https://github.com/MemoryArena/MemoryArena)

## Autonomous Research Simulation Harness (Local Custom)
- **Goal:** Verify memory-augmented hypothesis regression rate in autonomous loops.
- **Source:** Internal project artifact (Backlog B52)
- **Repository:** `benchmarks/autoresearch/`
- **License:** Project License
- **Release Date:** Planned for P11 (Late March 2026)
- **Status:** **Experimental** (In development)
- **Notes:** Uses deterministic seeds and ephemeral worktrees for safety.
