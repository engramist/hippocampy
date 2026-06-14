# Campy Ask — Augmented Inference with Graph-Native Thalamic Compression

**Date:** 2026-06-13
**Status:** Approved — ready for implementation planning
**Branch:** main
**Related backlog:** New initiative (B289+)

---

## Problem

Campy retrieval tools (`current_truth`, `compile_context`, `recall_relevant_lessons`) return raw memory bundles to the calling agent. The agent then reasons over that context in its own inference step. Two problems compound here:

1. **Token bloat on emission.** Campy emits serialized graph data as verbose JSON — curly braces, repeated keys, full UUIDs, raw relationship objects. A bundle that could convey the same information in 400 tokens often arrives at 1,200. This wastes the agent's context budget before any reasoning happens.

2. **No memory-grounded inference endpoint.** Agents can retrieve facts from Campy, but there is no way to delegate a full memory-grounded question to Campy and get a synthesized answer back. Non-coder users have no conversational interface to their project's brain at all.

This design solves both: a new `ask` pipeline that augments a query with memory, compresses the bundle using graph-native logic, makes an LLM inference call, and captures the result — exposed as both a CLI command and an MCP tool.

---

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Where compression lives | Campy's emit path (thalamus) | Desktop apps own their process; proxy interception is structurally blocked. MCP tool responses are Campy's to shape universally. |
| Fork headroom? | No — pure blueprint | Headroom's internals are generic-content implementations. They have no concept of graph node types, relationship semantics, or topology-based importance. Forking gives us an interface we'd gut entirely. We take the pattern, build from scratch. |
| Primary compression method | Graph-native PageRank pruning | Campy's bundles are subgraphs, not JSON arrays. The most powerful compression is semantic pruning based on graph topology — not syntax elimination. See §3 for why this matters. |
| Compression trigger | Always-on (Option B) | Compression is a quality amplifier, not emergency overflow relief. Structured data and code compress unconditionally (free). LLM prose fires only when prose is present in the bundle. |
| Front doors | CLI + MCP tool, one shared core | Thin wrappers over the same function. Nearly free to expose both; serves both user personas. |
| New heavy dependencies | None | No torch, no HuggingFace, no headroom, no model downloads. Two lightweight additions: `j2toon` (pure Python) and `py-tree-sitter-languages` (pre-compiled wheels, no cmake). |

---

## Architecture and Placement

### Why the Thalamus

Biologically, the thalamus is the brain's relay and gating station — it regulates what information flows through to the cortex. In Campy's anatomy, the thalamus is already the context-window-assembly and output plane: it houses `bundle_compiler.py` (augmentation), `working_memory.py` (token budgeting, dedup), and the formatters. Compression is the last shaping step before context leaves the brain. It belongs there, as the natural sibling of budgeting and formatting.

### Module Structure

```
campy/brain/thalamus/
├── compression/
│   ├── __init__.py           # Compressor ABC + PluggableCompressorRegistry + ContentRouter
│   ├── graph_bundle.py       # GraphBundleCompressor — PageRank pruning + compact adjacency notation
│   ├── structured_data.py    # StructuredDataCompressor — TOON/ONTO via j2toon
│   ├── llm_prose.py          # LLMCompressor — prose via existing LLMClient
│   ├── ast_mapper.py         # ASTCodeCompressor — signatures via tree-sitter
│   └── fallback.py           # NoOpCompressor — passthrough / opt-out
├── ask.py                    # Orchestrator: augment → classify → compress → send → capture
├── bundle_compiler.py        # (existing)
└── working_memory.py         # (existing)
```

### Two Front Doors, One Core

**CLI** — `campy ask "what did we decide about auth?"`
Human-facing Typer command. Campy is the agent. The user gets a memory-grounded answer in plain text. This is the consumer-facing "chat with your project's brain" front door for non-coder users.

**MCP tool** — `ask`
Agent-facing. When Claude Code or Codex calls `ask`, Campy makes its own LLM call internally and returns the synthesized answer as text. This is the sub-agent pattern: an LLM call nested inside the calling agent's tool call. The tool description explicitly scopes it to **"answer this question from project memory"** — not a general-purpose chat shortcut. Agents should use `current_truth` or `compile_context` when they want raw facts; `ask` is for delegating a synthesized answer.

