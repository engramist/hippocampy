# Plan for B231 - Installer Hardening and One-Line Bootstrap

## Card Metadata

- **Card ID**: B231
- **Priority**: P0
- **Dependencies**: B230 recommended before public package mode, but private source bootstrap can land first

## Summary

Make setup repeatable, repairable, and obvious on a fresh machine.

This card adds a private bootstrap script, hardens `sidequests install`, and introduces `sidequests doctor` as the main diagnostic/repair surface.

## Technical Approach

### Step 1: Add private bootstrap script

Create `scripts/install.sh`.

Behavior:

```bash
#!/usr/bin/env bash
set -euo pipefail
```

Required checks:

- macOS detection for launchd path, with clear fallback for other OSes
- `git` present
- Python 3.12 preferred
- reject Python 3.14+
- create `.venv` if missing
- install/upgrade pip
- `pip install -e .`
- run `.venv/bin/sidequests install`
- run `.venv/bin/sidequests doctor` or `.venv/bin/sidequests status`
- print `.venv/bin/sidequests activity --follow` as the operator check

Do not curl remote shell scripts in this repo yet. This is the source/private bootstrap.

### Step 2: Add `sidequests doctor`

Create `sidequests/cli/doctor.py` and wire it into `sidequests/cli/main.py`.

Checks should include:

- Python version
- package mode: editable/source vs installed wheel
- config file exists and parses
- runtime dir exists and permissions are sane
- Kuzu DB path exists or can be initialized
- daemon socket exists
- daemon communication works
- MCP tools visible
- launchd plist exists and is loaded on macOS
- activity log exists or can be created
- capture config enabled for supported clients
- Codex config has exactly one SideQuests MCP block
- Claude Code config registration exists when Claude Code is present
- Claude Desktop config registration exists when Claude Desktop is present
- VS Code MCP config exists when VS Code is present

Output should be table-based and end with repair suggestions.

### Step 3: Add safe repair mode

Support:

```bash
sidequests doctor --repair
```

Allowed repairs:

- create runtime dir
- create missing config from template
- clean duplicate SideQuests MCP blocks only
- recreate launchd plist
- restart daemon
- create activity log file

Forbidden repairs:

- delete `~/.sidequests/brain.db`
- delete user transcripts/journals
- remove unrelated MCP client config
- overwrite user config without backup

### Step 4: Harden installer idempotency

Review `sidequests/cli/install.py`, `sidequests/cli/setup.py`, and `sidequests/cli/register.py`.

Add tests for repeated install/registration behavior. Codex TOML was previously corrupted by duplicate bare adapter path tables; include a regression test for that exact failure mode.

### Step 5: Make final install output useful

After `sidequests install`, print:

```text
Next checks:
  sidequests status
  sidequests doctor
  sidequests activity --follow
```

If smoke checks fail, print the exact failed component and repair command.

### Step 6: Document install paths

Update:

- `README.md`
- `Instalation_Instructions.md`

Document:

- private source bootstrap
- future public one-liner target
- activity feed indicator
- reinstall/update commands

## Validation

Run exactly:

```bash
bash -n scripts/install.sh
.venv/bin/sidequests install
.venv/bin/sidequests install
.venv/bin/sidequests doctor
.venv/bin/sidequests status
.venv/bin/sidequests activity --lines 5
pytest -q tests/test_doctor_cli.py tests/test_installer_idempotency.py tests/test_setup_cli.py tests/test_activity_log.py
```

Run duplicate config check:

```bash
python - <<'PY'
from pathlib import Path
config = Path.home() / '.codex' / 'config.toml'
if config.exists():
    text = config.read_text()
    assert text.count('[mcp_servers.sidequests]') <= 1
    assert '[/Users/' not in text
print('codex config duplicate check ok')
PY
```

Adjust the final assertion if project-scoped path tables are intentionally retained; document rationale.

## Risks

- Installers that mutate user config need backups and precise merge logic.
- `doctor --repair` must be conservative; false positives are better than destructive fixes.
- Launchd behavior differs across macOS versions and privacy/TCC contexts.
