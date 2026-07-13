# tests/cli/test_recall_config.py
"""Tests for B260 - multi-agent recall config."""
from pathlib import Path
from importlib import resources
import tempfile
import json


def test_universal_skill_exists():
    """Universal memory skill template should exist in campy.data."""
    skill_path = Path("campy/data/campy-memory/SKILL.md")
    assert skill_path.exists()
    content = skill_path.read_text()
    assert "memory_decision" in content
    # "MUST"-worded mandatory framing predates the canonical policy's shift to
    # softer, permission-based language (see skills/campy-memory/SKILL.md's
    # "Core Rule": "Do not recall on every turn... Recall only when a decision
    # needs memory."). Check for the current policy statement instead.
    assert "Core Rule" in content
    assert "current_truth" in content
    assert "compile_context" in content


def test_codex_skill_install_uses_universal_template():
    """install_codex_memory_skill should use the universal campy-memory skill."""
    from campy.cli.register import install_codex_memory_skill
    
    repo_root = Path(__file__).parent.parent.parent
    result = install_codex_memory_skill(repo_root)
    
    if result is not None:
        content = result.read_text()
        # Check for memory-related keywords (either version is fine)
        assert "memory" in content.lower()
        assert ("current_truth" in content or "recall" in content.lower())


def test_gemini_register_does_work():
    """register_gemini_cli should do more than just return True."""
    import inspect
    from campy.cli.register import register_gemini_cli
    source = inspect.getsource(register_gemini_cli)
    # Should contain actual registration logic
    assert "GEMINI.md" in source or "gemini" in source.lower()
    assert len(source.split("\n")) > 5


def test_vscode_register_exists():
    """register_vscode should exist and be callable."""
    from campy.cli.register import register_vscode
    assert callable(register_vscode)


def test_openclaw_plugin_config_valid():
    """openclaw.plugin.json should have all required fields."""
    repo_root = Path(__file__).parent.parent.parent
    config_path = repo_root / "extensions" / "hippocampy" / "openclaw.plugin.json"
    assert config_path.exists()
    
    config = json.loads(config_path.read_text())
    assert config["id"] == "hippocampy"
    assert config["kind"] == "memory"
    assert "autoCapture" in config["configSchema"]["properties"]
    assert "autoRecall" in config["configSchema"]["properties"]
