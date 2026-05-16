# Plan for B236 - Public PyPI and pipx Install Path

## Metadata

- **Card ID**: B236
- **Priority**: P0
- **Dependencies**: B230, B232, B233
- **Risk**: Medium - packaging mistakes can create broken public releases

## Goal

Make the package install path reliable enough for a one-line bootstrap script to depend on it. The package path should work from wheel/sdist, local wheel install, pipx, and uv tool where available.

## Step 1: Finalize Package Metadata

Review and update `pyproject.toml`:

- package name/version
- license field
- URLs
- Python version constraints
- package data entries
- console scripts
- optional dependency groups

Do not include runtime state, generated artifacts, backlog archives, or local data in the wheel.

## Step 2: Add Release Build Script

Create `scripts/release_build.sh`.

Required behavior:

- `set -euo pipefail`
- remove `dist`, `build`, and `*.egg-info`
- run `scripts/audit_public_release.sh --release`
- build wheel/sdist
- run `twine check dist/*`
- optionally upload to TestPyPI only behind an explicit flag such as `--testpypi`
- never upload to real PyPI without an explicit `--publish` flag and confirmation text

## Step 3: Add Publish Checklist

Create `docs/release-publish-checklist.md` with:

- version bump procedure
- build commands
- TestPyPI dry run
- PyPI publish command
- rollback note: PyPI files cannot be overwritten; publish a new version
- privacy and patent-pending checks
- validation evidence template

## Step 4: Extend Tests

Update `tests/test_packaging_installed_mode.py` if needed so it validates installed-mode CLI commands:

- `campy --help`
- `campy doctor --help`
- `campy install --help`
- `campy activity --help`
- packaged resource access for config templates and memory skill

Add pipx/uv checks only if the binaries are present; otherwise skip with a clear reason.

## Step 5: Update Docs

Update `README.md` to include package install status:

- current canonical private/dev path
- pending public path
- final target commands for `pipx` and `uv tool`

Update `docs/public-release-audit.md` with package verification results after validation.

## Step 6: Validate

Run:

```bash
rm -rf dist build *.egg-info
.venv/bin/python -m build --wheel --sdist
.venv/bin/python -m twine check dist/*
bash scripts/audit_public_release.sh --release
.venv/bin/pytest -q tests/test_public_release_manifest.py tests/test_packaging_installed_mode.py
python -m venv /tmp/campy-wheel-test
/tmp/campy-wheel-test/bin/python -m pip install -U pip
/tmp/campy-wheel-test/bin/python -m pip install dist/hippocampy-*.whl
/tmp/campy-wheel-test/bin/campy --help
/tmp/campy-wheel-test/bin/campy doctor --help
```

## Completion Notes

Mark B236 complete only when the package path is validated and docs name the current release status honestly.
