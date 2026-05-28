import pytest
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from campy.brain.thalamus.wiki_projection import export_wiki_projection, WikiPage

@pytest.fixture
def mock_db():
    db = MagicMock()
    # Mocking result objects that behave like Kuzu result
    def mock_execute(query, params=None):
        mock_res = MagicMock()
        mock_res.__iter__.return_value = []
        return mock_res
    db.execute.side_effect = mock_execute
    return db

@pytest.fixture
def tmp_vault(tmp_path):
    vault = tmp_path / "wiki"
    return vault

@pytest.mark.asyncio
async def test_wiki_projection_disabled(mock_db):
    config = {"wiki_projection": {"enabled": False}}
    summary = await export_wiki_projection(mock_db, config)
    assert summary["status"] == "disabled"

@pytest.mark.asyncio
async def test_wiki_projection_basic(mock_db, tmp_vault):
    config = {
        "wiki_projection": {
            "enabled": True,
            "vault_dir": str(tmp_vault),
            "output_dir": str(tmp_vault / "personas" / "default"),
            "max_pages_per_sweep": 10
        }
    }
    
    # Mock some data returning from Kuzu
    def mock_execute(query, params=None):
        res = MagicMock()
        if "MATCH (l:Lesson)" in query:
            res.__iter__.return_value = [
                ("lesson_1", "Test lesson text", "research", 0.9)
            ]
        elif "MATCH (p:Procedure)" in query:
            res.__iter__.return_value = [
                ("proc_1", "Test Procedure", "A test procedure", "test-archetype")
            ]
        else:
            res.__iter__.return_value = []
        return res
    
    mock_db.execute.side_effect = mock_execute

    summary = await export_wiki_projection(mock_db, config)
    
    assert summary["status"] == "success"
    assert summary["pages_written"] > 0
    
    # Check if files exist
    assert (tmp_vault / "Home.md").exists()
    assert (tmp_vault / "personas" / "default" / "Home.md").exists()
    assert (tmp_vault / "personas" / "default" / "Index.md").exists()
    
    # Check page content
    pages_dir = tmp_vault / "personas" / "default" / "pages"
    assert pages_dir.exists()
    lesson_page = list(pages_dir.glob("lesson-*.md"))[0]
    content = lesson_page.read_text()
    assert "sidequests_projection: true" in content
    assert "persona: default" in content
    assert "source_node_ids: ['lesson_1']" in content
    assert "Test lesson text" in content

def test_slugify():
    from campy.brain.thalamus.wiki_projection import _slugify
    assert _slugify("Test Page Name") == "test-page-name"
    assert _slugify("Special! @Characters") == "special-characters"

@pytest.mark.asyncio
async def test_atomic_write(tmp_path):
    from campy.brain.thalamus.wiki_projection import _write_atomic
    test_file = tmp_path / "atomic.md"
    _write_atomic(test_file, "initial content")
    assert test_file.read_text() == "initial content"
    
    _write_atomic(test_file, "updated content")
    assert test_file.read_text() == "updated content"
