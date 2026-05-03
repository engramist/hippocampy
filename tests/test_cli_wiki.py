import pytest
from typer.testing import CliRunner
from sidequests.cli.main import app
from unittest.mock import MagicMock, patch

runner = CliRunner()

@pytest.fixture
def mock_config():
    return {
        "wiki_projection": {
            "enabled": True,
            "vault_dir": "test_wiki",
            "output_dir": "test_wiki/personas/default",
            "obsidian_vault_name": "Test Vault"
        }
    }

def test_wiki_path(mock_config):
    with patch("sidequests.cli.main.load_config", return_value=mock_config):
        result = runner.invoke(app, ["wiki", "path"])
        assert result.exit_code == 0
        assert "test_wiki" in result.stdout

def test_wiki_status_not_generated(mock_config):
    with patch("sidequests.cli.main.load_config", return_value=mock_config):
        with patch("sidequests.cli.wiki.Path.exists", return_value=False):
            result = runner.invoke(app, ["wiki", "status"])
            assert result.exit_code == 0
            assert "Wiki Projection: ENABLED" in result.stdout
            assert "Persona status:  NOT GENERATED" in result.stdout

def test_wiki_status_existing(mock_config):
    with patch("sidequests.cli.main.load_config", return_value=mock_config):
        with patch("sidequests.cli.wiki.Path.exists", return_value=True):
            with patch("sidequests.cli.wiki.Path.rglob", return_value=[MagicMock(), MagicMock()]):
                result = runner.invoke(app, ["wiki", "status"])
                assert result.exit_code == 0
                assert "Total Pages:     2" in result.stdout

@patch("subprocess.run")
@patch("platform.system", return_value="Darwin")
def test_wiki_open_mac(mock_system, mock_run, mock_config):
    with patch("sidequests.cli.main.load_config", return_value=mock_config):
        with patch("sidequests.cli.wiki.Path.exists", return_value=True):
            result = runner.invoke(app, ["wiki", "open"])
            assert result.exit_code == 0
            assert "Attempted to open Obsidian vault: Test Vault" in result.stdout
            mock_run.assert_called()
