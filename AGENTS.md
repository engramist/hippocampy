# AGENTS.md

This file gives agent-neutral guidance for Codex and other coding agents working in this repository.

## Sources Of Truth

Read `docs/ARCHITECTURE.md` before making architecture, schema, retrieval, capture, or daemon behavior changes.
Read `docs/ecosystem-rules.md` before changing package boundaries or persistence behavior.

KuzuDB is the single source of truth for persistent memory state. Do not introduce shadow stores for durable agent state; in-memory structures are allowed only as caches over graph-backed state.

## Memory Usage Policy

Use `skills/sidequests-memory/SKILL.md` as the canonical policy for when to recall SideQuests memory. The short version: do not recall on every turn; recall only when a decision needs durable memory, and keep returned context compact.

If you are unsure whether recall is warranted, call `memory_decision` first. It recommends the next recall tool without retrieving memory itself.

## Activity Indicator

Use the SideQuests activity feed to verify live memory behavior:

```bash
.venv/bin/sidequests activity --follow
```

This tails `~/.sidequests/activity.log`, the compact operator-facing feed for:

- memory writes
- recall calls
- durable capture scans
- daemon lifecycle state
- tool success/error status

The activity feed redacts full prompt and assistant-response bodies. It may include operational metadata such as source client, role, session, character counts, recall query previews, and status. Use `~/.sidequests/daemon.log` only when debugging failures, launchd issues, or stack traces.