Both front doors share the same `ask.py` core. The CLI adds a Typer entry point. The MCP tool adds a tool schema wrapper. Neither duplicates logic.

---

## Why Graph-Native Compression Is Different

**This section exists because agents reading this spec may be tempted to replace `GraphBundleCompressor` with a generic JSON compressor. Do not do this. The distinction is fundamental.**

Campy's memory bundles are not JSON arrays of uniform records. They are serialized subgraphs: heterogeneous node types (Concept, Decision, Lesson, Plan, Procedure, Constraint) connected by named, semantically meaningful edges (REQUIRES, ENABLES, CONTRADICTS, PART_OF, CHOSEN_OVER, IMPLEMENTS, EXTENDS, DEPRECATED_BY).

Generic compression approaches — including TOON/ONTO and headroom's SmartCrusher — reduce **syntactic overhead**: they eliminate curly braces, repeated keys, and structural punctuation. This is real but shallow. A TOON-compressed bundle of 40 Concept nodes still contains 40 nodes, most of which may be irrelevant to the current query.

**Graph topology is itself information.** A node with 12 active relationships to query-relevant neighbors is more important than an isolated node with 1 edge. A Decision node that sits on the shortest path between the query topic and 6 downstream Lessons is critical context. A Concept node that was archived 90 days ago and has no relationship to anything in the current query is noise.

Graph-native compression uses topology to answer the question generic compression cannot ask: **which nodes matter for this query?**

The research document referenced during brainstorming describes Personalized PageRank for code repo maps — ranking symbol importance relative to the active file using a directed graph and a query personalization vector. The identical algorithm applies to Campy's knowledge graph:

| Code repo map concept | Campy graph bundle equivalent |
|---|---|
| Files and symbols = nodes | Concept, Decision, Lesson, etc. = nodes |
| Import references = directed edges | REQUIRES, ENABLES, PART_OF, etc. = directed edges |
| Active file = personalization vector | Query embedding = personalization vector |
| PageRank → prune low-rank symbols | PageRank → prune low-relevance nodes |

This is deterministic. It uses KuzuDB traversal and the HNSW vector index already in Campy's schema. It requires no extra LLM call, no new infrastructure, and no new dependencies.

---

## The Compression Pipeline

The orchestrator in `ask.py` runs every bundle through a fixed sequence.

### Augment → Classify → Compress → Send → Capture

```
ask(query)
    │
    ▼
bundle_compiler.py          ← assembles typed bundle from KuzuDB
    │
    ▼
ContentRouter               ← classifies bundle sections by type
    │
    ├─► graph_data           → GraphBundleCompressor
    ├─► structured_metadata  → StructuredDataCompressor
    ├─► prose (if present)   → LLMCompressor
    └─► code_extracts        → ASTCodeCompressor
    │
    ▼
compressed bundle
    │
    ▼
LLMClient(query + bundle)   ← inference call
    │
    ▼
notify_turn(response)       ← passive ingestion / capture
    │
    ▼
return answer
```

### ContentRouter

Inspects the typed sections of the bundle dispatched by `bundle_compiler.py`. It knows Campy's own bundle structure — it is not a generic MIME sniffer. Each section type maps to exactly one compressor. A bundle with no prose section skips `LLMCompressor` entirely; a bundle with no code extracts skips `ASTCodeCompressor`. `GraphBundleCompressor` and `StructuredDataCompressor` always run.

---

### Compressor 1 — `GraphBundleCompressor` (primary)

**File:** `campy/brain/thalamus/compression/graph_bundle.py`
**Deps:** KuzuDB (already present), sentence-transformers (already present)
**Always runs:** Yes

This is the primary compressor and the novel piece that makes Campy's compression categorically different from headroom or any generic tool.

**Pipeline inside `graph_bundle.py`:**

1. **Embed the query.** The `ask` prompt is vectorized using Campy's existing sentence-transformer (same model, no second load).

2. **Score nodes via Personalized PageRank.** Run PageRank over the bundle subgraph with the query embedding as the personalization vector. Nodes that are:
   - semantically close to the query (high HNSW similarity), AND
   - well-connected to other relevant nodes (high adjacency weight)
   
   score high. Nodes that are semantically distant or isolated score low. KuzuDB traversal executes this over the live graph.

