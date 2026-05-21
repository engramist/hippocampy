# tests/cli/test_install_plugin_integration.py
import tempfile
from pathlib import Path
from campy.cli.plugin_installer import find_plugin_dir, install_claude_code_plugin

def test_full_plugin_install_to_temp_dir():
    """Full plugin install creates all expected files."""
    plugin_dir = find_plugin_dir()
    assert plugin_dir is not None

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "hippocampy"
        result = install_claude_code_plugin(plugin_dir, target)
        assert result is True
        assert (target / ".claude-plugin" / "plugin.json").exists()
        assert (target / ".mcp.json").exists()
        assert (target / "skills" / "recall" / "SKILL.md").exists()
        assert (target / "skills" / "memory-awareness" / "SKILL.md").exists()
        assert (target / "skills" / "quest-management" / "SKILL.md").exists()
        assert (target / "skills" / "status" / "SKILL.md").exists()

def test_install_is_idempotent():
    """Running install twice doesn't error or duplicate files."""
    plugin_dir = find_plugin_dir()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "hippocampy"
        install_claude_code_plugin(plugin_dir, target)
        result = install_claude_code_plugin(plugin_dir, target)
        assert result is True
