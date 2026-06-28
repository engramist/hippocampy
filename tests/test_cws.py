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
