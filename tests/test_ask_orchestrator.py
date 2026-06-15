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
async def test_ask_calls_capture_with_answer():
    from campy.brain.thalamus.ask import run_ask

    mock_db = MagicMock()
    config = {"compression": {}}
    mock_bundle = MagicMock()
    mock_bundle.sections = []
    mock_bundle.query = "test"

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "the answer"

    captured = {}

    async def fake_capture(answer, session_id, db, config):
        captured["answer"] = answer
        captured["session_id"] = session_id

    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=mock_bundle), \
         patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm), \
         patch("campy.brain.thalamus.ask._capture_turn", side_effect=fake_capture):
        await run_ask("test", "sess-99", mock_db, config)

    assert captured["answer"] == "the answer"
    assert captured["session_id"] == "sess-99"
