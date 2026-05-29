# tests/adapters/test_claude_code_hooks.py
import json
from pathlib import Path
import subprocess
import os
from unittest.mock import patch


def test_session_start_hook_exists():
    """Session start hook script should exist."""
    hook = Path("adapters/claude_code/hooks/session_start.sh")
    assert hook.exists(), f"Hook not found at {hook}"
    content = hook.read_text()
    assert "campy" in content.lower() or "recall" in content.lower()
    assert "#!/" in content  # Has shebang


def test_session_start_hook_is_executable():
    """Hook script should be executable."""
    hook = Path("adapters/claude_code/hooks/session_start.sh")
    assert os.access(hook, os.X_OK), "Hook script is not executable"


def test_pre_tool_use_hook_exists():
    """PreToolUse hook script should exist and reference manifest."""
    hook = Path("adapters/claude_code/hooks/pre_tool_use.sh")
    assert hook.exists()
    content = hook.read_text()
    assert "manifest" in content.lower()


def test_pre_tool_use_hook_is_executable():
    """PreToolUse hook should be executable."""
    hook = Path("adapters/claude_code/hooks/pre_tool_use.sh")
    assert os.access(hook, os.X_OK), "Hook script is not executable"


def test_session_start_hook_graceful_when_daemon_down():
    """Hook should not error when daemon is not running."""
    result = subprocess.run(
        ["bash", "adapters/claude_code/hooks/session_start.sh"],
        capture_output=True, text=True, timeout=10,
        env=dict(os.environ)
    )
    # Should exit 0 even if daemon is down
    assert result.returncode == 0
    # Should output something (either context or a fallback message)
    assert len(result.stdout.strip()) > 0


import tempfile


def test_setup_register_installs_hooks(tmp_path):
    """setup.register() should install hook scripts to project hooks dir."""
    from adapters.claude_code.setup import install_hooks
    
    hooks_dir = tmp_path / ".claude" / "hooks"
    install_hooks(project_root=tmp_path)
    
    assert (hooks_dir / "session_start.sh").exists()
    assert (hooks_dir / "pre_tool_use.sh").exists()
    assert (hooks_dir / "post_tool_use.sh").exists()


def test_write_hook_config_replaces_stale_hook_path(tmp_path):
    """Stale hook_user_turn.py entries should be replaced even if the path changed."""
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
                            "command": "/old/python /old/site-packages/adapters/claude_code/hook_user_turn.py",
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
    assert commands == [f"{repo_python} {claude_setup.HOOK_FILE}"]


def test_post_tool_use_hook_exists():
    """PostToolUse hook script should exist and reference manifest."""
    hook = Path("adapters/claude_code/hooks/post_tool_use.sh")
    assert hook.exists()
    content = hook.read_text()
    assert "manifest" in content.lower()
    assert "PostToolUse" in content


def test_post_tool_use_hook_is_executable():
    """PostToolUse hook should be executable."""
    hook = Path("adapters/claude_code/hooks/post_tool_use.sh")
    assert os.access(hook, os.X_OK), "PostToolUse hook is not executable"
