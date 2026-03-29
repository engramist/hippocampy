# B-21-openclaw-system-prompt — OpenClaw System Prompt + Tool Integration

**Card:** B21 | **Priority:** P7 | **Depends on:** None (LLM workflow)

## Summary
Implement system prompt injection and tool integration for OpenClaw sessions. Ensure OpenClaw agents use SideQuests tools with proper context guidance.

## Technical Approach

### System Prompt Layer
- Two-layer system prompt (same as Claude/Codex):
  - Layer 1 (always-on): quest context + "call current_truth before architecture questions"
  - Layer 2 (onboarding): tools overview + "notify_turn after every response"

### Tool Context Injection
- OpenClaw gateway connects to Brain Daemon
- Agent system prompt includes MCP tool surface
- Tool hints guide agent to use current_truth for memory-first responses

### Integration
- `extensions/sidequests-brain/src/index.ts` — system prompt construction
- `adapters/openclaw_gateway.py` — prompt building logic
- Verify: agent uses tools naturally without manual prompting

## Files to Create/Modify

- `extensions/sidequests-brain/src/index.ts` — enhance system prompt
- `adapters/openclaw_gateway.py` — LLM workflow integration
- `tests/test_openclaw_system_prompt.py` — verify prompt injection

## Acceptance Criteria

1. OpenClaw agents receive system prompt with quest context
2. Tools are visible and described in agent context
3. Agent naturally calls current_truth before decision/architecture questions
4. Agent calls notify_turn after responses
5. Integration test: OpenClaw agent → memory retrieval → correct tool called

## Notes

- System prompt is injected at gateway level, not at extension level
- Ensure multi-model compatibility (Claude, Gemini, others OpenClaw supports)