3. **Prune.** Drop all nodes scoring below `graph_prune_threshold` (default: bottom 30%). Their outbound and inbound edges are dropped with them. This step alone typically reduces bundle size 40–70%.

4. **Serialize in compact adjacency notation.** The pruned subgraph is emitted as a compact adjacency list using short relationship codes from Campy's schema and single-character node type prefixes. This eliminates JSON structural overhead on what remains after pruning.

**Compact adjacency notation:**

```
# Raw KuzuDB output (verbose JSON)
{"type": "Concept", "id": "c-1a2b", "text": "auth middleware", "confidence": 0.91}
{"rel": "REQUIRES", "from": "c-1a2b", "to": "c-3c4d", "confidence": 0.87}
{"type": "Decision", "id": "c-3c4d", "text": "use JWT, not sessions", "confidence": 0.95}
{"rel": "CONTRADICTS", "from": "c-3c4d", "to": "c-5e6f"}
{"type": "Concept", "id": "c-5e6f", "text": "cookie-based sessions", "confidence": 0.72}

# Compact adjacency notation (after pruning + serialization)
C:auth middleware -REQ-> D:use JWT, not sessions
D:use JWT, not sessions -CON-> C:cookie-based sessions
```

Relationship codes: `REQ` (REQUIRES), `ENB` (ENABLES), `CON` (CONTRADICTS), `POF` (PART_OF), `CHO` (CHOSEN_OVER), `IMP` (IMPLEMENTS), `EXT` (EXTENDS), `DEP` (DEPRECATED_BY).
Node prefixes: `C` (Concept), `D` (Decision), `L` (Lesson), `P` (Plan), `PR` (Procedure), `K` (Constraint).

The two-step compression (prune then serialize) compounds: pruning removes irrelevant nodes before serialization reduces overhead on what remains. Combined reduction: 60–85% on typical memory bundles.

---

### Compressor 2 — `StructuredDataCompressor`

**File:** `campy/brain/thalamus/compression/structured_data.py`
**Deps:** `j2toon` (pure Python, zero heavy deps, Apache-2.0)
**Always runs:** Yes

Handles flat structured data sections: session metadata, tool call records, configuration facts, tabular outputs. These are generic JSON arrays where graph topology is not present — TOON/ONTO is the right tool.

TOON declares schema once (`employees{id,name,role}:`), then streams rows as comma-delimited values. ONTO uses pipe delimiters with 4-space indentation for nested hierarchies. Format is selected by `structured_format` in `campy.toml` (default: `toon`). Token reduction: 30–60%. LLM comprehension is preserved or improved — models process 40–60% more data within the same budget.

---

### Compressor 3 — `LLMCompressor`

**File:** `campy/brain/thalamus/compression/llm_prose.py`
**Deps:** None (reuses existing `LLMClient`)
**Runs when:** Bundle contains prose sections (lesson text, plan summaries, procedure descriptions, decision rationale)

Uses Campy's existing `LLMClient` with a compression prompt tuned for memory fidelity:

> "Compress the following. Preserve every entity name, decision, number, file path, and negation verbatim. Eliminate connective tissue, filler phrases, and redundant transitions. Do not alter semantic intent."

A `compression_model` config key in `campy.toml` (default: empty, inherits from `[llm]`) can point at a cheaper model (e.g. `claude-3-5-haiku`, `ollama/llama3.1:8b`) to reduce per-call cost when the main inference uses a larger model.

---

### Compressor 4 — `ASTCodeCompressor`

**File:** `campy/brain/thalamus/compression/ast_mapper.py`
**Deps:** `py-tree-sitter-languages` (pre-compiled binary wheels, MIT/Apache-2.0, no cmake)
**Runs when:** Bundle contains code extracts from ingested documents

Uses tree-sitter to parse source files and fold function/method bodies to signatures. Strips inline comments and docstrings. Preserves class hierarchy and method signatures. Token reduction: 75–90% on typical source files.

Can be disabled via `ast_compression = false` in `campy.toml` if the binary wheels are unavailable on a target platform.

---

### `NoOpCompressor`

**File:** `campy/brain/thalamus/compression/fallback.py`

Passthrough — returns content unchanged. Used as the registry default if a content type is unrecognized, and as the opt-out path for users or tests that need raw output.

---

## Dependencies

