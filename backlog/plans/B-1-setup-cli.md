# B-1-setup-cli — `sidequests setup` CLI Command

**Card:** B1 | **Priority:** P1 | **Depends on:** None

## Summary
Implement an automated setup CLI that detects installed AI clients and registers SideQuests with each one, replacing manual JSON editing. Makes the system immediately usable without configuration friction.

## Technical Approach

### CLI Entry Point
- Create `sidequests/cli/main.py` with typer-based CLI
- Register `sidequests = "sidequests.cli.main:app"` in `pyproject.toml` as console script
- Main command: `sidequests setup [--target CLIENT]` with auto-detection if target not specified

### Client Detection
- `sidequests/cli/detect.py`: detect installed clients (Claude Code, Claude Desktop, ChatGPT Desktop, Codex)
  - Claude Code: check for `claude` CLI in PATH
  - Claude Desktop: check for `~/Library/Application Support/Claude/claude_desktop_config.json`
  - ChatGPT Desktop: check for ChatGPT config location
  - Codex: check for Codex CLI

### Registration Flow

#### Claude Code
```python
# Call: claude mcp add sidequests --  python /path/to/adapters/claude_code/adapter.py
subprocess.run(["claude", "mcp", "add", "sidequests", "--", "python", adapter_path])
```

#### Claude Desktop
```python
# Write to ~/Library/Application Support/Claude/claude_desktop_config.json
# Append to mcpServers object: "sidequests-brain": { "command": "python", "args": [...] }
```

#### ChatGPT Desktop
```python
# Write to ChatGPT config location with SSE endpoint
```

#### Codex
```python
# Register adapter with Codex
```

### Daemon Management
- `sidequests/cli/launchd.py`: generate `~/.LaunchAgents/ai.sidequests.brain.plist`
- Use `launchctl load/unload` to enable auto-start
- Make idempotent: load twice = no error

### Smoke Tests
- `sidequests/cli/smoke_test.py`:
  - Ping Ollama (or configured LLM provider)
  - Initialize Kùzu schema (or verify existing)
  - Call `tools/list` through each registered client
  - Validate all 5+ tools are surfaced
  - Print pass/fail summary

## Files to Create

- `sidequests/cli/__init__.py`
- `sidequests/cli/main.py` — entry point, CLI commands
- `sidequests/cli/detect.py` — client detection logic
- `sidequests/cli/register.py` — per-client registration (claude_code, claude_desktop, chatgpt, codex)
- `sidequests/cli/launchd.py` — plist generation + launchctl management
- `sidequests/cli/smoke_test.py` — end-to-end validation
- `tests/test_setup_cli.py` — unit + integration tests
- Update `pyproject.toml` — add entry point

## Acceptance Criteria

1. `sidequests setup` on a clean machine detects and registers all installed clients
2. Post-setup `sidequests tool list` shows all 5+ tools for each registered client
3. `launchctl list | grep sidequests` confirms daemon is enabled
4. Re-running `sidequests setup` is idempotent (no duplicate entries, no errors)
5. Pass/fail report after setup is human-readable and actionable
6. `tests/test_setup_cli.py` covers detection, registration, idempotency
7. Windows/Linux registration is stubbed with clear deferred message

## Testing

```bash
pytest tests/test_setup_cli.py -v
```

- Mock client detection (skip actual CLI calls in unit tests)
- Integration test on real system (if not CI)
- Test idempotency: run setup twice, verify no duplicates
