# Plan for B234 - Universal SideQuests Memory Usage Skill

## Card Metadata

- **Card ID**: B234
- **Priority**: P0
- **Dependencies**: Activity feed work, current recall tools, B235 optional companion

## Summary

Create one canonical SideQuests memory-use skill/policy and distribute it to supported agents in client-appropriate ways.

The skill is universal content. Codex can consume it as a real local skill; Claude, Gemini, ChatGPT Desktop, and VS Code receive the same policy through agent docs or adapter prompt fragments.

## Technical Approach

### Step 1: Create canonical skill

Create:

```text
skills/sidequests-memory/SKILL.md
```

The skill should include:

- Purpose: use SideQuests as durable memory without bloating prompt context.
- Definitions: write/capture vs recall.
- Recall decision tree.
- Tool mapping.
- Anti-bloat rules.
- Examples.
- Activity feed usage.
- Failure/offline behavior.

Suggested top-level structure:

```markdown
# SideQuests Memory Skill

## Purpose
## Core Rule
## Write vs Recall
## Recall Decision Tree
## Tool Map
## Anti-Bloat Rules
## Examples
## Activity Indicator
## Failure Modes
```

### Step 2: Encode recall decision tree

Include rules:

```text
Prior decisions / architecture / constraints / preferences -> current_truth
What changed since last session / another agent -> diff_since
Sequence / timeline / debugging history -> reconstruct_timeline
Planning similar work -> recall_plans
Reusable workflow / how we usually do this -> recall_procedures
Lessons learned / cross-session learning -> recall_relevant_lessons
Similar past project / analogy -> analogical_search
ARC mechanics / scene graph / world-model -> recall_mechanic_priors or recall_scene_graph_priors
Token/context health -> context_status
Simple local edit / current context sufficient -> do not recall
```

### Step 3: Encode anti-bloat behavior

Explicitly state:

- Do not recall on every turn.
- Do not paste large memory dumps into the answer.
- Prefer top 3 results unless user asks for exhaustive review.
- Summarize recalled memory compactly.
- Use raw `Message`/`DocumentExtract` evidence as provenance, not primary context.
- If unsure, call `memory_decision` once B235 exists.

### Step 4: Wire agent docs

Update:

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`

Keep these short and point to the canonical skill file.

### Step 5: Install Codex skill

Update installer/setup logic to copy:

```text
skills/sidequests-memory/SKILL.md
```

to:

```text
~/.codex/skills/sidequests-memory/SKILL.md
```

when Codex home exists or Codex target is selected.

Rules:

- Create parent directories if needed.
- Do not overwrite user-modified skill unless content matches prior managed version or user passes repair/force flag.
- If conflict exists, write `.new` or print instructions.

### Step 6: Align adapter prompts

Review adapter prompt fragments in:

- `adapters/codex/adapter.py`
- `adapters/claude_code/adapter.py`
- `adapters/claude_desktop/adapter.py`
- `adapters/chatgpt_desktop/adapter.py`
- `adapters/gemini_cli/adapter.py`

Keep prompt snippets compact. Avoid duplicating the full skill. Mention only the core tool selection rules.

### Step 7: Add tests

Create `tests/test_sidequests_memory_skill.py`.

Assertions:

- skill file exists
- mentions all core recall tools
- mentions `notify_turn` or passive capture
- mentions `sidequests activity --follow`
- includes anti-bloat language
- Codex install helper copies the skill in a temp HOME/CODEX_HOME if implemented as a pure helper

## Validation

Run exactly:

```bash
pytest -q tests/test_sidequests_memory_skill.py tests/test_adapters.py tests/test_setup_cli.py
rg -n "sidequests-memory|current_truth|recall_plans|reconstruct_timeline|diff_since|anti-bloat|activity --follow" skills AGENTS.md CLAUDE.md GEMINI.md adapters sidequests docs tests
```

## Risks

- Codex skills are not the same as Claude/Gemini instructions. Keep the skill canonical but delivery client-specific.
- Too much adapter prompt text can itself become context bloat. Keep adapter prompts short.
- Do not make the policy imply recall is mandatory every turn.
