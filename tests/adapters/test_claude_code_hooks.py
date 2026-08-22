# tests/adapters/test_claude_code_hooks.py
import json
import tempfile
import uuid
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
    """Hook should not error when daemon is not running.

    B351: this used to run with `env=dict(os.environ)` unmodified, so on a
    dev machine with a real daemon actually running (true for essentially
    this entire repo's own test sessions) it silently tested against the
    *real* daemon instead of a down one -- occasionally flaking with a
    subprocess timeout when the live daemon was slow to respond (itself
    tied to B342's memory-pressure findings), not because the hook script
    handled "daemon down" incorrectly. Point CAMPY_BRAIN_SOCKET at a
    guaranteed-nonexistent short path so this test actually exercises the
    down-daemon path it claims to, regardless of what's really running.

    Uses the system temp root directly (not pytest's `tmp_path`, which
    nests under a long per-test directory) -- AF_UNIX's sockaddr_un caps
    the path at roughly 104 bytes on macOS/BSD, and the hook script's own
    connect() attempt is subject to the same limit (see the `short_sock_path`
    fixture in tests/test_fail_open.py for the same reasoning in more
    detail).
    """
    env = dict(os.environ)
    env["CAMPY_BRAIN_SOCKET"] = str(
        Path(tempfile.gettempdir()) / f"campy-test-down-{uuid.uuid4().hex[:8]}.sock"
    )
    env.pop("CAMPY_BRAIN_URL", None)

    result = subprocess.run(
        ["bash", "adapters/claude_code/hooks/session_start.sh"],
        capture_output=True, text=True, timeout=10,
        env=env,
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
    assert "claude_memory_capture" in content
    assert "notify_turn" in content


def test_post_tool_use_hook_is_executable():
    """PostToolUse hook should be executable."""
    hook = Path("adapters/claude_code/hooks/post_tool_use.sh")
    assert os.access(hook, os.X_OK), "PostToolUse hook is not executable"
