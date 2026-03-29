# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Implementation Workflow

**Follow `GEMINI-DELEGATION.md` for all implementation work.** Do not write code directly. Instead:
1. Write a detailed `B-<feature>.md` plan (exact file paths, function signatures, logic, tests)
2. Get DJ's approval on the plan
3. Delegate to Gemini CLI: `gemini -p "Read B-<plan>.md and implement exactly as specified..." --yolo`
4. Review Gemini's output, run tests, fix issues
5. Commit when satisfied

## Architecture

**For all architecture, schema, Loop steps, tools, IP claims, and design details, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).**

This is the single source of truth for the system design — shared across all agents (Claude, Gemini, Codex).
