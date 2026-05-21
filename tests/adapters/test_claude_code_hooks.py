# tests/adapters/test_claude_code_hooks.py
from pathlib import Path
import subprocess
import os


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
    """PreToolUse hook script should exist."""
    hook = Path("adapters/claude_code/hooks/pre_tool_use.sh")
    assert hook.exists()
    content = hook.read_text()
    assert "memory" in content.lower() or "current_truth" in content.lower()


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
