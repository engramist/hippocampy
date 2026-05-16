# Plan for B238 - Clean-Machine One-Click Installer Validation Harness

## Metadata

- **Card ID**: B238
- **Priority**: P0
- **Dependencies**: B236, B237
- **Risk**: High - clean-machine validation can accidentally touch real user state if HOME isolation is wrong

## Goal

Prove the one-click installer works from a clean environment and does not rely on this developer machine's current state.

## Step 1: Create Clean HOME Tests

Create `tests/test_bootstrap_clean_home.py`.

Use `tmp_path` and environment overrides to simulate:

- no `~/.campy`
- no Codex config
- no Claude config
- no launchd plist
- existing partial config

Tests must not touch the real home directory.

## Step 2: Add Validation Script

Create `scripts/validate_one_click_install.sh`.

Required flags:

- `--dry-run`
- `--use-temp-home`
- `--skip-daemon`
- `--package dist/...whl`

The script should run bootstrap in a temp HOME where possible, then inspect generated files.

## Step 3: Doctor JSON Mode if Needed

If parsing `campy doctor` text is brittle, add a machine-readable option to `campy doctor`, such as:

```bash
campy doctor --json
```

Keep human output unchanged by default.

## Step 4: CI Smoke Test

If GitHub Actions is appropriate, create `.github/workflows/installer-smoke.yml` for non-mutating checks:

- shell syntax
- Python tests
- dry-run bootstrap
- package build

Do not require secrets.

## Step 5: Manual Validation Doc

Create `docs/one-click-validation.md` with:

- test matrix
- fresh Mac checklist
- work-computer checklist
- expected doctor output
- expected activity log behavior
- rollback/uninstall steps

## Step 6: Validate

Run:

```bash
bash -n scripts/validate_one_click_install.sh
bash scripts/validate_one_click_install.sh --dry-run
.venv/bin/pytest -q tests/test_bootstrap_clean_home.py tests/test_bootstrap_script.py tests/test_installer_idempotency.py tests/test_doctor_cli.py
HOME=$(mktemp -d) bash scripts/bootstrap.sh --dry-run
```

## Completion Notes

Mark B238 complete only when the harness proves bootstrap behavior without relying on the real user home.
