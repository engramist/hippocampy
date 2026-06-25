# tests/test_ask_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ask_returns_llm_response():
    from campy.brain.thalamus.ask import run_ask

    mock_db = MagicMock()
    config = {
        "llm": {"provider": "ollama", "model": "llama3.1:8b"},
        "compression": {"graph_prune_threshold": 0.30},
    }

    mock_bundle = MagicMock()
    mock_bundle.sections = []
    mock_bundle.query = "what auth decision did we make?"

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "We decided to use JWT tokens."

    with patch(
        "campy.brain.thalamus.ask.compile_bundle",
        new_callable=AsyncMock,
        return_value=mock_bundle,
    ), patch(
        "campy.brain.thalamus.ask._get_llm",
        return_value=mock_llm,
    ), patch(
        "campy.brain.thalamus.ask._capture_turn",
        new_callable=AsyncMock,
    ) as mock_capture:
        result = await run_ask(
            query="what auth decision did we make?",
            session_id="sess-1",
            db=mock_db,
            config=config,
        )

    assert result == "We decided to use JWT tokens."
    mock_capture.assert_called_once()


@pytest.mark.asyncio
async def test_ask_calls_capture_with_question_and_answer():
    """Closed loop captures BOTH the user's question and the answer."""
    from campy.brain.thalamus.ask import run_ask

    mock_db = MagicMock()
    config = {"compression": {}}
    mock_bundle = MagicMock()
    mock_bundle.sections = []
    mock_bundle.query = "test"

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "the answer"

    captured = {}

    async def fake_capture(query, answer, session_id, db, config):
        captured["query"] = query
        captured["answer"] = answer
        captured["session_id"] = session_id

    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=mock_bundle), \
         patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm), \
         patch("campy.brain.thalamus.ask._capture_turn", side_effect=fake_capture):
        await run_ask("what did we decide?", "sess-99", mock_db, config)

    assert captured["query"] == "what did we decide?"
    assert captured["answer"] == "the answer"
    assert captured["session_id"] == "sess-99"


@pytest.mark.asyncio
async def test_ask_no_capture_skips_writeback():
    """capture=False must not write anything back."""
    from campy.brain.thalamus.ask import run_ask

    mock_db = MagicMock()
    config = {"compression": {}}
    mock_bundle = MagicMock()
    mock_bundle.sections = []

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "ephemeral answer"

    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=mock_bundle), \
         patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm), \
         patch("campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock) as mock_capture:
        result = await run_ask("q", "sess-1", mock_db, config, capture=False)

    assert result == "ephemeral answer"
    mock_capture.assert_not_called()


@pytest.mark.asyncio
async def test_capture_falls_back_to_daemon_when_db_readonly():
    """When the local DB write raises (CLI read-only path), capture routes
    to the daemon via call_brain — both turns."""
    from campy.brain.thalamus import ask as ask_mod

    mock_db = MagicMock()
    config = {}

    async def failing_notify_turn(params, db, config):
        raise RuntimeError("Cannot write to a read-only database")

    sent = []

    async def fake_call_brain(method, params, timeout=10.0):
        sent.append((method, params["role"], params["content"]))
        return {"ok": True}

    with patch("campy.brain.thalamus.tools.notify_turn", side_effect=failing_notify_turn), \
         patch("campy.brain_transport.call_brain", side_effect=fake_call_brain):
        await ask_mod._capture_turn("the question", "the answer", "sess-7", mock_db, config)

    assert ("notify_turn", "user", "the question") in sent
    assert ("notify_turn", "assistant", "the answer") in sent
