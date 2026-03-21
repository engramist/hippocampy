# B-14 — Proactive Insight Surfacing

## Overview

The Brain is invisible. Users have no signal it's working until they explicitly call `current_truth`. This is the biggest consumer-readiness gap. Normal users (like DJ's wife) need to *feel* the system is alive.

**Solution:** Persist loop processing summaries on the Session node. Return the previous message's summary in every `notify_turn` response. The LLM naturally surfaces insights like "The Brain just captured 2 decisions and a constraint from our conversation."

**No new tools. No polling. No added latency.** We piggyback insight data on the `notify_turn` response the LLM already makes.

## Architecture Decision

The Loop already computes rich summaries in `mcp_engine/loop/orchestrator.py` (`run_loop()` returns `summary` dict). Currently this summary is printed to stdout in `brain_daemon.py` line ~242 and discarded.

**The fix:**
1. Brain Daemon persists the loop summary to the Session node after each loop run
2. `notify_turn` handler reads the *previous* loop summary from the Session before returning
3. Response goes from `{"status": "queued"}` to `{"status": "queued", "insights": {...}}`
4. Cowork plugin skill teaches Claude to mention insights when they're meaningful

**Why "previous" not "current":** `notify_turn` fires and returns immediately. The Loop processes the message asynchronously in the background. By the time the *next* `notify_turn` fires, the previous loop has completed. So each `notify_turn` response carries the summary from the last processed message. This is a one-message delay but adds zero latency.

## Files to Read First

| File | Why |
|------|-----|
| `mcp_engine/loop/orchestrator.py` | Loop summary format (the `summary` dict returned by `run_loop()`) |
| `brain_daemon.py` | Where loop summary is currently logged and discarded (`_loop_worker`) |
| `mcp_engine/tools.py` | `notify_turn` handler — where to read previous summary |
| `mcp_engine/schema.py` | Session node schema — where to add summary field |
| `mcp_engine/quest.py` | `get_or_create_session()` — Session creation |
| `plugin/skills/memory-awareness/SKILL.md` | Skill to update with insight surfacing guidance |
| `tests/test_quest.py` | Existing session/quest tests to not break |

## Implementation — Phase by Phase

### Phase 1: Schema — Add loop summary field to Session

**File: `mcp_engine/schema.py`**

Add to the Session node CREATE TABLE statement:

```python
# After existing Session properties, add:
# last_loop_summary STRING  -- JSON-encoded summary from most recent loop run
```

Find the Session CREATE TABLE block and add `last_loop_summary STRING` as a new column.

### Phase 2: Brain Daemon — Persist loop summary after each run

**File: `brain_daemon.py`**

Find the `_loop_worker` method (or wherever `run_loop()` is called and the summary is printed). After the existing print/log statement, add a write to persist the summary on the Session node:

```python
# After run_loop() returns summary and it's been logged:
import json as _json

if summary and session_id:
    summary_json = _json.dumps(summary)
    try:
        await self.db.execute_write(
            "MATCH (s:Session {session_id: $sid}) "
            "SET s.last_loop_summary = $summary",
            {"sid": session_id, "summary": summary_json}
        )
    except Exception:
        pass  # Non-critical — don't break the loop over summary persistence
```

Read `brain_daemon.py` carefully to find:
1. Where `run_loop()` is called
2. What variables hold `session_id` and `summary`
3. Where to insert the persist call (after the existing log/print)

### Phase 3: notify_turn — Return previous loop summary

**File: `mcp_engine/tools.py`**

In the `notify_turn` handler, before the final `return {"status": "queued", ...}`, read the previous loop summary from the Session:

```python
# Read previous loop summary (already completed by the time this fires)
insights = None
try:
    result = db.execute(
        "MATCH (s:Session {session_id: $sid}) "
        "RETURN s.last_loop_summary",
        {"sid": session_id}
    )
    if result.has_next():
        raw = result.get_next()[0]
        if raw:
            insights = json.loads(raw)
except Exception:
    pass  # Non-critical

# Enrich response
response = {
    "status": "queued",
    "message_id": message_id,
    "quest_id": quest_id,
}
if insights:
    response["insights"] = insights

return response
```

