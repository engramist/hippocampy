# Plan for B237 - Hosted One-Line Bootstrap Installer

## Metadata

- **Card ID**: B237
- **Priority**: P0
- **Dependencies**: B236, B231
- **Risk**: High - installer scripts mutate user machines

## Goal

Create a public bootstrap script that installs Campy without requiring a repo clone.

## Step 1: Create `scripts/bootstrap.sh`

Implement a shell script with:

- `set -euo pipefail`
- `--dry-run`
- `--dev-source PATH`
- `--version VERSION_OR_CHANNEL`
- `--no-start`
- `--no-register`
- `--help`

Default behavior should install from the package channel chosen in B236. Development mode may install from a local source path.

## Step 2: Runtime Safety Rules

The script must:

- reject unsupported Python versions
- avoid system Python mutation
- prefer `pipx` when present, otherwise use a managed venv under `~/.campy/installer` or another documented isolated path
- never delete `~/.campy/brain.db`
- never overwrite user-edited config without backup
- print every major action

## Step 3: Call Campy Installer

After package install, call:

```bash
campy install
campy doctor --repair
campy status
```

If `--no-start` is supplied, skip daemon start and tell the user how to start it.

## Step 4: Documentation

Update `README.md` with:

```bash
curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh | bash
```

Also include inspect-first path:

```bash
curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/bootstrap.sh -o /tmp/campy-bootstrap.sh
bash /tmp/campy-bootstrap.sh --dry-run
bash /tmp/campy-bootstrap.sh
```

Keep the command marked as pending until B238 validation passes.

## Step 5: Tests

Create `tests/test_bootstrap_script.py`.

Test:

- file exists
- has strict shell mode
- supports `--dry-run`
- mentions `doctor --repair`
- does not include destructive deletes of `~/.campy`
- `bash -n scripts/bootstrap.sh` passes

## Step 6: Validate

Run:

```bash
bash -n scripts/bootstrap.sh
bash scripts/bootstrap.sh --dry-run
.venv/bin/pytest -q tests/test_bootstrap_script.py tests/test_installer_idempotency.py tests/test_doctor_cli.py tests/test_setup_cli.py
```

## Completion Notes

Mark B237 complete only when bootstrap is idempotent, dry-run capable, and documented as pending or canonical according to B238 status.
