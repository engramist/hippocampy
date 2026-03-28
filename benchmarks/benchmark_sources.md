# SideQuest Brain — Benchmark Sources

This document provides canonical links, citations, and license terms for the benchmarks used to evaluate the SideQuest Brain Daemon.

## SWE-CI (SoftWare Engineering – Continuous Integration)
- **Goal:** Long-term codebase maintenance and EvoScore (maintenance vs. technical debt).
- **Source:** [SoftWare Engineering – Continuous Integration for Long-Term Maintenance](https://arxiv.org/abs/2603.xxxxx) (March 2026)
- **Repository:** `TBD` (Private/Beta early access)
- **License:** Apache 2.0
- **Release Date:** March 15, 2026
- **Task Count:** 100 tasks across 68 repositories.
- **Notes:** Specifically evaluates the ability to sustain code quality across multiple commits.

## LoCoBench (Long-Context Benchmark)
- **Goal:** Complex, large-scale software engineering scenarios (10k to 1M tokens).
- **Source:** [arxiv:2509.09614](https://arxiv.org/abs/2509.09614)
- **Repository:** [SalesforceAIResearch/LoCoBench](https://github.com/SalesforceAIResearch/LoCoBench)
- **License:** BSD 3-Clause
- **Release Date:** September 2025
- **Task Count:** 8,000 evaluation scenarios across 10 languages.
- **Notes:** High token volume testing; measures how models handle deep multi-file dependencies.

## AMA-Bench (Agent Memory with Any length)
- **Goal:** Long-horizon memory and continuous stream interaction.
- **Source:** [arxiv:2602.22769](https://arxiv.org/abs/2602.22769)
- **Repository:** [AMA-Bench/AMA-Bench](https://github.com/AMA-Bench/AMA-Bench)
- **License:** MIT
- **Release Date:** February 2026
- **Task Count:** 2,496 expert-curated QA pairs (Real-world subset).
- **Notes:** Tests the "Causality Graph" and tool-augmented retrieval performance.

## MemoryArena
- **Goal:** Agentic memory in interdependent multi-session agentic tasks.
- **Source:** [memoryarena.github.io](https://memoryarena.github.io/) / [arxiv:2602.16313](https://arxiv.org/abs/2602.16313)
- **Repository:** [MemoryArena/MemoryArena](https://github.com/MemoryArena/MemoryArena)
- **License:** MIT
- **Release Date:** February 2026
- **Task Count:** 4 Domains (Bundled Shopping, Travel Planning, Info Search, Formal Reasoning).
- **Notes:** Focuses on the "Memory-Agent-Environment loop" and latent task state maintenance.

## Autonomous Research Simulation Harness (Local Custom)
- **Goal:** Verify memory-augmented hypothesis regression rate in autonomous loops.
- **Source:** Internal project artifact (Backlog B52)
- **Repository:** `benchmarks/autoresearch/`
- **License:** Project License
- **Release Date:** Planned for P11 (Late March 2026)
- **Status:** **Experimental** (In development)
- **Notes:** Uses deterministic seeds and ephemeral worktrees for safety.
