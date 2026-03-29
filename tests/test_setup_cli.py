import os
import json
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from typer.testing import CliRunner
from sidequests.cli.main import app
from sidequests.cli.detect import detect_claude_code, detect_claude_desktop
from sidequests.cli.register import (
    register_claude_code, 
    register_claude_desktop, 
    register_codex
)
from sidequests.cli.launchd import generate_plist

runner = CliRunner()

def test_detect_claude_code():
    with patch("shutil.which", return_value="/usr/local/bin/claude"):
        assert detect_claude_code() is True
    with patch("shutil.which", return_value=None):
        assert detect_claude_code() is False

def test_detect_claude_desktop(tmp_path):
    config_dir = tmp_path / "Claude"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "claude_desktop_config.json"
    config_file.write_text("{}")
    
    with patch("os.path.expanduser", return_value=str(config_file)):
        with patch("os.path.exists", return_value=True):
            assert detect_claude_desktop() == str(config_file)

def test_register_claude_code():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Success", returncode=0)
        assert register_claude_code("/path/to/adapter.py") is True
        mock_run.assert_called_once()

def test_register_claude_desktop(tmp_path):
    config_file = tmp_path / "claude_desktop_config.json"
    config_file.write_text(json.dumps({"mcpServers": {}}))
    
    adapter_path = "/path/to/adapter.py"
    assert register_claude_desktop(adapter_path, str(config_file)) is True
    
    with open(config_file, "r") as f:
        config = json.load(f)
        assert "sidequests-brain" in config["mcpServers"]
        assert config["mcpServers"]["sidequests-brain"]["args"] == [adapter_path]

def test_register_codex(tmp_path):
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text("[mcp_servers]\n")
    
    adapter_path = "/path/to/adapter.py"
    with patch("os.path.expanduser", return_value=str(config_file)):
        assert register_codex(adapter_path) is True
        content = config_file.read_text()
        assert "[mcp_servers.sidequests]" in content
        assert adapter_path in content

def test_generate_plist(tmp_path):
    plist_path = tmp_path / "ai.sidequests.brain.plist"
    daemon_path = "/path/to/brain_daemon.py"
    
    assert generate_plist(daemon_path, str(plist_path)) is True
    assert plist_path.exists()
    content = plist_path.read_text()
    assert "ai.sidequests.brain" in content
    assert daemon_path in content

def test_setup_command_auto():
    with patch("sidequests.cli.main.detect_all") as mock_detect:
        mock_detect.return_value = {
            "claude_code": True,
            "claude_desktop": True,
            "chatgpt_desktop": True,
            "codex": True,
            "gemini_cli": False
        }
        with patch("sidequests.cli.main.register_claude_code", return_value=True):
            with patch("sidequests.cli.main.register_claude_desktop", return_value=True):
                with patch("sidequests.cli.main.register_chatgpt_desktop", return_value=True):
                    with patch("sidequests.cli.main.register_codex", return_value=True):
                        with patch("sidequests.cli.main.setup_daemon", return_value=True):
                            with patch("sidequests.cli.main.run_smoke_tests", new_callable=AsyncMock) as mock_smoke:
                                mock_smoke.return_value = {
                                    "Daemon Communication": True,
                                    "MCP Tool Visibility": True,
                                    "LLM Provider Connectivity": True,
                                    "Kùzu Health": True
                                }
                                with patch("platform.system", return_value="Darwin"):
                                    result = runner.invoke(app, ["setup"])
                                    assert result.exit_code == 0
                                    assert "SideQuests Setup" in result.stdout
                                    assert "Detected Claude Code" in result.stdout
                                    assert "Detected Claude Desktop" in result.stdout
                                    assert "Detected ChatGPT Desktop" in result.stdout
                                    assert "Detected Codex" in result.stdout
                                    assert "Setup complete!" in result.stdout

def test_setup_command_target():
    with patch("sidequests.cli.main.register_claude_code", return_value=True) as mock_reg:
        with patch("sidequests.cli.main.run_smoke_tests", new_callable=AsyncMock) as mock_smoke:
            mock_smoke.return_value = {"Test": True}
            result = runner.invoke(app, ["setup", "--target", "claude-code"])
            assert result.exit_code == 0
            assert "SideQuests Setup" in result.stdout
            mock_reg.assert_called_once()

@pytest.mark.asyncio
async def test_run_smoke_tests_success():
    from sidequests.cli.smoke_test import run_smoke_tests
    
    with patch("sidequests.cli.smoke_test._send") as mock_send:
        mock_send.return_value = {
            "result": {
                "tools": [{"name": f"tool_{i}"} for i in range(10)]
            }
        }
        with patch("sidequests.cli.smoke_test.check_ollama", return_value=True):
            with patch("sidequests.cli.smoke_test.Path.exists", return_value=True): # sidequests.toml
                # Mock tomllib to avoid needing real toml
                with patch("tomllib.load", return_value={"llm": {"provider": "ollama"}}):
                    with patch("builtins.open", MagicMock()):
                        results = await run_smoke_tests()
                        assert results["Daemon Communication"] is True
                        assert results["MCP Tool Visibility"] is True
                        assert results["Kùzu Health"] is True
                        assert results["LLM Provider Connectivity"] is True

@pytest.mark.asyncio
async def test_run_smoke_tests_failure():
    from sidequests.cli.smoke_test import run_smoke_tests
    
    with patch("sidequests.cli.smoke_test._send") as mock_send:
        mock_send.return_value = {"error": {"message": "Not running"}}
        with patch("sidequests.cli.smoke_test.time.sleep"): # Skip sleep in tests
            results = await run_smoke_tests()
            assert results["Daemon Communication"] is False
            assert results["MCP Tool Visibility"] is False
