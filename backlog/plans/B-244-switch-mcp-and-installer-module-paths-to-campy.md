# Plan for B244 - Switch MCP and Installer Module Paths to `campy.*`

## Metadata

- **Card ID**: B244
- **Priority**: P0
- **Dependencies**: B243
- **Risk**: Medium/High - can break installed client integrations

## Goal

Make all new MCP registrations use `campy.*` module paths while repairing/removing old `sidequests.*` registrations safely.

## Guardrails

- Never leave duplicate MCP server entries.
- Prefer writing the new `campy` entry before removing stale legacy entries.
- Do not delete user-authored unrelated MCP config blocks.
- Do not change durable DB/config paths.

## Step 1: Registration Writers

Update registration code under `campy/cli/register.py`, `campy/cli/setup.py`, and `campy/cli/install.py` so new module-mode registrations use:

```bash
python -m campy.adapters.mcp_server
```

Use the MCP server name `campy`.

## Step 2: Legacy Cleanup

When updating JSON/TOML MCP config files, remove stale blocks named:

```text
sidequests
sidequests-brain
sidequests-brain-desktop
```

Also repair stale module paths containing:

```text
sidequests.adapters.mcp_server
sidequests.adapters.claude_desktop
sidequests.cli.main
```

## Step 3: Doctor Repair

Update doctor repair so it can identify:

- missing `campy` MCP server
- stale `sidequests` MCP server
- stale `python -m sidequests.*` command path
- duplicate `campy` + legacy entries

Repair should converge to one `campy` entry.

## Step 4: Uninstall

Update uninstall to remove both current and legacy server names. Preserve unrelated MCP entries.

## Step 5: Tests

Update or add tests for:

- Codex TOML cleanup
- VS Code MCP JSON cleanup
- Claude Desktop JSON cleanup
- Claude Code fallback JSON cleanup
- Gemini settings cleanup
- doctor repair of stale module paths

## Step 6: Validate

Run exactly:

```bash
.venv/bin/pytest -q tests/test_installer_idempotency.py tests/test_setup_cli.py tests/test_doctor_cli.py tests/test_uninstall.py tests/test_mcp_server_adapter.py
.venv/bin/pytest -q tests/test_adapters.py tests/test_adapter_claude_desktop.py tests/test_adapter_chatgpt_desktop.py
```

## Completion Notes

Include one before/after MCP config example in the card completion notes.
