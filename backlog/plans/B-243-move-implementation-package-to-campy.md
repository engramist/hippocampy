# Plan for B243 - Move Implementation Package from `sidequests` to `campy`

## Metadata

- **Card ID**: B243
- **Priority**: P0
- **Dependencies**: B242
- **Risk**: High - moves Python modules and can break imports

## Goal

Make `campy/` the implementation package and reduce `sidequests/` to compatibility shims.

## Guardrails

- Do not change durable data paths in this card.
- Do not delete `sidequests/`; keep legacy import compatibility.
- Do not change config filename behavior; B245 owns that.
- Keep this mechanical and test-driven.

## Step 1: Move Implementation Files

Use `git mv` where possible:

```bash
git mv sidequests campy_impl_tmp
```

Then merge the implementation files into the existing `campy/` namespace created by B242. If conflicts exist, keep the implementation content and preserve any useful shim comments only where still relevant.

After the move, `campy/` should contain real implementation files.

## Step 2: Recreate `sidequests` Compatibility Shims

Recreate `sidequests/` as forwarding modules. At minimum preserve:

```text
sidequests/__init__.py
sidequests/daemon.py
sidequests/paths.py
sidequests/brain_daemon.py
sidequests/brain_transport.py
sidequests/cli/main.py
sidequests/cli/setup.py
sidequests/cli/register.py
sidequests/cli/doctor.py
sidequests/cli/uninstall.py
sidequests/cli/launchd.py
sidequests/adapters/mcp_server.py
sidequests/adapters/claude_desktop/adapter.py
```

Each shim should import from `campy.*`. Do not copy full implementation code back into `sidequests/`.

## Step 3: Preserve Package Data

Move primary package data to `campy/data/**`.

Keep legacy package resources only if tests or compatibility require them. If retained under `sidequests/data/**`, make clear they are legacy compatibility resources.

## Step 4: Update Import References

Replace internal imports from `sidequests.` to `campy.` across implementation code and tests, except in tests that explicitly validate the legacy shim.

Do not change graph ontology terms like `SideQuest`.

## Step 5: Entry Points

Update `pyproject.toml`:

```toml
campy = "campy.cli.main:app"
campy-daemon = "campy.daemon:main"
sidequests = "sidequests.cli.main:app"
sidequests-daemon = "sidequests.daemon:main"
```

## Step 6: Tests

Create `tests/test_sidequests_compat_namespace.py`:

- `import sidequests` works
- `from sidequests.paths import runtime_dir` works
- `python -m sidequests.cli.main --help` works
- `sidequests` entry point still resolves

Update `tests/test_campy_namespace.py` to assert `campy` is now the implementation package.

## Step 7: Validate

Run exactly:

```bash
.venv/bin/python -m compileall -q campy sidequests adapters mcp_engine
.venv/bin/pytest -q tests/test_campy_namespace.py tests/test_sidequests_compat_namespace.py tests/test_adapters.py tests/test_mcp_server_adapter.py tests/test_setup_cli.py
.venv/bin/pytest -q
```

## Completion Notes

List any `sidequests/` files that still contain non-shim implementation logic and why they remain.
