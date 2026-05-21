# tests/cli/test_plugin_installer.py
import tempfile
from pathlib import Path
from campy.cli.plugin_installer import find_plugin_dir, install_claude_code_plugin

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
