# Plan for B242 - Add `campy` Python Import Namespace Shim

## Metadata

- **Card ID**: B242
- **Priority**: P0
- **Dependencies**: B241
- **Risk**: Low/Medium - adds import surface but should not move existing code

## Goal

Create a thin `campy` Python namespace that forwards to the existing `sidequests` implementation so future cards can migrate imports safely.

## Guardrails

- Do not move or delete `sidequests/` in this card.
- Do not duplicate implementation logic.
- Do not change runtime directory selection.
- Do not change MCP registrations yet.

## Step 1: Create Forwarding Package

Create these files as thin shims:

```text
campy/__init__.py
campy/daemon.py
campy/brain_daemon.py
campy/brain_transport.py
campy/paths.py
campy/cli/__init__.py
campy/cli/main.py
campy/adapters/__init__.py
campy/adapters/mcp_server.py
```

Forward public objects from the matching `sidequests.*` modules. Keep comments short and explicit: `campy` is the primary namespace; `sidequests` is the implementation namespace until B243.

## Step 2: Add Module Entrypoints

Ensure these commands work:

```bash
.venv/bin/python -m campy.cli.main --help
.venv/bin/python -c "import campy; import campy.paths; import campy.adapters.mcp_server"
```

If `python -m campy.adapters.mcp_server` needs package `__main__.py`, add the smallest possible forwarding `__main__.py`.

## Step 3: Package Discovery

Update `pyproject.toml` package discovery to include `campy*`.

Do not remove `sidequests*`.

## Step 4: Tests

Create `tests/test_campy_namespace.py` with tests for:

- `import campy`
- `campy.paths.runtime_dir is usable`
- `python -m campy.cli.main --help`
- `campy.adapters.mcp_server` imports
- wheel package list includes `campy/__init__.py`

## Step 5: Validate

Run exactly:

```bash
.venv/bin/python -m compileall -q campy sidequests adapters mcp_engine
.venv/bin/pytest -q tests/test_campy_namespace.py tests/test_packaging_installed_mode.py tests/test_adapters.py
```

## Completion Notes

Record whether `python -m campy.adapters.mcp_server` required an `__main__.py` shim.
