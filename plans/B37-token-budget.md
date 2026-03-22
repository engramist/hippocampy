# B37: Token Budget & Graceful Rate Limiting

**Status:** In Progress  
**Priority:** High  
**Date:** 2026-03-22  
**Author:** SideClaw

---

## Problem

Opus 4.6 hit the Anthropic TPM/RPM rate limit overnight, causing SideClaw to go completely dark with HTTP 429 errors. No context was saved, DJ had to paste the entire prior conversation manually to recover state. This is a bad experience and avoidable.

---

## Research Findings

### OpenClaw Already Has This Built In (Partially)

OpenClaw supports `agents.defaults.model.fallbacks` — an ordered list of fallback models. When the primary model fails due to rate limits/timeouts after exhausting auth profile rotation, it automatically advances to the next model. Cooldowns use exponential backoff: 1m → 5m → 25m → 1h.

**This means: adding Sonnet as a fallback gives us auto-downshift for free.**

### What OpenClaw Does NOT Do (Yet)
- Proactive downshift before hitting limits (it waits for an actual 429)
- Per-task model routing (heartbeats always use primary unless overridden)
- Token budget monitoring with alerts
- Session cost/usage visibility beyond `/status`

### Anthropic Rate Limits (Tier 1 API key)
- Opus 4.6: ~32K tokens/min input, ~16K tokens/min output (rough estimates — varies by tier)
- A single heavy work session + active chat + hourly heartbeat can exceed this fast
- Sonnet 4.6: Higher limits, lower cost — perfect for routine work

---

## Architecture: Three-Layer Defense

### Layer 1: OpenClaw Model Fallback (IMPLEMENT NOW)
Configure Sonnet as automatic fallback. Zero code changes — just config.

```json
"model": {
  "primary": "anthropic/claude-opus-4-6",
  "fallbacks": ["anthropic/claude-sonnet-4-6"]
}
```

When Opus 429s → OpenClaw puts Opus in cooldown → automatically uses Sonnet → continues without interruption.

### Layer 2: Cron Job Model Routing (IMPLEMENT NOW)  
Work sessions don't need Opus for every task. Use Sonnet for:
- Heartbeats (reading files, checking status, simple decisions)
- Research/reading tasks (web search, file review)
- Writing/documentation tasks

Use Opus for:
- Architecture decisions
- Complex code review
- Debugging hard problems
- Anything where reasoning depth matters

OpenClaw cron jobs can specify a model override in the payload. Update cron messages to include `"model": "anthropic/claude-sonnet-4-6"` for routine sessions.

### Layer 3: SideQuests as Continuity Layer (FUTURE — B38)
The real fix for "going dark": if Brain has full context, hitting a rate limit is a non-event.

When approaching limits, the active session should:
1. Flush all working context to Brain via `memory_store` calls
2. Write a structured handoff note to `memory/YYYY-MM-DD.md`
3. Include a "RESUME_POINT" marker so any new session (Sonnet, Opus after cooldown, or even a different machine) can pick up exactly where we left off

This requires:
- B28 (tool binding) to be working — Brain needs to be callable from sessions
- A "graceful shutdown" hook in the cron session prompt
- A "resume from Brain" flow in session startup

Spinning this off as **B38: Graceful Rate Limit Handoff** since it depends on B28.

---

## Implementation Plan

### Phase 1: Config (Do Now — 5 min)
1. Add `fallbacks: ["anthropic/claude-sonnet-4-6"]` to `agents.defaults.model` in openclaw.json
2. This gives automatic Sonnet fallback when Opus rate-limits

### Phase 2: Cron Model Routing (Do Now — 10 min)
Update cron job prompts to specify Sonnet model for routine sessions.  
OpenClaw agentTurn payload accepts a `model` field.

### Phase 3: B38 (Future)
Spin off into its own backlog item. Requires B28 first.

---

## Task Routing Guide

| Task Type | Model | Reason |
|-----------|-------|--------|
| Heartbeat checks | Sonnet | Routine, low complexity |
| Cron work sessions | Sonnet | Can escalate to Opus if needed |
| Architecture decisions | Opus | Needs depth |
| Complex debugging | Opus | Needs reasoning |
| Code review | Opus | Pattern recognition + judgment |
| Research/reading | Sonnet | Reading comprehension, no deep reasoning |
| Writing docs/plans | Sonnet | Clear writing, not complex reasoning |
| DJ direct conversation | Opus | Best experience for the CEO |

---

## Success Criteria
- [ ] 429 errors trigger automatic Sonnet fallback (no dark period)
- [ ] Heartbeats run on Sonnet by default
- [ ] Cron work sessions use Sonnet unless task requires Opus
- [ ] When rate limit hits mid-conversation, context survives (B38)
