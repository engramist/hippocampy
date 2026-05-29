# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Implementation Workflow

Claude/Haiku may implement code directly in this repository.

Default workflow:
1. Read the target backlog card and dependencies.
2. Implement directly with minimal, safe edits.
3. Run relevant tests and fix regressions.
4. Summarize changed files, commands run, and results.
5. Commit when satisfied.

Optional delegation workflow:
- If requested, or if the task is large/multi-file, follow `GEMINI-DELEGATION.md`.
- You may still create a detailed `B-<feature>.md` plan first, then delegate to Gemini CLI.

## Architecture

**For all architecture, schema, Loop steps, tools, IP claims, and design details, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).**

**For ecosystem layer boundaries, separation rules, and import constraints, see [`docs/ecosystem-rules.md`](docs/ecosystem-rules.md).**

**For target region placement during the anatomy refactor, see [`docs/codebase-anatomy.md`](docs/codebase-anatomy.md) and [`docs/codebase-anatomy-refactor-plan.md`](docs/codebase-anatomy-refactor-plan.md).**

These are the sources of truth for the system design — shared across all agents (Claude, Gemini, Codex).

## Critical Rule: No Shadow Stores

**KuzuDB is the single source of truth for all persistent agent state.** Do NOT store persistent data (roles, hypotheses, victory conditions, action facts, chunk history) in Python dicts or instance variables as the primary store. In-memory variables are permitted ONLY as read-through caches over KuzuDB. See `docs/ecosystem-rules.md` "No shadow stores rule" for full details.

## Campy Memory Usage Policy

Use `skills/campy-memory/SKILL.md` (dev-only) or `plugin/skills/recall/SKILL.md` (ships with plugin) as the canonical memory-use policy. Do not recall on every turn. Use recall only when the answer or plan depends on durable prior decisions, timeline, lessons, procedures, or similar past work.

If uncertain, call `memory_decision` first; it recommends the appropriate recall tool without retrieving memory itself. For multi-entity or broad context queries, `memory_decision` routes to `compile_context` (B252) which assembles heterogeneous context bundles from all memory types.

## Context Window Integration (Layer Cake)

Campy uses a 4-layer system to automatically inject graph knowledge into agent context windows:

- **Layer 1 — File Bridge:** `CONTEXT.md` and ADR files generated from graph state in project directories. Read automatically by agents as regular files. Regen: `campy context regen`.
- **Layer 2 — Associative Hooks:** Trigger manifest at `~/.campy/triggers/manifest.json` compiled from Procedure/Lesson nodes. Claude Code hooks (`pre_tool_use.sh`, `post_tool_use.sh`) inject matching context on every tool call. Manage: `campy trigger add|list|remove|compile`.
- **Layer 3 — Anticipatory Engine:** GCL Step 4b auto-discovers trigger bindings during message processing. When error/action signals appear, checks entity embeddings against stored Lessons/Procedures and auto-binds triggers. No manual configuration needed.
- **Layer 4 — Process Skills:** 12 skills in `plugin/skills/` (auto-install with plugin). Includes forked process skills (`campy-grill`, `campy-diagnose`, `campy-tdd`, `campy-handoff`, `campy-improve-architecture`) with lean Campy memory integration, plus Campy-native skills (recall, brief, learn, session-start, memory-awareness, quest-management, status). Installed to Codex (`~/.codex/skills/`), Gemini CLI (`~/.gemini/skills/`), and VS Code Copilot (`.github/copilot-instructions.md`) during `campy install-plugin`.

Design spec: `docs/superpowers/specs/2026-05-22-context-window-integration-design.md`

## Campy Activity Indicator

Campy exposes a compact operator activity feed at `~/.campy/activity.log`.
Use this instead of the noisy daemon log when checking whether the brain is currently writing to memory, recalling, running durable capture, or changing daemon state.

Recommended command:

```bash
.venv/bin/campy activity --follow
```

The feed is intentionally redacted: it records operational metadata such as source client, role, session, character counts, recall queries, and status without dumping full prompt or assistant response bodies. Use `~/.campy/daemon.log` only for troubleshooting failures and stack traces.
