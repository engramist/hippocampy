# Implementation Plan: Cross-Agent Hook Installation & Installer Fix

## Context

After the codebase anatomy refactor (Phases 4-9), all code moved from `mcp_engine/` to `campy/brain/`. The installer needs updating to work with the new paths. Additionally, Codex CLI and Gemini CLI now support lifecycle hooks (like Claude Code's `PreToolUse`/`PostToolUse`/`SessionStart`), but Campy only has hooks for Claude Code. This plan adds hooks for both platforms and fixes the installer.

**What exists today:**
- Claude Code: 3 bash hook scripts (`session_start.sh`, `pre_tool_use.sh`, `post_tool_use.sh`) + 1 Python hook (`hook_user_turn.py`) + `setup.py` for registration
- Codex: MCP adapter only, no hooks, no setup.py
- Gemini CLI: MCP adapter only, no hooks, no setup.py

**What we're building:**
- Codex hook scripts (Python, JSON stdin/stdout per [Codex hooks spec](https://developers.openai.com/codex/hooks))
- Gemini CLI hook scripts (Python, JSON stdin/stdout per [Gemini hooks spec](https://geminicli.com/docs/hooks/))
- Setup/registration scripts for both platforms
- Installer wiring so `campy install-plugin` and `campy setup` install hooks

**Shared infrastructure all hooks use:**
- Trigger manifest at `~/.campy/triggers/manifest.json` (compiled from Procedure/Lesson nodes)
- Brain daemon health at `http://127.0.0.1:7799/health`
- Brain transport via `campy.brain_transport.call_brain()` (Unix socket + offline queue)
- `campy decide` CLI command for session-start context

---

## Hook Protocol Differences

| Aspect | Claude Code | Codex CLI | Gemini CLI |
|--------|-------------|-----------|------------|
| Config location | `~/.claude/settings.json` | `~/.codex/hooks.json` | `~/.gemini/settings.json` |
| Hook I/O | Env vars + plain text stdout | JSON stdin -> JSON/text stdout | JSON stdin -> JSON stdout |
| Tool name source | `$CLAUDE_TOOL_NAME` env var | `tool_name` field in stdin JSON | stdin JSON (event-specific) |
| Tool input source | `$CLAUDE_TOOL_INPUT` env var | `tool_input` field in stdin JSON | stdin JSON |
| Tool output source | stdin (plain text) | `tool_response` field in stdin JSON | stdin JSON |
| Session start output | Plain text to stdout | Plain text OR `{systemMessage}` JSON | JSON `{output: {message}}` |
| Available events | PreToolUse, PostToolUse, SessionStart, UserPromptSubmit | SessionStart, PreToolUse, PostToolUse, UserPromptSubmit, Stop | SessionStart, BeforeTool, AfterTool, BeforeAgent, AfterAgent |

---

## Tasks (optimised for parallel Haiku subagents)

All 6 tasks are independent -- they create new files or modify disjoint functions.

### Task 1: CODEX-HOOKS -- Create Codex hook scripts

**Create 4 new files** in `adapters/codex/hooks/`:

**`session_start.py`** (~40 lines)
- Read JSON from stdin (contains `session_id`, `cwd`, etc.)
- Check daemon health via `curl http://127.0.0.1:7799/health`
- Run `campy decide "new session starting" --format=prompt` to get context
- Output plain text to stdout (Codex adds this as system context for SessionStart)
- Graceful fallback if daemon is down

**`pre_tool_use.py`** (~60 lines)
- Read JSON from stdin: `{tool_name, tool_input, ...}`
- Load trigger manifest from `~/.campy/triggers/manifest.json`
- Filter triggers where `hook_type == "PreToolUse"`, match tool name and pattern against `json.dumps(tool_input)`
- If matches found, output `{systemMessage: "[Campy Memory -- name]\nsnippet\n..."}` JSON
- Cap at 3 matches. If no matches, output `{}` (empty JSON = no-op)

**`post_tool_use.py`** (~60 lines)
- Read JSON from stdin: `{tool_name, tool_input, tool_response, ...}`
- Load manifest, filter `hook_type == "PostToolUse"`, match against `str(tool_response)`
- Output `{systemMessage: "..."}` JSON with matched context snippets
- Cap at 3 matches

**`user_prompt.py`** (~40 lines)
- Read JSON from stdin: `{session_id, ...}` -- note: Codex UserPromptSubmit doesn't include prompt text directly, just metadata
- Import `campy.brain_transport.call_brain`
- Call `notify_turn(role="user", content=..., session_id=...)` via brain transport
- Offline queue fallback to `~/.campy/offline_queue.jsonl`
- Output `{}` (no-op JSON)

**Reference:** Claude Code equivalents at `adapters/claude_code/hooks/` and `adapters/claude_code/hook_user_turn.py`

---

### Task 2: GEMINI-HOOKS -- Create Gemini CLI hook scripts

**Create 3 new files** in `adapters/gemini_cli/hooks/`:

**`session_start.py`** (~40 lines)
- Read JSON from stdin
- Check daemon health, run `campy decide` for context
- Output JSON to stdout: `{"output": {"metadata": {"message": "context text here"}}}` (Gemini requires JSON, not plain text)
- If no context: `{}` (empty = no-op)
- All debug output to stderr only

**`before_tool.py`** (~60 lines)
- Read JSON from stdin (tool details per Gemini BeforeTool event)
- Load trigger manifest, filter PreToolUse triggers, match patterns
- Output JSON: `{"output": {"metadata": {"message": "[Campy Memory]\n..."}}}` for context injection
- Cap at 3 matches

**`after_tool.py`** (~60 lines)
- Read JSON from stdin (tool result per Gemini AfterTool event)
- Load manifest, filter PostToolUse triggers, match against tool result
- Output JSON with matched context snippets
- Cap at 3 matches

**Reference:** Same trigger manifest matching logic as Claude Code's `pre_tool_use.sh` but adapted for JSON I/O. Debug output MUST go to stderr per Gemini spec.

---

### Task 3: CODEX-SETUP -- Create Codex registration + setup

**Create `adapters/codex/setup.py`** (~80 lines)

Functions:
- `register(project_root)` -- entry point called by installer
- `install_hooks(project_root)` -- copies hook scripts to `~/.codex/hooks/campy/`
- `_write_hook_config()` -- creates/updates `~/.codex/hooks.json`

**hooks.json format** (per Codex spec):
```json
{
  "hooks": {
    "SessionStart": [{"matcher": "startup|resume", "hooks": [{"type": "command", "command": "python3 ~/.codex/hooks/campy/session_start.py", "timeout": 10}]}],
    "PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 ~/.codex/hooks/campy/pre_tool_use.py", "timeout": 5}]}],
    "PostToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 ~/.codex/hooks/campy/post_tool_use.py", "timeout": 5}]}],
    "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 ~/.codex/hooks/campy/user_prompt.py", "timeout": 5}]}]
  }
}
```

Key details:
- Merge with existing hooks.json (don't overwrite user's other hooks)
- Remove stale Campy entries before adding new ones (detect by script path containing "campy")
- Copy Python scripts to `~/.codex/hooks/campy/` (not project-local, since hooks are user-level)
- Set executable permissions

**Reference:** `adapters/claude_code/setup.py` for the registration pattern

---

### Task 4: GEMINI-SETUP -- Create Gemini CLI registration + setup

**Create `adapters/gemini_cli/setup.py`** (~80 lines)

Functions:
- `register(project_root)` -- entry point
- `install_hooks(project_root)` -- copies hook scripts to `~/.gemini/hooks/campy/`
- `_write_hook_config()` -- merges hook entries into `~/.gemini/settings.json`

**settings.json hooks format** (per Gemini spec):
```json
{
  "hooks": {
    "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/campy/session_start.py", "timeout": 5000, "name": "campy-session-start"}]}],
    "BeforeTool": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/campy/before_tool.py", "timeout": 5000, "name": "campy-before-tool"}]}],
    "AfterTool": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/campy/after_tool.py", "timeout": 5000, "name": "campy-after-tool"}]}]
  }
}
```

Key differences from Codex:
- Gemini timeout is in milliseconds (5000ms = 5s)
- Gemini hooks have a `name` field for identification
- Gemini settings.json already has other keys (`security`, `mcpServers`) -- must merge, not overwrite
- Hook scripts go to `~/.gemini/hooks/campy/`

**Reference:** `adapters/claude_code/setup.py` for pattern, Gemini hook docs for schema

---

### Task 5: INSTALLER-WIRING -- Update install.py registration methods

**Modify `campy/cli/install.py`** -- 2 methods:

**`_register_codex()` (around line 830-860):**
Add after the existing `config_path.write_text(updated)` line:
```python
# Install Codex hooks
try:
    from adapters.codex.setup import install_hooks, _write_hook_config
    install_hooks()
    _write_hook_config()
    click.echo("    [ok] Codex hooks installed")
except Exception as e:
    click.echo(f"    [!] Codex hook installation skipped: {e}")
```

**`_register_gemini_cli()` (around line 862-885):**
Add after the existing `self._merge_mcp_config(...)` call:
```python
# Install Gemini CLI hooks
try:
    from adapters.gemini_cli.setup import install_hooks, _write_hook_config
    install_hooks()
    _write_hook_config()
    click.echo("    [ok] Gemini CLI hooks installed")
except Exception as e:
    click.echo(f"    [!] Gemini CLI hook installation skipped: {e}")
```

Also update `register_codex()` in `campy/cli/register.py` (line 195-216) to call hook installation similarly.

---

### Task 6: PLUGIN-INSTALLER -- Update plugin_installer.py for hooks

**Modify `campy/cli/plugin_installer.py`** -- 2 functions:

**`install_codex_plugin()`:** After the skills copy loop, add hook installation:
```python
# Install hooks
hooks_src = plugin_dir.parent / "adapters" / "codex" / "hooks"
if hooks_src.exists():
    hooks_dst = Path.home() / ".codex" / "hooks" / "campy"
    hooks_dst.mkdir(parents=True, exist_ok=True)
    for hook_file in sorted(hooks_src.glob("*.py")):
        dst = hooks_dst / hook_file.name
        shutil.copy2(hook_file, dst)
        dst.chmod(0o755)
    logger.info(f"Codex: hooks installed to {hooks_dst}")
```

**`install_gemini_plugin()`:** Same pattern but target `~/.gemini/hooks/campy/`

Both should also call their respective `_write_hook_config()` to register the hooks in the config files.

---

## Verification

| Check | Command | Expected |
|-------|---------|----------|
| Codex hook files exist | `ls adapters/codex/hooks/` | 4 .py files |
| Gemini hook files exist | `ls adapters/gemini_cli/hooks/` | 3 .py files |
| Codex setup.py exists | `python -c "from adapters.codex.setup import register"` | No error |
| Gemini setup.py exists | `python -c "from adapters.gemini_cli.setup import register"` | No error |
| Hook scripts are valid Python | `python -m py_compile adapters/codex/hooks/session_start.py` | No error |
| Installer compiles | `python -c "from campy.cli.install import Installer"` | No error |
| Plugin installer compiles | `python -c "from campy.cli.plugin_installer import install_plugin_for_agents"` | No error |
| Dry-run Codex install | `campy install-plugin --target codex` then `ls ~/.codex/hooks/campy/` | 4 hook files |
| Dry-run Gemini install | `campy install-plugin --target gemini-cli` then `ls ~/.gemini/hooks/campy/` | 3 hook files |
| Existing tests pass | `pytest tests/ -q --ignore=tests/test_ab_reproducibility.py ...` | >=1277 passed |
