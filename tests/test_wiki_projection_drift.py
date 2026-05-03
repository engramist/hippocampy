import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock
from mcp_engine.wiki_projection import export_wiki_projection, _write_atomic

@pytest.fixture
def mock_db():
    db = MagicMock()
    def mock_execute(query, params=None):
        res = MagicMock()
        if "MATCH (l:Lesson)" in query:
            res.__iter__.return_value = [
                ("lesson_1", "Test lesson body", "research", 0.9)
            ]
        else:
            res.__iter__.return_value = []
        return res
    db.execute.side_effect = mock_execute
    return db

@pytest.fixture
def tmp_vault(tmp_path):
    return tmp_path / "wiki"

@pytest.mark.asyncio
async def test_drift_detection_and_conflict(mock_db, tmp_vault):
    config = {
        "wiki_projection": {
            "enabled": True,
            "vault_dir": str(tmp_vault),
            "output_dir": str(tmp_vault / "personas" / "default")
        }
    }

    # 1. Initial export
    summary = await export_wiki_projection(mock_db, config)
    assert summary["pages_written"] == 1
    assert summary["drift_detected"] == 0
    
    page_path = tmp_vault / "personas" / "default" / "pages" / "lesson-test-lesson-body.md"
    assert page_path.exists()
    
    # 2. Simulate manual edit
    content = page_path.read_text()
    edited_content = content + "\nUser added this line.\n"
    page_path.write_text(edited_content)
    
    # 3. Second export should detect drift
    summary2 = await export_wiki_projection(mock_db, config)
    assert summary2["pages_written"] == 1
    assert summary2["drift_detected"] == 1
    
    # Check for conflict file
    conflict_path = page_path.with_suffix(".conflict.md")
    assert conflict_path.exists()
    assert "User added this line." in conflict_path.read_text()
    
    # Original path should be restored to canonical state (without user line)
    restored_content = page_path.read_text()
    assert "User added this line." not in restored_content

@pytest.mark.asyncio
async def test_manual_notes_created(mock_db, tmp_vault):
    config = {
        "wiki_projection": {
            "enabled": True,
            "vault_dir": str(tmp_vault)
        }
    }
    
    await export_wiki_projection(mock_db, config)
    assert (tmp_vault / "manual-notes" / "Home.md").exists()
