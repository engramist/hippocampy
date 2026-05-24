"""Tests for Step 4b — Associative Pattern Check (Anticipatory Engine)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Unit tests for _has_signal
# ---------------------------------------------------------------------------

def test_has_signal_error():
    """_has_signal detects error signals."""
    from mcp_engine.loop.step4b_associative import _has_signal

    assert _has_signal("The build failed with exit code 1") == "error"
    assert _has_signal("Permission denied when accessing /etc") == "error"
    assert _has_signal("Traceback (most recent call last):") == "error"
    assert _has_signal("Error: connection refused on port 5432") == "error"
    assert _has_signal("Command not found: kubectl") == "error"
    assert _has_signal("SSO token expired, please refresh") == "error"


def test_has_signal_action():
    """_has_signal detects action signals."""
    from mcp_engine.loop.step4b_associative import _has_signal

    assert _has_signal("Running docker build for production") == "action"
    assert _has_signal("kubectl apply -f deployment.yaml") == "action"
    assert _has_signal("aws s3 cp data.tar.gz s3://bucket/") == "action"
    assert _has_signal("Starting deploy to staging") == "action"


def test_has_signal_none():
    """_has_signal returns None for neutral text."""
    from mcp_engine.loop.step4b_associative import _has_signal

    assert _has_signal("The weather is nice today") is None
    assert _has_signal("Let me think about this design") is None
    assert _has_signal("Here is the function signature") is None


# ---------------------------------------------------------------------------
# Unit tests for _build_trigger_pattern
# ---------------------------------------------------------------------------

def test_build_trigger_pattern_extracts_terms():
    """_build_trigger_pattern extracts key non-stopword terms."""
    from mcp_engine.loop.step4b_associative import _build_trigger_pattern

    pattern = _build_trigger_pattern("Docker container OAUTH_TOKEN setup")
    # Should contain key terms joined by |
    assert "|" in pattern
    assert "Docker" in pattern
    assert "OAUTH_TOKEN" in pattern
    # "setup" should be present (not a stopword)
    assert "setup" in pattern


def test_build_trigger_pattern_removes_stopwords():
    """_build_trigger_pattern filters out stopwords."""
    from mcp_engine.loop.step4b_associative import _build_trigger_pattern

    pattern = _build_trigger_pattern("the error in the system")
    parts = pattern.split("|")
    # "the" and "in" are stopwords, should not appear
    lower_parts = [p.lower() for p in parts]
    assert "the" not in lower_parts
    # "error" and "system" should remain
    assert "error" in lower_parts
    assert "system" in lower_parts


def test_build_trigger_pattern_caps_at_five():
    """_build_trigger_pattern caps at 5 terms."""
    from mcp_engine.loop.step4b_associative import _build_trigger_pattern

    pattern = _build_trigger_pattern("one two three four five six seven eight")
    assert len(pattern.split("|")) <= 5


def test_build_trigger_pattern_fallback():
    """_build_trigger_pattern falls back to escaped full text for short words."""
    from mcp_engine.loop.step4b_associative import _build_trigger_pattern

    # All words < 3 chars — should use fallback
    pattern = _build_trigger_pattern("a b")
    assert pattern  # Should return something, not empty


# ---------------------------------------------------------------------------
# Async tests for check_associative_triggers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_signal_skips_search():
    """Step 4b returns immediately when message has no error/action signals."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    db = AsyncMock()
    result = await check_associative_triggers(
        entity_text="some normal entity",
        entity_vector=[0.1] * 384,
        full_message="The weather is nice today",
        db=db,
        config={},
    )
    assert result["signal_type"] is None
    assert result["triggers_bound"] == 0
    # db.vector_search should NOT have been called
    db.vector_search.assert_not_called()


@pytest.mark.asyncio
async def test_no_vector_skips_search():
    """Step 4b returns immediately when no vector is provided."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    db = AsyncMock()
    result = await check_associative_triggers(
        entity_text="docker build failed",
        entity_vector=None,
        full_message="Error: docker build failed",
        db=db,
        config={},
    )
    assert result["signal_type"] == "error"
    assert result["triggers_bound"] == 0
    db.vector_search.assert_not_called()


@pytest.mark.asyncio
async def test_error_signal_triggers_lesson_search():
    """Step 4b searches Lessons when error signal detected and binds trigger."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    lesson_node = {
        "lesson_id": "lesson-001",
        "text_raw": "SSO tokens expire after 8 hours",
        "trigger_pattern": "",
        "archived": False,
        "lesson_type": "edge-case",
    }

    db = MagicMock()
    db.vector_search = MagicMock(side_effect=[
        [{"node": lesson_node, "score": 0.75}],  # Lesson results
        [],  # Procedure results
    ])
    db.execute_write = AsyncMock()

    result = await check_associative_triggers(
        entity_text="SSO token expired",
        entity_vector=[0.1] * 384,
        full_message="Error: SSO token expired, please run aws sso login",
        db=db,
        config={},
    )
    assert result["signal_type"] == "error"
    assert result["triggers_bound"] == 1
    assert result["lessons_matched"] == 1
    # Verify the write was called with PostToolUse (error → post)
    call_args = db.execute_write.call_args
    assert "trigger_pattern" in call_args[0][0]
    assert call_args[0][1]["hook_type"] == "PostToolUse"


