# AGENTS.md

This file gives agent-neutral guidance for Codex and other coding agents working in this repository.

## Sources Of Truth

Read `docs/ARCHITECTURE.md` before making architecture, schema, retrieval, capture, or daemon behavior changes.
Read `docs/ecosystem-rules.md` before changing package boundaries or persistence behavior.

KuzuDB is the single source of truth for persistent memory state. Do not introduce shadow stores for durable agent state; in-memory structures are allowed only as caches over graph-backed state.

## Memory Usage Policy

Use `skills/campy-memory/SKILL.md` as the canonical policy for when to recall Campy memory. The short version: do not recall on every turn; recall only when a decision needs durable memory, and keep returned context compact.

If you are unsure whether recall is warranted, call `memory_decision` first. It recommends the next recall tool without retrieving memory itself.

## Heterogeneous Retrieval (B249–B254)

For multi-entity or broad context queries, use `compile_context` instead of making multiple individual recall calls. It assembles a `ContextBundle` from exact facts, semantic search, graph traversals, tabular data, and wiki summaries — pre-compressed to your token budget and formatted for your agent type.

`memory_decision` automatically routes to `compile_context` when it detects multi-entity queries. You can also call it directly with a `token_budget` and optional `output_format` (generic, claude_code, codex, claude_desktop, chatgpt_desktop, arc).

Tabular data (CSV, XLSX, TSV) ingested via `ingest_document` is stored in per-dataset SQLite files with metadata and extracted facts in the Kuzu graph. The bundle compiler includes relevant tabular data when assembling context.

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
