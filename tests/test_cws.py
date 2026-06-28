# tests/test_cws.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_work_summary_node_exists_in_schema():
    """WorkSummary must be a registered node table."""
    from campy.brain.hippocampus.schema import NODE_TABLES
    assert "WorkSummary" in NODE_TABLES
    ddl = NODE_TABLES["WorkSummary"]
    assert "summary_id" in ddl
    assert "resume_line" in ddl
    assert "snapshot_text" in ddl
    assert "git_branch" in ddl
    assert "turn_count" in ddl


def test_work_artifact_node_exists_in_schema():
    """WorkArtifact must be a registered node table."""
    from campy.brain.hippocampus.schema import NODE_TABLES
    assert "WorkArtifact" in NODE_TABLES
    ddl = NODE_TABLES["WorkArtifact"]
    assert "artifact_id" in ddl
    assert "file_path" in ddl
    assert "document_type" in ddl
    assert "title" in ddl
    assert "summary" in ddl
    assert "linked_card" in ddl


def test_read_git_state_returns_unknown_for_empty_root():
    from campy.brain.thalamus.tools.work_summary import _read_git_state
    branch, commit = _read_git_state("")
    assert branch == "unknown"
    assert commit == "unknown"


def test_write_context_md_section_creates_file(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="Working on B290 (branch: main · abc1234). Last active: 2026-06-26 via claude_code.",
        snapshot_text="",
        turn_count=1,
        agent_source="claude_code",
        branch="main",
        commit="abc1234",
        ts="2026-06-26 20:53",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "## Current Work" in content
    assert "Working on B290" in content
    assert "abc1234" in content


def test_write_context_md_section_preserves_existing_content(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section
    (tmp_path / "CONTEXT.md").write_text(
        "# My Project\n\nSome description.\n\n## Language\n\n**foo**: bar\n"
    )
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="Working on B290.",
        snapshot_text="",
        turn_count=1,
        agent_source="claude_code",
        branch="main",
        commit="abc1234",
        ts="2026-06-26 20:53",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "## Current Work" in content
    assert "## Language" in content
    assert "**foo**" in content


def test_write_context_md_section_replaces_existing_current_work(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section
    (tmp_path / "CONTEXT.md").write_text(
        "## Current Work\n_Last active: old_\n\n**Resume:** Old resume line.\n\n## Language\n\n**foo**: bar\n"
    )
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="New resume line.",
        snapshot_text="",
        turn_count=1,
        agent_source="codex",
        branch="feat/x",
        commit="def5678",
        ts="2026-06-26 21:00",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "New resume line." in content
    assert "Old resume line." not in content
    assert "## Language" in content


def test_snapshot_written_at_interval(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section, _SNAPSHOT_INTERVAL
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="Resume.",
        snapshot_text="**Active card:** B290",
        turn_count=_SNAPSHOT_INTERVAL,
        agent_source="claude_code",
        branch="main",
        commit="abc",
        ts="2026-06-26 20:53",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "<details>" in content
    assert "**Active card:** B290" in content


def test_snapshot_not_written_between_intervals(tmp_path):
    from campy.brain.thalamus.tools.work_summary import _write_context_md_section, _SNAPSHOT_INTERVAL
    _write_context_md_section(
        project_root=str(tmp_path),
        resume_line="Resume.",
        snapshot_text="should not appear",
        turn_count=_SNAPSHOT_INTERVAL - 1,
        agent_source="claude_code",
        branch="main",
        commit="abc",
        ts="2026-06-26 20:53",
    )
    content = (tmp_path / "CONTEXT.md").read_text()
    assert "<details>" not in content
    assert "should not appear" not in content


@pytest.mark.asyncio
async def test_notify_turn_fires_update_work_summary():
    """notify_turn must fire update_work_summary as a background task."""
    from campy.brain.thalamus.tools import notify_turn

    mock_db = MagicMock()
    mock_db.execute_read = AsyncMock(return_value=[])
    mock_db.execute_write = AsyncMock(return_value=None)
    mock_db.execute = MagicMock()
    mock_db.execute.return_value.has_next.return_value = False

    config = {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}

    fired = []

    async def fake_update(session_id, db, config, agent_source="mcp", repo_root=""):
        fired.append(session_id)

    with patch("campy.brain.thalamus.tools.work_summary.update_work_summary", side_effect=fake_update), \
         patch("campy.brain.hippocampus.graph.embeddings.embed", return_value=[0.1] * 384), \
         patch("campy.brain.thalamus.tools.get_or_create_main_quest", new_callable=AsyncMock, return_value="q1"), \
         patch("campy.brain.thalamus.tools.get_or_create_session", new_callable=AsyncMock):
        await notify_turn(
            {"role": "user", "content": "hello", "session_id": "sess-cws-1",
             "repo_root": "/tmp/repo", "agent_source": "claude_code"},
            mock_db, config,
        )
        # Allow background task to run
        await asyncio.sleep(0)

    assert "sess-cws-1" in fired