@pytest.mark.asyncio
async def test_action_signal_checks_procedures():
    """Step 4b searches Procedures when action signal detected."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    proc_node = {
        "procedure_id": "proc-001",
        "name": "Docker Setup",
        "trigger_pattern": "",
        "archived": False,
    }

    db = MagicMock()
    db.vector_search = MagicMock(side_effect=[
        [],  # No Lesson matches
        [{"node": proc_node, "score": 0.72}],  # Procedure match
    ])
    db.execute_write = AsyncMock()

    result = await check_associative_triggers(
        entity_text="docker container setup",
        entity_vector=[0.1] * 384,
        full_message="Running docker build for the new service",
        db=db,
        config={},
    )
    assert result["signal_type"] == "action"
    assert result["procedures_matched"] == 1
    assert result["triggers_bound"] == 1
    call_args = db.execute_write.call_args
    assert call_args[0][1]["hook_type"] == "PreToolUse"


@pytest.mark.asyncio
async def test_skips_already_bound_triggers():
    """Step 4b skips nodes that already have trigger metadata."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    lesson_node = {
        "lesson_id": "lesson-001",
        "trigger_pattern": "docker|container",  # Already has trigger
        "archived": False,
    }

    db = MagicMock()
    db.vector_search = MagicMock(side_effect=[
        [{"node": lesson_node, "score": 0.80}],
        [],
    ])
    db.execute_write = AsyncMock()

    result = await check_associative_triggers(
        entity_text="docker error",
        entity_vector=[0.1] * 384,
        full_message="Error: docker build failed",
        db=db,
        config={},
    )
    assert result["lessons_matched"] == 1
    assert result["triggers_bound"] == 0  # Skipped — already bound
    db.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_skips_archived_nodes():
    """Step 4b skips archived nodes."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    lesson_node = {
        "lesson_id": "lesson-001",
        "trigger_pattern": "",
        "archived": True,  # Archived
    }

    db = MagicMock()
    db.vector_search = MagicMock(side_effect=[
        [{"node": lesson_node, "score": 0.80}],
        [],
    ])
    db.execute_write = AsyncMock()

    result = await check_associative_triggers(
        entity_text="docker error",
        entity_vector=[0.1] * 384,
        full_message="Error: docker build failed",
        db=db,
        config={},
    )
    assert result["triggers_bound"] == 0
    db.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_below_threshold_ignored():
    """Step 4b ignores matches below similarity threshold."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    lesson_node = {
        "lesson_id": "lesson-001",
        "trigger_pattern": "",
        "archived": False,
    }

    db = MagicMock()
    db.vector_search = MagicMock(side_effect=[
        [{"node": lesson_node, "score": 0.40}],  # Below 0.65
        [],
    ])
    db.execute_write = AsyncMock()

    result = await check_associative_triggers(
        entity_text="something vague",
        entity_vector=[0.1] * 384,
        full_message="Error: something failed",
        db=db,
        config={},
    )
    assert result["triggers_bound"] == 0
    db.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_max_bindings_cap():
    """Step 4b caps bindings at MAX_BINDINGS_PER_MESSAGE."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    lessons = [
        {"node": {"lesson_id": f"l-{i}", "trigger_pattern": "", "archived": False},
         "score": 0.80}
        for i in range(5)
    ]

    db = MagicMock()
    db.vector_search = MagicMock(side_effect=[lessons, []])
    db.execute_write = AsyncMock()

    result = await check_associative_triggers(
        entity_text="docker container error",
        entity_vector=[0.1] * 384,
        full_message="Fatal error: docker container crashed",
        db=db,
        config={},
    )
    assert result["triggers_bound"] == 3  # Capped at MAX_BINDINGS_PER_MESSAGE


@pytest.mark.asyncio
async def test_custom_threshold_from_config():
    """Step 4b respects custom similarity threshold from config."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    lesson_node = {
        "lesson_id": "lesson-001",
        "trigger_pattern": "",
        "archived": False,
    }

    db = MagicMock()
    db.vector_search = MagicMock(side_effect=[
        [{"node": lesson_node, "score": 0.60}],  # Above custom 0.50 threshold
        [],
    ])
    db.execute_write = AsyncMock()

    result = await check_associative_triggers(
        entity_text="custom threshold test",
        entity_vector=[0.1] * 384,
        full_message="Error: custom threshold test failed",
        db=db,
        config={"anticipatory": {"similarity_threshold": 0.50}},
    )
    assert result["triggers_bound"] == 1


@pytest.mark.asyncio
async def test_vector_search_failure_graceful():
    """Step 4b handles vector search exceptions gracefully."""
    from mcp_engine.loop.step4b_associative import check_associative_triggers

    db = MagicMock()
    db.vector_search = MagicMock(side_effect=RuntimeError("Index not found"))

    result = await check_associative_triggers(
        entity_text="docker error",
        entity_vector=[0.1] * 384,
        full_message="Error: docker build failed",
        db=db,
        config={},
    )
    # Should not raise, should return 0 bindings
    assert result["signal_type"] == "error"
    assert result["triggers_bound"] == 0
