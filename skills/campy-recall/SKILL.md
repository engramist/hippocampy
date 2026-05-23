---
name: campy-recall
description: Explicit memory recall from Campy. Use when you need past decisions, procedures, lessons, or project history. Use when you're about to make a decision and want to check if similar decisions were made before.
---

# Campy Recall

Explicitly query Campy's memory for specific information.

## When to Use

- "What did we decide about X?"
- "Have we tried this approach before?"
- "What's the procedure for Y?"
- "What lessons did we learn from Z?"
- Before making a decision that might repeat a past mistake

## Process

1. First, call `memory_decision` with your query.
   It returns: which recall tool to use, the refined query, and confidence.

2. Call the recommended tool:
   - `current_truth` — for decisions, constraints, architecture
   - `recall_plans` — for similar past work and their outcomes
   - `recall_procedures` — for step-by-step workflows
   - `recall_relevant_lessons` — for lessons learned
   - `compile_context` — for broad multi-entity context
   - `diff_since` — for what changed since a timestamp
   - `reconstruct_timeline` — for chronological history

3. Summarize findings in 2-3 sentences. Do not paste raw memory output.

4. If the recall returns nothing relevant, say so. Don't fabricate context.

## Anti-Bloat Rules

- Use top 3 results unless exhaustive review is specifically needed.
- Summarize compactly — memory informs your answer, it IS NOT the answer.
- If `memory_decision` says confidence is low, skip the recall.
