# Install/Setup Stabilization Plan

Status: approved for implementation
Owner: Copilot (plan/review) -> Gemini CLI (implementation)

## Goal

Restore the SideQuests CLI/install/setup surface so it matches the behavior already expected by the current Python test suite.

This is a stabilization pass, not a redesign. The current failures are caused by newer simplified implementations in the CLI layer drifting away from the richer contract used by the rest of the repo.

## Scope

In scope:
- Repair installer/setup command behavior so existing tests pass
- Restore launchd helper API expected by installer and uninstall paths
- Restore client detection API expected by installer/setup tests
- Restore main CLI commands expected by uninstall/setup tests
- Restore smoke test helpers expected by installer orchestration
- Preserve current working install/setup modules where already correct (`sidequests/cli/install.py`, `sidequests/cli/setup.py`, `sidequests/cli/uninstall.py`)
- Make retrieval panel URL tests pass if they were broken by related drift

Out of scope:
- New features
- Rewriting installer architecture
- Packaging/publishing work beyond what is required for imports/tests
- ARC benchmark changes

## Known Failing Tests To Fix

Primary failing buckets from the latest regression run:
- `tests/test_bringup_priorities.py`
- `tests/test_install.py`
- `tests/test_retrieval.py`
- `tests/test_setup.py`
- `tests/test_setup_cli.py`
- `tests/test_uninstall.py`

## Root Cause Summary

1. `sidequests/cli/detect.py` was simplified and no longer exposes `detect_installed_clients()` with the original key names (`claude-code`, `claude-desktop`, `codex`, `codex-desktop`, `chatgpt-desktop`, `gemini-cli`, `openclaw`).
2. `sidequests/cli/launchd.py` was replaced with a minimal plist writer and no longer exposes the installer-facing API (`LABEL`, `PLIST_PATH`, `LOG_PATH`, `resolve_system_python`, `_daemon_script`, `write_plist`, `load_plist`, `unload_plist`, `is_loaded`).
3. `sidequests/cli/main.py` was rewritten to a minimal Typer app and dropped commands that the rest of the code/tests still rely on (`install`, `uninstall`, `start`, `stop`, `status`, `review`).
4. `sidequests/cli/smoke_test.py` was reduced to stubs and no longer exposes `_send`, `smoke_test`, `check_sse_endpoint`, and `check_status` used by the installer tests and orchestration.
5. Some of the simplified replacements (`register.py`, `detect.py`) use different server names/arg formats than existing tests expect.
6. Retrieval tests likely need a small compatibility fix in `mcp_engine/tools.py` if `panel_url` behavior regressed.

## Files To Modify

1. `sidequests/cli/detect.py`
2. `sidequests/cli/launchd.py`
3. `sidequests/cli/main.py`
4. `sidequests/cli/smoke_test.py`
5. `sidequests/cli/register.py` only if required for setup CLI tests after the above fixes
6. `mcp_engine/tools.py` only if needed for `panel_url` retrieval tests

## Implementation Requirements

### 1. Repair `sidequests/cli/detect.py`

Keep the small helper functions if useful, but restore the installer-facing API.

Required public functions:
- `detect_claude_code() -> bool`
- `detect_claude_desktop() -> str | bool` or equivalent existing behavior compatible with tests
- `detect_chatgpt_desktop()`
- `detect_codex() -> bool`
- `detect_installed_clients() -> dict[str, bool]`
- `detect_all() -> dict[str, bool]` may remain as a compatibility wrapper

Required behavior:
- `detect_installed_clients()` must return keys:
	- `claude-code`
	- `claude-desktop`
	- `codex`
	- `codex-desktop`
	- `chatgpt-desktop`
	- `gemini-cli`
	- `openclaw`
- Detection should match the existing test expectations from `tests/test_setup.py` and installer code.
- `detect_all()` can translate to underscore keys for the simplified Typer setup command if still used.

### 2. Repair `sidequests/cli/launchd.py`

Restore the full launchd helper surface expected by installer and uninstall code.

Required module constants:
- `LABEL = "ai.sidequests.brain"`
- `PLIST_PATH`
- `LOG_PATH`

