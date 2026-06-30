# AGENTS.md

This file gives agent-neutral guidance for Codex and other coding agents working in this repository.

## Sources Of Truth

Read `docs/ARCHITECTURE.md` before making architecture, schema, retrieval, capture, or daemon behavior changes.
Read `docs/ecosystem-rules.md` before changing package boundaries or persistence behavior.
Use `docs/codebase-anatomy.md` when you need the target region for new code, and `docs/codebase-anatomy-refactor-plan.md` when you need migration context.

KuzuDB is the single source of truth for persistent memory state. Do not introduce shadow stores for durable agent state; in-memory structures are allowed only as caches over graph-backed state.

## Memory Usage Policy

Use `plugin/skills/recall/SKILL.md` as the canonical policy for when to recall Campy memory (dev-only: `skills/campy-memory/SKILL.md`). The short version: do not recall on every turn; recall only when a decision needs durable memory, and keep returned context compact.

If you are unsure whether recall is warranted, call `memory_decision` first. It recommends the next recall tool without retrieving memory itself.

## Heterogeneous Retrieval (B249–B254)

For multi-entity or broad context queries, use `compile_context` instead of making multiple individual recall calls. It assembles a `ContextBundle` from exact facts, semantic search, graph traversals, tabular data, and wiki summaries — pre-compressed to your token budget and formatted for your agent type.

`memory_decision` automatically routes to `compile_context` when it detects multi-entity queries. You can also call it directly with a `token_budget` and optional `output_format` (generic, claude_code, codex, claude_desktop, chatgpt_desktop, arc).

Tabular data (CSV, XLSX, TSV) ingested via `ingest_document` is stored in per-dataset SQLite files with metadata and extracted facts in the Kuzu graph. The bundle compiler includes relevant tabular data when assembling context.

## Augmented Inference (B289)

Use `ask` when you want a synthesized, memory-grounded answer in one call. It augments the query with graph-native memory, compresses the bundle through four pluggable compressors (`StructuredDataCompressor`, `LLMCompressor`, `ASTCodeCompressor`, `GraphBundleCompressor`), calls the LLM, and captures the result via `notify_turn`.

Tool selection guide:
- **Raw fact lookup** → `current_truth`
- **Assembled context bundle** → `compile_context`
- **Synthesized answer from memory** → `ask`

Human CLI: `campy ask "question"` (supports `--session`, `--budget`).

## Context Window Integration (Layer Cake)

Campy uses a 4-layer architecture to inject graph knowledge into agent context windows without requiring explicit tool calls:

1. **File Bridge** — `CONTEXT.md` and ADR files generated in project directories from graph state. Agents read these as regular files.
2. **Associative Hooks** — Trigger manifest compiled from Procedure/Lesson nodes. Claude Code hooks inject matching context before/after tool calls. Other agents get equivalent system prompt guidance.
3. **Anticipatory Engine** — GCL Step 4b auto-discovers trigger bindings during ingestion. Error/action patterns in messages trigger vector search against stored Lessons/Procedures; matches get auto-bound triggers.
4. **Process Skills** — Campy-native skills for deliberate deep retrieval.

Key modules: `mcp_engine/file_bridge.py`, `mcp_engine/trigger_manifest.py`, `mcp_engine/loop/step4b_associative.py`.
CLI: `campy context regen`, `campy trigger add|list|remove|compile`.
Design spec: `docs/superpowers/specs/2026-05-22-context-window-integration-design.md`.

## Activity Indicator

Use the Campy activity feed to verify live memory behavior:

```bash
.venv/bin/campy activity --follow
```

This tails `~/.campy/activity.log`, the compact operator-facing feed for:

- memory writes
- recall calls
- durable capture scans
- daemon lifecycle state
- tool success/error status

The activity feed redacts full prompt and assistant-response bodies. It may include operational metadata such as source client, role, session, character counts, recall query previews, and status. Use `~/.campy/daemon.log` only when debugging failures, launchd issues, or stack traces.

## PR Review Checklist (Ecosystem Gate)

When reviewing a pull request, check each rule below. Post findings in this exact table format:

| File | Line | Rule | Severity | Fix |
|------|------|------|----------|-----|

**Rules:**

**1. Layer placement** — new code must go in the correct directory per `docs/ecosystem-rules.md`.
- Flag: any file under `campy/` that imports from `agents/` or `benchmarks/`
- Flag: any file under `agents/` or `benchmarks/` that imports from `campy/`
- Flag: new files placed in the wrong top-level directory for their responsibility

**2. No shadow stores** — persistent agent state must go through KuzuDB, not in-memory structures.
- Flag: module-level `dict` or `list` in `campy/` whose name contains `store`, `cache`, `state`, `registry`, or `db` as an underscore-delimited component (e.g. `_cache`, `session_state`, `vector_db`)
- In-memory caches backed by KuzuDB reads are permitted; standalone in-memory state is not

**3. Tool registration** — every new MCP tool must be registered.
- Flag: a new function in `campy/brain/thalamus/tools/__init__.py` matching `*_tool` or `handle_*`
  that does not appear in the `TOOL_HANDLERS` dict in the same file

**4. Schema migrations** — schema additions need a migration entry.
- Flag: additions to `NODE_TABLES` or `REL_TABLES` in `campy/brain/hippocampus/schema.py`
  (both are module-level, no underscore prefix) that have no corresponding entry added to
  the `_MIGRATIONS` list inside the `init_schema()` function in the same file

**Decision:**
- If all rules pass: approve the PR.
- If any rule fails: request changes with the findings table above. Do not approve until fixed.
