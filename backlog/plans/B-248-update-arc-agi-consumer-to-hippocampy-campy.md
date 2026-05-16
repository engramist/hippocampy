# Plan for B248 - Update ARC_AGI Consumer to HippoCampy/Campy Namespace

## Metadata

- **Card ID**: B248
- **Priority**: P0
- **Dependencies**: B241; ideally B242 before import-path changes; B244 before final MCP module-path cutover
- **Risk**: Medium - cross-repo consumer migration can break live smoke tests
- **Target Repo**: sibling `../ARC_AGI`

## Goal

Update ARC_AGI so it uses HippoCampy/Campy names and paths for the shared memory system while preserving fallback compatibility with existing SideQuests-era installs.

## Guardrails

- Do not vendor or duplicate HippoCampy code into ARC_AGI.
- Do not create a separate ARC_AGI KuzuDB unless a test explicitly uses a temporary DB.
- Do not delete or move `~/.sidequests` data.
- Prefer additive fallback compatibility over hard cutovers.
- Keep ARC_AGI as an external consumer, not part of this repo.

## Step 1: Inventory ARC_AGI References

From this repo root, run:

```bash
cd ../ARC_AGI
rg -n "sidequests|SideQuests|sidequests-brain|SIDEQUESTS|~/.sidequests|brain.sock|mcp_server|campy|HippoCampy" .
```

Classify each hit as:

- runtime integration
- test expectation
- documentation/setup instruction
- legacy/historical note
- generated artifact to ignore

## Step 2: Socket and Environment Fallbacks

Update ARC_AGI socket discovery so the preferred order is:

1. `CAMPY_BRAIN_SOCKET`
2. `CAMPY_SOCKET_PATH`
3. active Campy default, usually `~/.campy/brain.sock`
4. legacy `SIDEQUESTS_BRAIN_SOCKET`
5. legacy `SIDEQUESTS_SOCKET_PATH`
6. legacy `~/.sidequests/brain.sock`

If the socket is missing, error text should say:

```text
HippoCampy brain socket is missing at <path>. Start the brain daemon with `campy start` or run `campy setup`.
```

It may also mention legacy `sidequests start` only as a fallback note.

## Step 3: CLI and Docs

Update user-facing ARC_AGI docs/scripts from:

```bash
sidequests start
sidequests setup
sidequests status
sidequests activity --follow
```

to:

```bash
campy start
campy setup
campy status
campy activity --follow
```

Keep a compatibility note: older installs may still expose `sidequests` as an alias.

## Step 4: Python Imports

If ARC_AGI imports SideQuests/HippoCampy Python modules directly, update to prefer `campy`:

```python
try:
    from campy.brain_transport import call_brain
except ImportError:  # legacy installed package fallback
    from sidequests.brain_transport import call_brain
```

Only use this pattern where ARC_AGI truly imports the package. Do not add imports if ARC_AGI talks only over sockets/MCP.

## Step 5: MCP Names and Config Examples

If ARC_AGI contains MCP config snippets or test fixtures, update primary server names to `campy`.

Legacy names to keep in cleanup/fallback tests only:

```text
sidequests
sidequests-brain
sidequests-brain-desktop
```

## Step 6: Tests

Add or update ARC_AGI tests to cover:

- Campy env var socket path wins.
- Legacy SideQuests env var still works.
- Missing socket error mentions `campy start` or `campy setup`.
- Any direct import path prefers `campy` with `sidequests` fallback.
- Existing durable runner tests still pass when HippoCampy is installed from the sibling repo.

## Step 7: Validation

Run from `../ARC_AGI`:

```bash
pytest -q tests/test_arc3_durable_runner.py tests/test_b185_failure_taxonomy.py
pytest -q
```

If full ARC_AGI tests are too expensive, run the smallest test subset that covers the changed files and document what was skipped.

Then run from this repo:

```bash
.venv/bin/pytest -q tests/test_adapters.py tests/test_mcp_server_adapter.py tests/test_installer_idempotency.py
```

## Completion Notes

Record:

- all ARC_AGI files changed
- whether any `sidequests` references remain and why
- exact tests run and results
- whether live smoke was run or intentionally skipped
