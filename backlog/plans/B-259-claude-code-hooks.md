# B259 - Claude Code Hooks for Automatic Recall

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Claude Code hooks that inject memory recall at session start and before architecture-related tool calls.

**Architecture:** Create shell script hooks that Claude Code's hook system executes. `SessionStart` hook calls `campy recall --format=prompt` to inject memory context. `PreToolUse` hook fires before Read/Edit/Write on architecture files to remind about `current_truth`. Hooks installed by `adapters/claude_code/setup.py`.

**Tech Stack:** Bash shell scripts, Python (setup.py), Claude Code hook system

---

### Task 1: Create SessionStart Hook Script

**Files:**
- Create: `adapters/claude_code/hooks/session_start.sh`

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_claude_code_hooks.py`:

```python
# tests/adapters/test_claude_code_hooks.py
from pathlib import Path

def test_session_start_hook_exists():
    """Session start hook script should exist."""
    hook = Path("adapters/claude_code/hooks/session_start.sh")
    assert hook.exists(), f"Hook not found at {hook}"
    content = hook.read_text()
    assert "campy recall" in content or "campy decide" in content
    assert "#!/" in content  # Has shebang

def test_session_start_hook_is_executable():
    """Hook script should be executable."""
    import os
    hook = Path("adapters/claude_code/hooks/session_start.sh")
    assert os.access(hook, os.X_OK), "Hook script is not executable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_claude_code_hooks.py::test_session_start_hook_exists -v`
Expected: FAIL — file doesn't exist

- [ ] **Step 3: Create the hook script**

Create `adapters/claude_code/hooks/session_start.sh`:

```bash
#!/usr/bin/env bash
# Claude Code SessionStart hook — injects Campy memory context
# Installed by: campy install-plugin (B255) or adapters/claude_code/setup.py
#
# This hook runs at the start of every Claude Code session.
# It queries the Campy daemon for relevant context and outputs
# it as system prompt text that Claude Code injects into the conversation.

set -euo pipefail

# Check if campy CLI is available
if ! command -v campy &>/dev/null; then
    # Try the Python module path
    CAMPY_CMD="python3 -m campy.cli.main"
else
    CAMPY_CMD="campy"
fi

# Check if daemon is running (quick health check)
if ! curl -sf http://127.0.0.1:7799/health >/dev/null 2>&1; then
    # Daemon not running — output a minimal reminder
    echo "Note: Campy memory daemon is not running. Start with: campy start"
    exit 0
fi

# Get memory context for session start
# The --format=prompt flag outputs bare text suitable for prompt injection
CONTEXT=$($CAMPY_CMD decide "new session starting" --format=prompt 2>/dev/null || true)

if [ -n "$CONTEXT" ]; then
    echo "$CONTEXT"
else
    echo "Campy memory is available. Use memory_decision to check what the Brain knows before starting work."
fi
```

- [ ] **Step 4: Make executable and run tests**

```bash
chmod +x adapters/claude_code/hooks/session_start.sh
pytest tests/adapters/test_claude_code_hooks.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/claude_code/hooks/session_start.sh tests/adapters/test_claude_code_hooks.py
git commit -m "feat(B259): create SessionStart hook for automatic recall"
```

---

### Task 2: Create PreToolUse Hook Script

**Files:**
- Create: `adapters/claude_code/hooks/pre_tool_use.sh`

- [ ] **Step 1: Write the failing test**

Add to `tests/adapters/test_claude_code_hooks.py`:

```python
def test_pre_tool_use_hook_exists():
    """PreToolUse hook script should exist."""
    hook = Path("adapters/claude_code/hooks/pre_tool_use.sh")
    assert hook.exists()
    content = hook.read_text()
    assert "current_truth" in content or "memory" in content.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_claude_code_hooks.py::test_pre_tool_use_hook_exists -v`
Expected: FAIL

- [ ] **Step 3: Create the hook script**

Create `adapters/claude_code/hooks/pre_tool_use.sh`:

