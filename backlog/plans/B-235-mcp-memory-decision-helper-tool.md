# Plan for B235 - MCP Memory Decision Helper Tool

## Card Metadata

- **Card ID**: B235
- **Priority**: P0
- **Dependencies**: B234 recommended, existing recall tools

## Summary

Add a universal MCP helper tool, `memory_decision`, that recommends whether and how an agent should recall SideQuests memory for the current user prompt.

Version 1 is deterministic and compact. It does not perform recall itself.

## Technical Approach

### Step 1: Implement policy module

Create:

```text
mcp_engine/memory_decision.py
```

Public function:

```python
def decide_memory_action(
    user_prompt: str,
    task_phase: str = "unknown",
    available_context_summary: str | None = None,
    session_id: str | None = None,
    client_name: str | None = None,
) -> dict:
    ...
```

Return shape:

```python
{
    "should_recall": True,
    "recommended_tool": "current_truth",
    "query": "installer architecture decisions",
    "reason": "User asks about prior project decisions.",
    "confidence": 0.86,
    "context_budget": "compact",
    "anti_bloat_guidance": "Use top 3 results; summarize, do not paste raw memory.",
}
```

For `should_recall=false`, set `recommended_tool` to `None` or `"none"` consistently.

### Step 2: Add deterministic routing rules

Use transparent lexical/phase rules first. Keep them easy to audit.

Examples:

- `what did we decide`, `previous decision`, `architecture`, `constraint`, `preference` -> `current_truth`
- `what changed`, `since last`, `other agent`, `sub agent finished` -> `diff_since`
- `timeline`, `sequence`, `what happened`, `in order`, `debug history` -> `reconstruct_timeline`
- `plan`, `implement`, `similar work`, `backlog card` -> `recall_plans`
- `procedure`, `workflow`, `how do we usually` -> `recall_procedures`
- `lesson`, `learned`, `avoid repeating` -> `recall_relevant_lessons`
- `similar to`, `analogy`, `like before` -> `analogical_search`
- `ARC`, `world model`, `mechanic`, `scene graph`, `puzzle` -> ARC recall tools
- short/simple coding requests with no history terms -> no recall

Handle precedence carefully. For example, "what changed in ARC world-model mechanics" may route to `diff_since` if the main intent is change-over-time, or ARC recall if the main intent is priors. Document precedence in code comments and tests.

### Step 3: Add MCP tool handler

In `mcp_engine/tools/__init__.py`, add async handler:

```python
async def memory_decision(params: dict, db, config: dict) -> dict:
    return decide_memory_action(...)
```

Do not query KuzuDB in v1 unless needed for a minimal health/session hint. The tool should be fast and side-effect-free.

### Step 4: Add tool schema

In `mcp_engine/tool_schemas.py`, add:

```python
{
    "name": "memory_decision",
    "description": "Recommend whether and how to recall SideQuests memory for the current user prompt without performing recall.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "user_prompt": {"type": "string"},
            "task_phase": {"type": "string"},
            "available_context_summary": {"type": "string"},
            "session_id": {"type": "string"},
            "client_name": {"type": "string"}
        },
        "required": ["user_prompt"],
        "additionalProperties": False
    }
}
```

### Step 5: Adapter visibility

If adapters centralize tool exposure from `tool_schemas.TOOLS`, no adapter-specific allowlist should be needed. If any adapter still has a hardcoded list, add `memory_decision` and add a test.

### Step 6: Docs

Update:

- `docs/tool-catalog.md`
- `docs/ARCHITECTURE.md`
- maybe `skills/sidequests-memory/SKILL.md` if B234 is already present

Document that `memory_decision` recommends recall but does not retrieve memory in v1.

### Step 7: Tests

Create `tests/test_memory_decision.py`.

Test cases:

- prior architecture decision -> `current_truth`
- what changed since subagent -> `diff_since`
- sequence/debug history -> `reconstruct_timeline`
- planning similar work -> `recall_plans`
- reusable workflow -> `recall_procedures`
- lessons learned -> `recall_relevant_lessons`
- analogy/similar project -> `analogical_search`
- ARC mechanics -> `recall_mechanic_priors`
- ARC scene graph -> `recall_scene_graph_priors`
- simple edit -> no recall
- empty prompt -> no recall with low confidence and validation-safe output

## Validation

Run exactly:

```bash
pytest -q tests/test_memory_decision.py tests/test_adapters.py tests/test_tool_schemas.py
rg -n "memory_decision|recommended_tool|should_recall|anti_bloat_guidance|recall_policy" mcp_engine adapters sidequests docs tests
.venv/bin/sidequests tool list | rg "memory_decision"
```

## Risks

- A deterministic lexical router can be overconfident. Keep confidence modest and reason strings transparent.
- Do not let `memory_decision` become hidden auto-recall in v1.
- If agents call `memory_decision` every turn, it is still much cheaper than recall, but adapter prompts should encourage using it only when uncertain.