Required functions:
- `resolve_system_python() -> str`
- `_daemon_script() -> str`
- `write_plist() -> Path`
- `load_plist() -> bool`
- `unload_plist() -> bool`
- `is_loaded() -> bool`

Behavioral requirements derived from tests:
- `resolve_system_python()` must skip pyenv shims by rejecting resolved paths containing `/.pyenv/shims/`.
- Candidate order should follow existing tests: `python3.12`, `python3`, `/usr/bin/python3`, then `sys.executable`.
- `write_plist()` must produce a plist with:
	- `ProgramArguments`
	- `EnvironmentVariables.PYTHONPATH`
	- stdout/stderr path at `LOG_PATH`
- `write_plist()` must use `resolve_system_python()`.
- Keep or preserve `setup_daemon()` wrapper only if still useful for the Typer setup command, but it should call the restored functions rather than bypass them.

### 3. Repair `sidequests/cli/smoke_test.py`

Restore the original installer-facing smoke-test API while keeping any lightweight wrappers if needed.

Required functions:
- `_send(method: str, params: dict | None = None) -> dict`
- `smoke_test() -> dict`
- `check_sse_endpoint(port: int = 7799) -> bool`
- `check_status() -> bool`

Requirements:
- Use `SOCKET_PATH = ~/.sidequests/brain.sock`
- Use expected tool set matching existing tests/installer logic
- `check_status()` should print human-readable status and return a bool
- If you keep `run_smoke_tests()`, implement it as a compatibility wrapper rather than a stub

### 4. Repair `sidequests/cli/main.py`

Keep Typer if you want, but restore the command surface expected by tests and existing modules.

Required commands:
- `setup`
- `install`
- `uninstall`
- `start`
- `stop`
- `status`
- `review`
- `tool list`

Behavioral requirements:
- `install` should delegate to `sidequests.cli.install.run_install`
- `uninstall` should support:
	- `--keep-data / --delete-data`
	- `--remove-ollama-model`
	- `--ollama-model`
	- `--yes` / `-y`
- `uninstall` default confirmation flow must match `tests/test_uninstall.py`
- `status` should call `sidequests.cli.smoke_test.check_status`
- `setup` command should still satisfy `tests/test_setup_cli.py`

Do not remove the Typer `app` object; tests import `from sidequests.cli.main import app`.

### 5. Adjust `sidequests/cli/register.py` only if required

After steps 1-4, run targeted tests first. Only touch this file if `tests/test_setup_cli.py` still fails.

If changes are needed:
- Preserve current helper function names used by `main.py`
- Align `register_claude_desktop()` expectations with the tests in `tests/test_setup_cli.py`
- Do not break the existing `sidequests/cli/setup.py` flow

### 6. Fix retrieval panel URL only if still failing

Read `tests/test_retrieval.py` and update `mcp_engine/tools.py` only if necessary.

Required behavior:
- `current_truth()` must include `panel_url`
- default base URL should be `http://127.0.0.1:7800`
- if `quest_id` present in params, `panel_url` should point to `/board`
- respect `mission_control.base_url` override

Make the smallest possible compatibility fix.

## Validation Commands

Run in this order:

1. `pytest tests/test_setup_cli.py tests/test_setup.py -q`
2. `pytest tests/test_install.py tests/test_bringup_priorities.py -q`
3. `pytest tests/test_uninstall.py tests/test_retrieval.py -q`
4. If all above pass: `pytest tests/test_bringup_priorities.py tests/test_install.py tests/test_retrieval.py tests/test_setup.py tests/test_setup_cli.py tests/test_uninstall.py -q`

## Acceptance Criteria

- All six targeted failure groups above pass.
- No regressions introduced in adjacent setup/install command behavior.
- The restored API surface is compatible with both the installer code and the current tests.
- Changes are minimal and scoped to stabilization.

## Delegation Prompt

Use exactly:

`gemini -p "Read B-install-setup-stabilization.md and implement exactly as specified. Read the existing install/setup/uninstall/launchd/detect/smoke_test/main modules and the failing tests first. Use minimal safe changes. Preserve existing behavior outside this stabilization scope. Run the targeted pytest commands from the plan and report changed files, test commands, pass/fail summary, and any follow-up issues." --yolo 2>&1`
