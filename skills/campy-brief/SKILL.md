---
name: campy-brief
description: Deep context briefing from Campy's knowledge graph. Use when starting a new session, switching tasks, or needing full project context. Also use when you feel you're missing context about a project.
---

# Campy Brief

Get a comprehensive briefing from Campy's memory about the current project.

## When to Use

- Starting a new coding session
- Switching to a different area of the codebase
- Feeling like you're missing context about prior decisions
- Before making a significant architectural choice

## Process

1. Call `compile_context` with:
   - query: describe the current task or area of focus
   - token_budget: 8000 (keep it focused)
   - output_format: match your agent type (claude_code, codex, etc.)

2. Read the returned bundle. It contains:
   - Global constraints and preferences
   - Relevant prior decisions
   - Related lessons from past work
   - Graph relationships between key concepts

3. If CONTEXT.md exists in the project root, read it for domain terminology.

4. If docs/adr/ exists, scan for relevant ADRs.

5. Summarize key findings in 3-5 bullet points for your working context.
   Do NOT paste the entire bundle into your response.

## Anti-Bloat

- Request only what you need. Default token_budget of 8000 is usually sufficient.
- Summarize findings, don't paste raw memory.
- If the bundle is truncated, that's fine — you got the highest-priority items.
