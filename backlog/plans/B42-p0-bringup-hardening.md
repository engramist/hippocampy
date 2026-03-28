# B42 — P0 Bring-Up Hardening (Codex + GPT Desktop)

## Goal

Complete the three highest-priority P0 backlog items for reliable install/bring-up:

1. Fix installer seed-path packaging bug (schema init path must work in installed environments)
2. Fix macOS launchd Python interpreter resolution (avoid pyenv shim/wrapper failures)
3. Force daemon reload during install/update (avoid stale tool registry)

This plan also converts targeted xfail tests to passing for the implemented behavior.

## Scope

In scope:
- Installer/runtime hardening in SideQuests CLI install path
- Packaging inclusion for seed examples resource
- Deterministic daemon reload at install time
- Automated tests for all three P0 items

Out of scope:
- P1 end-to-end live manual validation steps
- P2 queue replay and smoke retry/backoff
- Non-P0 backlog items

## Files To Modify

- sidequests/cli/install.py
- sidequests/cli/launchd.py
- pyproject.toml
- tests/test_bringup_priorities.py
- tests/test_install.py

## Implementation Details

### 1) P0.1 — Seed Path Packaging Bug

#### Problem

Schema initializer currently uses project-root absolute path:
- sidequests/cli/install.py: SchemaInitializer.init() inline script sets seed_path to PROJECT_ROOT/InvertorsDocs/GistSeedExamples.md

This fails in wheel-installed contexts where that path may not exist.

#### Changes

##### A. Add wheel-safe resolver helper in installer

File: sidequests/cli/install.py

Add helper near constants/classes:

- def resolve_seed_examples_path() -> str
  - Candidate order:
    1) PROJECT_ROOT/InvertorsDocs/GistSeedExamples.md (dev checkout)
    2) importlib.resources path under package data: sidequests/data/GistSeedExamples.md
  - If no candidate exists: raise RuntimeError with actionable error text

Use this helper inside SchemaInitializer.init() script payload.

Implementation approach for inline script:
- Pass the already-resolved absolute seed path into the inline script string
- Keep inline script simple and deterministic

##### B. Add package data path for wheel installs

File: pyproject.toml

Update wheel build config to include data file under package path:
- Add sidequests/data/GistSeedExamples.md to wheel include list

Also ensure the source file exists in package tree:
- If sidequests/data/GistSeedExamples.md does not exist, create it as a copy of InvertorsDocs/GistSeedExamples.md

Note: keep existing InvertorsDocs seed file untouched for docs/history.

#### Tests

File: tests/test_bringup_priorities.py
- Convert test_schema_initializer_uses_wheel_safe_seed_resource from xfail to normal test
- Assert inline script no longer depends on InvertorsDocs project-root literal
- Assert resolver uses package-resource fallback when project-root path is unavailable

File: tests/test_install.py
- Add test_resolve_seed_examples_path_prefers_project_root
- Add test_resolve_seed_examples_path_falls_back_to_package_data
- Add test_resolve_seed_examples_path_raises_when_missing


### 2) P0.2 — launchd Interpreter Resolution

#### Problem

launchd startup can fail when python path resolves to pyenv shim/wrapper.

Current behavior in both:
- sidequests/cli/launchd.py write_plist()
- sidequests/cli/install.py DaemonSetup._write_plist()

Both pick python3.12/python3 via shutil.which with no robust shim filtering.

#### Changes

##### A. Add canonical resolver in launchd module

File: sidequests/cli/launchd.py

Add helper:
- def resolve_system_python() -> str

Behavior:
- Candidate order:
  1) shutil.which("python3.12")
  2) shutil.which("python3")
  3) /usr/bin/python3 if present
  4) sys.executable
- Resolve candidate through os.path.realpath
- Reject known pyenv shim locations (contains /.pyenv/shims/)
- Return first safe real path
- Final fallback: sys.executable realpath

Use helper inside write_plist() when computing program args.

##### B. Reuse resolver in installer-specific plist writer

File: sidequests/cli/install.py

In DaemonSetup._write_plist(), replace direct shutil.which selection with:
- from sidequests.cli.launchd import resolve_system_python
- system_python = resolve_system_python()

This keeps both code paths aligned.

#### Tests

File: tests/test_bringup_priorities.py
- Convert test_launchd_write_plist_resolves_real_python_interpreter from xfail to normal
- Verify pyenv shim input returns real, non-shim python path

File: tests/test_install.py
- Add test_daemon_setup_write_plist_uses_launchd_resolver
- Add test_launchd_resolver_skips_pyenv_shim


### 3) P0.3 — Force Daemon Reload on Install/Update

#### Problem

Stale daemon process can serve old tool registry, causing Unknown tool errors after updates.

DaemonSetup.setup currently unloads only if launchd is_loaded() is true. This does not guarantee stale non-launchd process cleanup and does not force-reload robustly in all states.

#### Changes

File: sidequests/cli/install.py

In DaemonSetup.setup():

1. Add best-effort stale-process cleanup before launchctl load:
- Run pkill -f brain_daemon.py (best-effort, ignore non-zero)
- Run pkill -f sidequests.daemon (best-effort, ignore non-zero)

2. Force launchd reload sequence regardless of is_loaded state:
- Call unload_plist() unconditionally (ignore failure)
- Call load_plist() and check result

3. Improve operator logging:
- Print that reload is forced to refresh tool registry

No behavior changes outside macOS branch.

#### Tests

File: tests/test_bringup_priorities.py
- Convert test_run_install_forces_daemon_reload_before_smoke from xfail to normal
- Validate explicit daemon-reload action occurs before smoke test

File: tests/test_install.py
- Add test_daemon_setup_forces_unload_then_load_even_when_not_loaded
- Add test_daemon_setup_best_effort_process_cleanup_called


## Test Execution Plan

Run targeted tests first:
- pytest -q tests/test_bringup_priorities.py
- pytest -q tests/test_install.py

Then run broader integration coverage:
- pytest -q tests/test_adapters.py tests/test_web.py tests/test_insight_surfacing.py

If green, run full suite:
- pytest -q

## Acceptance Criteria

P0.1 acceptance:
- SchemaInitializer can resolve seed file path in both dev checkout and package-installed scenarios
- No hard dependency on PROJECT_ROOT InvertorsDocs path
- New tests pass

P0.2 acceptance:
- launchd plist uses resolved concrete interpreter path, not pyenv shim
- installer plist path uses same resolver
- New tests pass

P0.3 acceptance:
- install flow force-reloads daemon and does so before smoke test
- stale process cleanup is attempted (best effort)
- New tests pass

## Risk Notes

- Changing packaging include rules can affect build artifact size; keep include minimal (single seed file)
- pkill usage must be best-effort and macOS-only to avoid surprising failures
- Keep fallback behavior robust for developer local runs where /usr/bin/python3 may vary

## Rollback Plan

If regressions occur:
- Revert installer helper additions in sidequests/cli/install.py
- Revert resolver integration in sidequests/cli/launchd.py
- Revert pyproject.toml wheel include changes
- Revert newly added tests and restore xfail status in tests/test_bringup_priorities.py

