# tests/cli/test_plugin_installer.py
import json
import tempfile
from pathlib import Path
from campy.cli.plugin_installer import (
    find_plugin_dir,
    install_claude_code_plugin,
    install_codex_plugin,
    install_gemini_plugin,
)

def test_find_plugin_dir():
    """Should find the plugin/ dir relative to repo root."""
    result = find_plugin_dir()
    assert result is not None
    assert (result / ".claude-plugin" / "plugin.json").exists()

def test_install_claude_code_plugin_creates_mcp_config(tmp_path):
    """Should create .mcp.json in the target directory."""
    plugin_dir = find_plugin_dir()
    target_dir = tmp_path / ".claude" / "plugins" / "hippocampy"
    install_claude_code_plugin(plugin_dir, target_dir)
    assert (target_dir / ".mcp.json").exists()


def test_install_codex_plugin_uses_shared_hooks(monkeypatch, tmp_path):
    """Codex plugin install should copy shared wrappers and write wrapper-based hook config."""
    monkeypatch.setenv("HOME", str(tmp_path))
    plugin_dir = find_plugin_dir()

    assert install_codex_plugin(plugin_dir) is True

    hooks_dir = tmp_path / ".codex" / "hooks" / "campy"
    assert (hooks_dir / "campy_hook.py").exists()
    assert (hooks_dir / "pre_tool_use_wrapper.py").exists()

    hooks_config = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    command = hooks_config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "pre_tool_use_wrapper.py" in command
    assert "adapters/codex" not in command


def test_install_gemini_plugin_uses_shared_hooks(monkeypatch, tmp_path):
    """Gemini plugin install should copy shared wrappers and write wrapper-based hook config."""
    monkeypatch.setenv("HOME", str(tmp_path))
    plugin_dir = find_plugin_dir()

    assert install_gemini_plugin(plugin_dir) is True

    hooks_dir = tmp_path / ".gemini" / "hooks" / "campy"
    assert (hooks_dir / "campy_hook.py").exists()
    assert (hooks_dir / "post_tool_use_wrapper.py").exists()

    settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
    command = settings["hooks"]["BeforeTool"][0]["hooks"][0]["command"]
    assert "pre_tool_use_wrapper.py --gemini" in command
    assert "adapters/gemini_cli" not in command
