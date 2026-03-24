# B13 Guided Installer Completion Plan

Status: Draft for approval
Owner: Opus (plan) -> Gemini CLI (implementation)

## Goal
Close the remaining gaps between current `sidequests install` behavior and backlog item B13 acceptance criteria, while preserving recent bring-up hardening.

## Scope
In scope:
- Linux auto-install path for Ollama package install (in addition to existing macOS Homebrew path)
- Explicit install report with per-step pass/fail status and actionable next-step guidance
- Explicit LLM connectivity smoke check in installer flow for both local and BYOK paths
- Keep installer idempotent and safe to rerun

Out of scope:
- DMG/native GUI installer packaging
- Homebrew formula publishing
- uninstall command (B19)
- OpenClaw sandbox allowlist integration follow-up

## Current State (verified)
Implemented already:
- Single entry point `sidequests install`
- Initial provider decision: local Ollama vs BYOK
- BYOK provider choice + API key validation call
- Auto-detection and registration for supported clients
- Config writing to `~/.sidequests/config.toml`
- Venv/dependencies/spaCy/embedding prewarm/schema init/daemon start/smoke test steps
- Safe rerun behavior for many subsystems

Remaining B13 gaps:
1) `OllamaInstaller.install()` only supports Homebrew path (macOS), no Linux package manager path.
2) Installer output is step-by-step logs but not a structured final pass/fail report with explicit remediation per failed step.
3) No explicit unified LLM connectivity check stage in the same summary model used by other smoke checks.

## Files To Modify
1. `sidequests/cli/install.py`
2. `tests/test_install.py`
3. `backlog.md` (mark B13 done only if all tests pass and behavior matches criteria)

## Detailed Implementation Plan

### 1) Add explicit result model for installer steps
File: `sidequests/cli/install.py`

Add dataclass near top-level imports:

```python
from dataclasses import dataclass

@dataclass
class InstallStepResult:
    name: str
    passed: bool
    detail: str
    fix_hint: str = ""
```

Add helper printers:

```python
def _print_step_header(step_num: int, total_steps: int, title: str) -> None:
    ...

def _print_install_report(results: list[InstallStepResult]) -> bool:
    """Print final pass/fail report and return True only if all critical steps passed."""
    ...
```

Rules:
- Keep existing human-friendly log lines.
- At end of install, always print a compact report table/list.
- Each failed step includes a one-line fix hint.
- Return boolean success from report helper.

### 2) Extend Ollama install path for Linux
File: `sidequests/cli/install.py`

Refactor `OllamaInstaller.install()` to:
- Detect OS via `platform.system()`
- macOS path: existing Homebrew flow unchanged
- Linux path:
  - If `apt-get` exists: run `sudo apt-get update` then `sudo apt-get install -y ollama`
  - Else if `dnf` exists: run `sudo dnf install -y ollama`
  - Else if `pacman` exists: run `sudo pacman -S --noconfirm ollama`
  - Else: print manual install instruction and return False
- Keep timeout/error capture and user-facing messages concise
- Maintain idempotency: if `ollama` already installed, skip package install

Notes:
- Do not add unsupported assumptions about service managers.
- Existing `ensure_running()` and `pull_model()` remain the activation path.

### 3) Add explicit LLM connectivity check stage
File: `sidequests/cli/install.py`

Add function:

```python
def verify_llm_connectivity(llm_config: dict) -> tuple[bool, str]:
    """Return (ok, detail) by issuing a minimal request to chosen provider."""
```

Behavior:
- For `provider == "ollama"`:
  - Check local API endpoint via HTTP call (`/api/tags` or `/v1/models`) and return clear error if unreachable.
- For BYOK providers:
  - Reuse OpenAI SDK client path with provider-specific `base_url` and a 1-token completion request.
- Must not log API keys.
- Must return terse detail text for report.

### 4) Rework `run_install()` orchestration to collect results
File: `sidequests/cli/install.py`

Change orchestration from early `sys.exit(1)` into result aggregation with controlled short-circuiting:
- Keep hard dependency ordering.
- If a prerequisite fails, mark dependent steps as failed with `detail="skipped due to earlier failure"` and fix hints.
- Continue enough to provide full report; do not crash mid-run.

Target staged flow:
1. Provider setup
2. LLM connectivity verify
3. Python environment + deps + models
4. Config write
5. Schema init
6. Adapter registration
7. Daemon setup
8. tools/list smoke test

End behavior:
- Always print final report.
- Exit code semantics:
  - success: return normally
  - failure: `raise click.ClickException("Installation completed with failures. See report above.")`

### 5) Add/adjust tests for new behavior
File: `tests/test_install.py`

Add tests:
1. Linux apt path chosen when `platform.system() == "Linux"` and `apt-get` exists.
2. Linux fallback message when no known package manager exists.
3. `verify_llm_connectivity()` success/failure for ollama endpoint.
4. `verify_llm_connectivity()` BYOK success/failure with mocked OpenAI client.
5. `_print_install_report()` returns False when any step fails.
6. `run_install()` emits final report even when an intermediate step fails.

Update existing tests only where behavior changed (for example, command sequencing expectations).

### 6) Mark backlog item complete
File: `backlog.md`

After green tests, update B13 section header to include done marker and date, with bullet notes indicating:
- guided install flow complete
- local and BYOK connectivity validated
- adapter auto-registration and smoke report included

If any B13 criterion is still intentionally deferred, explicitly list it under B13 notes instead of marking complete.

## Exact Test Commands
Run in this order:

1. `pytest tests/test_install.py -q --no-header`
2. `pytest tests/test_bringup_priorities.py tests/test_adapters.py -q --no-header`
3. `pytest tests/test_cli.py -q --no-header` (if present)

If failures are installer-related, fix before stopping. If unrelated pre-existing failures appear, document them in final summary.

## Delegation Prompt (for Gemini)
Use exactly:

`gemini -p "Read B-13-guided-installer.md and implement exactly as specified. Read existing sidequests/cli/install.py and tests/test_install.py first, preserve existing behavior unless the plan says to change it, and add/adjust tests accordingly. Do not modify unrelated files." --yolo 2>&1`

## Acceptance Checklist
- `sidequests install` still works on macOS paths already in use.
- Linux has at least one automatic package-manager install path for Ollama.
- Installer prints a final pass/fail summary with actionable hints.
- Explicit LLM connectivity check is part of flow and report.
- Installer remains idempotent (safe rerun).
- Target tests pass.
- Backlog B13 status updated only if criteria are fully met.
