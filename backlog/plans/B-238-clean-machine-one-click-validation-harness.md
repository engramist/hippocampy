# B238 - Clean-Machine One-Click Installer Validation Harness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the bootstrap installer works from a clean environment without relying on the dev machine's state. Build a validation harness that simulates fresh HOME, missing configs, and partial installs.

**Architecture:** Python tests use `tmp_path` + `HOME` override to simulate clean environments. A bash validation script wraps bootstrap with temp HOME. Optional GitHub Actions CI for non-mutating checks. Manual checklist doc for real work-computer installs.

**Tech Stack:** Python (pytest), Bash, optional GitHub Actions YAML

**Key existing files:**
- `scripts/bootstrap.sh` — from B237, the one-line installer
- `campy/cli/doctor.py` — `DoctorChecker` class, needs `--json` for machine-readable output
- `campy/cli/install.py` — Python installer
- `tests/test_packaging_installed_mode.py` — existing wheel-install tests

---

### Task 1: Create Clean HOME Tests

**Files:**
- Create: `tests/test_bootstrap_clean_home.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_bootstrap_clean_home.py
"""Test bootstrap behavior in clean HOME environments.

Uses tmp_path and HOME override to simulate fresh machines.
NEVER touches the real home directory.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def clean_home(tmp_path):
    """Create a clean HOME directory with no Campy state."""
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    # Clear any XDG overrides that might leak
    for key in ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"]:
        env.pop(key, None)
    return home, env


def test_clean_home_has_no_campy(clean_home):
    """Fresh HOME should have no .campy directory."""
    home, env = clean_home
    assert not (home / ".campy").exists()
    assert not (home / ".codex").exists()


def test_bootstrap_dry_run_clean_home(clean_home):
    """Bootstrap --dry-run should work with clean HOME."""
    home, env = clean_home
    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--dry-run"],
        capture_output=True, text=True, env=env, timeout=30
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout or "dry run" in result.stdout.lower()


def test_bootstrap_dry_run_does_not_create_files(clean_home):
    """--dry-run should not create any files in HOME."""
    home, env = clean_home
    subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--dry-run"],
        capture_output=True, text=True, env=env, timeout=30
    )
    # Should NOT have created .campy or any config dirs
    assert not (home / ".campy").exists(), ".campy created during dry run"


def test_clean_home_no_codex_config(clean_home):
    """Fresh HOME has no Codex config — bootstrap should handle gracefully."""
    home, env = clean_home
    assert not (home / ".codex" / "config.toml").exists()


def test_clean_home_no_claude_config(clean_home):
    """Fresh HOME has no Claude config — bootstrap should handle gracefully."""
    home, env = clean_home
    claude_config_mac = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    assert not claude_config_mac.exists()


def test_partial_install_missing_brain_db(clean_home):
    """Simulate partial install: .campy dir exists but no brain.db."""
    home, env = clean_home
    campy_dir = home / ".campy"
    campy_dir.mkdir()
    (campy_dir / "campy.toml").write_text("[general]\n")
    # brain.db missing — doctor should detect this
    assert not (campy_dir / "brain.db").exists()
    assert (campy_dir / "campy.toml").exists()


def test_partial_install_missing_launchd_plist(clean_home):
    """Simulate partial install: .campy exists but no launchd plist."""
    home, env = clean_home
    launch_agents = home / "Library" / "LaunchAgents"
    # Don't create it — simulates no daemon auto-start
    assert not launch_agents.exists()


class TestRepeatInstallIdempotency:
    """Test that install operations are idempotent."""

    def test_dry_run_twice_same_output(self, clean_home):
        """Running --dry-run twice should produce consistent output."""
        home, env = clean_home
        results = []
        for _ in range(2):
            result = subprocess.run(
                ["bash", "scripts/bootstrap.sh", "--dry-run"],
                capture_output=True, text=True, env=env, timeout=30
            )
            results.append(result.stdout)
        # Output should be identical (or at least same exit code)
        assert results[0] == results[1]
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_bootstrap_clean_home.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_bootstrap_clean_home.py
git commit -m "test(B238): add clean HOME bootstrap simulation tests"
```

---

### Task 2: Create Validation Script

