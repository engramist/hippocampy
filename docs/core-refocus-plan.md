# Core Refocus Plan

## Why This Pivot

SideQuests is strongest when it acts as a local memory layer for multi-agent workflows:

- durable recall across sessions and tools
- shared memory across multiple AI agents
- smaller, more purposeful prompts
- lower cost through less redundant context injection

The ARC-AGI work produced useful stress tests and some reusable infrastructure, but it is no longer the main product direction. For the next stretch, ARC should be treated as a paused side track, not the driver of roadmap priority.

## Product North Star

SideQuests/Campy should help a user run multiple AI agents against the same work without paying to repeatedly restate:

- what the project is
- what has already been decided
- what constraints are active
- what work is in flight
- what lessons were learned in prior sessions

The value proposition is:

1. Local-first persistent memory
2. Multi-agent continuity and handoff
3. Token-efficient retrieval instead of transcript stuffing
4. Lower cloud spend through targeted recall and model routing

## Keep, De-Emphasize, Pause

### Keep and strengthen

- `mcp_engine/hippocampus.py`
  Semantic quest routing is core to shared multi-session memory.
- `mcp_engine/working_memory.py`
  Loaded-node tracking and dedup are directly tied to token savings.
- `mcp_engine/warm_frontier.py`
  Pre-activation supports just-in-time recall without bloating prompts.
- `mcp_engine/tools/`
  The retrieval surface is the real product.
- `adapters/`
  Cross-client memory access is required for multi-agent workflows.
- `sidequests/cli/`
  Setup and reliability are adoption-critical.
- `web/`
  Local visibility and debugging matter for trust.

### De-emphasize

- benchmark storytelling that centers ARC as the main proof point
- solver-specific orchestration logic that only exists for puzzle play
- roadmap sequencing that assumes ARC success is the primary milestone

### Pause unless needed for maintenance

- `agents/arc3/`
- ARC-specific ready cards in the backlog
- submission/offline packaging work that does not improve the core memory product

## Core Execution Priorities

### Priority 1: make shared local memory undeniable

Prove that two or more agents can:

- write to the same memory graph
- retrieve each other's decisions and constraints
- hand off work without full prompt restarts
- continue accurately after a fresh session

This should become the main demo path.

### Priority 2: tighten token and cost efficiency

Double down on the existing working-memory design:

- confirm `LOADED` edge tracking is stable across adapters
- measure dedup savings in real multi-turn, multi-agent sessions
- keep retrieval outputs compact and decision-oriented
- route simpler tasks to smaller/local models when quality allows

### Priority 3: improve retrieval quality under real project work

The retrieval layer should return:

- active decisions
- current constraints
- open action items
- recently learned lessons
- high-signal quest context

The test is not whether the graph is clever. The test is whether the next agent step needs less repeated explanation.

### Priority 4: make setup boring

The install and adapter story must stay simple enough that SideQuests feels like infrastructure, not an experiment.

## Suggested Near-Term Work Queue

1. Run and document a real multi-agent memory workflow using existing adapters.
2. Validate token savings on that workflow using working-memory metrics rather than ARC prompts.
3. Audit retrieval outputs for over-injection and weak ranking.
4. Improve handoff quality between sessions on the same quest.
5. Tighten the UI/status surfaces so users can see what memory was recalled, why, and what tokens were avoided.

## Repo-Level Guidance

- Do not remove ARC code blindly; just stop letting it set the roadmap.
- Prefer new work in `mcp_engine/`, `adapters/`, `sidequests/cli/`, and `web/`.
- Treat ARC assets as optional benchmarking and regression infrastructure unless a change clearly benefits the core memory system.
- When choosing between "better puzzle solving" and "better multi-agent memory continuity", choose the latter.

## Success Criteria For The Refocus

We are back on track when:

1. A multi-agent SideQuests demo is stronger than the ARC story.
2. Memory handoff quality is obvious in normal software/project workflows.
3. Token savings are measured on real agent collaboration, not just synthetic cases.
4. New backlog work is mostly about memory quality, retrieval quality, adapter reliability, and setup UX.
