# SideQuests Architecture

> Canonical architecture reference for `sidequests-brain`.
> This document defines the memory-system architecture only.
> ARC solver and benchmark architecture now lives in the sibling `ARC_AGI` repo.

## Scope

`sidequests-brain` is the local memory engine.

Its responsibilities are:

- persistent graph-native memory
- compact retrieval for agent decision support
- cross-session and cross-agent continuity
- working-memory tracking for context efficiency
- local adapters and runtime surfaces that let multiple AI clients share memory

It is not the home for ARC solver architecture.

### Wiki Projections

Read-only Markdown surfaces generated from graph state.

- **Primary UI:** Obsidian (local vault).
- **Secondary UI:** Any Markdown viewer.
- **Ownership:** SideQuests (Dreaming phase).
- **Invariant:** Graph-native state in KuzuDB is the single source of truth.
  - **ARC artifacts:** ARC_AGI run artifacts are evidence inputs and must be ingested into KuzuDB (for example via `ingest_arc_artifacts`) before the Wiki projects them. The Wiki must not treat raw ARC JSON files as authoritative memory.

Detailed specification: [docs/wiki-projection-architecture.md](wiki-projection-architecture.md)

## Companion References

- Ecosystem rules: [docs/ecosystem-rules.md](ecosystem-rules.md)
- Tool catalog: [docs/tool-catalog.md](tool-catalog.md)
- Token-efficiency design note: [docs/token-efficiency-side-effect.md](token-efficiency-side-effect.md)
- Backlog rules: [backlog/BacklogRules.md](../backlog/BacklogRules.md)
- Backlog tracker: [backlog/masterBacklogTracker.md](../backlog/masterBacklogTracker.md)
- Refocus note: [docs/core-refocus-plan.md](core-refocus-plan.md)

## Mission

SideQuests/Campy is a local-first memory system for multi-agent workflows.

The product goal is simple:

- remember durable project context
- reduce prompt repetition
- preserve continuity across sessions and tools
- supply compact, relevant memory only when it helps a decision

The operating philosophy is:

- keep prompts small and purposeful
- retrieve just in time
- rank and compress memory rather than dump transcripts
- treat the context window as a scarce working resource

## Core Principles

### 1. Retrieval should shrink context

SideQuests should make the next prompt smaller and better, not larger and noisier.

### 2. Memory is graph-native

The system stores entities, decisions, constraints, plans, and lessons as connected nodes and edges, not as flat text blobs.

### 3. Passive ingestion, active recall

The system can ingest turns continuously, but retrieval should be selective and decision-triggered.

### 4. Working memory matters

What the assistant has already seen in the current session should be tracked so we do not keep re-injecting the same memory.

### 5. Multi-agent continuity is a first-class use case

Different assistants should be able to converge on the same quest context and reuse shared memory instead of repeatedly re-establishing state.

## High-Level Architecture

```
SideQuests Brain Daemon
  ├── embedded graph + vector storage
  ├── gated consolidation loop
  ├── retrieval and memory tools
  ├── session routing + working-memory tracking
  ├── local adapters for AI clients
  └── local inspection/control UI
```

### Deployment Model

```
Brain Daemon (Python)
  ├── Kuzu embedded database
  ├── memory ingestion + retrieval engine
  ├── local IPC surfaces
  └── local-only web panel

Adapters
  ├── Claude Code
  ├── Claude Desktop
  ├── Codex
  ├── ChatGPT Desktop
  └── Gemini CLI
```

Adapters forward turns and tool calls into the memory system.
The daemon owns the durable state.

## Technology Stack

- Python
- Kuzu `0.11.3` as the embedded graph/vector database
- spaCy for low-cost entity extraction
- sentence-transformers for local embeddings
- FastAPI for the local-only UI/runtime endpoints
- configurable LLM provider interface for the parts of the loop that need model help

## Runtime Boundaries

### What lives in SideQuests

- graph schema
- ingestion loop
- retrieval and ranking logic
- quest/session routing
- working-memory tracking
- memory tools
- adapters
- local web/status surfaces

### What does not live here anymore

- ARC solver orchestration
- ARC benchmark harness architecture
- ARC submission/compliance architecture

Those belong in the sibling `ARC_AGI` repo.

## Main Subsystems

### Quest Routing

Implemented primarily in `mcp_engine/hippocampus.py`.

Purpose:

- decide which MainQuest a session belongs to
- reuse an existing quest when evidence is strong
- create a new quest when the work is genuinely distinct
- support cross-session continuity without manual bookkeeping

Routing uses:

- git/workspace signals when available
- semantic similarity
- confidence thresholds
- tentative to consolidated progression over time

### Working Memory

Implemented primarily in `mcp_engine/working_memory.py`.

Purpose:

