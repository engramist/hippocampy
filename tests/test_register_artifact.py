# tests/test_register_artifact.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_register_artifact_upserts_new_node():
    from campy.brain.thalamus.tools import register_artifact

    written = []
    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[])  # no existing node
    async def capture_write(q, p=None):
        written.append((q, p))
    mock_db.execute_write = capture_write

    await register_artifact(
        {
            "file_path": "backlog/B290.md",
            "document_type": "backlog_card",
            "title": "B290 — Continuous Work State",
            "summary": "Cross-agent handoff via hot WorkSummary writes.",
            "linked_card": "B290",
            "session_id": "sess-1",
            "agent_source": "claude_code",
        },
        mock_db,
        {},
    )

    assert any("WorkArtifact" in q for q, _ in written)


@pytest.mark.asyncio
async def test_register_artifact_updates_existing_node():
    from campy.brain.thalamus.tools import register_artifact

    written = []
    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[{"wa.artifact_id": "art-1"}])
    async def capture_write(q, p=None):
        written.append((q, p))
    mock_db.execute_write = capture_write

    await register_artifact(
        {
            "file_path": "backlog/B290.md",
            "title": "Updated title",
            "session_id": "sess-1",
        },
        mock_db,
        {},
    )

    assert any("SET" in q for q, _ in written)


@pytest.mark.asyncio
async def test_register_artifact_infers_document_type_from_path():
    from campy.brain.thalamus.tools import register_artifact

    written_params = []
    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[])
    async def capture_write(q, p=None):
        written_params.append(p or {})
    mock_db.execute_write = capture_write

    await register_artifact(
        {"file_path": "docs/superpowers/specs/2026-06-26-cws.md", "session_id": "s1"},
        mock_db,
        {},
    )

    doc_types = [p.get("dt") for p in written_params if "dt" in p]
    assert any(dt == "spec" for dt in doc_types)


def test_register_artifact_in_tool_handlers():
    from campy.brain.thalamus.tools import TOOL_HANDLERS
    assert "register_artifact" in TOOL_HANDLERS