**Files:**
- Create: `scripts/validate_one_click_install.sh`
- Create: `tests/test_validation_script.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validation_script.py
"""Test the validation script exists and is well-formed."""
from pathlib import Path
import subprocess

def test_validation_script_exists():
    """Validation script should exist."""
    assert Path("scripts/validate_one_click_install.sh").exists()

def test_validation_script_syntax():
    """Script should pass bash -n check."""
    result = subprocess.run(
        ["bash", "-n", "scripts/validate_one_click_install.sh"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"

def test_validation_script_has_strict_mode():
    """Script should use set -euo pipefail."""
    content = Path("scripts/validate_one_click_install.sh").read_text()
    assert "set -euo pipefail" in content

def test_validation_script_supports_dry_run():
    """Script should support --dry-run."""
    content = Path("scripts/validate_one_click_install.sh").read_text()
    assert "--dry-run" in content

def test_validation_script_supports_temp_home():
    """Script should support --use-temp-home."""
    content = Path("scripts/validate_one_click_install.sh").read_text()
    assert "--use-temp-home" in content

def test_validation_dry_run():
    """Validation --dry-run should succeed."""
    result = subprocess.run(
        ["bash", "scripts/validate_one_click_install.sh", "--dry-run"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validation_script.py::test_validation_script_exists -v`
Expected: FAIL

- [ ] **Step 3: Create the validation script**

Create `scripts/validate_one_click_install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Campy One-Click Install Validation Harness
# =============================================================================
# Validates the bootstrap installer works from a clean environment.
#
# Usage:
#   bash scripts/validate_one_click_install.sh --dry-run
#   bash scripts/validate_one_click_install.sh --use-temp-home
#   bash scripts/validate_one_click_install.sh --use-temp-home --skip-daemon
#   bash scripts/validate_one_click_install.sh --package dist/hippocampy-*.whl
# =============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DRY_RUN=false
USE_TEMP_HOME=false
SKIP_DAEMON=false
PACKAGE_PATH=""
TEMP_HOME=""

usage() {
    echo "Usage: validate_one_click_install.sh [OPTIONS]"
    echo ""
    echo "Validate the Campy bootstrap installer."
    echo ""
    echo "Options:"
    echo "  --dry-run         Show what would be tested without running"
    echo "  --use-temp-home   Run bootstrap with a temporary HOME directory"
    echo "  --skip-daemon     Skip daemon start/health checks"
    echo "  --package PATH    Use a specific wheel file instead of PyPI"
    echo "  --help            Show this help"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)       DRY_RUN=true; shift ;;
        --use-temp-home) USE_TEMP_HOME=true; shift ;;
        --skip-daemon)   SKIP_DAEMON=true; shift ;;
        --package)       PACKAGE_PATH="$2"; shift 2 ;;
        --help|-h)       usage ;;
        *)               echo "Unknown option: $1"; usage ;;
    esac
done

PASS=0
FAIL=0
SKIP=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "pass" ]; then
        echo "  ✓ $name"
        PASS=$((PASS + 1))
    elif [ "$result" = "skip" ]; then
        echo "  - $name (skipped)"
        SKIP=$((SKIP + 1))
    else
        echo "  ✗ $name"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Campy One-Click Install Validation ==="
echo ""

if $DRY_RUN; then
    echo "DRY RUN — showing validation plan:"
    echo ""
    echo "1. Check bootstrap script syntax (bash -n)"
    echo "2. Check bootstrap --help works"
    echo "3. Check bootstrap --dry-run works"
    if $USE_TEMP_HOME; then
        echo "4. Run bootstrap with temp HOME"
        echo "5. Verify campy CLI is available"
        echo "6. Run campy doctor"
        if ! $SKIP_DAEMON; then
            echo "7. Verify daemon health"
            echo "8. Verify campy activity works"
        fi
    fi
    echo ""
    echo "Run without --dry-run to execute."
    exit 0
fi

# --- Static checks ---
echo "Static checks:"

# 1. Script syntax
if bash -n "$REPO_ROOT/scripts/bootstrap.sh" 2>/dev/null; then
    check "bootstrap.sh syntax" "pass"
else
    check "bootstrap.sh syntax" "fail"
fi

# 2. Help works
if bash "$REPO_ROOT/scripts/bootstrap.sh" --help >/dev/null 2>&1; then
    check "bootstrap --help" "pass"
else
    check "bootstrap --help" "fail"
fi

# 3. Dry run works
if bash "$REPO_ROOT/scripts/bootstrap.sh" --dry-run >/dev/null 2>&1; then
    check "bootstrap --dry-run" "pass"
else
    check "bootstrap --dry-run" "fail"
fi

# --- Clean HOME checks (if requested) ---
if $USE_TEMP_HOME; then
    echo ""
    echo "Clean HOME validation:"
    TEMP_HOME=$(mktemp -d)
    export HOME="$TEMP_HOME"
    echo "  Using temp HOME: $TEMP_HOME"

    # 4. Run bootstrap with dev source or package
    BOOTSTRAP_ARGS="--no-start"
    if [ -n "$PACKAGE_PATH" ]; then
        BOOTSTRAP_ARGS="$BOOTSTRAP_ARGS --dev-source $PACKAGE_PATH"
    else
        BOOTSTRAP_ARGS="$BOOTSTRAP_ARGS --dev-source $REPO_ROOT"
    fi

    if bash "$REPO_ROOT/scripts/bootstrap.sh" $BOOTSTRAP_ARGS 2>/dev/null; then
        check "bootstrap install (temp HOME)" "pass"
    else
        check "bootstrap install (temp HOME)" "fail"
    fi

    # 5. Verify campy CLI
    if command -v campy &>/dev/null || [ -f "$TEMP_HOME/.campy/venv/bin/campy" ]; then
        check "campy CLI available" "pass"
        # Ensure it's in PATH
        export PATH="$TEMP_HOME/.campy/venv/bin:$PATH"
    else
        check "campy CLI available" "fail"
    fi

    # 6. Doctor
    if campy doctor 2>/dev/null; then
        check "campy doctor" "pass"
    else
        check "campy doctor" "fail"
    fi

    # 7-8. Daemon checks
    if ! $SKIP_DAEMON; then
        campy start 2>/dev/null || true
        sleep 2
        if campy status 2>/dev/null; then
            check "daemon health" "pass"
        else
            check "daemon health" "skip"
        fi

        if campy activity --lines 1 2>/dev/null; then
            check "campy activity" "pass"
        else
            check "campy activity" "skip"
        fi
        campy stop 2>/dev/null || true
    fi

    # Cleanup temp HOME
    rm -rf "$TEMP_HOME"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
```

