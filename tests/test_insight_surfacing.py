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
# Stub out kuzu so mcp_engine modules can be imported without the real package.
# kuzu is a compiled C extension not available in all test environments.
# ---------------------------------------------------------------------------

def _stub_kuzu():
    if "kuzu" not in sys.modules:
        import types
        _kuzu = types.ModuleType("kuzu")

        class _DB:
            def __init__(self, *a, **kw): pass

        class _Conn:
            def __init__(self, *a, **kw): pass
            def execute(self, *a, **kw): return None

        _kuzu.Database = _DB
        _kuzu.Connection = _Conn
        sys.modules["kuzu"] = _kuzu

_stub_kuzu()


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
    # Check the NODE_TABLES dict directly
    assert "last_loop_summary" in schema.NODE_TABLES["Session"]


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
            if "Session" in q and p and "sid" in p:
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
    assert "insights" in text