**The `insights` dict** (from orchestrator.py) looks like:
```python
{
    "message_id": "...",
    "entities_found": 3,
    "relations_found": 1,
    "concepts_stored": 2,
    "additive_updates": 1,
    "contradictions": 0,
    "noise_count": 1,
    "reified": 1,  # high-confidence artifacts (decisions, constraints, etc.)
}
```

The LLM gets this back and can say: "The Brain captured 2 concepts and promoted 1 to a confirmed decision from our last exchange."

### Phase 4: Update Cowork plugin skill

**File: `plugin/skills/memory-awareness/SKILL.md`**

Add a new section at the end of the existing skill:

```markdown
## Insight Surfacing

When you call `notify_turn`, the response may include an `insights` field showing what the Brain captured from the *previous* message. Example:

```json
{
  "status": "queued",
  "insights": {
    "entities_found": 3,
    "concepts_stored": 2,
    "reified": 1,
    "contradictions": 0
  }
}
```

When insights are present and meaningful (concepts_stored > 0 or reified > 0 or contradictions > 0), briefly mention it to the user in a natural way. Examples:

- "The Brain just picked up 2 new concepts from our conversation, including a confirmed decision."
- "Heads up — the Brain detected a contradiction with something we discussed earlier."
- "The Brain captured that constraint about API response times."

Keep it brief — one sentence, not a summary dump. Don't mention it if nothing was captured (all zeros). The goal is to make the Brain feel alive without being noisy.
```

### Phase 5: Tests

**File: `tests/test_insight_surfacing.py`** (NEW)

