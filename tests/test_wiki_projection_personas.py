import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from mcp_engine.wiki_projection import export_wiki_projection

@pytest.fixture
def mock_db():
    db = MagicMock()
    def mock_execute(query, params=None):
        res = MagicMock()
        if "MATCH (l:Lesson)" in query:
            all_lessons = [
                ("lesson_arch", "Architecture lesson", "architecture", 0.9),
                ("lesson_res", "Research lesson", "research", 0.9)
            ]
            if params and "domains" in params:
                filtered = [l for l in all_lessons if l[2] in params["domains"]]
                res.__iter__.return_value = filtered
            else:
                res.__iter__.return_value = all_lessons
        else:
            res.__iter__.return_value = []
        return res
    db.execute.side_effect = mock_execute
    return db

@pytest.fixture
def tmp_vault(tmp_path):
    return tmp_path / "wiki"

@pytest.mark.asyncio
async def test_persona_isolation(mock_db, tmp_vault):
    config = {
        "wiki_projection": {
            "enabled": True,
            "vault_dir": str(tmp_vault),
            "personas": [
                {
                    "name": "engineer",
                    "output_dir": str(tmp_vault / "personas" / "engineer"),
                    "include_domains": ["architecture"]
                },
                {
                    "name": "researcher",
                    "output_dir": str(tmp_vault / "personas" / "researcher"),
                    "include_domains": ["research"]
                }
            ]
        }
    }

    summary = await export_wiki_projection(mock_db, config)
    assert summary["personas_processed"] == 2
    
    eng_dir = tmp_vault / "personas" / "engineer" / "pages"
    res_dir = tmp_vault / "personas" / "researcher" / "pages"
    
    assert eng_dir.exists()
    assert res_dir.exists()
    
    # Check that engineer ONLY has architecture lesson
    eng_pages = list(eng_dir.glob("*.md"))
    assert len(eng_pages) == 1
    assert "Architecture lesson" in eng_pages[0].read_text()
    assert "persona: engineer" in eng_pages[0].read_text()
    
    # Check that researcher ONLY has research lesson
    res_pages = list(res_dir.glob("*.md"))
    assert len(res_pages) == 1
    assert "Research lesson" in res_pages[0].read_text()
    assert "persona: researcher" in res_pages[0].read_text()

@pytest.mark.asyncio
async def test_global_home_generation(mock_db, tmp_vault):
    config = {
        "wiki_projection": {
            "enabled": True,
            "vault_dir": str(tmp_vault),
            "personas": [
                {"name": "p1", "output_dir": str(tmp_vault / "p1")},
                {"name": "p2", "output_dir": str(tmp_vault / "p2")}
            ]
        }
    }
    
    await export_wiki_projection(mock_db, config)
    global_home = (tmp_vault / "Home.md").read_text()
    assert "[[p1/Home|P1 Persona]]" in global_home
    assert "[[p2/Home|P2 Persona]]" in global_home

def test_cli_persona_path(tmp_vault):
    from sidequests.cli.main import app
    from typer.testing import CliRunner
    runner = CliRunner()
    
    mock_config = {
        "wiki_projection": {
            "enabled": True,
            "vault_dir": str(tmp_vault),
            "personas": [{"name": "eng", "output_dir": "/tmp/eng"}]
        }
    }
    
    with patch("sidequests.cli.main.load_config", return_value=mock_config):
        result = runner.invoke(app, ["wiki", "path", "--persona", "eng"])
        assert result.exit_code == 0
        assert "/tmp/eng" in result.stdout