- track which nodes have already been loaded into a session
- demote already-loaded memory during retrieval
- support handoff into later sessions
- estimate context bloat before the prompt gets too large

This is the core of the token-efficiency story.

### Gated Consolidation Loop

Implemented under `mcp_engine/loop/`.

Purpose:

- transform raw turns into structured, queryable memory
- filter noise before it becomes durable graph state
- classify, connect, and strengthen meaningful memory

Core flow:

1. Extract candidate entities and relations
2. Classify concepts into usable shapes
3. Connect or create graph state
4. retrieve nearby relevant memory for contradiction/comparison
5. update pathway strength and confidence

This loop exists to improve memory quality, not to preserve every message verbatim.

### Retrieval Layer

Implemented across `mcp_engine/tools/`, graph helpers, and ranking logic.

Purpose:

- return compact, decision-relevant memory
- prefer active constraints, decisions, and open work
- avoid bulk transcript replay
- support both direct lookup and graph-neighborhood exploration

The retrieval layer is the product surface the user feels most directly.

### Adapters

Implemented under `adapters/` and `sidequests/adapters/`.

Purpose:

- connect different AI clients to the same local memory engine
- keep tool surfaces aligned across clients
- preserve the same memory model regardless of the front-end assistant

### Local UI / Visibility

Implemented under `web/`.

Purpose:

- inspect health and memory behavior locally
- make memory visible and debuggable
- help users trust what was stored, recalled, and ranked

### Wiki Projection

Implemented via the Dreaming/sweep phase and `WikiExporter` (B222).

Purpose:

- provide a tactile, human-readable surface for graph memory
- support relationship-heavy browsing (backlinks, related pages)
- allow persona-isolated views of complex knowledge
- bridge the gap between AI-native memory and human mental models

The Wiki is a read-only projection; the graph remains the authoritative source.

## Repository Structure

```
sidequests-brain/
├── sidequests/
│   ├── brain_daemon.py
│   ├── daemon.py
│   ├── cli/
│   └── adapters/
├── mcp_engine/
│   ├── hippocampus.py
│   ├── working_memory.py
│   ├── warm_frontier.py
│   ├── quest.py
│   ├── schema.py
│   ├── tool_schemas.py
│   ├── observability.py
│   ├── graph/
│   ├── llm/
│   ├── loop/
│   └── tools/
├── adapters/
├── web/
├── docs/
└── tests/
```

## Key Memory Concepts

### MainQuest / SideQuest

These are the scoping primitives for durable work.
They let multiple sessions and assistants converge on the same project context.

### Decisions, Constraints, Requirements, Action Items

These are the durable high-signal artifacts retrieval should prefer.

### Lessons and Outcomes

These preserve what worked, what failed, and what should influence future choices.

### Pathway Strength

A memory-strength signal that increases with meaningful access and decays over time.

### Confidence

A dynamic trust signal.
Low-confidence memory can exist, but it should rank lower and remain eligible for re-evaluation.

## Read Path

The normal read flow is:

1. receive a retrieval query
2. identify relevant quest/session scope
3. perform vector and graph-local search
4. demote already-loaded nodes when appropriate
5. rank for decision usefulness
6. return compact structured context

The read path should answer, "What does the next agent step need to know right now?"

Bounded episodic recall can return raw `Message` / `DocumentExtract` evidence
for provenance-style questions, but those raw nodes should not become
working-memory handoff cargo. They count against token/bloat estimates when
returned, while `LOADED` tracking remains reserved for consolidated artifact
memory.

## Write Path

The normal write flow is:

1. ingest a turn or artifact
2. extract candidate meaning
3. classify and normalize
4. deduplicate or link to existing graph state
5. update memory strength and provenance

The write path should preserve durable knowledge without turning the graph into a transcript dump.

## Configuration

Primary runtime config lives in `sidequests.toml`.

Important configurable areas include:

- LLM provider/model
- embedding model
- ingestion limits
- pruning/decay behavior
- context-window/working-memory thresholds

## Security / Local-First Constraints

- prefer local-first operation
- keep memory surfaces on localhost/local IPC only
- avoid exposing external network services by default
- treat graph state as user-controlled local data

## Current Product Direction

The near-term roadmap is centered on:

- better multi-agent shared memory
- better handoff quality
- better retrieval compactness and ranking
- adapter reliability
- lower token/cost footprint through working-memory-aware recall

## Relationship To ARC_AGI

`ARC_AGI` is now a sibling repo and should consume SideQuests as a dependency.

This repo should not be the canonical place for:

- ARC solve strategy design
- ARC benchmark orchestration
- ARC compliance/submission flow

Those architectural details belong with the ARC codebase itself. **Note:** Some historical ARC-related integration tests, schema fields, and benchmark baselines are retained in this repository solely for regression testing of the core memory engine. See `docs/arc-extraction-cleanup-audit.md` for the full manifest.