| Package | Purpose | Size | License | Notes |
|---|---|---|---|---|
| `j2toon` | TOON serialization | Pure Python, ~10KB | Apache-2.0 | Zero heavy deps |
| `py-tree-sitter-languages` | Pre-compiled tree-sitter parsers (40+ languages) | ~30MB binary wheels | MIT/Apache-2.0 | Ships as platform wheels — no cmake, no build step at install time |

No headroom. No torch. No HuggingFace. No model downloads. The B272 curl installer experience is preserved.

---

## `campy.toml` Configuration

```toml
[compression]
# Model used for LLM prose compression.
# Empty = inherit from [llm]. Set to a cheaper model to reduce compression cost.
# Example: "claude-3-5-haiku", "ollama/llama3.1:8b"
compression_model = ""

# Nodes scoring below this percentile by PageRank are pruned from graph bundles.
# 0.30 = drop bottom 30%. Lower = more aggressive pruning.
graph_prune_threshold = 0.30

# Serialization format for flat structured data sections: "toon" or "onto"
# TOON: better for uniform flat arrays. ONTO: better for nested hierarchies.
structured_format = "toon"

# Set to false to disable ASTCodeCompressor (e.g. tree-sitter wheels unavailable)
ast_compression = true
```

All keys are optional. Defaults produce full compression behavior without any `campy.toml` changes.

---

## Testing

### `GraphBundleCompressor`
Uses deterministic fixture graphs built directly in KuzuDB — not mocks. Each fixture encodes a known topology: a hub node with high expected PageRank, isolated leaf nodes that should be pruned, and a query vector seeded to be close to the hub. Assertions:
- Pruned output contains hub node; drops leaves below threshold
- Compact adjacency notation round-trips (decode back to same node/edge set)
- Changing `graph_prune_threshold` produces measurably different output sizes
- Empty bundle → empty output, no crash

### `StructuredDataCompressor`
Fixture: known JSON dict → TOON string → assert token count reduction ≥ 30%. Second fixture verifies LLM can extract a specific field from TOON output (prevents format comprehension regressions).

### `LLMCompressor`
Real `LLMClient` call — not mocked (same philosophy as no-mock-DB rule). Fixture: known prose block with specific entity names, numbers, and negations. Assertions: all entity names preserved verbatim, all numbers preserved, negation phrases preserved, output shorter than input.

### `ASTCodeCompressor`
Fixture: known Python file with class + method bodies. Assert output contains only signatures (`def foo(self, x):...`), no bodies, no comments. Assert token count reduction ≥ 70%.

### `ask.py` Orchestrator (integration)
End-to-end: seed fixture graph + prose bundle, call `ask`, assert LLM receives compressed bundle (via `LLMClient` call log), assert captured turn lands in KuzuDB via `notify_turn`. Covers the full augment → classify → compress → send → capture path.

### Regression Guard
A single parametrized test runs all four compressors on canonical fixture inputs and records output token counts. Any PR that regresses compression ratio by more than 5% on any fixture fails CI.

---

## Phase Scope

**Phase A — `ask` tool pipeline only**
Implement the full augment → classify → compress → send → capture chain in `ask.py`. Expose as both CLI (`campy ask`) and MCP tool (`ask`). All four compressors land here.

**Phase B — Compress all MCP tool responses**
Extend the same `compression/` module to wrap *all* Campy MCP tool responses: `current_truth`, `compile_context`, `recall_relevant_lessons`, `reconstruct_timeline`, etc. Same compressors, same registry — the emit path for every tool routes through `compression/` before returning to the caller. Phase B is additive: it wires existing tools through the Phase A infrastructure.

---

## What to Preserve When Implementing

- **Do not replace `GraphBundleCompressor` with a generic JSON compressor.** TOON/ONTO is correct for flat structured data (Section 3 of the pipeline) but wrong for graph bundles. Graph bundles require topology-aware pruning first, then serialization. The two steps are not interchangeable.
- **`compression_model` must default to the same model as `[llm]`.** Never load a second model by default. The cost knob is opt-in.
- **Both front doors must share one implementation.** The CLI entry point and the MCP tool schema are thin wrappers only. No logic duplication.
- **`notify_turn` is the capture step, not an optional add-on.** Every `ask` call must capture the turn so the exchange becomes part of the project's memory.