```bash
#!/usr/bin/env bash
# Claude Code PreToolUse hook — reminds about memory before architecture changes
#
# This hook fires before Read/Edit/Write tool calls.
# Claude Code passes the tool name and arguments as environment variables:
#   CLAUDE_TOOL_NAME — the tool being called (Read, Edit, Write, etc.)
#   CLAUDE_TOOL_INPUT — JSON string of tool arguments
#
# Only outputs a reminder for architecture-related file operations.

set -euo pipefail

TOOL_NAME="${CLAUDE_TOOL_NAME:-}"
TOOL_INPUT="${CLAUDE_TOOL_INPUT:-}"

# Only trigger for file-modifying tools
case "$TOOL_NAME" in
    Edit|Write)
        # Check if the file path matches architecture patterns
        if echo "$TOOL_INPUT" | grep -qiE '"file_path".*\b(architecture|ARCHITECTURE|design|schema|config)\b'; then
            echo "Reminder: Before modifying architecture files, check current_truth for existing constraints and decisions."
        fi
        ;;
    *)
        # No output for other tools (no-op)
        ;;
esac
```

- [ ] **Step 4: Make executable and run tests**

```bash
chmod +x adapters/claude_code/hooks/pre_tool_use.sh
pytest tests/adapters/test_claude_code_hooks.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/claude_code/hooks/pre_tool_use.sh tests/adapters/test_claude_code_hooks.py
git commit -m "feat(B259): create PreToolUse hook for architecture file reminders"
```

---

### Task 3: Update setup.py to Install Hooks

**Files:**
- Modify: `adapters/claude_code/setup.py`

- [ ] **Step 1: Read current setup.py**

Read `adapters/claude_code/setup.py` to understand the existing `register()` function.

- [ ] **Step 2: Write the failing test**

Add to `tests/adapters/test_claude_code_hooks.py`:

```python
import tempfile
from pathlib import Path

def test_setup_register_installs_hooks(tmp_path):
    """setup.register() should install hook scripts to project hooks dir."""
    # Create a mock project structure
    hooks_dir = tmp_path / ".claude" / "hooks"
    
    from adapters.claude_code.setup import install_hooks
    install_hooks(project_root=tmp_path)
    
    assert (hooks_dir / "session_start.sh").exists()
    assert (hooks_dir / "pre_tool_use.sh").exists()
```

- [ ] **Step 3: Add install_hooks function to setup.py**

Add to `adapters/claude_code/setup.py`:

```python
import shutil
from pathlib import Path

def install_hooks(project_root: Path = None) -> bool:
    """Install Claude Code hooks for Campy memory integration."""
    if project_root is None:
        project_root = Path.cwd()
    
    hooks_dir = project_root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    
    # Source hooks from the adapter directory
    adapter_hooks = Path(__file__).parent / "hooks"
    if not adapter_hooks.exists():
        return False
    
    installed = []
    for hook_script in adapter_hooks.glob("*.sh"):
        dest = hooks_dir / hook_script.name
        shutil.copy2(hook_script, dest)
        dest.chmod(0o755)
        installed.append(dest)
    
    return len(installed) > 0
```

Update the existing `register()` function to call `install_hooks()`:

```python
def register(project_root: Path = None):
    """Register Claude Code with Campy — MCP + hooks."""
    # ... existing registration code ...
    install_hooks(project_root)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/adapters/test_claude_code_hooks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/claude_code/setup.py tests/adapters/test_claude_code_hooks.py
git commit -m "feat(B259): setup.register() installs hooks to .claude/hooks/"
```

---

### Task 4: Graceful Degradation Test

**Files:**
- Modify: `tests/adapters/test_claude_code_hooks.py`

- [ ] **Step 1: Test hook graceful failure**

```python
import subprocess

def test_session_start_hook_graceful_when_daemon_down():
    """Hook should not error when daemon is not running."""
    result = subprocess.run(
        ["bash", "adapters/claude_code/hooks/session_start.sh"],
        capture_output=True, text=True, timeout=10,
        env={**dict(__import__("os").environ), "PATH": __import__("os").environ["PATH"]}
    )
    # Should exit 0 even if daemon is down
    assert result.returncode == 0
    # Should output something (either context or a fallback message)
    assert len(result.stdout.strip()) > 0
```

- [ ] **Step 2: Run test**

Run: `pytest tests/adapters/test_claude_code_hooks.py::test_session_start_hook_graceful_when_daemon_down -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/adapters/test_claude_code_hooks.py
git commit -m "test(B259): verify hooks degrade gracefully when daemon is down"
```
