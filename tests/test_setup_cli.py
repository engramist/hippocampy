import os
import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from typer.testing import CliRunner
from campy.cli.main import app
from campy.cli.detect import detect_claude_code, detect_claude_desktop
from campy.cli.register import (
    register_claude_code, 
    register_claude_desktop, 
    register_codex,
    register_vscode,
)
from campy.cli.launchd import generate_plist

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
        assert "campy" in config["mcpServers"]
        assert config["mcpServers"]["campy"]["args"] == ["-m", "campy.adapters.claude_desktop"]

def test_register_codex(tmp_path):
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text("[mcp_servers]\n")

    adapter_path = "/path/to/adapter.py"
    with patch("os.path.expanduser", return_value=str(config_file)):
        assert register_codex(adapter_path) is True
        content = config_file.read_text()
        assert "[mcp_servers.campy]" in content
        assert '"-m", "campy.adapters.mcp_server"' in content

def test_register_codex_replaces_stale_and_stray_entries(tmp_path):
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    adapter_path = str(tmp_path / "repo" / "adapters" / "codex" / "adapter.py")
    Path(adapter_path).parent.mkdir(parents=True)
    Path(adapter_path).write_text("# adapter")
    config_file.write_text(
        f'["{adapter_path}"]\n\n'
        '[mcp_servers.campy]\n'
        'command = "/wrong/python"\n'
        'args = ["/wrong/adapter.py"]\n'
    )

    with patch("os.path.expanduser", return_value=str(config_file)):
        assert register_codex(adapter_path) is True

    content = config_file.read_text()
    assert f'["{adapter_path}"]' not in content.splitlines()
    assert content.count("[mcp_servers.campy]") == 1
    assert '"-m", "campy.adapters.mcp_server"' in content
    assert "/wrong/python" not in content

def test_register_vscode(tmp_path):
    config_file = tmp_path / "mcp.json"
    adapter_path = str(tmp_path / "repo" / "adapters" / "codex" / "adapter.py")
    Path(adapter_path).parent.mkdir(parents=True)
    Path(adapter_path).write_text("# adapter")

    assert register_vscode(adapter_path, str(config_file)) is True
    config = json.loads(config_file.read_text())
    assert config["servers"]["campy"]["type"] == "stdio"
    assert config["servers"]["campy"]["args"] == ["-m", "campy.adapters.mcp_server"]

def test_claude_code_hook_registration_repairs_stale_python(tmp_path):
    from adapters.claude_code import setup as claude_setup

    home = tmp_path / "home"
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"/tmp/pytest-python {claude_setup.HOOK_FILE}",
                        }
                    ],
                }
            ]
        }
    }))

    repo_python = claude_setup.REPO_ROOT / ".venv" / "bin" / "python"
    with patch.object(claude_setup.Path, "home", return_value=home):
        with patch.object(claude_setup, "_python_executable", return_value=str(repo_python)):
            claude_setup._write_hook_config()

    settings = json.loads(settings_path.read_text())
    entries = settings["hooks"]["UserPromptSubmit"]
    commands = [hook["command"] for entry in entries for hook in entry["hooks"]]
    assert len(commands) == 1
    assert commands[0].startswith(str(repo_python))
    assert "/tmp/pytest-python" not in commands[0]

def test_generate_plist(tmp_path):
    plist_path = tmp_path / "ai.hippocampy.brain.plist"
    daemon_path = "/path/to/brain_daemon.py"
    
    assert generate_plist(daemon_path, str(plist_path)) is True
    assert plist_path.exists()
    content = plist_path.read_text()
    assert "ai.hippocampy.brain" in content
    assert daemon_path in content

def test_setup_command_auto():
    with patch("campy.cli.main.detect_all") as mock_detect:
        mock_detect.return_value = {
            "claude_code": True,
            "claude_desktop": True,
            "chatgpt_desktop": True,
            "codex": True,
            "gemini_cli": False,
            "vscode": True,
        }
        with patch("campy.cli.main.register_claude_code", return_value=True):
            with patch("campy.cli.main.register_claude_desktop", return_value=True):
                with patch("campy.cli.main.register_chatgpt_desktop", return_value=True):
                    with patch("campy.cli.main.register_codex", return_value=True):
                        with patch("campy.cli.main.register_vscode", return_value=True):
                            with patch("campy.cli.main.setup_daemon", return_value=True):
                                with patch("campy.cli.main.run_smoke_tests", new_callable=AsyncMock) as mock_smoke:
                                    mock_smoke.return_value = {
                                        "Daemon Communication": True,
                                        "MCP Tool Visibility": True,
                                        "LLM Provider Connectivity": True,
                                        "Kùzu Health": True
                                    }
                                    with patch("platform.system", return_value="Darwin"):
                                        result = runner.invoke(app, ["setup"])
                                        assert result.exit_code == 0
                                        assert "HippoCampy Setup" in result.stdout
                                        assert "Detected Claude Code" in result.stdout
                                        assert "Detected Claude Desktop" in result.stdout
                                        assert "Detected ChatGPT Desktop" in result.stdout
                                        assert "Detected Codex" in result.stdout
                                        assert "Detected VS Code" in result.stdout
                                        assert "Setup complete!" in result.stdout

def test_setup_command_target():
    with patch("campy.cli.main.register_claude_code", return_value=True) as mock_reg:
        with patch("campy.cli.main.run_smoke_tests", new_callable=AsyncMock) as mock_smoke:
            mock_smoke.return_value = {"Test": True}
            result = runner.invoke(app, ["setup", "--target", "claude-code"])
            assert result.exit_code == 0
            assert "HippoCampy Setup" in result.stdout
            mock_reg.assert_called_once()

def test_setup_command_target_vscode():
    with patch("campy.cli.main.register_vscode", return_value=True) as mock_reg:
        with patch("campy.cli.main.setup_daemon", return_value=True):
            with patch("campy.cli.main.run_smoke_tests", new_callable=AsyncMock) as mock_smoke:
                mock_smoke.return_value = {"Test": True}
                result = runner.invoke(app, ["setup", "--target", "vscode"])
                assert result.exit_code == 0
                mock_reg.assert_called_once()

@pytest.mark.asyncio
async def test_run_smoke_tests_success():
    from campy.cli.smoke_test import run_smoke_tests
    
    with patch("campy.cli.smoke_test._send") as mock_send:
        mock_send.return_value = {
            "result": {
                "tools": [{"name": f"tool_{i}"} for i in range(10)]
            }
        }
        with patch("campy.cli.smoke_test.check_ollama", return_value=True):
            with patch("campy.cli.smoke_test.Path.exists", return_value=True): # campy.toml
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
    from campy.cli.smoke_test import run_smoke_tests
    
    with patch("campy.cli.smoke_test._send") as mock_send:
        mock_send.return_value = {"error": {"message": "Not running"}}
        with patch("campy.cli.smoke_test.time.sleep"): # Skip sleep in tests
            results = await run_smoke_tests()
            assert results["Daemon Communication"] is False
            assert results["MCP Tool Visibility"] is False
