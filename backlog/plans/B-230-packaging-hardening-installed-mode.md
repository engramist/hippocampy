# Plan for B230 - Packaging Hardening for Installed Mode

## Card Metadata

- **Card ID**: B230
- **Priority**: P0
- **Dependencies**: B4, B5, B231 downstream

## Summary

Make SideQuests run correctly from wheel/sdist installation, not only from `pip install -e .` in a source checkout.

This is the packaging foundation for public one-line installation. The technical goal is to separate package resources from mutable runtime state and remove repo-root assumptions from daemon, CLI, adapters, and web assets.

## Technical Approach

### Step 1: Audit current packaging and path assumptions

Run targeted searches for source-tree assumptions:

```bash
rg -n "Path\(__file__\)|parent.parent|parents\[|Desktop/GitProjects|sidequests-brain|cwd\(\)|os.getcwd|__file__" sidequests mcp_engine adapters brain_daemon.py web tests pyproject.toml
```

Classify each result:

- Package resource path: should use `importlib.resources` or a centralized package path helper.
- Runtime state path: should use `~/.sidequests` or configured runtime dir.
- Development-only path: acceptable only in tests/docs.
- Bug: source checkout assumption that breaks wheel mode.

### Step 2: Add centralized path/resource helper

Create or update `sidequests/paths.py` with helpers similar to:

```python
from importlib import resources
from pathlib import Path

RUNTIME_DIR = Path.home() / ".sidequests"

def runtime_dir() -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    return RUNTIME_DIR

def package_root() -> Path:
    return Path(__file__).resolve().parent

def resource_path(package: str, name: str) -> Path:
    return Path(str(resources.files(package).joinpath(name)))
```

If any resource must be copied to runtime before use, implement an explicit copy helper rather than writing into package directories.

### Step 3: Fix package data

Update `pyproject.toml` package data so wheel/sdist includes required runtime resources.

Check at minimum:

- default config template
- adapters
- web static/templates if used
- seed markdown files required by schema/bootstrap
- any bundled schema, dictionary, wiki, or prompt templates

If `MANIFEST.in` is needed for sdist-only files, add it deliberately and test both wheel and sdist.

### Step 4: Harden daemon entry point

Verify daemon can launch without repo root.

Preferred target:

```bash
sidequests-daemon
```

or:

```bash
python -m sidequests.daemon
```

If root `brain_daemon.py` remains the implementation entry point, create a package wrapper that imports and runs it from installed mode without requiring the repo file path.

### Step 5: Harden adapter registration for installed mode

Review generated config for:

- Codex MCP server command
- Claude Code MCP server command
- Claude Desktop config
- VS Code MCP config

Installed mode should point to stable commands/wrappers, not `.../Desktop/GitProjects/sidequests-brain/adapters/...` paths unless explicitly running from editable dev mode.

If direct adapter scripts are still required, install them as package data and generate runtime wrapper scripts under `~/.sidequests/bin`.

### Step 6: Add clean venv install test

Create `tests/test_packaging_installed_mode.py`.

The test should:

1. Build wheel in an isolated temp dist dir or use current `dist` when explicitly requested.
2. Create a temp venv.
3. Install wheel.
4. Run:

```bash
sidequests --help
sidequests install --help
sidequests activity --help
```

Keep destructive daemon-start behavior out of the unit test unless guarded by an env var.

### Step 7: Update docs

Update README and architecture to describe:

- Source/dev install
- Package-installed mode
- Runtime state under `~/.sidequests`
- Package resources are read-only
- Public one-line installer depends on this card

## Validation

Run exactly:

```bash
python -m build --wheel --sdist
python -m twine check dist/*
python -m venv /tmp/sidequests-wheel-test
/tmp/sidequests-wheel-test/bin/python -m pip install -U pip
/tmp/sidequests-wheel-test/bin/python -m pip install dist/sidequests_brain-*.whl
/tmp/sidequests-wheel-test/bin/sidequests --help
/tmp/sidequests-wheel-test/bin/sidequests install --help
/tmp/sidequests-wheel-test/bin/sidequests activity --help
pytest -q tests/test_packaging_installed_mode.py tests/test_setup_cli.py tests/test_activity_log.py
```

Also run the path audit command from Step 1 and document any retained source-path assumptions in the card completion notes.

## Risks

- Launchd and adapter configs may still need real script paths; solve by generating wrapper scripts under `~/.sidequests/bin`.
- Package data omissions may only appear in sdist or only in wheel; test both.
- The root `brain_daemon.py` may be too source-tree-oriented; prefer a package entry wrapper if needed.
