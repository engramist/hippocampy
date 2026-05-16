# Plan for B241 - Rename Product to HippoCampy and Add `campy` CLI

## Metadata

- **Card ID**: B241
- **Priority**: P0
- **Dependencies**: B230, B231; coordinate with B236-B240
- **Risk**: High - touches packaging, installer, runtime paths, adapters, docs, and user data migration

## Goal

Rename the public product identity to HippoCampy/Campy without breaking existing SideQuests installs or losing local memory.

## Non-Negotiable Migration Rule

Never delete or overwrite existing user memory. If `~/.sidequests/brain.db` exists, preserve it. New `~/.campy` behavior must either migrate, symlink, or explicitly continue using the old path with a clear compatibility note.

## Step 0: Verify Name Availability

Before changing package publication settings, verify availability for:

- Python distribution: `hippocampy`
- fallback distributions: `campy-memory`, `hippocampy-memory`, `campy-ai`
- CLI: `campy`
- GitHub/org/repo naming target
- domain or marketing URL if applicable

Document the result in the card completion notes. Do not claim availability without checking current registry/domain state.

## Step 1: Define Naming Constants

Add a small central module if one does not exist, for example `sidequests/branding.py`, with constants:

```python
PRODUCT_NAME = "HippoCampy"
SHORT_NAME = "Campy"
PRIMARY_CLI = "campy"
LEGACY_CLI = "sidequests"
PRIMARY_RUNTIME_DIR = ".campy"
LEGACY_RUNTIME_DIR = ".sidequests"
PRIMARY_LAUNCHD_LABEL = "ai.hippocampy.brain"
LEGACY_LAUNCHD_LABEL = "ai.sidequests.brain"
```

Use this module in installer, doctor, launchd, setup, and user-facing CLI output.

## Step 2: Add CLI Aliases

Update `pyproject.toml` scripts:

```toml
campy = "sidequests.cli.main:app"
campy-daemon = "sidequests.daemon:main"
sidequests = "sidequests.cli.main:app"
sidequests-daemon = "sidequests.daemon:main"
```

Keep legacy aliases for at least one release.

## Step 3: Runtime Directory Migration

Update `sidequests/paths.py`:

- prefer `~/.campy` for new installs
- detect `~/.sidequests` when no `~/.campy` exists
- provide a safe migration helper
- never move/delete automatically unless the command is explicit or a tested idempotent migration path exists

Suggested first implementation: use `~/.sidequests` if it already exists, otherwise create `~/.campy`. This is safer than moving data in the first rename card.

## Step 4: Launchd Compatibility

Update `sidequests/cli/launchd.py` and `doctor.py`:

- new label: `ai.hippocampy.brain`
- detect old label: `ai.sidequests.brain`
- repair should install the new plist
- repair should not kill a running daemon unless restart is explicitly needed
- cleanup should handle stale old plist only after the new service is healthy

## Step 5: Client Registration Migration

Update registration logic:

- Codex MCP block should become `[mcp_servers.campy]` or chosen canonical name
- remove or update old `[mcp_servers.sidequests]` safely
- Claude Desktop server should become `campy` or `hippocampy`
- VS Code server should become `campy`
- preserve old entries during migration only if duplicate registration would break active users

Add tests proving repeated setup does not duplicate old and new blocks.

## Step 6: Skill Rename

Add packaged skill path:

- `skills/campy-memory/SKILL.md`
- `sidequests/data/campy-memory/SKILL.md`

Compatibility options:

- leave `skills/sidequests-memory/SKILL.md` as a short forwarding/deprecated copy, or
- keep both identical for one release

Installer should install the `campy-memory` Codex skill and optionally remove/ignore stale `sidequests-memory` only if safe.

## Step 7: Docs and Backlog Alignment

Update user-facing docs to HippoCampy/Campy:

- `README.md`
- `Instalation_Instructions.md`
- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `docs/tool-catalog.md`
- B236-B240 one-click install cards and plans

Do not blindly rename historical patent docs or graph ontology terms. If `SideQuest` means the domain concept of a branch quest, keep it unless product branding requires clarification.

## Step 8: Tests

Add or update tests for:

- `campy --help` in installed wheel
- `sidequests --help` legacy alias
- runtime path selection: fresh install uses `~/.campy`; legacy install can still use `~/.sidequests`
- launchd label migration
- Codex/Claude/VS Code registration idempotency with old and new names
- skill installation under `~/.codex/skills/campy-memory`
- public release manifest excludes both `.campy` and `.sidequests`

## Step 9: Audit Remaining Strings

Run:

```bash
rg -n "sidequests-brain|SideQuests Brain|SideQuest Brain|sidequests-daemon|~/.sidequests|ai.sidequests.brain|sidequests-memory" pyproject.toml README.md Instalation_Instructions.md AGENTS.md CLAUDE.md GEMINI.md docs sidequests adapters extensions tests backlog
```

Classify every remaining hit as:

- historical reference
- graph ontology term
- legacy compatibility alias
- bug to rename

Record classification in completion notes.

## Step 10: Validate

Run:

```bash
.venv/bin/python -m build --wheel --sdist
.venv/bin/python -m twine check dist/*
.venv/bin/pytest -q tests/test_packaging_installed_mode.py tests/test_installer_idempotency.py tests/test_setup_cli.py tests/test_doctor_cli.py tests/test_uninstall.py tests/test_adapters.py tests/test_web.py
.venv/bin/pytest -q
```

## Completion Notes

Mark B241 complete only when HippoCampy/Campy is the public identity, compatibility aliases remain working, and existing user memory is protected.
