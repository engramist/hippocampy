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

These are the sources of truth for the system design — shared across all agents (Claude, Gemini, Codex).
