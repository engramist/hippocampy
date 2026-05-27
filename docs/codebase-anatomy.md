# Codebase Anatomy

This document describes the **target anatomy for the upcoming refactor**, not necessarily the repository's full current layout. It is a navigation guide for contributors and agents so we can place new work in the right region, keep boundaries clean, and avoid mixing unrelated concerns.

The refactor organizes Campy memory-engine code into five functional brain regions:

- `brainstem`
- `sensory_cortex`
- `temporal_lobe`
- `hippocampus`
- `thalamus`

## Region Map

| Region | Responsibility | Examples |
|---|---|---|
| `brainstem` | Daemon lifecycle, status, telemetry, config, maintenance sweeps, and other always-on operational plumbing. | Startup/shutdown wiring, activity feed, observability, phase/status helpers, background sweep coordination. |
| `sensory_cortex` | Capture, ingestion, parsing, normalization, and local deterministic NLP that turns raw input into structured signals. | Transcript capture connectors, ingestion entrypoints, tabular ingestion, spaCy wrappers, parsing/normalization helpers. |
| `temporal_lobe` | Consolidation, classification, entity routing, salience, and anomaly handling. | Gated Consolidation Loop steps, dictionary routing, memory routing, anomaly detection, salience heuristics. |
| `hippocampus` | Durable graph memory, schema, quest identity, embeddings, and storage facades. | Kuzu schema DDL, graph client abstraction, embeddings, quest state, semantic quest routing. |
| `thalamus` | Retrieval routing, tool surface, graph traversal, context bundles, and working-context formatting. | MCP tool implementations, tool schemas, `current_truth`, `compile_context`, bundle formatters, retrieval decision helpers. |

## Where Do I Put My Change?

Use this as the default decision guide when you are not sure where a module belongs.

- `brainstem` if the change is about daemon startup, runtime health, telemetry, config, or background maintenance.
- `sensory_cortex` if the change starts with raw input and turns it into normalized data.
- `temporal_lobe` if the change decides what something is, how it should be routed, or whether it is salient or anomalous.
- `hippocampus` if the change touches durable graph storage, schema, quest identity, or embeddings tied to stored memory.
- `thalamus` if the change serves retrieval, context assembly, tool routing, or output formatting for agents.

If a change spans two regions, keep the region with the clearest ownership as the home and isolate the shared logic behind a small interface rather than merging the responsibilities.

## Do Not Cross These Boundaries

- Campy and agent/benchmark code stay separate. Campy code must not import from `agents/` or `benchmarks/`; those systems talk to Campy through `BrainClientProtocol` and MCP tool contracts.
- KuzuDB is the single source of truth for durable memory state. Do not add a shadow store for agent memory. In-memory structures are fine only as caches over graph-backed state.
- Transport stays loopback or stdin-based where required. MCP adapter transport should remain stdio or Unix-domain-socket based, and local control/status services may bind only to `127.0.0.1`.
- File writes must be safe by default. Canonicalize paths, reject traversal and symlink escapes, and keep writes inside the intended project or runtime directories.

## Notes For Contributors

This anatomy is meant to make future moves predictable, but the actual migration will happen in stages. During the transition, some modules may still live in their old homes or have compatibility shims. Use this map to choose the right target region for new code and to spot when a change is crossing a boundary it should not cross.
