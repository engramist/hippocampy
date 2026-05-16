# Plan for B245 - Rename Config Namespace from `sidequests.toml` to `campy.toml`

## Metadata

- **Card ID**: B245
- **Priority**: P0
- **Dependencies**: B241, B242
- **Risk**: Medium - config lookup changes can break local projects

## Goal

Use `campy.toml` as the primary project config while preserving `sidequests.toml` fallback compatibility.

## Guardrails

- Do not delete `sidequests.toml` automatically.
- Do not move DB/log/socket runtime data.
- If both config files exist, `campy.toml` wins.
- Explicit config path always wins.

## Step 1: Add Primary Config File

Create `campy.toml` from the current root `sidequests.toml`.

Leave root `sidequests.toml` in place for one release, or replace it with a comment-only legacy pointer only if tests confirm no code depends on its full content.

Recommended for this card: keep both files identical initially.

## Step 2: Package Config Resource

Add packaged config resource:

```text
campy/data/config/campy.toml
```

Keep legacy packaged resource as needed for compatibility tests.

## Step 3: Config Loader Search Order

Update the config loader so search order is:

1. explicit path
2. `./campy.toml`
3. `./sidequests.toml`
4. `~/.campy/config.toml`
5. `~/.sidequests/config.toml`
6. packaged default only where explicitly intended by installer/test code

## Step 4: Installer and Doctor

Update new project/global config writes to mention/write Campy config names.

Doctor should report:

- active config path
- whether it is legacy
- recommended migration command or copy command if only `sidequests.toml` exists

## Step 5: Tests

Update `tests/test_config.py` to cover:

- explicit path wins
- `campy.toml` wins over `sidequests.toml`
- legacy `sidequests.toml` still loads
- missing config error names both `campy.toml` and legacy fallback

Update packaging tests to assert `campy.toml` resource is present.

## Step 6: Validate

Run exactly:

```bash
.venv/bin/pytest -q tests/test_config.py tests/test_packaging_installed_mode.py tests/test_doctor_cli.py tests/test_setup_cli.py
.venv/bin/python -m compileall -q campy sidequests mcp_engine adapters
```

## Completion Notes

Document whether root `sidequests.toml` remains as a full legacy config or a pointer file.