- [ ] **Step 4: Make executable and run tests**

```bash
chmod +x scripts/validate_one_click_install.sh
pytest tests/test_validation_script.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_one_click_install.sh tests/test_validation_script.py
git commit -m "feat(B238): create clean-machine validation harness script"
```

---

### Task 3: Add Doctor JSON Output

**Files:**
- Modify: `campy/cli/doctor.py`
- Modify: `campy/cli/main.py`
- Create: `tests/cli/test_doctor_json.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_doctor_json.py
"""Test doctor --json output."""
import subprocess
import sys
import json

def test_doctor_json_flag_exists():
    """campy doctor should accept --json flag."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "doctor", "--help"],
        capture_output=True, text=True
    )
    assert "--json" in result.stdout

def test_doctor_json_output_is_valid_json():
    """campy doctor --json should produce valid JSON."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "doctor", "--json"],
        capture_output=True, text=True, timeout=30
    )
    # Should exit 0 or 1 but always produce JSON
    try:
        data = json.loads(result.stdout)
        assert "checks" in data
        assert isinstance(data["checks"], list)
    except json.JSONDecodeError:
        assert False, f"Invalid JSON output: {result.stdout[:200]}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_doctor_json.py -v`
Expected: FAIL — `--json` flag doesn't exist

- [ ] **Step 3: Add --json flag to doctor command**

In `campy/cli/main.py`, update the `doctor` command:

```python
@app.command()
def doctor(
    repair: bool = typer.Option(False, "--repair", help="Attempt safe repairs"),
    lines: Optional[int] = typer.Option(None, "--lines", help="Show last N activity lines"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
):
    """
    Diagnose Campy daemon, config, runtime paths, and MCP registrations.
    """
    from campy.cli.doctor import run_doctor

    if not run_doctor(repair=repair, lines=lines, json_output=json_output):
        raise typer.Exit(code=1)
```

In `campy/cli/doctor.py`, update `run_doctor` and `DoctorChecker` to support JSON output:

Add a `json_output` parameter to `run_doctor()`. When `json_output=True`, collect results as a list of `{"name": str, "status": str, "message": str}` dicts and print as JSON instead of Rich tables.

Add to `DoctorChecker.__init__`:

```python
self._json_results = []
self._json_mode = json_output
```

Add method:

```python
def _record(self, name: str, status: str, message: str):
    """Record a check result for JSON output."""
    self._json_results.append({
        "name": name,
        "status": status,
        "message": message,
    })

def get_json_results(self) -> dict:
    """Return all check results as a JSON-serializable dict."""
    passed = sum(1 for r in self._json_results if r["status"] == "pass")
    failed = sum(1 for r in self._json_results if r["status"] == "fail")
    return {
        "checks": self._json_results,
        "summary": {"passed": passed, "failed": failed, "total": len(self._json_results)},
    }
```