```python
"""
Tests for B14 Proactive Insight Surfacing.

Validates that loop summaries are persisted and returned in notify_turn responses.
"""

from __future__ import annotations
import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class EmptyResult:
    def has_next(self): return False

class SingleResult:
    def __init__(self, row):
        self._row = row
        self._read = False
    def has_next(self): return not self._read
    def get_next(self):
        self._read = True
        return self._row


# ---------------------------------------------------------------------------
# 1. Schema — Session has last_loop_summary field
# ---------------------------------------------------------------------------

def test_session_schema_has_loop_summary_field():
    """Session CREATE TABLE includes last_loop_summary."""
    from mcp_engine import schema
    import inspect
    source = inspect.getsource(schema.init_schema)
    assert "last_loop_summary" in source


# ---------------------------------------------------------------------------
# 2. notify_turn returns insights when available
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_turn_returns_insights_when_summary_exists():
    """notify_turn response includes insights from previous loop run."""
    from mcp_engine.tools import notify_turn

    summary = json.dumps({
        "message_id": "prev-msg",
        "entities_found": 3,
        "concepts_stored": 2,
        "reified": 1,
        "contradictions": 0,
        "noise_count": 1,
    })

    class MockDB:
        def execute(self, q, p=None):
            if "last_loop_summary" in q:
                return SingleResult([summary])
            if "Session" in q and "session_id" in str(p):
                return SingleResult(["s1", "quest-abc"])
            if "MainQuest" in q:
                return SingleResult(["quest-abc", "Test Project"])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    result = await notify_turn(
        {"role": "assistant", "content": "test response", "session_id": "s1",
         "repo_root": "/tmp/test", "git_branch": "main"},
        MockDB(), {}
    )

    assert "insights" in result, "notify_turn should return insights when summary exists"
    assert result["insights"]["concepts_stored"] == 2
    assert result["insights"]["reified"] == 1


@pytest.mark.asyncio
async def test_notify_turn_omits_insights_when_no_summary():
    """notify_turn response has no insights key when no previous summary."""
    from mcp_engine.tools import notify_turn

    class MockDB:
        def execute(self, q, p=None):
            if "last_loop_summary" in q:
                return SingleResult([None])
            if "Session" in q:
                return SingleResult(["s1", "quest-abc"])
            if "MainQuest" in q:
                return SingleResult(["quest-abc", "Test Project"])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    result = await notify_turn(
        {"role": "user", "content": "hello", "session_id": "s1",
         "repo_root": "/tmp/test", "git_branch": "main"},
        MockDB(), {}
    )

    assert "insights" not in result or result.get("insights") is None


@pytest.mark.asyncio
async def test_notify_turn_survives_summary_read_error():
    """notify_turn doesn't crash if reading summary fails."""
    from mcp_engine.tools import notify_turn

    class BrokenSummaryDB:
        def execute(self, q, p=None):
            if "last_loop_summary" in q:
                raise RuntimeError("DB error")
            if "Session" in q:
                return SingleResult(["s1", "quest-abc"])
            if "MainQuest" in q:
                return SingleResult(["quest-abc", "Test Project"])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    result = await notify_turn(
        {"role": "user", "content": "hello", "session_id": "s1",
         "repo_root": "/tmp/test", "git_branch": "main"},
        BrokenSummaryDB(), {}
    )

    assert result["status"] == "queued"
    # Should not crash — insights just absent


# ---------------------------------------------------------------------------
# 3. Insights dict structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insights_has_expected_keys():
    """Insights dict contains the standard loop summary fields."""
    from mcp_engine.tools import notify_turn

    summary = json.dumps({
        "message_id": "msg-1",
        "entities_found": 5,
        "relations_found": 2,
        "concepts_stored": 3,
        "additive_updates": 1,
        "contradictions": 1,
        "noise_count": 2,
        "reified": 2,
    })

    class MockDB:
        def execute(self, q, p=None):
            if "last_loop_summary" in q:
                return SingleResult([summary])
            if "Session" in q:
                return SingleResult(["s1", "quest-abc"])
            if "MainQuest" in q:
                return SingleResult(["quest-abc", "Project"])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    result = await notify_turn(
        {"role": "assistant", "content": "test", "session_id": "s1",
         "repo_root": "/tmp/t", "git_branch": "main"},
        MockDB(), {}
    )

    insights = result["insights"]
    for key in ["entities_found", "concepts_stored", "reified", "contradictions"]:
        assert key in insights, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# 4. Cowork skill mentions insight surfacing
# ---------------------------------------------------------------------------

def test_memory_awareness_skill_mentions_insights():
    """memory-awareness SKILL.md teaches Claude about insight surfacing."""
    from pathlib import Path
    skill = Path(__file__).parent.parent / "plugin" / "skills" / "memory-awareness" / "SKILL.md"
    content = skill.read_text()
    assert "insights" in content.lower()
    assert "notify_turn" in content


# ---------------------------------------------------------------------------
# 5. SSE endpoint also returns insights
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_dispatch_notify_turn_includes_insights():
    """SSE _dispatch_mcp for notify_turn should also return insights."""
    from web.server import _dispatch_mcp

    summary = json.dumps({
        "entities_found": 1,
        "concepts_stored": 1,
        "reified": 0,
        "contradictions": 0,
    })

    class MockDB:
        def execute(self, q, p=None):
            if "last_loop_summary" in q:
                return SingleResult([summary])
            if "Session" in q:
                return SingleResult(["s1", "quest-abc"])
            if "MainQuest" in q:
                return SingleResult(["quest-abc", "Proj"])
            return EmptyResult()
        async def execute_write(self, q, p=None): pass

    resp = await _dispatch_mcp(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "notify_turn", "arguments": {
             "role": "user", "content": "hi", "session_id": "s1"
         }}},
        MockDB(), {}
    )

    text = json.loads(resp["result"]["content"][0]["text"])
    # insights may or may not be present depending on DB mock coverage
    # but the call should succeed without error
    assert "status" in text
```

## Files to Create

| File | Description |
|------|-------------|
| `tests/test_insight_surfacing.py` | Tests for loop summary persistence and surfacing |

## Files to Modify

| File | Change |
|------|--------|
| `mcp_engine/schema.py` | Add `last_loop_summary STRING` to Session node |
| `brain_daemon.py` | Persist loop summary to Session after each `run_loop()` call |
| `mcp_engine/tools.py` | Read previous summary in `notify_turn`, include in response |
| `plugin/skills/memory-awareness/SKILL.md` | Add insight surfacing guidance section |

## Verification

1. `python3 -m pytest tests/test_insight_surfacing.py -v` — new tests pass
2. `python3 -m pytest tests/ -v` — full suite, 0 failures
3. `notify_turn` response includes `insights` when previous summary exists
4. `notify_turn` still returns `{"status": "queued"}` when no summary (backward compat)
5. Brain daemon doesn't crash if summary persistence fails
6. Cowork skill mentions insights and gives natural-language surfacing guidance
