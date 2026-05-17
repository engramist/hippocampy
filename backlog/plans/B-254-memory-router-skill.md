# Plan for 254 - Memory Router Skill (Agent-Side Guidance)

## Metadata

- **Card ID**: 254
- **Priority**: P2
- **Dependencies**: 252, 253
- **Risk**: Low - mostly documentation and heuristic updates

## Goal

Upgrade `memory_decision` to recommend `compile_context` when appropriate, and update agent-facing skill documentation and onboarding prompts to teach agents how to use the full Memory OS capabilities.

## Step 1: Upgrade memory_decision.py

Add new routing rules (insert before the default rule):

```python
# Rule: Multi-entity or broad context query → compile_context
BUNDLE_TRIGGERS = [
    "everything about", "full context", "brief me on", "what do we know about",
    "summary of", "overview of", "bundle", "compile",
]

# Rule: Query mentions multiple distinct entities → compile_context
def _is_multi_entity(prompt: str) -> bool:
    """Heuristic: does this prompt reference multiple distinct topics?"""
    # Simple: count capitalized proper nouns or quoted terms
    # Better: use spaCy NER if available
    ...
```

New recommendation output:

```python
{
    "should_recall": True,
    "recommended_tool": "compile_context",
    "query": "Project X budget and constraints",
    "reason": "Multi-entity query spanning decisions, constraints, and tabular data",
    "confidence": 0.85,
    "context_budget": "moderate",
    "anti_bloat_guidance": "Bundle is pre-compressed to token budget. Inject directly, do not re-summarize.",
    "suggested_params": {
        "token_budget": 32000,
        "include_tabular": True,
        "output_format": "claude_code"
    }
}
```

## Step 2: Update Skill Documentation

Update `skills/campy-memory/SKILL.md` and `sidequests/data/campy-memory/SKILL.md`:

Add section:

```markdown
## Bundle Compilation (compile_context)

Use `compile_context` when you need assembled context from multiple memory types:
- "What do we know about Project X?" → compile_context
- "Brief me on the current constraints and budget" → compile_context
- Multi-entity queries that span decisions, data, and relationships → compile_context

Use `current_truth` when you need a quick fact check:
- "What did we decide about the database?" → current_truth
- "Is there a constraint on deployment?" → current_truth

### Token Budget Guidance

Set `token_budget` based on your available context:
- Small context (4K-8K): set token_budget=4000 — get exact facts + top 3 results
- Medium context (32K-128K): set token_budget=32000 — full context with tabular summaries
- Large context (200K+): set token_budget=100000 — everything including raw data

### Output Format

Set `output_format` to match your agent type:
- claude_code: structured markdown
- codex: compact code-focused
- chatgpt_desktop: conversational prose
- generic: raw JSON (default)

### Anti-Bloat Rules for Bundles

- Bundles are already compressed to your token budget — inject directly
- Do NOT re-summarize a bundle; it's already summarized
- Do NOT request a bundle and then also call current_truth — the bundle includes semantic results
- If the bundle is truncated (truncated: true), increase token_budget or narrow your query
```

## Step 3: Update Layer 2 Onboarding Prompt

In each adapter's Layer 2 prompt, add:

```
For complex queries spanning multiple topics or data types:
- compile_context: call to get a pre-assembled context bundle.
  Specify token_budget matching your available context window.
  The bundle includes exact facts, semantic context, relationships,
  tabular data, and summaries — all pre-compressed.
```

## Step 4: Tests

Update `tests/test_memory_decision.py`:

- Test "everything about X" → recommends compile_context
- Test "full context on Y" → recommends compile_context
- Test multi-entity query detection → recommends compile_context
- Test simple "what did we decide" → still recommends current_truth
- Test suggested_params include output_format and token_budget
- Test backwards compatibility: all existing test cases still pass

## Completion Criteria

```bash
.venv/bin/pytest -q tests/test_memory_decision.py
.venv/bin/pytest -q
```