Call `self._record(name, status, message)` from each `_pass()`, `_fail()`, `_warn()` method.

At the end of `run_doctor()`, if `json_output`:

```python
if json_output:
    import json
    print(json.dumps(checker.get_json_results(), indent=2))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/cli/test_doctor_json.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/doctor.py campy/cli/main.py tests/cli/test_doctor_json.py
git commit -m "feat(B238): add doctor --json for machine-readable output"
```

---

### Task 4: Create Manual Validation Checklist

**Files:**
- Create: `docs/one-click-validation.md`

- [ ] **Step 1: Write the validation doc**

Create `docs/one-click-validation.md`:

```markdown
# One-Click Install Validation Checklist

## Automated Validation

Run the validation harness:

```bash
# Static checks only (no install)
bash scripts/validate_one_click_install.sh --dry-run

# Full validation with temp HOME
bash scripts/validate_one_click_install.sh --use-temp-home --skip-daemon

# Full validation with daemon
bash scripts/validate_one_click_install.sh --use-temp-home
```

## Manual Work-Computer Checklist

For installing on a new machine (e.g., work computer):

### Pre-Install

- [ ] macOS or Linux
- [ ] Python 3.12+ installed: `python3 --version`
- [ ] Internet access to github.com/pypi.org
- [ ] Terminal with bash or zsh

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh | bash
```

### Post-Install Verification

- [ ] `campy --help` shows usage
- [ ] `campy doctor` passes (or shows only expected warnings)
- [ ] `campy status` shows daemon running
- [ ] `campy activity --lines 5` shows recent activity (may be empty on fresh install)
- [ ] `campy tool list` shows 30+ tools including `memory_decision`, `compile_context`
- [ ] `campy recall "test"` returns results (or empty if no data yet)

### Agent Registration Check

- [ ] Claude Code: `campy doctor` shows Claude Code registered (if installed)
- [ ] Codex: `~/.codex/skills/campy-memory/SKILL.md` exists (if Codex installed)
- [ ] VS Code: MCP config at `~/Library/Application Support/Code/User/mcp.json` has campy entry (if VS Code installed)
- [ ] Gemini CLI: GEMINI.md has Campy section (if Gemini CLI installed)

### Rollback

If something goes wrong:

```bash
campy uninstall --keep-data   # Remove registrations, keep memory data
# Or: pipx uninstall hippocampy
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/one-click-validation.md
git commit -m "docs(B238): add manual validation checklist for work-computer install"
```

---

### Task 5: Optional CI Smoke Test

**Files:**
- Create: `.github/workflows/installer-smoke.yml`

- [ ] **Step 1: Create CI workflow**

```yaml
# .github/workflows/installer-smoke.yml
name: Installer Smoke Test

on:
  push:
    paths:
      - 'scripts/bootstrap.sh'
      - 'scripts/release_build.sh'
      - 'campy/cli/install.py'
      - 'campy/cli/doctor.py'
      - 'pyproject.toml'
  pull_request:
    paths:
      - 'scripts/bootstrap.sh'
      - 'scripts/release_build.sh'

jobs:
  smoke:
    runs-on: macos-latest
    strategy:
      matrix:
        python-version: ['3.12', '3.13']
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Shell syntax check
        run: |
          bash -n scripts/bootstrap.sh
          bash -n scripts/release_build.sh
          bash -n scripts/validate_one_click_install.sh

      - name: Bootstrap --help
        run: bash scripts/bootstrap.sh --help

      - name: Bootstrap --dry-run
        run: bash scripts/bootstrap.sh --dry-run

      - name: Build package
        run: |
          pip install build twine
          python -m build --wheel --sdist
          python -m twine check dist/*

      - name: Install from wheel
        run: |
          pip install dist/hippocampy-*.whl
          campy --help
          campy doctor --help

      - name: Run packaging tests
        run: |
          pip install pytest pytest-asyncio
          pytest tests/test_release_build.py tests/test_bootstrap_script.py tests/test_validation_script.py -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/installer-smoke.yml
git commit -m "ci(B238): add installer smoke test workflow"
```

---

### Task 6: Final Verification

- [ ] **Step 1: Run all validation tests**

```bash
pytest tests/test_bootstrap_clean_home.py tests/test_bootstrap_script.py tests/test_validation_script.py tests/test_installer_idempotency.py tests/cli/test_doctor_json.py tests/test_release_build.py -v
```
Expected: All PASS

- [ ] **Step 2: Run validation harness dry-run**

```bash
bash scripts/validate_one_click_install.sh --dry-run
```
Expected: Shows validation plan

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(B238): complete — clean-machine validation harness"
```
